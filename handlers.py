"""Lógica de roteamento das mensagens recebidas."""
import os
import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

import whatsapp as wa
import ia
from menu import menu_principal, voltar_menu, CONVITE_QUALIFICAR
from content import (CONTEUDO, ATALHOS, texto_atendente, texto_saudacao,
                     em_horario_comercial, previsao_representante,
                     ASSINATURA_SOL, HORARIO_REPRESENTANTES,
                     NUMERO_ATENDENTE)
from db import (registrar_interesse, get_status, marcar_humano, get_interesses,
                get_nome, set_nome, marcar_aguardando_nome, salvar_mensagem,
                get_qualificacao, salvar_qualificacao, materiais_enviados,
                marcar_material, avancar_etapa)

log = logging.getLogger("sitio-bot")

TZ = ZoneInfo(os.getenv("TIMEZONE", "America/Sao_Paulo"))
# Horário dos representantes (humanos): segunda a sábado, 8h às 18h.
# O bot e a IA respondem 24h.

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


CONFIRMACOES_EQUIPE = {"sim", "ok", "confirmo", "confirmado", "s", "👍", "beleza",
                       "blz", "positivo"}


async def responder_equipe(msg: dict):
    """
    A equipe respondendo ao aviso da agenda. Só reage ao SIM (e sinônimos)
    com uma confirmação curta — qualquer reply ja abriu a janela de 24h
    da Meta, o que era o objetivo. Nao rotea para o fluxo do cliente.
    """
    de = msg.get("from", "")
    if msg.get("type") != "text":
        return
    texto = (msg.get("text", {}).get("body") or "").strip().lower()
    if not texto:
        return
    # aceita "sim", "SIM!", "sim confirmo", "ok" etc.
    primeira = texto.split()[0].strip(".!?,;:")
    if primeira in CONFIRMACOES_EQUIPE or texto in CONFIRMACOES_EQUIPE:
        try:
            await wa.texto(de, "🌻 Anotado! Você continuará recebendo o resumo diário.",
                           registrar=False)
        except Exception as e:
            log.error("Falha ao confirmar equipe: %s", e)


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
    return em_horario_comercial(datetime.now(TZ))


ROTULOS = {
    "casamento": "Casamento",
    "quinze": "15 anos",
    "infantil": "Evento infantil",
    "confraternizacao": "Aniversário/Confraternização",
    "decorado": "Espaço decorado",
    "locacao": "Locação do espaço",
    "fotos": "Fotos do espaço",
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
        await wa.texto(NUMERO_ATENDENTE, texto, registrar=False)
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


# Preço e data: com a IA ligada ela captura tipo/convidados/data antes de
# passar para a equipe, em vez de encaminhar direto.
PALAVRAS_DA_IA = {"data", "valor", "quanto", "preco", "preço", "orcamento", "orçamento"}


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
        # Com a IA ligada, palavra-chave só vale em texto curto ("fotos",
        # "casamento"); frase inteira vai para a IA, que entende o contexto.
        if ia.ativo and len(bruto.split()) > 3:
            return None
        for chave, destino in ATALHOS.items():
            if chave in bruto:
                if ia.ativo and chave in PALAVRAS_DA_IA:
                    continue
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
            await wa.enviar(await montar_menu(de, candidato))
        else:
            # Não insiste: segue sem o nome para não travar o atendimento
            await set_nome(de, "")
            await wa.enviar(await montar_menu(de, "tudo bem"))
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
        await wa.texto(de, texto_saudacao())
        return
    else:
        nome = "tudo bem"

    escolha = extrair_escolha(msg)

    if escolha == "humano":
        await encaminhar_equipe(de, nome, "pediu representante")
        return

    # Texto livre que não é opção do menu nem palavra-chave curta: a IA
    # conduz. Saudação curta continua abrindo o menu.
    if escolha is None and msg.get("type") == "text":
        pergunta = msg["text"]["body"].strip()
        if not eh_saudacao(pergunta) and await responder_com_ia(de, nome, pergunta):
            return

    # Opção do menu: pacote da aba Preços ou item fixo (com material)
    if not escolha or not await blocos_material(escolha):
        await wa.enviar(await montar_menu(de, nome))
        return

    await enviar_material(de, nome, escolha)
    # Com a IA ligada, o material puxa a conversa para a qualificação.
    if ia.ativo:
        await salvar_qualificacao(de, tipo_evento=escolha if escolha in ia.TIPOS else "")
        await wa.enviar(voltar_menu(de, CONVITE_QUALIFICAR))
    else:
        await wa.enviar(voltar_menu(de))


SAUDACOES = {"oi", "oii", "oie", "ola", "olá", "opa", "eae", "e ai", "e aí", "menu",
             "inicio", "início", "bom dia", "boa tarde", "boa noite", "hello", "hi",
             "ok", "obrigado", "obrigada", "valeu", "blz", "beleza", "sim", "nao", "não"}


def eh_saudacao(texto: str) -> bool:
    t = texto.lower().strip(" !?.,🌻").strip()
    return t in SAUDACOES or len(t) < 3


async def encaminhar_equipe(de: str, nome: str, motivo: str, texto_cliente=None):
    """
    Passa a conversa para a equipe. Leva junto o que a IA já capturou:
    no aviso para o atendente e numa nota no histórico do painel.
    """
    q = await get_qualificacao(de)
    resumo_txt = ia.resumo(q)
    await marcar_humano(de, nome)
    await avancar_etapa(de, "com_representante")
    if texto_cliente is None:
        # Mensagem padrão: previsão de retorno + resumo (ou pedido dos dados)
        texto_cliente = texto_atendente(resumo=resumo_txt if ia.completo(q) else "")
    await wa.texto(de, texto_cliente)
    if resumo_txt:
        # Nota interna: aparece no painel, não é enviada ao cliente.
        await salvar_mensagem(de, "enviada", "sistema",
                              f"📋 Resumo para a equipe: {resumo_txt}")
    await notificar(de, nome, f"{motivo}" + (f" — {resumo_txt}" if resumo_txt else ""))


INTENCAO_FECHAR = ("fechar", "fecho", "fechamos", "reserv", "contrat", "represent",
                   "atendent", "falar com", "pessoa", "humano", "agendar", "visita",
                   "neia", "proprietári", "telefone", "whats", "contato")


def quer_representante(texto: str) -> bool:
    t = texto.lower()
    return any(p in t for p in INTENCAO_FECHAR)


async def responder_com_ia(de: str, nome: str, pergunta: str) -> bool:
    """
    Pergunta livre → IA. Devolve True se tratou a mensagem (o fluxo para
    aqui) ou False para cair no menu, como antes da IA existir.
    """
    r = await ia.atender(de, nome, pergunta)
    if not r:
        return False

    # Restrito ao menu por desviar do foco: só o menu, sem IA. Quem pede
    # para fechar ou falar com alguém ainda é encaminhado.
    if r["acao"] == "pausada":
        if quer_representante(pergunta):
            await encaminhar_equipe(de, nome, "quer fechar")
        else:
            await wa.enviar(await montar_menu(de, nome))
        return True

    # Fora do tema dos eventos: menu de novo, sem texto da IA.
    if r["acao"] == "menu":
        await wa.enviar(await montar_menu(de, nome))
        return True

    tipo = r["qualificacao"].get("tipo_evento")
    if tipo in CONTEUDO:
        await registrar_interesse(de, nome, tipo)

    texto_sol = f"{ASSINATURA_SOL}\n\n{r['resposta']}"

    if r["acao"] == "atendente":
        await encaminhar_equipe(
            de, nome, "IA encaminhou para fechamento",
            f"{texto_sol}\n\n{previsao_representante(datetime.now(TZ))}")
        return True

    # PDF/imagem do tipo de evento vai uma vez só (salvo pedido de reenvio);
    # fotos do espaço, localização, contato e regras vão sempre que pedirem.
    material = r.get("material") or "nenhum"
    if material != "nenhum":
        from db import obter_pacote
        unico = material in MATERIAIS_UNICOS or bool(await obter_pacote(material))
        if not unico or r.get("reenviar_material") \
                or material not in await materiais_enviados(de):
            await enviar_material(de, nome, material)

    await wa.enviar(voltar_menu(de, texto_sol))
    return True


MATERIAIS_UNICOS = {"casamento", "quinze", "infantil", "confraternizacao", "decorado",
                    "locacao"}


async def montar_menu(para: str, nome: str) -> dict:
    """Menu principal com os pacotes atuais da aba Preços."""
    try:
        from db import listar_pacotes, DATABASE_URL
        pacotes = await listar_pacotes() if DATABASE_URL else None
    except Exception as e:
        log.error("Menu: não consegui ler os pacotes — %s", e)
        pacotes = None
    return menu_principal(para, nome, pacotes or None, qualificar=ia.ativo)


async def blocos_material(chave: str) -> list:
    """Material a enviar: o do pacote (editado no painel, aba Preços) se
    houver; senão o de content.CONTEUDO."""
    from db import obter_pacote
    pac = await obter_pacote(chave)
    if pac and pac.get("ativo", True) and pac.get("materiais"):
        return pac["materiais"]
    return (CONTEUDO.get(chave) or {}).get("blocos", [])


async def enviar_material(de: str, nome: str, escolha: str):
    blocos = await blocos_material(escolha)
    if not blocos:
        return
    await registrar_interesse(de, nome, escolha)
    await marcar_material(de, escolha)

    for bloco in blocos:
        t = bloco["tipo"]
        if t == "texto":
            await wa.texto(de, bloco["texto"])
        elif t == "pdf":
            await wa.pdf(de, bloco["url"], bloco.get("arquivo") or "material.pdf",
                         bloco.get("legenda", ""))
        elif t == "imagem":
            await wa.imagem(de, bloco["url"], bloco.get("legenda", ""))
        elif t == "localizacao":
            await wa.localizacao(de, bloco["lat"], bloco["lng"],
                                 bloco["nome"], bloco["endereco"])
        elif t == "contato":
            await wa.contato(de, bloco["dados"])
        await asyncio.sleep(1.5)   # preserva a ordem de entrega
