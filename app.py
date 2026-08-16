"""
Bot de atendimento — Sítio de Eventos (Fase 1: catálogo)
FastAPI + WhatsApp Cloud API + Render Free
"""
import os
import logging
from fastapi import FastAPI, Request, Response, BackgroundTasks
from fastapi.staticfiles import StaticFiles

from handlers import processar_mensagem
from db import init_db, ja_processada

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("sitio-bot")

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "")

app = FastAPI(title="Bot Sítio de Eventos")

# Serve as mídias: https://SEU-APP.onrender.com/images/piscina.png
# Monta só o que existe — pasta ausente vira aviso no log, não crash no boot.
for _pasta in ("images", "pdfs"):
    if os.path.isdir(_pasta):
        app.mount(f"/{_pasta}", StaticFiles(directory=_pasta), name=_pasta)
    else:
        log.warning("Pasta '%s' não encontrada — essas mídias não serão servidas", _pasta)


@app.on_event("startup")
async def startup():
    await init_db()
    log.info("Bot iniciado")


@app.get("/health")
def health():
    """Endpoint leve para o ping do cron externo. NÃO consulta o banco."""
    return Response(content="ok", media_type="text/plain")


@app.get("/")
def home():
    return {"status": "online", "servico": "Bot Sítio de Eventos"}


# ---------------------------------------------------------------
# 1) Verificação do webhook (a Meta chama uma vez, no cadastro)
# ---------------------------------------------------------------
@app.get("/webhook")
def verificar(request: Request):
    params = request.query_params
    if (params.get("hub.mode") == "subscribe"
            and params.get("hub.verify_token") == VERIFY_TOKEN):
        # Precisa ser texto puro, não JSON
        return Response(content=params.get("hub.challenge", ""),
                        media_type="text/plain")
    return Response(status_code=403)


# ---------------------------------------------------------------
# 2) Recebimento de mensagens
# ---------------------------------------------------------------
@app.post("/webhook")
async def receber(request: Request, bg: BackgroundTasks):
    body = await request.json()

    try:
        value = body["entry"][0]["changes"][0]["value"]
        msg = value["messages"][0]
    except (KeyError, IndexError):
        # Payload de status de entrega (sent/delivered/read) — ignora
        return Response(status_code=200)

    nome = "cliente"
    try:
        nome = value["contacts"][0]["profile"]["name"].split()[0]
    except (KeyError, IndexError):
        pass

    # Deduplicação: essencial no Free tier, porque o cold start
    # faz a Meta reenviar o mesmo evento 2-3 vezes.
    if await ja_processada(msg["id"]):
        log.info("Duplicata ignorada: %s", msg["id"])
        return Response(status_code=200)

    # Processa DEPOIS de responder 200 — a Meta espera resposta rápida
    bg.add_task(processar_mensagem, msg, nome)
    return Response(status_code=200)
