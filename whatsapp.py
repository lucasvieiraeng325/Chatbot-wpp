"""Envio de mensagens pela WhatsApp Cloud API."""
import os
import logging
import httpx

log = logging.getLogger("sitio-bot")

TOKEN = os.getenv("WHATSAPP_TOKEN", "")
PHONE_ID = os.getenv("PHONE_NUMBER_ID", "")
API = f"https://graph.facebook.com/v21.0/{PHONE_ID}/messages"


async def enviar(payload: dict):
    corpo = {"messaging_product": "whatsapp", **payload}
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(
            API,
            headers={"Authorization": f"Bearer {TOKEN}"},
            json=corpo,
        )
    if r.status_code >= 400:
        log.error("Erro Meta %s: %s", r.status_code, r.text)
    return r


async def texto(para: str, msg: str):
    return await enviar({
        "to": para,
        "type": "text",
        "text": {"body": msg, "preview_url": False},
    })


async def pdf(para: str, url: str, nome_arquivo: str, legenda: str = ""):
    return await enviar({
        "to": para,
        "type": "document",
        "document": {"link": url, "filename": nome_arquivo, "caption": legenda},
    })


async def imagem(para: str, url: str, legenda: str = ""):
    return await enviar({
        "to": para,
        "type": "image",
        "image": {"link": url, "caption": legenda},
    })


async def localizacao(para: str, lat: float, lng: float, nome: str, endereco: str):
    return await enviar({
        "to": para,
        "type": "location",
        "location": {
            "latitude": lat,
            "longitude": lng,
            "name": nome,
            "address": endereco,
        },
    })
