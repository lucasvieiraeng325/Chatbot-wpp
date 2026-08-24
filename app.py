"""
Bot de atendimento — Sítio de Eventos (Fase 1: catálogo)
FastAPI + WhatsApp Cloud API + Render Free
"""
import os
import logging
from fastapi import FastAPI, Request, Response, BackgroundTasks
from fastapi.staticfiles import StaticFiles

from handlers import processar_mensagem
from db import init_db, ja_processada, salvar_mensagem

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("sitio-bot")

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "")

app = FastAPI(title="Bot Sítio de Eventos")

# Painel de atendimento (/painel)
from painel import router as painel_router
app.include_router(painel_router)

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

    bg.add_task(_registrar_recebida, msg, nome)

    # Processa DEPOIS de responder 200 — a Meta espera resposta rápida
    bg.add_task(processar_mensagem, msg, nome)
    return Response(status_code=200)


async def _registrar_recebida(msg: dict, nome: str = ""):
    """Grava no histórico a mensagem que o cliente enviou e avisa o painel."""
    import push
    from db import get_status
    de = msg["from"]
    t = msg.get("type")
    resumo = ""
    try:
        if t == "text":
            resumo = msg["text"]["body"]
            await salvar_mensagem(de, "recebida", "cliente", resumo)
        elif t == "interactive":
            it = msg["interactive"]
            titulo = (it.get("list_reply") or it.get("button_reply") or {}).get("title", "")
            resumo = f"Escolheu: {titulo}"
            await salvar_mensagem(de, "recebida", "cliente", f"[{titulo}]")
        else:
            rotulo = {"audio": "Enviou um áudio", "image": "Enviou uma imagem",
                      "video": "Enviou um vídeo", "document": "Enviou um arquivo"}
            resumo = rotulo.get(t, f"Enviou {t}")
            # Guarda o media_id: o arquivo é buscado na Meta quando o
            # atendente abrir, evitando armazenar nada aqui.
            mid = (msg.get(t) or {}).get("id", "")
            legenda = (msg.get(t) or {}).get("caption", "")
            await salvar_mensagem(de, "recebida", "cliente",
                                  legenda or resumo, t,
                                  f"meta:{mid}" if mid else "")
    except Exception as e:
        log.error("Falha ao registrar recebida: %s", e)

    # Só avisa quando a conversa está com o atendente — enquanto o bot
    # responde sozinho, notificar cada clique de menu seria ruído.
    try:
        if await get_status(de) == "humano":
            await push.nova_mensagem(de, nome, resumo)
    except Exception as e:
        log.error("Falha ao notificar: %s", e)
