"""
Google Agenda — espelha os agendamentos do painel num calendário do Google.

Cada visita/evento criado, editado ou excluído no painel é refletido numa
agenda compartilhada (ex: "Sítio Girassol – Agenda"), que as contas da
equipe veem no Google Agenda do celular.

Configuração (Render → Environment):
  GOOGLE_CREDENCIAIS   conteúdo inteiro do .json da conta de serviço
  GOOGLE_CALENDAR_ID   ID da agenda (…@group.calendar.google.com)

A agenda precisa estar compartilhada com o e-mail da conta de serviço
com a permissão "Fazer alterações nos eventos".

Falhar aqui nunca desfaz nada no painel: o Google é um espelho.
"""
import os
import json
import asyncio
import logging
from datetime import date, datetime, timedelta

import httpx

log = logging.getLogger("sitio-bot")

CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "").strip()
TZ_NOME = os.getenv("TIMEZONE", "America/Sao_Paulo")
NOME_SITIO = os.getenv("NOME_SITIO", "Sítio Girassol")

# Duração padrão quando o compromisso tem hora (o painel só guarda o início)
DURACAO_MIN = {
    "visita": int(os.getenv("AGENDA_DURACAO_VISITA_MIN", "60")),
    "evento": int(os.getenv("AGENDA_DURACAO_EVENTO_MIN", "300")),
}
# Cores do Google Agenda: 10 = manjericão (verde), 5 = banana (amarelo)
COR = {"visita": "10", "evento": "5"}

API = "https://www.googleapis.com/calendar/v3/calendars/{cal}/events"
ESCOPO = ["https://www.googleapis.com/auth/calendar.events"]

_credenciais = None
_erro_config = ""
try:
    _bruto = os.getenv("GOOGLE_CREDENCIAIS", "").strip()
    if _bruto and CALENDAR_ID:
        from google.oauth2 import service_account
        _credenciais = service_account.Credentials.from_service_account_info(
            json.loads(_bruto), scopes=ESCOPO)
except Exception as e:  # JSON colado errado não pode derrubar o boot
    _erro_config = f"GOOGLE_CREDENCIAIS inválido: {e}"
    log.error("Google Agenda: %s", _erro_config)

ativo = _credenciais is not None
if not ativo and not _erro_config:
    log.info("Google Agenda desativado — defina GOOGLE_CREDENCIAIS e GOOGLE_CALENDAR_ID")

# Um lock por agendamento: evita criar dois eventos quando o atendente
# salva duas vezes seguidas antes do primeiro envio terminar.
_travas: dict = {}


def _trava(id_: int) -> asyncio.Lock:
    if id_ not in _travas:
        _travas[id_] = asyncio.Lock()
    return _travas[id_]


async def _token() -> str:
    """O refresh do google-auth é síncrono — roda numa thread."""
    if not _credenciais.valid:
        from google.auth.transport.requests import Request
        await asyncio.to_thread(_credenciais.refresh, Request())
    return _credenciais.token


async def _chamar(metodo: str, sufixo: str = "", corpo: dict | None = None):
    url = API.format(cal=_escapar(CALENDAR_ID)) + sufixo
    async with httpx.AsyncClient(timeout=20) as c:
        return await c.request(
            metodo, url,
            headers={"Authorization": f"Bearer {await _token()}"},
            json=corpo,
        )


def _escapar(s: str) -> str:
    from urllib.parse import quote
    return quote(s, safe="")


def _corpo(ag: dict) -> dict:
    """Agendamento do painel → evento do Google."""
    tipo = ag.get("tipo") or "visita"
    icone = "🚗" if tipo == "visita" else "🎉"
    titulo = ag.get("titulo") or "Compromisso"
    if ag.get("status") == "pendente":
        titulo = f"⚠️ {titulo} (a confirmar)"

    linhas = []
    quem = ag.get("cliente") or ag.get("nome_lead") or ""
    if quem:
        linhas.append(f"Cliente: {quem}")
    if ag.get("telefone"):
        linhas.append(f"WhatsApp: https://wa.me/{ag['telefone']}")
    if ag.get("observacoes"):
        linhas.append("")
        linhas.append(ag["observacoes"])
    linhas.append("")
    linhas.append(f"Criado no painel do {NOME_SITIO} — edite por lá para não perder a alteração.")

    dia = ag["dia"]
    if isinstance(dia, str):
        dia = date.fromisoformat(dia[:10])
    hora = ag.get("hora")

    if hora:
        inicio = datetime.combine(dia, hora)
        fim = inicio + timedelta(minutes=DURACAO_MIN.get(tipo, 60))
        quando = {
            "start": {"dateTime": inicio.isoformat(), "timeZone": TZ_NOME},
            "end": {"dateTime": fim.isoformat(), "timeZone": TZ_NOME},
        }
    else:
        quando = {
            "start": {"date": dia.isoformat()},
            "end": {"date": (dia + timedelta(days=1)).isoformat()},
        }

    return {
        "summary": f"{icone} {titulo}",
        "description": "\n".join(linhas),
        "colorId": COR.get(tipo, "10"),
        "status": "confirmed",
        # Marca de origem: permite reconhecer o que o app criou caso um dia
        # a agenda do Google também seja lida de volta para o painel.
        "extendedProperties": {"private": {"sitio_id": str(ag["id"])}},
        **quando,
    }


async def sincronizar(ag: dict) -> None:
    """
    Cria, atualiza ou remove o evento do agendamento no Google.
    Cancelado → remove do Google. Grava o id do evento no banco.
    """
    if not ativo or not ag or not ag.get("id"):
        return
    # Importado de um .ics: já existe num Google Agenda — espelhar duplicaria.
    if ag.get("uid"):
        return
    from db import definir_gcal_id

    async with _trava(ag["id"]):
        gid = ag.get("gcal_id") or ""
        try:
            if ag.get("status") == "cancelado":
                if gid:
                    await remover(gid)
                    await definir_gcal_id(ag["id"], "")
                return

            corpo = _corpo(ag)
            if gid:
                r = await _chamar("PUT", f"/{_escapar(gid)}", corpo)
                if r.status_code in (404, 410):
                    gid = ""   # apagaram no Google: recria
                elif r.status_code >= 400:
                    log.error("Google Agenda: falha ao atualizar %s — %s",
                              ag["id"], r.text[:300])
                    return
            if not gid:
                r = await _chamar("POST", "", corpo)
                if r.status_code >= 400:
                    log.error("Google Agenda: falha ao criar %s — %s",
                              ag["id"], r.text[:300])
                    return
                await definir_gcal_id(ag["id"], r.json().get("id", ""))
            log.info("Google Agenda: agendamento %s sincronizado", ag["id"])
        except Exception as e:
            log.error("Google Agenda: erro ao sincronizar %s — %s", ag.get("id"), e)


async def remover(gcal_id: str) -> None:
    if not ativo or not gcal_id:
        return
    try:
        r = await _chamar("DELETE", f"/{_escapar(gcal_id)}")
        if r.status_code >= 400 and r.status_code not in (404, 410):
            log.error("Google Agenda: falha ao remover %s — %s", gcal_id, r.text[:300])
    except Exception as e:
        log.error("Google Agenda: erro ao remover %s — %s", gcal_id, e)


async def enviar_pendentes() -> int:
    """
    Manda para o Google os compromissos futuros que ainda não estão lá.
    Roda no boot: cobre o que já existia antes da integração e o que
    falhou por o Google estar fora do ar. Importados do .ics ficam de
    fora — já vieram de um Google Agenda e duplicariam.
    """
    if not ativo:
        return 0
    from db import agendamentos_sem_gcal
    from zoneinfo import ZoneInfo
    hoje = datetime.now(ZoneInfo(TZ_NOME)).date()
    itens = await agendamentos_sem_gcal(hoje)
    for ag in itens:
        await sincronizar(ag)
        await asyncio.sleep(0.3)   # folga na cota da API
    if itens:
        log.info("Google Agenda: %d compromisso(s) enviados no boot", len(itens))
    return len(itens)


async def diagnostico() -> dict:
    """Usado pelo painel para mostrar se a integração está de pé."""
    if _erro_config:
        return {"ativo": False, "erro": _erro_config}
    if not ativo:
        return {"ativo": False,
                "erro": "Defina GOOGLE_CREDENCIAIS e GOOGLE_CALENDAR_ID no Render"}
    try:
        r = await _chamar("GET", "?maxResults=1")
        if r.status_code == 404:
            return {"ativo": False, "erro": (
                "Agenda não encontrada. Confira o GOOGLE_CALENDAR_ID e se a agenda "
                f"foi compartilhada com {_credenciais.service_account_email}")}
        if r.status_code == 403:
            return {"ativo": False, "erro": (
                f"Sem permissão. Compartilhe a agenda com {_credenciais.service_account_email} "
                "como 'Fazer alterações nos eventos'")}
        if r.status_code >= 400:
            return {"ativo": False, "erro": r.text[:300]}
        return {"ativo": True, "robo": _credenciais.service_account_email}
    except Exception as e:
        return {"ativo": False, "erro": str(e)[:300]}
