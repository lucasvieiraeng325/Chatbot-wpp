"""
Painel de atendimento — API.

Tela onde o atendente lê e responde as conversas do WhatsApp.
Protegida por senha simples (variável PAINEL_SENHA).
"""
import os
import hmac
import hashlib
import base64
import logging
import time

from fastapi import APIRouter, Request, Response, HTTPException, UploadFile, File, Form, UploadFile, File, Form
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse, StreamingResponse

import whatsapp as wa
import push
from db import (listar_conversas, historico, marcar_lidas,
                definir_status, salvar_mensagem, get_status,
                salvar_inscricao, remover_inscricao)

log = logging.getLogger("sitio-bot")
router = APIRouter()

SENHA = os.getenv("PAINEL_SENHA", "")
SEGREDO = os.getenv("PAINEL_SEGREDO", SENHA or "troque-isso")
DIAS = 30
COOKIE = "painel_sessao"
# Em produção o Render serve por HTTPS; em teste local o cookie precisa ser não-seguro
SEGURO = os.getenv("PAINEL_COOKIE_SEGURO", "1") != "0"


def _assinar(expira: int) -> str:
    msg = str(expira).encode()
    sig = hmac.new(SEGREDO.encode(), msg, hashlib.sha256).digest()
    return f"{expira}.{base64.urlsafe_b64encode(sig).decode().rstrip('=')}"


def _valido(token: str) -> bool:
    try:
        expira_str, _ = token.split(".", 1)
        expira = int(expira_str)
    except (ValueError, AttributeError):
        return False
    if expira < time.time():
        return False
    return hmac.compare_digest(token, _assinar(expira))


def _exige_login(request: Request):
    if not SENHA:
        raise HTTPException(503, "Painel sem senha configurada (PAINEL_SENHA)")
    if not _valido(request.cookies.get(COOKIE, "")):
        raise HTTPException(401, "Sessão expirada")


# ---------------------------------------------------------------
# Tela
# ---------------------------------------------------------------
@router.get("/painel")
def painel():
    caminho = os.path.join(os.path.dirname(__file__), "painel.html")
    if not os.path.exists(caminho):
        raise HTTPException(404, "painel.html não encontrado")
    return FileResponse(caminho, media_type="text/html")


# ---------------------------------------------------------------
# Sessão
# ---------------------------------------------------------------
@router.post("/api/login")
async def login(request: Request):
    if not SENHA:
        return JSONResponse({"erro": "Painel sem senha configurada"}, 503)
    dados = await request.json()
    if not hmac.compare_digest(str(dados.get("senha", "")), SENHA):
        return JSONResponse({"erro": "Senha incorreta"}, 401)

    expira = int(time.time()) + DIAS * 86400
    r = JSONResponse({"ok": True})
    r.set_cookie(COOKIE, _assinar(expira), max_age=DIAS * 86400,
                 httponly=True, samesite="lax", secure=SEGURO)
    return r


@router.get("/api/sessao")
def sessao(request: Request):
    return {"autenticado": _valido(request.cookies.get(COOKIE, ""))}


@router.post("/api/sair")
def sair():
    r = JSONResponse({"ok": True})
    r.delete_cookie(COOKIE)
    return r


# ---------------------------------------------------------------
# Conversas
# ---------------------------------------------------------------
@router.get("/api/conversas")
async def conversas(request: Request):
    _exige_login(request)
    itens = await listar_conversas()
    for i in itens:
        if i.get("ultimo_contato"):
            i["ultimo_contato"] = i["ultimo_contato"].isoformat()
        i["interesses"] = list(i.get("interesses") or [])
    return {"conversas": itens}


@router.get("/api/mensagens/{telefone}")
async def mensagens(telefone: str, request: Request):
    _exige_login(request)
    msgs = await historico(telefone)
    await marcar_lidas(telefone)
    for m in msgs:
        m["criado_em"] = m["criado_em"].isoformat()
    return {"mensagens": msgs, "status": await get_status(telefone)}


@router.post("/api/enviar")
async def enviar(request: Request):
    _exige_login(request)
    dados = await request.json()
    telefone = (dados.get("telefone") or "").strip()
    texto = (dados.get("texto") or "").strip()
    if not telefone or not texto:
        return JSONResponse({"erro": "Informe o telefone e a mensagem"}, 400)

    r = await wa.enviar({
        "to": telefone,
        "type": "text",
        "text": {"body": texto, "preview_url": False},
        "_autor": "atendente",
    })
    if r.status_code >= 400:
        detalhe = ""
        try:
            detalhe = r.json().get("error", {}).get("message", "")
        except Exception:
            pass
        if "24" in detalhe or "131047" in str(detalhe):
            detalhe = ("Passaram mais de 24h desde a última mensagem do cliente. "
                       "O WhatsApp só permite retomar com modelo aprovado.")
        return JSONResponse({"erro": detalhe or "O WhatsApp recusou o envio"}, 502)

    return {"ok": True}


@router.post("/api/assumir/{telefone}")
async def assumir(telefone: str, request: Request):
    """Pausa o bot: a conversa passa a ser do atendente."""
    _exige_login(request)
    await definir_status(telefone, "humano")
    return {"ok": True, "status": "humano"}


@router.post("/api/devolver/{telefone}")
async def devolver(telefone: str, request: Request):
    """Devolve a conversa ao bot."""
    _exige_login(request)
    await definir_status(telefone, "bot")
    return {"ok": True, "status": "bot"}


# ---------------------------------------------------------------
# Arquivos do app instalável (PWA)
# ---------------------------------------------------------------
def _arquivo(nome: str, tipo: str):
    caminho = os.path.join(os.path.dirname(__file__), nome)
    if not os.path.exists(caminho):
        raise HTTPException(404, f"{nome} não encontrado")
    return FileResponse(caminho, media_type=tipo)


@router.get("/sw.js")
def service_worker():
    # Precisa ser servido da raiz para controlar todo o site
    r = _arquivo("sw.js", "application/javascript")
    r.headers["Service-Worker-Allowed"] = "/"
    r.headers["Cache-Control"] = "no-cache"
    return r


@router.get("/manifest.json")
def manifest():
    return _arquivo("manifest.json", "application/manifest+json")


@router.get("/icone-192.png")
def icone_192():
    return _arquivo("icone-192.png", "image/png")


@router.get("/icone-512.png")
def icone_512():
    return _arquivo("icone-512.png", "image/png")


# ---------------------------------------------------------------
# Notificações
# ---------------------------------------------------------------
@router.get("/api/push/chave")
def chave_push(request: Request):
    _exige_login(request)
    return {"chave": push.CHAVE_PUBLICA, "ativo": push.ativo}


@router.post("/api/push/inscrever")
async def inscrever(request: Request):
    _exige_login(request)
    dados = await request.json()
    endpoint = dados.get("endpoint")
    if not endpoint:
        return JSONResponse({"erro": "Inscrição inválida"}, 400)
    import json as _json
    await salvar_inscricao(endpoint, _json.dumps(dados))
    return {"ok": True}


@router.post("/api/push/cancelar")
async def cancelar(request: Request):
    _exige_login(request)
    dados = await request.json()
    if dados.get("endpoint"):
        await remover_inscricao(dados["endpoint"])
    return {"ok": True}


@router.post("/api/push/testar")
async def testar(request: Request):
    _exige_login(request)
    await push.notificar("🌻 Teste", "As notificações estão funcionando.", urgente=False)
    return {"ok": True}


# ---------------------------------------------------------------
# Mídia
# ---------------------------------------------------------------
MIMES = {
    "image": {"image/jpeg", "image/png", "image/webp"},
    "audio": {"audio/aac", "audio/mp4", "audio/mpeg", "audio/amr", "audio/ogg"},
    "video": {"video/mp4", "video/3gpp"},
}
LIMITE_MB = {"image": 5, "audio": 16, "video": 16, "document": 95}


@router.get("/api/midia/{media_id}")
async def midia(media_id: str, request: Request):
    """Busca o arquivo na Meta e devolve ao painel. Nada é armazenado aqui."""
    _exige_login(request)
    conteudo, mime = await wa.baixar_midia(media_id)
    if not conteudo:
        raise HTTPException(404, "Arquivo indisponível. A Meta guarda mídias por 30 dias.")
    return Response(content=conteudo, media_type=mime or "application/octet-stream",
                    headers={"Cache-Control": "private, max-age=3600"})


@router.post("/api/enviar-midia")
async def enviar_midia(request: Request,
                       telefone: str = Form(...),
                       legenda: str = Form(""),
                       arquivo: UploadFile = File(...)):
    _exige_login(request)

    conteudo = await arquivo.read()
    mime = (arquivo.content_type or "").split(";")[0].strip()
    nome = arquivo.filename or "arquivo"

    # O navegador grava em WebM; a Cloud API só aceita OGG/Opus.
    # Também cobre áudios enviados em formatos que a Meta não reconhece.
    if mime.startswith("audio/") and mime not in MIMES["audio"]:
        from midia import para_ogg
        convertido = await para_ogg(conteudo)
        if convertido is None:
            return JSONResponse(
                {"erro": "Não foi possível preparar o áudio para envio."}, 400)
        conteudo, mime = convertido, "audio/ogg"
        nome = os.path.splitext(nome)[0] + ".ogg"

    if mime in MIMES["image"]:
        tipo = "image"
    elif mime in MIMES["audio"]:
        tipo = "audio"
    elif mime in MIMES["video"]:
        tipo = "video"
    else:
        tipo = "document"

    limite = LIMITE_MB[tipo] * 1024 * 1024
    if len(conteudo) > limite:
        return JSONResponse(
            {"erro": f"Arquivo muito grande. O limite para {tipo} é {LIMITE_MB[tipo]} MB."}, 400)

    media_id = await wa.subir_midia(conteudo, nome, mime)
    if not media_id:
        return JSONResponse({"erro": "O WhatsApp não aceitou este arquivo"}, 502)

    r = await wa.enviar_midia(telefone, media_id, tipo,
                              legenda=legenda, nome_arquivo=nome)
    if r.status_code >= 400:
        detalhe = ""
        try:
            detalhe = r.json().get("error", {}).get("message", "")
        except Exception:
            pass
        if "24" in detalhe or "131047" in str(detalhe):
            detalhe = ("Passaram mais de 24h desde a última mensagem do cliente. "
                       "O WhatsApp só permite retomar com modelo aprovado.")
        return JSONResponse({"erro": detalhe or "O WhatsApp recusou o envio"}, 502)

    return {"ok": True, "tipo": tipo}
