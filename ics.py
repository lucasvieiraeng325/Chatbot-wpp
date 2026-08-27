"""
Leitura de arquivos .ics (iCalendar) — o formato que o Google Agenda exporta.

Escrito à mão de propósito: uma biblioteca de calendário traria dezenas de
dependências para o Render free tier, e aqui só precisamos de VEVENT com
data, hora e título.

Uso:
    eventos = ler(conteudo_do_arquivo, ZoneInfo("America/Sao_Paulo"))
"""
import re
import hashlib
import logging
from datetime import datetime, date, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

log = logging.getLogger("sitio-bot")

# Um evento cujo título tenha uma destas palavras entra como visita.
PALAVRAS_VISITA = ("visita", "visitar", "conhecer o espa", "conhecer espa",
                   "tour", "mostrar o s", "apresenta")

# Fusos do Outlook não existem no banco IANA; cai no fuso do sítio.
_TZ_CACHE = {}


def _fuso(tzid: str, padrao):
    if not tzid:
        return padrao
    if tzid not in _TZ_CACHE:
        try:
            _TZ_CACHE[tzid] = ZoneInfo(tzid)
        except (ZoneInfoNotFoundError, ValueError, KeyError):
            log.info("ICS: fuso '%s' desconhecido, usando o do sítio", tzid)
            _TZ_CACHE[tzid] = padrao
    return _TZ_CACHE[tzid]


def _desdobrar(texto: str) -> list:
    """
    O iCalendar quebra linhas longas em 75 caracteres e continua a linha
    seguinte com um espaço. Sem desdobrar, títulos grandes chegam picados.
    """
    linhas = []
    for bruta in texto.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if bruta[:1] in (" ", "\t") and linhas:
            linhas[-1] += bruta[1:]
        else:
            linhas.append(bruta)
    return linhas


def _propriedade(linha: str):
    """NOME;PARAM=VAL:valor  ->  ("NOME", {"PARAM": "VAL"}, "valor")"""
    i, aspas = 0, False
    while i < len(linha):
        c = linha[i]
        if c == '"':
            aspas = not aspas
        elif c == ":" and not aspas:
            break
        i += 1
    else:
        return None

    cabeca, valor = linha[:i], linha[i + 1:]
    partes = cabeca.split(";")
    params = {}
    for p in partes[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            params[k.upper()] = v.strip('"')
    return partes[0].upper(), params, valor


def _texto(valor: str) -> str:
    """Desfaz o escape do iCalendar."""
    return (valor.replace("\\n", "\n").replace("\\N", "\n")
                 .replace("\\,", ",").replace("\\;", ";")
                 .replace("\\\\", "\\").strip())


def _momento(valor: str, params: dict, tz):
    """
    Devolve (dia, hora). hora=None significa evento de dia inteiro.

    Três formatos aparecem na prática:
      DTSTART;VALUE=DATE:20260827              -> dia inteiro
      DTSTART:20260827T130000Z                 -> UTC
      DTSTART;TZID=America/Sao_Paulo:20260827T100000
    """
    v = valor.strip()
    if params.get("VALUE", "").upper() == "DATE" or len(v) == 8:
        try:
            return datetime.strptime(v[:8], "%Y%m%d").date(), None
        except ValueError:
            return None, None

    bruto = v.rstrip("Z")
    try:
        d = datetime.strptime(bruto[:15], "%Y%m%dT%H%M%S")
    except ValueError:
        try:
            return datetime.strptime(v[:8], "%Y%m%d").date(), None
        except ValueError:
            return None, None

    if v.endswith("Z"):
        d = d.replace(tzinfo=timezone.utc).astimezone(tz)
    else:
        d = d.replace(tzinfo=_fuso(params.get("TZID", ""), tz)).astimezone(tz)
    return d.date(), d.time().replace(second=0, microsecond=0)


_RE_TEL = re.compile(
    r"(?:\+?\s*55[\s.-]*)?\(?\s*([1-9]\d)\s*\)?[\s.-]*(9?\d{4})[\s.-]*(\d{4})(?!\d)")


def _telefone(*textos) -> str:
    """
    Pesca um celular brasileiro no título/descrição, para o agendamento já
    nascer ligado à conversa do cliente. Na dúvida, devolve vazio.
    """
    for t in textos:
        if not t:
            continue
        for m in _RE_TEL.finditer(t):
            ddd, meio, fim = m.groups()
            numero = f"55{ddd}{meio}{fim}"
            if len(numero) in (12, 13):
                return numero
    return ""


def _tipo(titulo: str, descricao: str, padrao: str) -> str:
    alvo = f"{titulo} {descricao}".lower()
    if any(p in alvo for p in PALAVRAS_VISITA):
        return "visita"
    return padrao


def ler(conteudo: str, tz, tipo_padrao: str = "evento") -> list:
    """Lê o .ics e devolve uma lista pronta para virar agendamento."""
    eventos = []
    atual = None

    for linha in _desdobrar(conteudo):
        if not linha.strip():
            continue
        if linha.upper().startswith("BEGIN:VEVENT"):
            atual = {}
            continue
        if linha.upper().startswith("END:VEVENT"):
            if atual is not None:
                pronto = _montar(atual, tz, tipo_padrao)
                if pronto:
                    eventos.append(pronto)
            atual = None
            continue
        if atual is None:
            continue

        p = _propriedade(linha)
        if not p:
            continue
        nome, params, valor = p

        if nome == "UID":
            atual["uid"] = valor.strip()[:180]
        elif nome == "SUMMARY":
            atual["titulo"] = _texto(valor)[:120]
        elif nome == "DESCRIPTION":
            atual["descricao"] = _texto(valor)
        elif nome == "LOCATION":
            atual["local"] = _texto(valor)
        elif nome == "STATUS":
            atual["status_ics"] = valor.strip().upper()
        elif nome == "RRULE":
            atual["recorrente"] = True
        elif nome == "DTSTART":
            atual["dia"], atual["hora"] = _momento(valor, params, tz)
        elif nome == "DTEND":
            atual["fim_dia"], atual["fim_hora"] = _momento(valor, params, tz)

    eventos.sort(key=lambda e: (e["dia"], e["hora"] or datetime.min.time()))
    return eventos


def _montar(bruto: dict, tz, tipo_padrao: str):
    dia = bruto.get("dia")
    if not dia:
        return None

    titulo = bruto.get("titulo") or "Evento sem título"
    descricao = bruto.get("descricao", "")
    local = bruto.get("local", "")

    obs = []
    if descricao:
        obs.append(descricao)
    if local:
        obs.append(f"Local: {local}")
    if bruto.get("recorrente"):
        obs.append("⚠️ Evento repetido no Google — só a primeira data veio.")

    # Sem UID não há como detectar reimportação. Alguns exportadores omitem;
    # nesse caso inventamos um estável a partir do próprio evento.
    uid = bruto.get("uid", "")
    if not uid:
        marca = f"{dia}|{bruto.get('hora')}|{titulo}"
        uid = "sem-uid-" + hashlib.sha1(marca.encode()).hexdigest()[:24]

    return {
        "uid": uid,
        "tipo": _tipo(titulo, descricao, tipo_padrao),
        "titulo": titulo,
        "dia": dia,
        "hora": bruto.get("hora"),
        "cliente": "",
        "telefone": _telefone(titulo, descricao, local),
        "observacoes": "\n".join(obs)[:400],
        "status": "cancelado" if bruto.get("status_ics") == "CANCELLED" else "confirmado",
        "recorrente": bool(bruto.get("recorrente")),
    }
