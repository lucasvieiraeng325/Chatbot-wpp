"""Envio de mensagens pela WhatsApp Cloud API."""
import os
import logging
import httpx

log = logging.getLogger("sitio-bot")

TOKEN = os.getenv("WHATSAPP_TOKEN", "")
PHONE_ID = os.getenv("PHONE_NUMBER_ID", "")
API = f"https://graph.facebook.com/v21.0/{PHONE_ID}/messages"


async def enviar(payload: dict, registrar: bool = True):
    corpo = {"messaging_product": "whatsapp",
             **{k: v for k, v in payload.items() if not k.startswith("_")}}
    # Quote de mensagem: a Meta espera context.message_id no topo do payload.
    reply_to = payload.get("_reply_to") or ""
    if reply_to:
        corpo["context"] = {"message_id": reply_to}
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(
            API,
            headers={"Authorization": f"Bearer {TOKEN}"},
            json=corpo,
        )
    if r.status_code >= 400:
        log.error("Erro Meta %s: %s", r.status_code, r.text)
    elif registrar:
        await _registrar(payload, r)
    return r


async def _registrar(payload: dict, resposta):
    """Salva no histórico o que o bot enviou, para o painel do atendente."""
    try:
        from db import salvar_mensagem
    except Exception:
        return
    para = payload.get("to", "")
    t = payload.get("type")
    autor = payload.pop("_autor", "bot")
    reply_to = payload.pop("_reply_to", "") or ""
    # ID que a Meta devolveu — o painel precisa dele para permitir quote
    # da mensagem que a atendente acabou de mandar.
    wa_id = ""
    try:
        wa_id = (resposta.json().get("messages") or [{}])[0].get("id", "") or ""
    except Exception:
        pass
    try:
        if t == "text":
            await salvar_mensagem(para, "enviada", autor, payload["text"]["body"],
                                  wa_message_id=wa_id, resposta_a=reply_to)
        elif t in ("image", "audio", "video"):
            i = payload[t]
            url = i.get("link") or (f"meta:{i['id']}" if i.get("id") else "")
            await salvar_mensagem(para, "enviada", autor, i.get("caption", ""), t, url,
                                  wa_message_id=wa_id, resposta_a=reply_to)
        elif t == "document":
            d = payload["document"]
            url = d.get("link") or (f"meta:{d['id']}" if d.get("id") else "")
            await salvar_mensagem(para, "enviada", autor,
                                  d.get("caption") or d.get("filename", ""), "document", url,
                                  wa_message_id=wa_id, resposta_a=reply_to)
        elif t == "location":
            l = payload["location"]
            await salvar_mensagem(para, "enviada", autor,
                                  f"📍 {l.get('name','')}", "location", "",
                                  wa_message_id=wa_id, resposta_a=reply_to)
        elif t == "interactive":
            corpo = payload["interactive"].get("body", {}).get("text", "")
            await salvar_mensagem(para, "enviada", autor, corpo, "interactive",
                                  wa_message_id=wa_id, resposta_a=reply_to)
        elif t == "template":
            nome = payload["template"].get("name", "")
            await salvar_mensagem(para, "enviada", autor, f"[modelo: {nome}]", "template",
                                  wa_message_id=wa_id, resposta_a=reply_to)
        elif t == "contacts":
            c0 = (payload.get("contacts") or [{}])[0]
            nome = c0.get("name", {}).get("formatted_name", "contato")
            await salvar_mensagem(para, "enviada", autor,
                                  f"📇 {nome}", "contacts", "",
                                  wa_message_id=wa_id, resposta_a=reply_to)
    except Exception as e:
        log.error("Falha ao registrar mensagem: %s", e)


async def texto(para: str, msg: str, autor: str = "bot", registrar: bool = True,
                reply_to: str = ""):
    """
    registrar=False para recados internos (equipe): evita que o número
    da própria equipe vire uma "conversa" na lista do painel.
    reply_to = wa_message_id da mensagem sendo citada (opcional).
    """
    return await enviar({
        "to": para,
        "type": "text",
        "text": {"body": msg, "preview_url": False},
        "_autor": autor,
        "_reply_to": reply_to,
    }, registrar=registrar)


async def pdf(para: str, url: str, nome_arquivo: str, legenda: str = "",
              autor: str = "bot"):
    return await enviar({
        "to": para,
        "type": "document",
        "document": {"link": url, "filename": nome_arquivo, "caption": legenda},
        "_autor": autor,
    })


async def imagem(para: str, url: str, legenda: str = "", autor: str = "bot"):
    return await enviar({
        "to": para,
        "type": "image",
        "image": {"link": url, "caption": legenda},
        "_autor": autor,
    })


async def localizacao(para: str, lat: float, lng: float, nome: str, endereco: str,
                      autor: str = "bot"):
    return await enviar({
        "to": para,
        "type": "location",
        "location": {
            "latitude": lat,
            "longitude": lng,
            "name": nome,
            "address": endereco,
        },
        "_autor": autor,
    })


async def contato(para: str, dados: dict, autor: str = "bot",
                  reply_to: str = ""):
    """
    Envia um cartão de contato (tipo 'contacts' da Cloud API).

    dados aceita: nome (obrigatório), telefone, email, endereco.
    O cliente vê "Adicionar aos contatos" no próprio WhatsApp.
    """
    nome = (dados.get("nome") or "").strip() or "Contato"
    contato_meta = {"name": {"formatted_name": nome, "first_name": nome}}
    tel = "".join(c for c in str(dados.get("telefone") or "") if c.isdigit())
    if tel:
        contato_meta["phones"] = [{"phone": f"+{tel}", "type": "WORK", "wa_id": tel}]
    email = (dados.get("email") or "").strip()
    if email:
        contato_meta["emails"] = [{"email": email, "type": "WORK"}]
    endereco = (dados.get("endereco") or "").strip()
    if endereco:
        contato_meta["addresses"] = [{"street": endereco, "type": "WORK"}]
    return await enviar({
        "to": para,
        "type": "contacts",
        "contacts": [contato_meta],
        "_autor": autor,
        "_reply_to": reply_to,
    })


async def template(para: str, nome: str, idioma: str = "pt_BR",
                   parametros: list | None = None, autor: str = "bot",
                   registrar: bool = False):
    """
    Modelo aprovado na Meta — o único jeito de escrever para alguém
    fora da janela de 24h.

    Atenção: variáveis de modelo NÃO aceitam quebra de linha nem tabulação.
    Passe sempre um resumo em linha única.
    """
    corpo = {"name": nome, "language": {"code": idioma}}
    if parametros:
        corpo["components"] = [{
            "type": "body",
            "parameters": [{"type": "text", "text": str(p)} for p in parametros],
        }]
    return await enviar({
        "to": para,
        "type": "template",
        "template": corpo,
        "_autor": autor,
    }, registrar=registrar)


# ---------------------------------------------------------------
# Mídia recebida
# ---------------------------------------------------------------

async def url_da_midia(media_id: str) -> str:
    """
    A Meta não manda o arquivo, só um ID. Este endpoint devolve uma URL
    temporária — e mesmo ela exige o token para ser baixada.
    """
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(
            f"https://graph.facebook.com/v21.0/{media_id}",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
    if r.status_code >= 400:
        log.error("Erro ao consultar mídia %s: %s", media_id, r.text[:200])
        return ""
    return r.json().get("url", "")


async def baixar_midia(media_id: str):
    """Devolve (bytes, mime) do arquivo que o cliente enviou."""
    url = await url_da_midia(media_id)
    if not url:
        return None, ""
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as c:
        r = await c.get(url, headers={"Authorization": f"Bearer {TOKEN}"})
    if r.status_code >= 400:
        log.error("Erro ao baixar mídia %s: %s", media_id, r.status_code)
        return None, ""
    return r.content, r.headers.get("content-type", "")


# ---------------------------------------------------------------
# Envio de mídia pelo atendente
# ---------------------------------------------------------------

async def subir_midia(conteudo: bytes, nome: str, mime: str) -> str:
    """
    Sobe o arquivo para a Meta e devolve o media_id.
    Usar media_id evita depender de URL pública nossa.
    """
    async with httpx.AsyncClient(timeout=90) as c:
        r = await c.post(
            f"https://graph.facebook.com/v21.0/{PHONE_ID}/media",
            headers={"Authorization": f"Bearer {TOKEN}"},
            data={"messaging_product": "whatsapp", "type": mime},
            files={"file": (nome, conteudo, mime)},
        )
    if r.status_code >= 400:
        log.error("Erro ao subir mídia: %s", r.text[:300])
        return ""
    return r.json().get("id", "")


async def enviar_midia(para: str, media_id: str, tipo: str,
                       legenda: str = "", nome_arquivo: str = "",
                       autor: str = "atendente", reply_to: str = ""):
    """tipo: image | audio | document | video"""
    conteudo = {"id": media_id}
    if tipo in ("image", "video", "document") and legenda:
        conteudo["caption"] = legenda
    if tipo == "document" and nome_arquivo:
        conteudo["filename"] = nome_arquivo
    return await enviar({
        "to": para,
        "type": tipo,
        tipo: conteudo,
        "_autor": autor,
        "_reply_to": reply_to,
    })
