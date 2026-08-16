"""Lógica de roteamento das mensagens recebidas."""
import os
import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

import whatsapp as wa
from menu import menu_principal, voltar_menu
from content import CONTEUDO, ATALHOS
from db import registrar_interesse, get_status, marcar_humano, get_interesses

log = logging.getLogger("sitio-bot")

TZ = ZoneInfo(os.getenv("TIMEZONE", "America/Sao_Paulo"))
HORA_ABRE = int(os.getenv("HORA_ABRE", "7"))
HORA_FECHA = int(os.getenv("HORA_FECHA", "22"))

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


def dentro_do_horario() -> bool:
    h = datetime.now(TZ).hour
    return HORA_ABRE <= h < HORA_FECHA


async def notificar(telefone: str, nome: str, motivo: str):
    """Avisa o dono do sítio no Telegram."""
    if not TELEGRAM_TOKEN:
        log.info("LEAD: %s (%s) — %s", nome, telefone, motivo)
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

    # Bot pausado: atendente humano assumiu a conversa
    if await get_status(de) == "humano":
        return

    # Mídia recebida — a Fase 1 não interpreta áudio/imagem
    if msg.get("type") in ("audio", "image", "video", "document", "sticker"):
        await wa.texto(de, (
            "Recebi seu arquivo! 🌿 Por aqui consigo ler apenas texto, "
            "mas já avisei um atendente para te responder."
        ))
        await marcar_humano(de, nome)
        await notificar(de, nome, "enviou mídia")
        return

    escolha = extrair_escolha(msg)

    if escolha == "humano":
        await marcar_humano(de, nome)
        aviso = ("Perfeito! Um atendente vai te responder em instantes. 🌿"
                 if dentro_do_horario() else
                 f"Perfeito! Nosso atendimento é das {HORA_ABRE}h às {HORA_FECHA}h — "
                 "um atendente te responde assim que abrirmos. 🌿")
        await wa.texto(de, aviso)
        await notificar(de, nome, "pediu atendente")
        return

    # Primeira interação fora do horário: avisa, mas continua atendendo
    if not dentro_do_horario() and escolha is None:
        await wa.texto(de, (
            f"Olá! 🌿 Nosso atendimento humano é das {HORA_ABRE}h às {HORA_FECHA}h, "
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
