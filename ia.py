"""
IA de atendimento (Claude Haiku 5.5) — conduz o cliente até o fechamento.

Entra em cena quando o cliente escreve texto livre que não é saudação nem
opção do menu. Papel:

  1. Criar relação e capturar tipo de evento, número de convidados e data
     (gravados no lead; o cliente pode mudar a qualquer momento).
  2. Com a data, consultar a agenda do painel; se o dia tiver evento,
     sugerir o fim de semana livre mais próximo. Data ambígua: considera a
     próxima ocorrência e diz qual, para o cliente corrigir.
  3. Tirar as dúvidas e só oferecer o representante quando não houver mais.
  4. Fora do tema → menu, sem texto da IA. Fuga de foco (fora do tema ou
     pergunta repetida) conta desvio; no 5º, só menu por 1 hora.

Configuração (Render → Environment):
  ANTHROPIC_API_KEY   chave da API (platform.claude.com)
  IA_ATIVA            0 desliga sem apagar a chave (padrão 1)
  IA_LIMITE_DIARIO    chamadas da IA por cliente por dia (padrão 40)
  IA_DESVIOS          desvios de foco até a pausa (padrão 5)
  IA_PAUSA_MIN        minutos só com menu após os desvios (padrão 60)

Qualquer falha devolve None — o bot cai no menu, como antes da IA.
"""
import os
import json
import re
import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from content import ROTEIRO_IA, NOME_ASSISTENTE

log = logging.getLogger("sitio-bot")

MODELO = "claude-haiku-5-5"
TZ = ZoneInfo(os.getenv("TIMEZONE", "America/Sao_Paulo"))
LIMITE_DIARIO = int(os.getenv("IA_LIMITE_DIARIO", "40"))
# Foco: mensagens fora do tema ou repetidas. Na 5ª, só menu por 1 hora.
LIMITE_DESVIOS = int(os.getenv("IA_DESVIOS", "5"))
PAUSA_MIN = int(os.getenv("IA_PAUSA_MIN", "60"))

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
             "decorado", "fotos", "localizacao", "regras"]
TIPOS = ["", "casamento", "quinze", "infantil", "confraternizacao", "decorado",
         "locacao", "outro"]
ROTULO_TIPO = {"casamento": "Casamento", "quinze": "15 anos", "infantil": "Infantil",
               "confraternizacao": "Aniversário/confraternização",
               "decorado": "Espaço decorado", "locacao": "Locação do espaço",
               "outro": "Outro"}
AVISO_ESTIMATIVA = ("_Valores estimados com base na nossa tabela. O valor final é "
                    "fechado com um de nossos representantes._")
DIAS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]

def esquema(materiais: list) -> dict:
    """Esquema da resposta com os materiais válidos agora (inclui pacotes
    criados no painel)."""
    e = json.loads(json.dumps(ESQUEMA))
    e["properties"]["material"]["enum"] = materiais
    return e


ESQUEMA = {
    "type": "object",
    "properties": {
        "acao": {"type": "string", "enum": ["responder", "atendente", "menu"]},
        "resposta": {"type": "string"},
        "material": {"type": "string", "enum": MATERIAIS},
        "tipo_evento": {"type": "string", "enum": TIPOS},
        "convidados": {"type": "integer"},
        "data_interesse": {"type": "string"},
        "reenviar_material": {"type": "boolean"},
        "desvio": {"type": "boolean"},
        "resumo_conversa": {"type": "string"},
    },
    "required": ["acao", "resposta", "material", "tipo_evento", "convidados",
                 "data_interesse", "reenviar_material", "desvio", "resumo_conversa"],
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

def ferramenta_valores(pacotes: list) -> dict:
    """Ferramenta de preços montada com os pacotes ativos do painel."""
    lista = "; ".join(f"{p['chave']} = {p['nome']}" for p in pacotes)
    return {
        "name": "consultar_valores",
        "description": (
            "Devolve a estimativa de tabela de um pacote (todos os menus) para o "
            "número de convidados e a data. Use sempre que o cliente perguntar "
            f"preço/valor/quanto custa. Pacotes com tabela: {lista}. Sem data, "
            "devolve todas as colunas."),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "pacote": {"type": "string", "enum": [p["chave"] for p in pacotes]},
                "convidados": {"type": "integer"},
                "data": {"type": "string", "description": "AAAA-MM-DD ou vazio"},
            },
            "required": ["pacote", "convidados", "data"],
            "additionalProperties": False,
        },
    }


SISTEMA = f"""Você é a {NOME_ASSISTENTE}, assistente virtual do Sítio Girassol no WhatsApp.
Seu objetivo é criar uma boa relação com o cliente e levá-lo até o
fechamento com um de nossos representantes (pessoas da equipe). Você é a
assistente virtual, não um representante: nunca se passe por um.

# Campo "acao"
- "menu": a mensagem NÃO tem relação com eventos no sítio (assunto aleatório,
  spam, pedido sem sentido). O bot mostra o menu; deixe "resposta" vazia.
- "atendente": o cliente pede para fechar, reservar, negociar desconto,
  agendar visita ou falar com uma pessoa/representante (inclusive com a
  dona do sítio, a Neia ou qualquer pessoa da equipe), pede
  telefone/WhatsApp/contato do sítio, reclama ou parece insatisfeito, OU
  disse que não tem mais dúvidas e aceitou falar com um representante.
  Diga que um de nossos representantes vai entrar em contato e que já
  recebe o resumo da conversa. NÃO fale prazo nem horário de retorno: o bot
  acrescenta a previsão certa logo depois da sua resposta.
- "responder": qualquer outra mensagem sobre os eventos.

# Conduza a conversa
1. Precisamos de três informações: tipo de evento, data de interesse e número
   de convidados. A cada informação que o cliente der, comente com
   simpatia e de forma pessoal (ex: "Casamento no campo é lindo demais!",
   "120 convidados dá uma festa animada!") e pergunte o que ainda falta, no
   máximo duas coisas por vez. Responda antes o que o cliente perguntou.
2. DATAS AMBÍGUAS: não deixe o cliente sem resposta. Sem ano ("12/12", "dia
   5 de março"), considere a próxima ocorrência a partir de hoje, consulte a
   agenda e diga claramente a data completa que considerou, convidando a
   corrigir ("Considerei *sábado, 12/12/2026* — se for outro ano, é só me
   falar"). Só mês ("em dezembro"): pergunte o dia. Data por extenso
   relativa ("sábado que vem"): calcule a partir de hoje e diga a data.
3. O cliente pode MUDAR a data, o tipo ou os convidados a qualquer momento:
   use sempre a informação mais recente, consulte a agenda de novo para a
   nova data e confirme a mudança.
4. A agenda está aberta só até o fim do ano seguinte (o limite vem na
   mensagem). Data depois disso: explique que a agenda ainda não abriu e
   que um representante pode anotar o interesse.
5. SEMPRE que o cliente informar ou mudar uma data, chame
   consultar_disponibilidade nessa mesma resposta e diga o resultado. Livre:
   diga que está livre, mas que a reserva só vale com um representante.
   Ocupada: ofereça os dias livres que a ferramenta devolver.
6. Capacidade máxima do sítio: 300 convidados. Acima disso, diga com
   gentileza que o limite é 300 e pergunte se dá para ajustar.
7. Com as três informações, tire as dúvidas e termine perguntando se ficou
   alguma dúvida. Só ofereça falar com um representante ("Quer que eu chame
   um de nossos representantes para montar seu orçamento e reservar a
   data?") quando o cliente indicar que não tem mais dúvidas.

# Campo "desvio"
true quando a mensagem foge do foco: assunto sem relação com os eventos, ou
a mesma pergunta que já foi respondida nesta conversa. false em todo o resto
(inclusive dúvidas novas, mudanças de data e respostas às suas perguntas).

# Regras
- Use SOMENTE o roteiro. Se não estiver lá, diga que um representante
  confirma no orçamento. Nunca faça reserva nem dê desconto.
- VALORES SÓ QUANDO PERGUNTAREM: não fale de preço, valor, entrada, sinal,
  parcelamento ou formas de pagamento por iniciativa própria — nem para
  "adiantar". Só responda sobre isso quando o cliente perguntar diretamente
  (ex: "quanto custa?", "qual o valor da entrada?", "como pago?"). Também
  não escolha o material "regras" se ele não perguntou de pagamento.
- Valores (quando perguntarem): só com consultar_valores (precisa do tipo e
  dos convidados; se faltar, pergunte). Apresente SEMPRE como estimativa ("fica em torno de",
  "a estimativa é"), nunca como preço fechado: o valor final é definido por
  um representante. Mostre os menus da faixa, em reais (ex: *R$ 18.000*).
  Sem data, mostre as colunas (ex: semana e fim de semana). Fim de semana e
  feriado usam a mesma coluna. Escolha o pacote que corresponde ao evento.
  Junto de cada valor, resuma em uma linha o que aquele menu inclui (use
  "o_que_inclui" da ferramenta, destacando o que diferencia um menu do
  outro). Formato: uma linha por menu, ex: "• *Standard* — *R$ 23.500*:
  2 caldos, ilha de massas, prato à escolha, salgados, bebidas e cortesias".
  Nessa mensagem pode passar de 3 frases.
- CONTATOS: nunca envie nem escreva telefone, WhatsApp, e-mail ou contato
  do sítio, da dona, da Neia ou de qualquer pessoa da equipe — nem se o
  cliente insistir. Responda que um de nossos representantes vai entrar em
  contato com ele (acao "atendente").
- Materiais: se for enviar algo (fotos, PDF, localização, material
  de um pacote pela chave do pacote), escolha esse item em "material". O
  material chega ao cliente ANTES da sua resposta: não anuncie nem repita o
  envio ("vou te enviar", "segue as fotos", "te mandei"). Use a resposta
  para seguir a conversa — de preferência perguntando o que falta entre
  tipo de evento, data e convidados. O PDF do tipo de evento vai uma vez só: quando o
  tipo é confirmado pela primeira vez; depois diga "confira no PDF que te
  enviei". Fotos e localização podem ir sempre que pedirem. Se o
  cliente pedir de novo um PDF já enviado, escolha-o e marque
  reenviar_material = true. O PDF certo é SEMPRE o do tipo de evento atual
  do cliente (se ele mudou de 15 anos para casamento, é o de casamento).
- Preencha tipo_evento, convidados e data_interesse com a informação mais
  recente da conversa ("" / 0 quando não souber). Datas em AAAA-MM-DD.
- resumo_conversa: 1 ou 2 frases para a equipe sobre o que o cliente quer,
  o que já foi dito e o que ficou pendente (ex: "Quer casamento ao ar livre
  em dez/2026 para 120 pessoas; perguntou de DJ e estacionamento; ainda
  decidindo entre Standard e Premium.").

# Estilo
- Português do Brasil, caloroso, próximo e direto. No máximo 3 frases curtas.
- Formatação do WhatsApp: *negrito* com um asterisco. 🌻 com moderação.
- Não se apresente nem assine: o bot já identifica suas mensagens como da
  assistente virtual.

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
    limite = date(hoje.year + 1, 12, 31)
    if dia > limite:
        return {"data": dia.isoformat(), "erro": (
            f"a agenda ainda não está aberta para essa data: só vai até "
            f"{limite.strftime('%d/%m/%Y')}. Um representante pode anotar o interesse.")}
    janela_ini = max(hoje, dia - timedelta(days=60))
    janela_fim = min(limite, dia + timedelta(days=120))
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


def valores(pacote: dict, convidados, dia) -> dict:
    """Estimativa do pacote para a faixa de convidados — sem conta da IA."""
    if not pacote:
        return {"erro": "sem tabela para esse pacote: orçamento com um representante"}
    try:
        n = int(convidados or 0)
    except (TypeError, ValueError):
        n = 0
    if n <= 0:
        return {"erro": "informe o número de convidados"}
    faixas = list(pacote.get("faixas") or [])
    if not faixas:
        return {"erro": "pacote sem tabela: orçamento com um representante"}
    if n > faixas[-1]:
        return {"erro": f"acima de {faixas[-1]} convidados o orçamento é feito por um representante"}
    k = next(i for i, f in enumerate(faixas) if f >= n)
    menus, colunas, precos = pacote["menus"], pacote["colunas"], pacote["precos"]

    def preco(m, c):
        try:
            v = precos[m][c][k]
        except (IndexError, TypeError):
            v = None
        return _reais(v) if v else "sob consulta"

    saida = {"pacote": pacote["nome"], "convidados": n, "faixa_usada": f"até {faixas[k]} pessoas"}
    if pacote.get("variacao") == "dia" and dia and len(colunas) >= 2:
        c = 1 if dia.weekday() >= 5 else 0
        saida["dia"] = f"{DIAS[dia.weekday()]} → coluna '{colunas[c]}'" + \
            (" (se for feriado, vale a de fim de semana)" if c == 0 else "")
        for m, nome in enumerate(menus):
            saida[nome] = preco(m, c)
    else:
        if pacote.get("variacao") != "dia":
            saida["observacao"] = "o preço varia por: " + " / ".join(colunas)
        for m, nome in enumerate(menus):
            saida[nome] = {col: preco(m, c) for c, col in enumerate(colunas)}
    inc = pacote.get("inclui") or []
    inclui = {nome: inc[m].strip() for m, nome in enumerate(menus)
              if m < len(inc) and (inc[m] or "").strip()}
    if inclui:
        saida["o_que_inclui"] = inclui
    if pacote.get("adicionais"):
        saida["adicionais_por_convidado"] = {
            a["nome"]: _reais(a["valor"]) for a in pacote["adicionais"] if a.get("valor")}
    saida["lembrete"] = ("ESTIMATIVA de tabela, não é preço fechado: o valor final "
                         "é definido por um de nossos representantes")
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


async def _chamar(conteudo: str, pacotes: dict):
    """Conversa com o modelo, executando a consulta de datas quando pedida."""
    materiais = MATERIAIS + [k for k in pacotes if k not in MATERIAIS]
    ferramentas = [FERRAMENTA] + ([ferramenta_valores(list(pacotes.values()))] if pacotes else [])
    mensagens = [{"role": "user", "content": conteudo}]
    usados = set()
    for _ in range(3):
        r = await _cliente.messages.create(
            model=MODELO,
            max_tokens=2048,  # sobra para o raciocínio interno + resposta curta
            system=[{"type": "text", "text": SISTEMA,
                     "cache_control": {"type": "ephemeral"}}],
            tools=ferramentas,
            output_config={"effort": "low",
                           "format": {"type": "json_schema", "schema": esquema(materiais)}},
            messages=mensagens,
        )
        if r.stop_reason != "tool_use":
            return r, usados
        resultados = []
        for b in r.content:
            if b.type != "tool_use":
                continue
            usados.add(b.name)
            if b.name == "consultar_valores":
                saida = valores(pacotes.get(b.input.get("pacote")),
                                b.input.get("convidados"), _data(b.input.get("data")))
            else:
                d = _data(b.input.get("data"))
                saida = await disponibilidade(d) if d else {"erro": "data inválida"}
            log.info("IA: %s %s → %s", b.name, b.input, saida)
            resultados.append({"type": "tool_result", "tool_use_id": b.id,
                               "content": json.dumps(saida, ensure_ascii=False)})
        mensagens.append({"role": "assistant", "content": r.content})
        mensagens.append({"role": "user", "content": resultados})
    return None, usados


async def _responder(conteudo: str, pacotes: dict):
    """Uma rodada com o modelo. Devolve (dados, resposta, ferramentas usadas)
    ou (None, ...) se a resposta não serviu."""
    r, ferramentas = await _chamar(conteudo, pacotes)
    if r is None or r.stop_reason != "end_turn":
        log.warning("IA: resposta interrompida (%s)", r and r.stop_reason)
        return None, r, ferramentas
    texto = next((b.text for b in r.content if b.type == "text"), "")
    try:
        dados = json.loads(texto)
    except (ValueError, TypeError):
        dados = None
    if (not isinstance(dados, dict)
            or dados.get("acao") not in ("responder", "atendente", "menu")
            or (dados.get("material") not in MATERIAIS and dados.get("material") not in pacotes)
            or dados.get("tipo_evento") not in TIPOS):
        log.error("IA: resposta fora do formato — %r", texto[:200])
        return None, r, ferramentas
    if dados["acao"] != "menu" and not (dados.get("resposta") or "").strip():
        return None, r, ferramentas
    if _tem_contato(dados.get("resposta") or ""):
        log.warning("IA: resposta com telefone/e-mail barrada")
        dados["acao"] = "atendente"
        dados["resposta"] = ("Vou pedir para um de nossos representantes "
                             "entrar em contato com você! 🌻")
    return dados, r, ferramentas


# Telefone (8+ dígitos, com ou sem DDD/separadores) ou e-mail.
_CONTATO_RE = re.compile(
    r"(?<![\d/.,])(?:\+?55\s?)?(?:\(?\d{2}\)?\s?)?9?\d{4}[\s.-]?\d{4}(?![\d/])"
    r"|[\w.+-]+@[\w-]+\.[\w.]+")


def _tem_contato(texto: str) -> bool:
    return bool(_CONTATO_RE.search(texto))


async def atender(telefone: str, nome: str, pergunta: str):
    """
    Devolve um dict com:
      acao: "responder" | "atendente" | "menu" | "pausada"
      resposta, material, reenviar_material, qualificacao (dict), resumo (str),
      pausou (bool: a IA acabou de entrar em pausa por desvios)
    ou None se a IA não puder responder (desligada, erro, limite diário).
    "pausada" = cliente restrito ao menu por desviar do foco.
    """
    if not ativo or not pergunta.strip():
        return None
    from db import (get_qualificacao, salvar_qualificacao, ia_pausada,
                    registrar_desvio, salvar_resumo_ia, avancar_etapa)

    if await ia_pausada(telefone):
        return {"acao": "pausada"}
    q = await get_qualificacao(telefone)
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
    conteudo += f"Agenda aberta até {date(hoje.year + 1, 12, 31).strftime('%d/%m/%Y')}.\n"
    if nome and nome not in ("cliente", "tudo bem"):
        conteudo += f"Nome do cliente: {nome}\n"
    conteudo += f"Já sabemos: {sabido}\n"
    conteudo += f"Falta capturar: {', '.join(falta) if falta else 'nada'}\n"
    try:
        from db import materiais_enviados
        enviados = sorted(await materiais_enviados(telefone))
    except Exception:
        enviados = []
    conteudo += f"Materiais já enviados: {', '.join(enviados) if enviados else 'nenhum'}\n"
    historico_txt = await _contexto(telefone)
    if historico_txt:
        conteudo += f"\n<conversa_recente>\n{historico_txt}\n</conversa_recente>\n"
    conteudo += f"\nMensagem do cliente:\n{pergunta[:1000]}"

    try:
        from db import listar_pacotes
        pacotes = {p["chave"]: p for p in await listar_pacotes(so_ativos=True)}
        dados, r, ferramentas = await _responder(conteudo, pacotes)

        # Data nova sem consulta à agenda: pede a resposta de novo, já
        # mandando consultar. Garante que toda data informada é verificada.
        nova = _data((dados or {}).get("data_interesse"))
        if dados and nova and nova != q.get("data_interesse") \
                and nova >= hoje and "consultar_disponibilidade" not in ferramentas:
            log.info("IA: data %s sem consulta à agenda — pedindo de novo", nova)
            conteudo += (f"\n\n[Aviso do sistema: o cliente informou a data "
                         f"{nova.isoformat()}. Chame consultar_disponibilidade "
                         f"para ela antes de responder e diga o resultado.]")
            dados2, r2, ferr2 = await _responder(conteudo, pacotes)
            if dados2:
                dados, r, ferramentas = dados2, r2, ferramentas | ferr2
    except Exception as e:
        log.error("IA: falha na chamada — %s", e)
        return None
    if not dados:
        return None

    # Guarda o que a IA capturou (a informação mais recente vence).
    nova_data = _data(dados.get("data_interesse"))
    if nova_data and nova_data < hoje:
        nova_data = None
    convidados = dados.get("convidados") or 0
    convidados = convidados if 0 < convidados < 10000 else 0
    await salvar_qualificacao(telefone, dados.get("tipo_evento") or "",
                              convidados, nova_data)
    await salvar_resumo_ia(telefone, (dados.get("resumo_conversa") or "").strip())
    q = await get_qualificacao(telefone)
    if completo(q):
        await avancar_etapa(telefone, "qualificado")
    elif q.get("tipo_evento") or q.get("convidados") or q.get("data_interesse"):
        await avancar_etapa(telefone, "qualificando")

    # Foco: assunto fora dos eventos ou pergunta repetida conta um desvio.
    dados["pausou"] = False
    if dados.get("desvio") or dados["acao"] == "menu":
        dados["pausou"] = await registrar_desvio(telefone, LIMITE_DESVIOS, PAUSA_MIN)

    u = r.usage
    log.info("IA: %s → %s/%s [%s] (in=%s cache=%s out=%s)", telefone, dados["acao"],
             dados["material"], resumo(q), u.input_tokens,
             getattr(u, "cache_read_input_tokens", 0), u.output_tokens)

    # Valor da tabela sempre sai como estimativa, mesmo que a IA esqueça.
    if "consultar_valores" in ferramentas and dados["acao"] != "menu":
        dados["resposta"] = dados["resposta"].rstrip() + "\n\n" + AVISO_ESTIMATIVA

    dados["qualificacao"] = q
    dados["resumo"] = resumo(q)
    return dados
