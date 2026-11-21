"""
Painel de atendimento — API.

Tela onde o atendente lê e responde as conversas do WhatsApp.
Protegida por senha simples (variável PAINEL_SENHA).

A aba Agenda vive em agenda.py e reaproveita o _exige_login daqui.
"""
import os
import csv
import hmac
import hashlib
import base64
import io
import logging
import time
from datetime import datetime, timedelta, time as _time
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request, Response, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

import whatsapp as wa
from content import ASSINATURA_REP
import push
from db import (listar_conversas, historico, marcar_lidas,
                definir_status, salvar_mensagem, get_status, get_nome,
                salvar_inscricao, remover_inscricao,
                leads_por_bucket, distribuicao_interesses,
                total_leads_periodo, leads_para_exportar,
                get_ficha, resetar_cliente, definir_bloqueio, agenda_por_telefone,
                atualizar_ficha, ETAPAS, listar_pacotes, salvar_pacote,
                remover_pacote, salvar_arquivo, obter_arquivo)

log = logging.getLogger("sitio-bot")
router = APIRouter()

TZ = ZoneInfo(os.getenv("TIMEZONE", "America/Sao_Paulo"))
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
    itens = await listar_conversas(hoje=datetime.now(TZ).date())
    for i in itens:
        if i.get("ultimo_contato"):
            i["ultimo_contato"] = i["ultimo_contato"].isoformat()
        i["interesses"] = list(i.get("interesses") or [])
        # Agendamento em destaque, para exibir e para a busca alcançar
        i["agenda"] = ({
            "dia": i["ag_dia"].isoformat(),
            "hora": i["ag_hora"].strftime("%H:%M") if i.get("ag_hora") else None,
            "tipo": i.get("ag_tipo") or "visita",
            "titulo": i.get("ag_titulo") or "",
        } if i.get("ag_dia") else None)
        i["etapa_rotulo"] = dict(ETAPAS).get(i.get("etapa") or "novo", "")
        for k in ("ag_dia", "ag_hora", "ag_tipo", "ag_titulo"):
            i.pop(k, None)
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
    resposta_a = (dados.get("resposta_a") or "").strip()
    if not telefone or not texto:
        return JSONResponse({"erro": "Informe o telefone e a mensagem"}, 400)

    # Assinatura: o cliente distingue a pessoa da equipe da assistente virtual.
    if not texto.startswith(ASSINATURA_REP):
        texto = f"{ASSINATURA_REP}\n\n{texto}"

    r = await wa.enviar({
        "to": telefone,
        "type": "text",
        "text": {"body": texto, "preview_url": False},
        "_autor": "atendente",
        "_reply_to": resposta_a,
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


# ---------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------
TZ_NOME = os.getenv("TIMEZONE", "America/Sao_Paulo")

# Rotulos dos interesses conhecidos, para a legenda ler bonito. Chave nao
# mapeada aparece com o nome cru — nao esconde nada novo que apareca.
ROTULO_INTERESSE = {
    "casamento": "Casamento",
    "quinze": "15 anos",
    "infantil": "Infantil",
    "confraternizacao": "Aniversário/Confraternização",
    "decorado": "Espaço decorado",
    "locacao": "Locação do espaço",
    "fotos": "Fotos do espaço",
    "localizacao": "Localização",
    "regras": "Informações",
    "humano": "Falou com atendente",
}


def _janela(periodo: str):
    """
    Devolve (inicio, fim, unidade, buckets_esperados).

    inicio/fim: datetimes em UTC (timestamptz do banco esta em UTC),
    unidade: string aceita por date_trunc.
    buckets_esperados: lista de datetimes NO FUSO LOCAL, que o front
    pode consumir direto sem pensar em UTC.
    """
    tz = ZoneInfo(TZ_NOME)
    agora_local = datetime.now(tz)
    if periodo == "diaria":
        inicio_local = datetime.combine(agora_local.date(), _time.min).replace(tzinfo=tz)
        fim_local = inicio_local + timedelta(days=1)
        buckets = [inicio_local + timedelta(hours=h) for h in range(24)]
        unidade = "hour"
    elif periodo == "semanal":
        base = datetime.combine(agora_local.date(), _time.min).replace(tzinfo=tz)
        inicio_local = base - timedelta(days=6)
        fim_local = base + timedelta(days=1)
        buckets = [inicio_local + timedelta(days=d) for d in range(7)]
        unidade = "day"
    elif periodo == "mensal":
        base = datetime.combine(agora_local.date(), _time.min).replace(tzinfo=tz)
        inicio_local = base - timedelta(days=29)
        fim_local = base + timedelta(days=1)
        buckets = [inicio_local + timedelta(days=d) for d in range(30)]
        unidade = "day"
    elif periodo == "anual":
        # 12 meses cheios contando o atual, comecando pelo primeiro dia do mes
        primeiro = agora_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        # Volta 11 meses
        y, m = primeiro.year, primeiro.month
        m2, y2 = m - 11, y
        while m2 <= 0:
            m2 += 12
            y2 -= 1
        inicio_local = primeiro.replace(year=y2, month=m2)
        # Fim = inicio do proximo mes
        prox_m, prox_y = (primeiro.month + 1, primeiro.year) if primeiro.month < 12 else (1, primeiro.year + 1)
        fim_local = primeiro.replace(year=prox_y, month=prox_m)
        buckets = []
        cur_y, cur_m = y2, m2
        for _ in range(12):
            buckets.append(datetime(cur_y, cur_m, 1, tzinfo=tz))
            cur_m += 1
            if cur_m > 12:
                cur_m = 1
                cur_y += 1
        unidade = "month"
    else:
        raise HTTPException(400, "periodo deve ser diaria|semanal|mensal|anual")

    return inicio_local, fim_local, unidade, buckets


def _formatar_bucket(dt: datetime, periodo: str) -> str:
    """Rótulo curto para o eixo X do gráfico."""
    if periodo == "diaria":
        return f"{dt.hour:02d}h"
    if periodo == "semanal":
        return dt.strftime("%a %d/%m").lower()
    if periodo == "mensal":
        return dt.strftime("%d/%m")
    if periodo == "anual":
        meses = ["jan", "fev", "mar", "abr", "mai", "jun",
                 "jul", "ago", "set", "out", "nov", "dez"]
        return f"{meses[dt.month - 1]}/{dt.year % 100:02d}"
    return dt.isoformat()


@router.get("/api/analytics")
async def analytics(request: Request, periodo: str = "semanal"):
    _exige_login(request)
    inicio, fim, unidade, buckets = _janela(periodo)

    dados = await leads_por_bucket(inicio, fim, TZ_NOME, unidade)
    interesses = await distribuicao_interesses(inicio, fim)
    total = await total_leads_periodo(inicio, fim)

    # Casa os buckets esperados com o que o banco devolveu — o banco
    # nao retorna bucket vazio, e o gráfico precisa de todos para o eixo.
    contagens = {}
    for d in dados:
        b = d["bucket"]
        # Se veio sem tzinfo (naive) do driver, assume TZ local — o
        # date_trunc(...) AT TIME ZONE devolve timestamp sem fuso.
        if b.tzinfo is None:
            b = b.replace(tzinfo=ZoneInfo(TZ_NOME))
        contagens[b.replace(tzinfo=None)] = d["count"]

    serie = []
    for b in buckets:
        chave = b.replace(tzinfo=None)
        serie.append({
            "rotulo": _formatar_bucket(b, periodo),
            "iso": b.isoformat(),
            "count": contagens.get(chave, 0),
        })

    dias_no_periodo = max(1, (fim - inicio).days) if periodo != "diaria" else 1
    return {
        "periodo": periodo,
        "inicio": inicio.isoformat(),
        "fim": fim.isoformat(),
        "total": total,
        "media_por_dia": round(total / dias_no_periodo, 1) if periodo != "diaria" else total,
        "pico": max((s["count"] for s in serie), default=0),
        "serie": serie,
        "interesses": [
            {"chave": i["interesse"],
             "rotulo": ROTULO_INTERESSE.get(i["interesse"], i["interesse"]),
             "count": i["count"]}
            for i in interesses
        ],
    }


@router.get("/api/exportar-leads.csv")
async def exportar_leads(request: Request):
    _exige_login(request)
    rows = await leads_para_exportar()

    buf = io.StringIO()
    escritor = csv.writer(buf, delimiter=";")  # ; abre certo no Excel BR
    escritor.writerow([
        "telefone", "nome", "primeiro_contato", "ultimo_contato",
        "interesses", "status", "nao_lidas",
    ])
    for r in rows:
        escritor.writerow([
            r.get("telefone", ""),
            r.get("nome") or "",
            r["primeiro_contato"].isoformat() if r.get("primeiro_contato") else "",
            r["ultimo_contato"].isoformat() if r.get("ultimo_contato") else "",
            ", ".join(r.get("interesses") or []),
            r.get("status", ""),
            r.get("nao_lidas", 0),
        ])
    conteudo = "﻿" + buf.getvalue()  # BOM para Excel abrir com acento
    hoje = datetime.now(ZoneInfo(TZ_NOME)).strftime("%Y-%m-%d")
    return Response(
        content=conteudo,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="leads-sitio-{hoje}.csv"'},
    )


# ---------------------------------------------------------------
# Pacotes e tabela de preços estimados (aba Preços)
# ---------------------------------------------------------------
def _slug(nome: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode().lower()
    t = "".join(c if c.isalnum() else "_" for c in t).strip("_")
    while "__" in t:
        t = t.replace("__", "_")
    return t[:30] or "pacote"


def _normalizar_pacote(d: dict) -> dict:
    """Valida e limpa o pacote vindo do painel. Levanta ValueError com a
    mensagem para o representante."""
    def texto(v, limite, campo):
        v = str(v or "").strip()
        if not v:
            raise ValueError(f"Preencha {campo}.")
        return v[:limite]

    nome = texto(d.get("nome"), 40, "o nome do pacote")
    variacao = d.get("variacao")
    if variacao not in ("dia", "livre"):
        raise ValueError("Escolha se o preço varia pelo dia ou por outra opção.")
    colunas = [texto(c, 30, "o nome de cada coluna") for c in (d.get("colunas") or [])]
    if variacao == "dia" and len(colunas) != 2:
        raise ValueError("Preço por dia precisa de 2 colunas: semana e fim de semana.")
    if not 1 <= len(colunas) <= 4:
        raise ValueError("Use de 1 a 4 colunas.")
    menus = [texto(m, 30, "o nome de cada menu") for m in (d.get("menus") or [])]
    if not 1 <= len(menus) <= 4:
        raise ValueError("Use de 1 a 4 menus.")
    try:
        faixas = [int(f) for f in (d.get("faixas") or [])]
    except (TypeError, ValueError):
        raise ValueError("As faixas de convidados precisam ser números.")
    if not 1 <= len(faixas) <= 10 or any(f <= 0 for f in faixas) \
            or any(b <= a for a, b in zip(faixas, faixas[1:])):
        raise ValueError("Faixas de convidados: de 1 a 10 números, em ordem crescente, sem repetir.")

    bruto = d.get("precos") or []
    precos = []
    for m in range(len(menus)):
        linha_m = []
        for c in range(len(colunas)):
            linha_c = []
            for k in range(len(faixas)):
                try:
                    v = bruto[m][c][k]
                except (IndexError, TypeError, KeyError):
                    v = None
                if v in (None, ""):
                    linha_c.append(None)
                    continue
                try:
                    if isinstance(v, (int, float)):
                        v = int(round(v))
                    else:   # texto em formato BR: "14.000" ou "14000,50"
                        v = int(round(float(str(v).strip().replace(".", "").replace(",", "."))))
                except ValueError:
                    raise ValueError(f"Valor inválido em {menus[m]} / {colunas[c]} / até {faixas[k]}.")
                if not 0 <= v <= 10_000_000:
                    raise ValueError("Valor fora do limite.")
                linha_c.append(v)
            linha_m.append(linha_c)
        precos.append(linha_m)

    adicionais = []
    for a in (d.get("adicionais") or [])[:6]:
        n = str(a.get("nome") or "").strip()[:60]
        if not n:
            continue
        try:
            v = int(float(str(a.get("valor") or 0).replace(",", ".")))
        except ValueError:
            raise ValueError(f"Valor inválido no adicional '{n}'.")
        adicionais.append({"nome": n, "valor": max(v, 0)})

    materiais = []
    for m in (d.get("materiais") or [])[:8]:
        tipo = m.get("tipo")
        if tipo == "texto":
            t = str(m.get("texto") or "").strip()
            if t:
                materiais.append({"tipo": "texto", "texto": t[:1500]})
            continue
        if tipo not in ("pdf", "imagem"):
            raise ValueError("Material com tipo inválido.")
        url = str(m.get("url") or "").strip()
        if not url.startswith(("https://", "http://")):
            raise ValueError("Material sem arquivo: envie o PDF ou a imagem.")
        item = {"tipo": tipo, "url": url, "legenda": str(m.get("legenda") or "").strip()[:300]}
        if tipo == "pdf":
            nome_arq = str(m.get("arquivo") or "").strip()[:120] or f"{nome}.pdf"
            item["arquivo"] = nome_arq if nome_arq.lower().endswith(".pdf") else nome_arq + ".pdf"
        materiais.append(item)

    bruto_inc = d.get("inclui") or []
    inclui = [str(bruto_inc[i] if i < len(bruto_inc) else "").strip()[:600]
              for i in range(len(menus))]

    return {"chave": d.get("chave") or _slug(nome), "nome": nome, "materiais": materiais,
            "inclui": inclui,
            "descricao": str(d.get("descricao") or "").strip()[:72],
            "no_menu": bool(d.get("no_menu", True)),
            "ativo": bool(d.get("ativo", True)), "variacao": variacao,
            "colunas": colunas, "menus": menus, "faixas": faixas,
            "precos": precos, "adicionais": adicionais}


# Limites da Cloud API: imagem 5 MB, documento 100 MB. O arquivo fica no
# banco, então seguramos o PDF em 15 MB para não pesar no plano grátis.
LIMITE_ARQUIVO = {"pdf": 15, "imagem": 5}


@router.post("/api/arquivos")
async def enviar_arquivo(request: Request, arquivo: UploadFile = File(...)):
    """Recebe o PDF/imagem de um pacote e devolve o link público."""
    _exige_login(request)
    from content import BASE
    conteudo = await arquivo.read()
    mime = (arquivo.content_type or "").split(";")[0].strip().lower()
    nome = os.path.basename(arquivo.filename or "arquivo")[:120]
    if mime == "application/pdf" or nome.lower().endswith(".pdf"):
        tipo, mime = "pdf", "application/pdf"
    elif mime in ("image/jpeg", "image/png"):
        tipo = "imagem"
    else:
        return JSONResponse({"erro": "Envie um PDF ou uma imagem JPG/PNG."}, 400)
    if not conteudo:
        return JSONResponse({"erro": "O arquivo chegou vazio."}, 400)
    if len(conteudo) > LIMITE_ARQUIVO[tipo] * 1024 * 1024:
        return JSONResponse({"erro": f"Arquivo grande demais: o limite para {tipo} é "
                                     f"{LIMITE_ARQUIVO[tipo]} MB."}, 400)
    id_ = await salvar_arquivo(nome, mime, conteudo)
    if not id_:
        return JSONResponse({"erro": "Banco de dados indisponível"}, 503)
    from urllib.parse import quote
    return {"ok": True, "tipo": tipo, "arquivo": nome,
            "url": f"{BASE}/arquivos/{id_}/{quote(nome)}"}


@router.get("/arquivos/{id_}/{nome}")
async def baixar_arquivo(id_: str, nome: str):
    """Público: o WhatsApp baixa o material por aqui. O id é aleatório."""
    a = await obter_arquivo(id_)
    if not a:
        raise HTTPException(404, "Arquivo não encontrado")
    return Response(content=bytes(a["conteudo"]), media_type=a["mime"],
                    headers={"Cache-Control": "public, max-age=86400"})


@router.get("/api/pacotes")
async def pacotes(request: Request):
    _exige_login(request)
    return {"pacotes": await listar_pacotes()}


@router.post("/api/pacotes")
async def novo_pacote(request: Request):
    _exige_login(request)
    d = await request.json()
    try:
        pac = _normalizar_pacote({**d, "chave": None})
    except ValueError as e:
        return JSONResponse({"erro": str(e)}, 400)
    # Chaves de opções internas do bot não podem virar pacote.
    existentes = {p["chave"] for p in await listar_pacotes()} | {
        "fotos", "localizacao", "regras", "contato", "humano", "menu", "nenhum"}
    base, i = pac["chave"], 2
    while pac["chave"] in existentes:
        pac["chave"] = f"{base}_{i}"
        i += 1
    if not await salvar_pacote(pac, novo=True):
        return JSONResponse({"erro": "Não foi possível criar o pacote"}, 500)
    return {"ok": True, "pacote": pac}


@router.put("/api/pacotes/{chave}")
async def editar_pacote(chave: str, request: Request):
    _exige_login(request)
    d = await request.json()
    try:
        pac = _normalizar_pacote({**d, "chave": chave})
    except ValueError as e:
        return JSONResponse({"erro": str(e)}, 400)
    if not await salvar_pacote(pac):
        return JSONResponse({"erro": "Pacote não encontrado"}, 404)
    return {"ok": True, "pacote": pac}


@router.delete("/api/pacotes/{chave}")
async def apagar_pacote(chave: str, request: Request):
    _exige_login(request)
    if not await remover_pacote(chave):
        return JSONResponse({"erro": "Pacote não encontrado"}, 404)
    return {"ok": True}


@router.get("/api/vcard/{telefone}")
async def vcard(telefone: str, request: Request):
    """
    Baixa o contato do cliente como .vcf para importar no celular.
    O nome vem do cadastro (leads.nome); se estiver vazio, cai no telefone.
    """
    _exige_login(request)
    tel = "".join(c for c in telefone if c.isdigit())
    if not tel:
        raise HTTPException(400, "Telefone inválido")
    nome = (await get_nome(tel)) or f"+{tel}"
    # vCard 3.0 é o formato que Android e iPhone abrem sem tratativa.
    # \r\n é obrigatório pela RFC 2426 — sem isso alguns leitores quebram.
    vcf = (
        "BEGIN:VCARD\r\n"
        "VERSION:3.0\r\n"
        f"FN:{nome}\r\n"
        f"N:{nome};;;;\r\n"
        f"TEL;TYPE=CELL:+{tel}\r\n"
        "END:VCARD\r\n"
    )
    filename = "".join(c if c.isalnum() or c in "-_" else "_" for c in nome)[:60] or tel
    return Response(
        content=vcf,
        media_type="text/vcard; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}.vcf"'},
    )


# ---------------------------------------------------------------
# Ficha do cliente (cabeçalho da conversa)
# ---------------------------------------------------------------
ROTULO_TIPO_EVENTO = {"casamento": "Casamento", "quinze": "15 anos",
                      "infantil": "Infantil", "confraternizacao": "Aniversário/confraternização",
                      "decorado": "Espaço decorado", "locacao": "Locação do espaço",
                      "outro": "Outro"}


def _compromisso(lista: list, tipo: str, hoje):
    """O próximo compromisso do tipo; se não houver, o último que passou."""
    ativos = [a for a in lista if a.get("tipo") == tipo and a.get("status") != "cancelado"]
    futuros = sorted((a for a in ativos if a["dia"] >= hoje), key=lambda a: a["dia"])
    passados = sorted((a for a in ativos if a["dia"] < hoje), key=lambda a: a["dia"])
    a = futuros[0] if futuros else (passados[-1] if passados else None)
    if not a:
        return None
    return {"id": a["id"], "dia": a["dia"].isoformat(),
            "hora": a["hora"].strftime("%H:%M") if a.get("hora") else None,
            "status": a.get("status"), "passou": a["dia"] < hoje}


@router.get("/api/cliente/{telefone}")
async def ficha(telefone: str, request: Request):
    _exige_login(request)
    f = await get_ficha(telefone)
    if not f:
        return {"telefone": telefone, "existe": False}
    agora = datetime.now(TZ)
    agenda = await agenda_por_telefone(telefone)
    pausa = f.get("ia_pausa_ate")
    return {
        "telefone": telefone,
        "existe": True,
        "nome": f.get("nome") or "",
        "etapa": f.get("etapa") or "novo",
        "etapa_rotulo": dict(ETAPAS).get(f.get("etapa") or "novo", f.get("etapa")),
        "etapa_em": f["etapa_em"].astimezone(TZ).strftime("%d/%m %H:%M")
            if f.get("etapa_em") else None,
        "etapas": [{"id": e, "rotulo": r} for e, r in ETAPAS],
        "tipo_evento_id": f.get("tipo_evento") or "",
        "tipos": [{"id": k, "rotulo": v} for k, v in ROTULO_TIPO_EVENTO.items()],
        "status": f.get("status"),
        "bloqueado": f.get("bloqueado", False),
        "tipo_evento": ROTULO_TIPO_EVENTO.get(f.get("tipo_evento"), f.get("tipo_evento") or ""),
        "convidados": f.get("convidados") or 0,
        "data_interesse": f["data_interesse"].isoformat() if f.get("data_interesse") else None,
        "resumo": f.get("resumo_ia") or "",
        "interesses": list(f.get("interesses") or []),
        "visita": _compromisso(agenda, "visita", agora.date()),
        "evento": _compromisso(agenda, "evento", agora.date()),
        # Contrato: funcionalidade futura — por enquanto só o campo.
        "contrato_enviado_em": f["contrato_enviado_em"].isoformat()
            if f.get("contrato_enviado_em") else None,
        "ia_pausada_ate": pausa.astimezone(TZ).strftime("%H:%M")
            if pausa and pausa > agora else None,
        "desvios": f.get("desvios_ia") or 0,
    }


@router.put("/api/cliente/{telefone}")
async def editar_ficha(telefone: str, request: Request):
    """O representante corrige a ficha: tipo, data, convidados, resumo,
    nome e etapa do funil. Só os campos enviados mudam."""
    _exige_login(request)
    dados = await request.json()
    campos = {}
    if "nome" in dados:
        campos["nome"] = str(dados["nome"] or "")
    if "tipo_evento" in dados:
        t = dados["tipo_evento"] or ""
        if t and t not in ROTULO_TIPO_EVENTO:
            return JSONResponse({"erro": "Tipo de evento inválido"}, 400)
        campos["tipo_evento"] = t
    if "convidados" in dados:
        try:
            n = int(dados["convidados"] or 0)
        except (TypeError, ValueError):
            return JSONResponse({"erro": "Convidados deve ser um número"}, 400)
        if not 0 <= n < 10000:
            return JSONResponse({"erro": "Número de convidados inválido"}, 400)
        campos["convidados"] = n
    if "data_interesse" in dados:
        bruto = dados["data_interesse"] or ""
        try:
            campos["data_interesse"] = (datetime.strptime(bruto[:10], "%Y-%m-%d").date()
                                        if bruto else None)
        except ValueError:
            return JSONResponse({"erro": "Data inválida"}, 400)
    if "resumo" in dados:
        campos["resumo_ia"] = str(dados["resumo"] or "")
    if "etapa" in dados:
        if dados["etapa"] not in dict(ETAPAS):
            return JSONResponse({"erro": "Etapa inválida"}, 400)
        campos["etapa"] = dados["etapa"]
    await atualizar_ficha(telefone, campos)
    return {"ok": True}


@router.post("/api/cliente/{telefone}/resetar")
async def resetar(telefone: str, request: Request):
    """Zera o que o bot e a IA sabem do cliente (histórico e agenda ficam)."""
    _exige_login(request)
    await resetar_cliente(telefone)
    try:
        import ia
        ia._uso.pop(telefone, None)
    except Exception:
        pass
    return {"ok": True}


@router.post("/api/cliente/{telefone}/bloqueio")
async def bloqueio(telefone: str, request: Request):
    """Bloqueado: as mensagens desse número são descartadas na chegada."""
    _exige_login(request)
    dados = await request.json()
    bloquear = bool(dados.get("bloquear"))
    await definir_bloqueio(telefone, bloquear)
    return {"ok": True, "bloqueado": bloquear}


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
                       resposta_a: str = Form(""),
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
                              legenda=legenda, nome_arquivo=nome,
                              reply_to=resposta_a)
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
