"""
Agenda — visitas ao sítio e datas de evento.

Duas coisas moram aqui:

  1. A API que a aba "Agenda" do painel consome (CRUD dos compromissos).
  2. O resumo diário: às 7h30 um cron externo chama /api/cron/agenda e a
     equipe recebe no WhatsApp de trabalho tudo o que acontece no dia.

Também ficam aqui os atalhos de anexo — os materiais que já existem em
content.py, enviados com um toque durante a conversa.
"""
import os
import hmac
import logging
import asyncio
from datetime import date, time, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse

import whatsapp as wa
import push
import ics
from content import (CONTEUDO, NUMEROS_EQUIPE, catalogo_anexos,
                     texto_confirmacao)
from db import (criar_agendamento, atualizar_agendamento, remover_agendamento,
                listar_agendamentos, agendamentos_do_dia, agenda_por_telefone,
                obter_agendamento, aviso_ja_enviado, marcar_aviso_enviado,
                uids_conhecidos, importar_agendamentos)
from painel import _exige_login

log = logging.getLogger("sitio-bot")
router = APIRouter()

TZ = ZoneInfo(os.getenv("TIMEZONE", "America/Sao_Paulo"))

# Segredo do cron externo (cron-job.org). Sem ele a rota fica fechada.
CRON_SEGREDO = os.getenv("CRON_SEGREDO", "")

# Modelo aprovado na Meta, usado quando a janela de 24h já fechou.
# O modelo precisa ter exatamente uma variável no corpo. Ex: "agenda_do_dia"
TEMPLATE_AGENDA = os.getenv("TEMPLATE_AGENDA", "")
TEMPLATE_IDIOMA = os.getenv("TEMPLATE_IDIOMA", "pt_BR")

# Espelhar o resumo no push do painel instalado.
AVISO_PUSH = os.getenv("AGENDA_PUSH", "1") != "0"

# Rodapé fixo do aviso diário — pedir SIM mantém a janela de 24h da Meta
# aberta com o atendente, para o texto livre seguir chegando sem cair no
# template. Enviado todo dia, inclusive quando não há compromisso.
CONFIRMACAO_DIARIA = (
    "_Responda *SIM* para continuar recebendo estes avisos._"
)

TIPOS = {"visita", "evento"}
STATUS = {"confirmado", "pendente", "cancelado", "realizado"}

ROTULO_TIPO = {"visita": "Visita", "evento": "Evento"}
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
         "agosto", "setembro", "outubro", "novembro", "dezembro"]


def hoje() -> date:
    return datetime.now(TZ).date()


# ---------------------------------------------------------------
# Conversão
# ---------------------------------------------------------------
def _data(valor, campo="dia"):
    if isinstance(valor, date):
        return valor
    try:
        return date.fromisoformat(str(valor)[:10])
    except (ValueError, TypeError):
        raise HTTPException(400, f"Data inválida em '{campo}'. Use AAAA-MM-DD.")


def _hora(valor):
    if valor in (None, "", "null"):
        return None
    if isinstance(valor, time):
        return valor
    try:
        return time.fromisoformat(str(valor)[:8] if len(str(valor)) > 5 else str(valor))
    except (ValueError, TypeError):
        raise HTTPException(400, "Hora inválida. Use HH:MM.")


def _limpo(a: dict) -> dict:
    """Formato que o painel consome — datas em ISO, nada de objetos Python."""
    return {
        "id": a["id"],
        "tipo": a["tipo"],
        "titulo": a["titulo"],
        "dia": a["dia"].isoformat() if a.get("dia") else None,
        "hora": a["hora"].strftime("%H:%M") if a.get("hora") else None,
        "cliente": a.get("cliente") or a.get("nome_lead") or "",
        "telefone": a.get("telefone") or "",
        "observacoes": a.get("observacoes") or "",
        "status": a.get("status") or "confirmado",
        "criado_em": a["criado_em"].isoformat() if a.get("criado_em") else None,
    }


def normalizar_telefone(bruto: str) -> str:
    """
    Deixa o número no formato que o WhatsApp usa: DDI + DDD + número.

    A atendente digita "21 99999-1234" ou "(21) 9 9999-1234"; o WhatsApp
    guarda "5521999991234". Sem normalizar aqui, o agendamento nunca casa
    com a conversa e a etiqueta não aparece.
    """
    d = "".join(c for c in str(bruto or "") if c.isdigit())
    if not d:
        return ""
    if d.startswith("00"):
        d = d[2:]
    # 10 = fixo com DDD, 11 = celular com DDD: falta só o país
    if len(d) in (10, 11):
        d = "55" + d
    return d[:15]


def _validar(dados: dict, parcial: bool = False) -> dict:
    saida = {}

    if "tipo" in dados or not parcial:
        tipo = (dados.get("tipo") or "visita").strip().lower()
        if tipo not in TIPOS:
            raise HTTPException(400, "Tipo deve ser 'visita' ou 'evento'.")
        saida["tipo"] = tipo

    if "dia" in dados or not parcial:
        saida["dia"] = _data(dados.get("dia"))

    if "hora" in dados or not parcial:
        saida["hora"] = _hora(dados.get("hora"))

    for campo in ("titulo", "cliente", "telefone", "observacoes"):
        if campo in dados or not parcial:
            saida[campo] = (dados.get(campo) or "").strip()[:400]

    if "telefone" in saida:
        saida["telefone"] = normalizar_telefone(saida["telefone"])

    if "status" in dados or not parcial:
        st = (dados.get("status") or "confirmado").strip().lower()
        if st not in STATUS:
            raise HTTPException(400, "Status inválido.")
        saida["status"] = st

    if not parcial and not saida.get("titulo"):
        rotulo = ROTULO_TIPO.get(saida.get("tipo", "visita"), "Compromisso")
        saida["titulo"] = f"{rotulo} — {saida.get('cliente') or 'sem nome'}"

    return saida


DIAS_SEMANA = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
               "sexta-feira", "sábado", "domingo"]


def _por_extenso(dia: date, hora) -> str:
    texto = f"{DIAS_SEMANA[dia.weekday()]}, {dia.day} de {MESES[dia.month - 1]}"
    if hora:
        texto += f", às {hora.strftime('%H:%M')}"
    return texto


async def confirmar_com_cliente(ag: dict, remarcado: bool = False) -> dict:
    """
    Manda a confirmação para o cliente e devolve o que aconteceu, para o
    painel avisar a atendente. Nunca levanta erro: falhar o aviso não pode
    desfazer um agendamento que já está gravado.
    """
    telefone = ag.get("telefone") or ""
    if not telefone:
        return {"enviado": False, "motivo": "o agendamento não tem WhatsApp"}

    nome = (ag.get("cliente") or ag.get("nome_lead") or "").split()[0:1]
    texto = texto_confirmacao(
        ag.get("tipo") or "visita",
        _por_extenso(ag["dia"], ag.get("hora")),
        nome[0] if nome else "",
        remarcado=remarcado,
    )
    try:
        r = await wa.texto(telefone, texto, autor="atendente")
    except Exception as e:
        log.error("Confirmação ao cliente falhou: %s", e)
        return {"enviado": False, "motivo": "não consegui falar com o WhatsApp"}

    if r.status_code < 400:
        return {"enviado": True}

    detalhe = ""
    try:
        detalhe = r.json().get("error", {}).get("message", "")[:160]
    except Exception:
        pass
    if "24" in detalhe or "131047" in str(detalhe):
        detalhe = ("o cliente não escreve há mais de 24h; o WhatsApp só permite "
                   "retomar com modelo aprovado")
    log.error("Confirmação recusada para %s: %s", telefone, detalhe)
    return {"enviado": False, "motivo": detalhe or "o WhatsApp recusou o envio"}


# ---------------------------------------------------------------
# CRUD — rotas fixas antes das que têm {id}
# ---------------------------------------------------------------
@router.get("/api/agenda/hoje")
async def agenda_hoje(request: Request):
    _exige_login(request)
    dia = hoje()
    itens = await agendamentos_do_dia(dia)
    return {"dia": dia.isoformat(), "agendamentos": [_limpo(a) for a in itens]}


@router.get("/api/agenda/resumo")
async def agenda_resumo(request: Request):
    """Contadores do rodapé/aba: quantos compromissos hoje e nos próximos 7 dias."""
    _exige_login(request)
    d = hoje()
    proximos = await listar_agendamentos(d, d + timedelta(days=7), False)
    de_hoje = [a for a in proximos if a["dia"] == d]
    return {
        "hoje": len(de_hoje),
        "semana": len(proximos),
        "proximo": _limpo(proximos[0]) if proximos else None,
    }


@router.get("/api/agenda/conversa/{telefone}")
async def agenda_da_conversa(telefone: str, request: Request):
    _exige_login(request)
    itens = await agenda_por_telefone(telefone)
    return {"agendamentos": [_limpo(a) for a in itens]}


@router.post("/api/agenda/avisar")
async def avisar_agora(request: Request):
    """Botão 'reenviar agenda de hoje' no painel."""
    _exige_login(request)
    return await disparar_resumo(hoje(), forcar=True)


TAMANHO_MAXIMO_ICS = 3 * 1024 * 1024      # ~15 mil eventos; mais que isso é engano


@router.post("/api/agenda/importar")
async def importar(request: Request,
                   arquivo: UploadFile = File(...),
                   desde: str = Form(""),
                   tipo_padrao: str = Form("evento"),
                   previa: int = Form(1)):
    """
    Importa um .ics exportado do Google Agenda.

    Chamado duas vezes pelo painel: `previa=1` só lê e mostra o que vai
    acontecer, `previa=0` grava. O navegador reenvia o mesmo arquivo, o que
    evita guardar estado no servidor entre os dois passos.
    """
    _exige_login(request)

    if tipo_padrao not in TIPOS:
        tipo_padrao = "evento"
    corte = _data(desde, "desde") if desde else hoje()

    conteudo = await arquivo.read()
    if len(conteudo) > TAMANHO_MAXIMO_ICS:
        return JSONResponse({"erro": "Arquivo grande demais (limite de 3 MB)."}, 400)
    if not conteudo:
        return JSONResponse({"erro": "O arquivo chegou vazio."}, 400)

    try:
        texto = conteudo.decode("utf-8")
    except UnicodeDecodeError:
        texto = conteudo.decode("latin-1", errors="replace")

    if "BEGIN:VCALENDAR" not in texto.upper():
        return JSONResponse(
            {"erro": "Isto não parece um arquivo .ics do Google Agenda."}, 400)

    try:
        eventos = ics.ler(texto, TZ, tipo_padrao)
    except Exception as e:
        log.error("Falha ao ler .ics: %s", e)
        return JSONResponse({"erro": "Não consegui ler este arquivo."}, 400)

    antigos = [e for e in eventos if e["dia"] < corte]
    candidatos = [e for e in eventos if e["dia"] >= corte]

    com_uid = [e["uid"] for e in candidatos if e["uid"]]
    ja_tem = await uids_conhecidos(com_uid)
    novos = [e for e in candidatos if not e["uid"] or e["uid"] not in ja_tem]
    repetidos = len(candidatos) - len(novos)

    resumo = {
        "previa": bool(previa),
        "desde": corte.isoformat(),
        "no_arquivo": len(eventos),
        "fora_do_periodo": len(antigos),
        "ja_importados": repetidos,
        "novos": len(novos),
        "itens": [{
            "titulo": e["titulo"],
            "tipo": e["tipo"],
            "dia": e["dia"].isoformat(),
            "hora": e["hora"].strftime("%H:%M") if e["hora"] else None,
            "telefone": e["telefone"],
            "observacoes": e["observacoes"][:160],
            "status": e["status"],
            "recorrente": e["recorrente"],
        } for e in novos[:300]],
    }

    if previa:
        return resumo

    if not novos:
        return {**resumo, "importados": 0}

    await importar_agendamentos(novos)
    log.info("Agenda: %d eventos importados do Google", len(novos))
    return {**resumo, "importados": len(novos)}


@router.post("/api/agenda/teste-envio")
async def teste_envio(request: Request):
    """
    Diagnóstico: manda um "oi" para um número e devolve o que a Meta respondeu,
    sem filtro. É o jeito de descobrir por que um aviso aceito não chega.
    """
    _exige_login(request)
    dados = await request.json()
    numero = "".join(c for c in str(dados.get("telefone") or "") if c.isdigit())
    if not numero:
        return JSONResponse({"erro": "Informe o telefone"}, 400)

    r = await wa.texto(numero, "🌻 Teste de aviso do Sítio Girassol.",
                       autor="sistema", registrar=False)
    try:
        corpo = r.json()
    except Exception:
        corpo = {"texto": r.text[:400]}
    return {"numero_enviado": numero, "http": r.status_code, "resposta_da_meta": corpo}


@router.get("/api/agenda")
async def listar(request: Request, inicio: str = "", fim: str = ""):
    _exige_login(request)
    d = hoje()
    ini = _data(inicio, "inicio") if inicio else d.replace(day=1)
    fi = _data(fim, "fim") if fim else ini + timedelta(days=45)
    if fi < ini:
        raise HTTPException(400, "O fim do período é anterior ao início.")
    if (fi - ini).days > 400:
        raise HTTPException(400, "Período longo demais (máximo 400 dias).")
    itens = await listar_agendamentos(ini, fi)
    return {"inicio": ini.isoformat(), "fim": fi.isoformat(),
            "agendamentos": [_limpo(a) for a in itens]}


@router.post("/api/agenda")
async def criar(request: Request):
    _exige_login(request)
    bruto = await request.json()
    dados = _validar(bruto)
    criado = await criar_agendamento(dados)
    if not criado:
        return JSONResponse({"erro": "Banco de dados indisponível"}, 503)

    aviso = None
    if bruto.get("avisar_cliente") and criado.get("telefone"):
        aviso = await confirmar_com_cliente(criado)
    return {"ok": True, "agendamento": _limpo(criado), "aviso": aviso}


@router.put("/api/agenda/{id_}")
async def editar(id_: int, request: Request):
    _exige_login(request)
    bruto = await request.json()
    dados = _validar(bruto, parcial=True)
    if not dados:
        return JSONResponse({"erro": "Nada para atualizar"}, 400)

    antes = await obter_agendamento(id_)
    atualizado = await atualizar_agendamento(id_, dados)
    if not atualizado:
        return JSONResponse({"erro": "Agendamento não encontrado"}, 404)

    aviso = None
    if bruto.get("avisar_cliente") and atualizado.get("telefone"):
        mudou = bool(antes) and (antes.get("dia") != atualizado.get("dia")
                                 or antes.get("hora") != atualizado.get("hora"))
        aviso = await confirmar_com_cliente(atualizado, remarcado=mudou)
    return {"ok": True, "agendamento": _limpo(atualizado), "aviso": aviso}


@router.delete("/api/agenda/{id_}")
async def apagar(id_: int, request: Request):
    _exige_login(request)
    if not await remover_agendamento(id_):
        return JSONResponse({"erro": "Agendamento não encontrado"}, 404)
    return {"ok": True}


# ---------------------------------------------------------------
# Anexos de acesso rápido
# ---------------------------------------------------------------
@router.get("/api/anexos")
async def anexos(request: Request):
    _exige_login(request)
    return {"anexos": catalogo_anexos()}


@router.post("/api/anexos/enviar")
async def enviar_anexo(request: Request):
    """Manda para o cliente o mesmo material que o bot enviaria."""
    _exige_login(request)
    dados = await request.json()
    telefone = "".join(c for c in str(dados.get("telefone") or "") if c.isdigit())
    chave = (dados.get("chave") or "").strip()

    item = CONTEUDO.get(chave)
    if not telefone or not item:
        return JSONResponse({"erro": "Material não encontrado"}, 400)

    enviados = 0
    for bloco in item["blocos"]:
        t = bloco["tipo"]
        if t == "texto":
            r = await wa.texto(telefone, bloco["texto"], autor="atendente")
        elif t == "pdf":
            r = await wa.pdf(telefone, bloco["url"], bloco["arquivo"],
                             bloco.get("legenda", ""), autor="atendente")
        elif t == "imagem":
            r = await wa.imagem(telefone, bloco["url"], bloco.get("legenda", ""),
                                autor="atendente")
        elif t == "localizacao":
            r = await wa.localizacao(telefone, bloco["lat"], bloco["lng"],
                                     bloco["nome"], bloco["endereco"],
                                     autor="atendente")
        elif t == "contato":
            r = await wa.contato(telefone, bloco["dados"], autor="atendente")
        else:
            continue

        if r.status_code >= 400:
            detalhe = ""
            try:
                detalhe = r.json().get("error", {}).get("message", "")
            except Exception:
                pass
            if "24" in detalhe or "131047" in str(detalhe):
                detalhe = ("Passaram mais de 24h desde a última mensagem do cliente. "
                           "O WhatsApp só permite retomar com modelo aprovado.")
            return JSONResponse(
                {"erro": detalhe or "O WhatsApp recusou o envio", "enviados": enviados},
                502)

        enviados += 1
        await asyncio.sleep(1.2)   # preserva a ordem de entrega

    return {"ok": True, "enviados": enviados}


# ---------------------------------------------------------------
# Resumo diário para o WhatsApp da equipe
# ---------------------------------------------------------------
def _linha(a: dict) -> str:
    hora = a["hora"].strftime("%H:%M") if a.get("hora") else "dia todo"
    quem = a.get("cliente") or a.get("nome_lead") or ""
    linha = f"• *{hora}* — {a['titulo']}"
    if quem and quem.lower() not in (a["titulo"] or "").lower():
        linha += f"\n  {quem}"
    if a.get("telefone"):
        linha += f"\n  wa.me/{a['telefone']}"
    if a.get("observacoes"):
        linha += f"\n  _{a['observacoes'][:120]}_"
    if a.get("status") == "pendente":
        linha += "\n  ⚠️ ainda não confirmado"
    return linha


def montar_resumo(dia: date, itens: list) -> str:
    cabeca = f"🌻 *Agenda de {dia.day} de {MESES[dia.month - 1]}*"

    if not itens:
        # Dia vazio ainda sai: mantém o ritmo diário, e o pedido de SIM
        # renova a janela de 24h independente de ter compromisso.
        return f"{cabeca}\n\nSem agenda para o dia.\n\n{CONFIRMACAO_DIARIA}"

    visitas = [a for a in itens if a["tipo"] == "visita"]
    eventos = [a for a in itens if a["tipo"] == "evento"]

    partes = [cabeca]
    if eventos:
        partes.append("*🎉 Eventos*\n" + "\n".join(_linha(a) for a in eventos))
    if visitas:
        partes.append("*🚗 Visitas ao sítio*\n" + "\n".join(_linha(a) for a in visitas))
    partes.append("Bom trabalho! 🌻")
    partes.append(CONFIRMACAO_DIARIA)
    return "\n\n".join(partes)


def montar_resumo_curto(dia: date, itens: list) -> str:
    """
    Versão de uma linha só — variáveis de modelo da Meta não aceitam
    quebra de linha, e estourar isso derruba o envio inteiro.
    """
    if not itens:
        return f"{dia.strftime('%d/%m')}: sem agenda para o dia."
    pedacos = []
    for a in itens[:6]:
        hora = a["hora"].strftime("%H:%M") if a.get("hora") else "dia todo"
        pedacos.append(f"{hora} {ROTULO_TIPO.get(a['tipo'], '')} {a['titulo']}".strip())
    resto = f" (+{len(itens) - 6})" if len(itens) > 6 else ""
    return f"{dia.strftime('%d/%m')}: " + " | ".join(pedacos) + resto


def _recibo(numero: str, via: str, resposta) -> dict:
    """
    A Meta aceitar (HTTP 200) não é a mesma coisa que entregar.

    O corpo da resposta traz o `wa_id` — o número como o WhatsApp realmente o
    conhece. Se ele vier diferente do que mandamos, ou vier vazio, a mensagem
    foi aceita para um destino que não existe e some sem erro nenhum.
    """
    recibo = {"numero": numero, "via": via, "ok": True}
    try:
        d = resposta.json()
        wa_id = (d.get("contacts") or [{}])[0].get("wa_id", "")
        recibo["wa_id"] = wa_id
        recibo["msg_id"] = (d.get("messages") or [{}])[0].get("id", "")
        if not wa_id:
            recibo["atencao"] = "a Meta não devolveu wa_id — número provavelmente sem WhatsApp"
        elif wa_id != numero:
            recibo["atencao"] = f"a Meta entregou para {wa_id}, não para {numero}"
    except Exception:
        pass
    log.info("Agenda: aviso aceito para %s — %s", numero, recibo)
    return recibo


async def _mandar_para(numero: str, texto_completo: str, curto: str) -> dict:
    """
    Texto livre primeiro; modelo aprovado como plano B.

    O texto livre precisa da janela de 24h aberta, e é justamente o SIM que
    a equipe responde ao aviso do dia anterior que mantém essa janela viva
    — por isso o rodapé fixo pedindo confirmação.
    """
    try:
        r = await wa.texto(numero, texto_completo, autor="sistema", registrar=False)
        if r.status_code < 400:
            return _recibo(numero, "texto", r)
        detalhe = ""
        try:
            detalhe = r.json().get("error", {}).get("message", "")[:140]
        except Exception:
            pass
    except Exception as e:
        detalhe = str(e)[:140]

    if TEMPLATE_AGENDA:
        try:
            r = await wa.template(numero, TEMPLATE_AGENDA, TEMPLATE_IDIOMA, [curto],
                                  autor="sistema")
            if r.status_code < 400:
                return _recibo(numero, "modelo", r)
            try:
                detalhe = r.json().get("error", {}).get("message", "")[:140]
            except Exception:
                pass
        except Exception as e:
            detalhe = str(e)[:140]

    log.error("Agenda: falha ao avisar %s — %s", numero, detalhe)
    return {"numero": numero, "ok": False, "erro": detalhe or "envio recusado"}


async def disparar_resumo(dia: date, forcar: bool = False) -> dict:
    """
    Monta e envia a agenda do dia. Idempotente por dia, salvo forcar=True.

    Envia sempre — dias sem compromisso viram "Sem agenda para o dia" —
    para preservar o ritmo diário e a confirmação por SIM que mantém a
    janela de 24h aberta com o atendente.
    """
    if not forcar and await aviso_ja_enviado(dia):
        return {"ok": True, "ignorado": "aviso do dia já enviado"}

    itens = await agendamentos_do_dia(dia)
    completo = montar_resumo(dia, itens)
    curto = montar_resumo_curto(dia, itens)

    if AVISO_PUSH:
        try:
            titulo = ("🌻 Agenda de hoje"
                      if itens else "🌻 Hoje sem compromissos")
            await push.notificar(titulo, curto, urgente=False, aba="agenda")
        except Exception as e:
            log.error("Agenda: push falhou — %s", e)

    resultados = []
    for numero in NUMEROS_EQUIPE:
        resultados.append(await _mandar_para(numero, completo, curto))

    if not NUMEROS_EQUIPE:
        log.warning("Agenda: NUMEROS_EQUIPE vazio — resumo só foi para o push.\n%s",
                    completo)

    await marcar_aviso_enviado(dia, len(itens))
    return {"ok": True, "dia": dia.isoformat(), "total": len(itens),
            "enviado": True, "destinos": resultados}


@router.api_route("/api/cron/agenda", methods=["GET", "POST"])
async def cron_agenda(chave: str = "", dia: str = "", forcar: int = 0):
    """
    Chamado pelo cron externo às 7h30 (America/Sao_Paulo).

      https://SEU-APP.onrender.com/api/cron/agenda?chave=SEU_CRON_SEGREDO

    Rota pública por natureza — por isso o segredo é obrigatório.
    """
    if not CRON_SEGREDO:
        return JSONResponse({"erro": "CRON_SEGREDO não configurado"}, 503)
    if not hmac.compare_digest(chave, CRON_SEGREDO):
        return JSONResponse({"erro": "chave inválida"}, 403)
    alvo = _data(dia) if dia else hoje()
    return await disparar_resumo(alvo, forcar=bool(forcar))
