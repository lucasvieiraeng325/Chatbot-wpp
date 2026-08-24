"""Lógica de roteamento das mensagens recebidas."""
import os
import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

import whatsapp as wa
from menu import menu_principal, voltar_menu
from content import CONTEUDO, ATALHOS, texto_atendente, NUMERO_ATENDENTE
from db import (registrar_interesse, get_status, marcar_humano, get_interesses,
                get_nome, set_nome, marcar_aguardando_nome)

log = logging.getLogger("sitio-bot")

TZ = ZoneInfo(os.getenv("TIMEZONE", "America/Sao_Paulo"))
HORA_ABRE = int(os.getenv("HORA_ABRE", "7"))
HORA_FECHA = int(os.getenv("HORA_FECHA", "22"))

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


GENERICOS = {"cliente", "usuario", "usuário", "user", "whatsapp", "eu", "sim", "nao",
             "não", "oi", "ola", "olá", "ok", "okay", "blz", "beleza", "obrigado",
             "obrigada", "bom", "boa", "tudo", "certo", "isso", "aí", "ai", "teste"}


def nome_valido(nome) -> bool:
    """O perfil do WhatsApp costuma vir vazio, com número ou apelido."""
    if not nome:
        return False
    n = nome.strip()
    if len(n) < 2 or len(n) > 30:
        return False
    if n.lower() in GENERICOS:
        return False
    # Precisa ter ao menos duas letras seguidas (descarta "123", "🌻", ".")
    letras = sum(c.isalpha() for c in n)
    return letras >= 2


def limpar_nome(texto: str):
    """Extrai o primeiro nome de respostas como 'meu nome é Ana Paula'."""
    t = texto.strip().rstrip(".!,")
    for prefixo in ("meu nome e ", "meu nome é ", "me chamo ", "sou o ", "sou a ",
                    "aqui e ", "aqui é ", "e o ", "é o ", "e a ", "é a "):
        if t.lower().startswith(prefixo):
            t = t[len(prefixo):]
            break
    primeiro = t.split()[0] if t.split() else ""
    primeiro = "".join(c for c in primeiro if c.isalpha() or c in "-'")
    return primeiro.capitalize() if nome_valido(primeiro) else None


def dentro_do_horario() -> bool:
    h = datetime.now(TZ).hour
    return HORA_ABRE <= h < HORA_FECHA


ROTULOS = {
    "casamento": "Casamento",
    "quinze": "15 anos",
    "infantil": "Evento infantil",
    "confraternizacao": "Aniversário/Confraternização",
    "decorado": "Espaço decorado",
    "localizacao": "Localização",
    "regras": "Informações gerais",
}


async def avisar_atendente(telefone: str, nome: str, motivo: str):
    """
    Manda o resumo do lead para o WhatsApp do atendente.

    Só funciona se o atendente tiver escrito para o número do bot nas
    últimas 24h (janela de serviço da Meta). Para receber sempre, ele
    deve mandar um 'oi' para o bot uma vez por dia, ou usar um template.
    """
    if not NUMERO_ATENDENTE:
        log.info("LEAD: %s (%s) — %s", nome, telefone, motivo)
        return

    interesses = await get_interesses(telefone)
    lista = ", ".join(ROTULOS.get(i, i) for i in interesses) or "—"
    hora = datetime.now(TZ).strftime("%d/%m às %H:%M")

    texto = (
        "🔔 *Novo lead no bot*\n\n"
        f"*Nome:* {nome}\n"
        f"*WhatsApp:* wa.me/{telefone}\n"
        f"*Interesses:* {lista}\n"
        f"*Motivo:* {motivo}\n"
        f"*Quando:* {hora}"
    )
    try:
        await wa.texto(NUMERO_ATENDENTE, texto)
    except Exception as e:
        log.error("Falha ao avisar atendente: %s", e)


async def notificar(telefone: str, nome: str, motivo: str):
    """Avisa a equipe: push no painel, WhatsApp e Telegram (se configurados)."""
    import push
    try:
        interesses = await get_interesses(telefone)
        rotulos = ", ".join(ROTULOS.get(i, i) for i in interesses)
        await push.pediu_atendente(telefone, nome, rotulos)
    except Exception as e:
        log.error("Falha no push: %s", e)

    await avisar_atendente(telefone, nome, motivo)
    if not TELEGRAM_TOKEN:
        return
    interesses = await get_interesses(telefone)
    txt = (
        f"🔔 *Novo lead*\n"
        f"Nome: {nome}\n"
        f"Telefone: wa.me/{telefone}\n"
        f"Interesses: {', '.join(interesses) or '—'}\n"
        f"Motivo: {motivo}\n"
        f"Hora: {datetime.now(TZ).strftime('%d/%m %H:%M')}"
    )
    async with httpx.AsyncClient(timeout=10) as c:
        await c.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": txt, "parse_mode": "Markdown"},
        )


def extrair_escolha(msg: dict):
    inter = msg.get("interactive", {})
    if inter.get("type") == "list_reply":
        return inter["list_reply"]["id"]
    if inter.get("type") == "button_reply":
        return inter["button_reply"]["id"]
    if msg.get("type") == "text":
        bruto = msg["text"]["body"].lower().strip()
        if bruto in CONTEUDO:
            return bruto
        for chave, destino in ATALHOS.items():
            if chave in bruto:
                return destino
    return None


async def processar_mensagem(msg: dict, nome: str):
    de = msg["from"]
    status = await get_status(de)

    # Bot pausado: atendente humano assumiu a conversa
    if status == "humano":
        return

    # Estamos esperando o cliente digitar o nome dele
    if status == "aguardando_nome":
        candidato = limpar_nome(msg.get("text", {}).get("body", "")) if msg.get("type") == "text" else None
        if candidato:
            await set_nome(de, candidato)
            await wa.texto(de, f"Prazer, {candidato}! 🌻")
            await wa.enviar(menu_principal(de, candidato))
        else:
            # Não insiste: segue sem o nome para não travar o atendimento
            await set_nome(de, "")
            await wa.enviar(menu_principal(de, "tudo bem"))
        return

    # Mídia recebida — a Fase 1 não interpreta áudio/imagem
    if msg.get("type") in ("audio", "image", "video", "document", "sticker"):
        await wa.texto(de, (
            "Recebi seu arquivo! 🌻 Por aqui consigo ler apenas texto, "
            "mas já chamei um atendente."
        ))
        await asyncio.sleep(1.0)
        await wa.texto(de, texto_atendente())
        await marcar_humano(de, nome)
        await notificar(de, nome, "enviou mídia")
        return

    # Nome: usa o salvo, senão o do perfil; se nenhum servir, pergunta uma vez
    salvo = await get_nome(de)
    if salvo:
        nome = salvo
    elif nome_valido(nome):
        pass
    elif salvo is None:
        await marcar_aguardando_nome(de)
        await wa.texto(de, (
            "Olá! 🌻 Sou o assistente virtual do Sítio Girassol.\n\n"
            "Como posso te chamar?"
        ))
        return
    else:
        nome = "tudo bem"

    escolha = extrair_escolha(msg)

    if escolha == "humano":
        await marcar_humano(de, nome)
        await wa.texto(de, texto_atendente())
        if not dentro_do_horario():
            await asyncio.sleep(1.0)
            await wa.texto(de, (
                f"Nosso horário de atendimento é das {HORA_ABRE}h às {HORA_FECHA}h. "
                "Assim que abrirmos, retornamos o seu contato! 🌻"
            ))
        await notificar(de, nome, "pediu atendente")
        return

    # Primeira interação fora do horário: avisa, mas continua atendendo
    if not dentro_do_horario() and escolha is None:
        await wa.texto(de, (
            f"Olá! 🌻 Nosso atendimento humano é das {HORA_ABRE}h às {HORA_FECHA}h, "
            "mas posso te mostrar nossos materiais agora mesmo!"
        ))

    item = CONTEUDO.get(escolha)
    if not item:
        await wa.enviar(menu_principal(de, nome))
        return

    await registrar_interesse(de, nome, escolha)

    for bloco in item["blocos"]:
        t = bloco["tipo"]
        if t == "texto":
            await wa.texto(de, bloco["texto"])
        elif t == "pdf":
            await wa.pdf(de, bloco["url"], bloco["arquivo"], bloco.get("legenda", ""))
        elif t == "imagem":
            await wa.imagem(de, bloco["url"], bloco.get("legenda", ""))
        elif t == "localizacao":
            await wa.localizacao(de, bloco["lat"], bloco["lng"],
                                 bloco["nome"], bloco["endereco"])
        await asyncio.sleep(1.5)   # preserva a ordem de entrega

    await wa.enviar(voltar_menu(de))
