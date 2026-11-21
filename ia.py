"""
IA de atendimento (Claude Haiku 5.5) — conduz o cliente até o fechamento.

Entra em cena quando o cliente escreve texto livre que não é saudação nem
opção do menu. Papel:

  1. Capturar tipo de evento, número de convidados e data de interesse
     (gravados no lead, a IA não pergunta de novo).
  2. Com a data, consultar a agenda do painel; se o dia tiver evento,
     sugerir o fim de semana livre mais próximo.
  3. Tirar até LIMITE_DUVIDAS dúvidas depois da qualificação, sempre
     puxando para o fechamento — que é sempre da equipe humana.
  4. Pergunta fora do tema dos eventos → o bot mostra o menu, sem texto da IA.

Configuração (Render → Environment):
  ANTHROPIC_API_KEY   chave da API (platform.claude.com)
  IA_ATIVA            0 desliga sem apagar a chave (padrão 1)
  IA_LIMITE_DIARIO    chamadas da IA por cliente por dia (padrão 15)
  IA_DUVIDAS          dúvidas livres após a qualificação (padrão 3)

Qualquer falha devolve None — o bot cai no menu, como antes da IA.
"""
import os
import json
import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from content import ROTEIRO_IA, NOME_ASSISTENTE

log = logging.getLogger("sitio-bot")

MODELO = "claude-haiku-5-5"
TZ = ZoneInfo(os.getenv("TIMEZONE", "America/Sao_Paulo"))
LIMITE_DIARIO = int(os.getenv("IA_LIMITE_DIARIO", "15"))
LIMITE_DUVIDAS = int(os.getenv("IA_DUVIDAS", "3"))

ativo = bool(os.getenv("ANTHROPIC_API_KEY")) and os.getenv("IA_ATIVA", "1") != "0"

_cliente = None
if ativo:
    try:
        from anthropic import AsyncAnthropic
        # Resposta precisa voltar rápido: o cliente está esperando no WhatsApp.
        _cliente = AsyncAnthropic(timeout=25.0, max_retries=1)
    except Exception as e:
        log.error("IA: não consegui iniciar o cliente Anthropic — %s", e)
        ativo = False

MATERIAIS = ["nenhum", "casamento", "quinze", "infantil", "confraternizacao",
             "decorado", "fotos", "localizacao", "regras", "contato"]
TIPOS = ["", "casamento", "quinze", "infantil", "confraternizacao", "decorado", "outro"]
ROTULO_TIPO = {"casamento": "Casamento", "quinze": "15 anos", "infantil": "Infantil",
               "confraternizacao": "Aniversário/confraternização",
               "decorado": "Espaço decorado", "outro": "Outro"}
DIAS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]

ESQUEMA = {
    "type": "object",
    "properties": {
        "acao": {"type": "string", "enum": ["responder", "atendente", "menu"]},
        "resposta": {"type": "string"},
        "material": {"type": "string", "enum": MATERIAIS},
        "tipo_evento": {"type": "string", "enum": TIPOS},
        "convidados": {"type": "integer"},
        "data_interesse": {"type": "string"},
    },
    "required": ["acao", "resposta", "material", "tipo_evento",
                 "convidados", "data_interesse"],
    "additionalProperties": False,
}

FERRAMENTA = {
    "name": "consultar_disponibilidade",
    "description": (
        "Consulta a agenda do sítio. Diz se a data já tem evento marcado e, se "
        "tiver, lista os dias de fim de semana livres mais próximos. Use sempre "
        "que souber a data de interesse do cliente, antes de falar sobre ela."),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {"data": {"type": "string", "description": "AAAA-MM-DD"}},
        "required": ["data"],
        "additionalProperties": False,
    },
}

FERRAMENTA_VALORES = {
    "name": "consultar_valores",
    "description": (
        "Devolve os valores de tabela do pacote (menus Standard e Premium) para "
        "o tipo de evento, o número de convidados e a data. Use sempre que o "
        "cliente perguntar preço/valor/quanto custa de casamento, 15 anos ou "
        "infantil. Sem data, devolve as duas tabelas de dia."),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "tipo_evento": {"type": "string", "enum": ["casamento", "quinze", "infantil"]},
            "convidados": {"type": "integer"},
            "data": {"type": "string", "description": "AAAA-MM-DD ou vazio"},
        },
        "required": ["tipo_evento", "convidados", "data"],
        "additionalProperties": False,
    },
}

SISTEMA = f"""Você é a {NOME_ASSISTENTE}, assistente virtual do Sítio Girassol no WhatsApp.
Seu objetivo é levar o cliente até o fechamento com a equipe, de forma simpática.

# Campo "acao"
- "menu": a mensagem NÃO tem relação com eventos no sítio (assunto aleatório,
  spam, pedido sem sentido). O bot mostra o menu; deixe "resposta" vazia.
- "atendente": o cliente quer fechar, reservar, negociar desconto, agendar
  visita, falar com uma pessoa, reclamar ou parecer insatisfeito. Responda
  dizendo que vai chamar a equipe para continuar (e que ela já recebe o
  resumo do que conversaram).
- "responder": qualquer outra pergunta sobre os eventos.

# Conduza a conversa
1. Primeiro capture, com naturalidade e sem interrogatório: tipo de evento,
   data de interesse e número de convidados. Pergunte o que falta (no máximo
   duas coisas por vez), depois de responder o que o cliente perguntou.
2. Quando souber a data, chame consultar_disponibilidade antes de falar dela.
   Se estiver livre, diga que está livre, mas que a reserva só vale com a
   equipe. Se não estiver, ofereça os dias livres que a ferramenta devolver.
3. Com tipo, data e convidados capturados, tire as dúvidas e termine sempre
   convidando para o próximo passo: "Quer que eu chame a equipe para montar
   seu orçamento e reservar a data?".

# Regras
- Use SOMENTE o roteiro. Se não estiver lá, diga que a equipe confirma no
  orçamento. Nunca faça reserva nem dê desconto.
- Valores: só com consultar_valores (precisa do tipo e dos convidados; se
  faltar, pergunte). Mostre o Standard e o Premium da faixa, em reais
  (ex: *R$ 18.000*), diga que é valor de tabela para a faixa de convidados e
  envie o material do tipo de evento. Sem data, mostre semana e fim de
  semana. Fim de semana e feriado usam a mesma tabela.
- Dúvida de buffet, cardápio, regras ou do que o pacote inclui: responda o que
  souber e escolha em "material" o material do tipo de evento do cliente. O
  material chega ao cliente logo ANTES da sua resposta.
- Preencha tipo_evento, convidados e data_interesse com o que o cliente disse
  nesta conversa ("" / 0 quando não souber). Datas no formato AAAA-MM-DD;
  sem ano, use a próxima ocorrência a partir de hoje.

# Estilo
- Português do Brasil, acolhedor e direto. No máximo 3 frases curtas.
- Formatação do WhatsApp: *negrito* com um asterisco. 🌻 com moderação.
- Não se apresente de novo: o cliente já conversa com você.

<roteiro>
{ROTEIRO_IA}
</roteiro>"""

# Contagem diária por telefone, em memória: um restart zera, o que só
# deixa passar algumas chamadas a mais — aceitável para o volume do sítio.
_uso: dict = {}


def _pode_usar(telefone: str) -> bool:
    hoje = date.today()
    dia, n = _uso.get(telefone, (hoje, 0))
    if dia != hoje:
        n = 0
    if n >= LIMITE_DIARIO:
        return False
    _uso[telefone] = (hoje, n + 1)
    return True


def _data(s):
    try:
        return date.fromisoformat(str(s)[:10]) if s else None
    except ValueError:
        return None


def _por_extenso(d: date) -> str:
    return f"{DIAS[d.weekday()]}, {d.strftime('%d/%m/%Y')}"


def completo(q: dict) -> bool:
    return bool(q.get("tipo_evento")) and q.get("convidados", 0) > 0 \
        and q.get("data_interesse") is not None


def resumo(q: dict) -> str:
    partes = []
    if q.get("tipo_evento"):
        partes.append(ROTULO_TIPO.get(q["tipo_evento"], q["tipo_evento"]))
    if q.get("convidados"):
        partes.append(f"{q['convidados']} convidados")
    if q.get("data_interesse"):
        partes.append(_por_extenso(q["data_interesse"]))
    return " · ".join(partes)


async def disponibilidade(dia: date) -> dict:
    """Livre se o dia não tem evento. Senão, até 3 dias de fim de semana livres
    mais próximos (antes ou depois), nunca no passado."""
    from db import dias_com_evento
    hoje = datetime.now(TZ).date()
    if dia < hoje:
        return {"data": dia.isoformat(), "erro": "data no passado"}
    janela_ini, janela_fim = max(hoje, dia - timedelta(days=60)), dia + timedelta(days=120)
    ocupados = await dias_com_evento(janela_ini, janela_fim)
    livre = dia not in ocupados
    saida = {"data": dia.isoformat(), "dia_semana": DIAS[dia.weekday()], "livre": livre}
    if not livre:
        candidatos = []
        d = janela_ini
        while d <= janela_fim:
            if d.weekday() in (5, 6) and d not in ocupados and d != dia:
                candidatos.append(d)
            d += timedelta(days=1)
        candidatos.sort(key=lambda x: (abs((x - dia).days), x))
        saida["fins_de_semana_livres_mais_proximos"] = [_por_extenso(x) for x in candidatos[:3]]
    return saida


def _reais(v: int) -> str:
    return "R$ " + f"{v:,.0f}".replace(",", ".")


def valores(tipo: str, convidados, dia) -> dict:
    """Tabela do pacote para a faixa de convidados — sem conta da IA."""
    from content import PRECOS, ADICIONAL_CALDO, ADICIONAL_JANTAR
    tabela = PRECOS.get(tipo)
    if not tabela:
        return {"erro": "sem tabela para esse tipo de evento: orçamento com a equipe"}
    try:
        n = int(convidados or 0)
    except (TypeError, ValueError):
        n = 0
    if n <= 0:
        return {"erro": "informe o número de convidados"}
    faixas = sorted(next(iter(tabela["standard"].values())))
    if n > faixas[-1]:
        return {"erro": f"acima de {faixas[-1]} convidados o orçamento é feito pela equipe"}
    faixa = next(f for f in faixas if f >= n)

    saida = {"tipo_evento": tipo, "convidados": n, "faixa_usada": f"até {faixa} pessoas"}
    if tipo == "infantil":
        saida["observacao"] = "preço não varia pelo dia; varia com ou sem decoração"
        for menu in ("standard", "premium"):
            saida[menu] = {k: _reais(v[faixa]) for k, v in tabela[menu].items()}
    else:
        if dia:
            chave = "fim_de_semana" if dia.weekday() >= 5 else "semana"
            saida["dia"] = f"{DIAS[dia.weekday()]} → tabela {chave.replace('_', ' ')}" \
                + (" (se for feriado, vale a tabela de fim de semana)" if chave == "semana" else "")
            for menu in ("standard", "premium"):
                saida[menu] = _reais(tabela[menu][chave][faixa])
        else:
            for menu in ("standard", "premium"):
                saida[menu] = {k: _reais(v[faixa]) for k, v in tabela[menu].items()}
    saida["adicionais_por_convidado"] = {
        "mais um caldo": _reais(ADICIONAL_CALDO),
        "mais um prato principal (Standard)": _reais(ADICIONAL_JANTAR)}
    saida["lembrete"] = "valor de tabela; orçamento final e reserva com a equipe"
    return saida


async def _contexto(telefone: str) -> str:
    """Últimas mensagens da conversa, para a IA não perder o fio."""
    try:
        from db import historico
        msgs = await historico(telefone, limite=400)
    except Exception:
        return ""
    linhas = []
    for m in msgs[-12:]:
        texto = (m.get("conteudo") or "").strip()
        if not texto or m.get("tipo") not in ("text", "interactive", None):
            continue
        quem = "Cliente" if m.get("direcao") == "recebida" else "Sítio"
        linhas.append(f"{quem}: {texto[:300]}")
    return "\n".join(linhas[:-1])  # a última é a própria pergunta


async def _chamar(conteudo: str):
    """Conversa com o modelo, executando a consulta de datas quando pedida."""
    mensagens = [{"role": "user", "content": conteudo}]
    for _ in range(3):
        r = await _cliente.messages.create(
            model=MODELO,
            max_tokens=2048,  # sobra para o raciocínio interno + resposta curta
            system=[{"type": "text", "text": SISTEMA,
                     "cache_control": {"type": "ephemeral"}}],
            tools=[FERRAMENTA, FERRAMENTA_VALORES],
            output_config={"effort": "low",
                           "format": {"type": "json_schema", "schema": ESQUEMA}},
            messages=mensagens,
        )
        if r.stop_reason != "tool_use":
            return r
        resultados = []
        for b in r.content:
            if b.type != "tool_use":
                continue
            if b.name == "consultar_valores":
                saida = valores(b.input.get("tipo_evento"), b.input.get("convidados"),
                                _data(b.input.get("data")))
            else:
                d = _data(b.input.get("data"))
                saida = await disponibilidade(d) if d else {"erro": "data inválida"}
            log.info("IA: %s %s → %s", b.name, b.input, saida)
            resultados.append({"type": "tool_result", "tool_use_id": b.id,
                               "content": json.dumps(saida, ensure_ascii=False)})
        mensagens.append({"role": "assistant", "content": r.content})
        mensagens.append({"role": "user", "content": resultados})
    return None


async def atender(telefone: str, nome: str, pergunta: str):
    """
    Devolve um dict com:
      acao: "responder" | "atendente" | "menu" | "limite"
      resposta, material, qualificacao (dict), resumo (str)
    ou None se a IA não puder responder (desligada, erro, limite diário).
    "limite" = dúvidas livres esgotadas: o bot só oferece o atendente.
    """
    if not ativo or not pergunta.strip():
        return None
    from db import get_qualificacao, salvar_qualificacao

    q = await get_qualificacao(telefone)
    ja_completo = completo(q)
    if ja_completo and q.get("duvidas_ia", 0) >= LIMITE_DUVIDAS:
        return {"acao": "limite", "qualificacao": q, "resumo": resumo(q)}
    if not _pode_usar(telefone):
        log.info("IA: limite diário atingido para %s", telefone)
        return None

    hoje = datetime.now(TZ).date()
    sabido = resumo(q) or "nada ainda"
    falta = [n for n, ok in (("tipo de evento", q.get("tipo_evento")),
                             ("data de interesse", q.get("data_interesse")),
                             ("número de convidados", q.get("convidados")))
             if not ok]
    conteudo = f"Hoje é {_por_extenso(hoje)}.\n"
    if nome and nome not in ("cliente", "tudo bem"):
        conteudo += f"Nome do cliente: {nome}\n"
    conteudo += f"Já sabemos: {sabido}\n"
    conteudo += f"Falta capturar: {', '.join(falta) if falta else 'nada'}\n"
    if ja_completo:
        restam = LIMITE_DUVIDAS - q.get("duvidas_ia", 0)
        conteudo += f"Dúvidas livres restantes antes de passar para a equipe: {restam}\n"
    historico_txt = await _contexto(telefone)
    if historico_txt:
        conteudo += f"\n<conversa_recente>\n{historico_txt}\n</conversa_recente>\n"
    conteudo += f"\nMensagem do cliente:\n{pergunta[:1000]}"

    try:
        r = await _chamar(conteudo)
    except Exception as e:
        log.error("IA: falha na chamada — %s", e)
        return None
    if r is None or r.stop_reason != "end_turn":
        log.warning("IA: resposta interrompida (%s)", r and r.stop_reason)
        return None

    texto = next((b.text for b in r.content if b.type == "text"), "")
    try:
        dados = json.loads(texto)
    except (ValueError, TypeError):
        dados = None
    if (not isinstance(dados, dict)
            or dados.get("acao") not in ("responder", "atendente", "menu")
            or dados.get("material") not in MATERIAIS
            or dados.get("tipo_evento") not in TIPOS):
        log.error("IA: resposta fora do formato — %r", texto[:200])
        return None
    if dados["acao"] != "menu" and not (dados.get("resposta") or "").strip():
        return None

    # Guarda o que a IA capturou; a dúvida conta só se a qualificação já
    # estava completa antes desta mensagem.
    nova_data = _data(dados.get("data_interesse"))
    if nova_data and nova_data < hoje:
        nova_data = None
    convidados = dados.get("convidados") or 0
    convidados = convidados if 0 < convidados < 10000 else 0
    await salvar_qualificacao(
        telefone, dados.get("tipo_evento") or "", convidados, nova_data,
        somar_duvida=ja_completo and dados["acao"] == "responder")
    q = await get_qualificacao(telefone)

    u = r.usage
    log.info("IA: %s → %s/%s [%s] (in=%s cache=%s out=%s)", telefone, dados["acao"],
             dados["material"], resumo(q), u.input_tokens,
             getattr(u, "cache_read_input_tokens", 0), u.output_tokens)

    dados["qualificacao"] = q
    dados["resumo"] = resumo(q)
    return dados
