"""
IA para perguntas livres (Claude Haiku 5.5).

Só entra em cena quando o cliente escreve algo que não casa com nenhuma
opção do menu nem com as palavras-chave de content.ATALHOS. Responde com
base no ROTEIRO_IA de content.py e nunca fecha nada: data, orçamento,
contrato e reserva vão sempre para a equipe.

Configuração (Render → Environment):
  ANTHROPIC_API_KEY   chave da API (console.anthropic.com)
  IA_ATIVA            0 desliga sem precisar apagar a chave (padrão 1)
  IA_LIMITE_DIARIO    respostas da IA por cliente por dia (padrão 15)

Qualquer falha devolve None — o bot cai no menu, como antes da IA.
"""
import os
import json
import logging
from datetime import date

from content import ROTEIRO_IA, NOME_ASSISTENTE

log = logging.getLogger("sitio-bot")

MODELO = "claude-haiku-5-5"
LIMITE_DIARIO = int(os.getenv("IA_LIMITE_DIARIO", "15"))

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

ESQUEMA = {
    "type": "object",
    "properties": {
        "resposta": {"type": "string"},
        "acao": {"type": "string", "enum": ["responder", "atendente"]},
        "material": {"type": "string", "enum": MATERIAIS},
    },
    "required": ["resposta", "acao", "material"],
    "additionalProperties": False,
}

SISTEMA = f"""Você é a {NOME_ASSISTENTE}, assistente virtual do Sítio Girassol no WhatsApp.
Você responde dúvidas de pessoas interessadas em fazer eventos no sítio.

Use SOMENTE as informações do roteiro abaixo. Se a resposta não estiver no
roteiro, não invente: diga que vai confirmar com a equipe e use acao "atendente".

Encaminhe para a equipe (acao "atendente") sempre que a pessoa:
- pedir orçamento, preço ou valor;
- quiser saber se uma data está livre, reservar, agendar visita ou marcar evento;
- falar em fechar, assinar contrato ou pagar;
- pedir para falar com uma pessoa, reclamar ou parecer insatisfeita.
Nesses casos, diga com simpatia que vai chamar alguém da equipe para continuar.
Você nunca confirma data, nunca informa valores e nunca fecha negócio.

Estilo:
- Português do Brasil, tom acolhedor e direto, como uma atendente simpática.
- No máximo 3 frases curtas. Pode usar 🌻 com moderação.
- Formatação do WhatsApp: *negrito* com um asterisco. Sem listas longas.
- Não se apresente de novo se a conversa já começou.

Campo "material": se um material do roteiro ajudar a responder (por exemplo
o PDF do casamento para quem pergunta o que o pacote inclui), escolha-o;
senão use "nenhum". Não repita na resposta o que o material já mostra.

<roteiro>
{ROTEIRO_IA}
</roteiro>"""

# Contagem diária por telefone, em memória: um restart zera, o que só
# deixa passar alguns pedidos a mais — aceitável para o volume do sítio.
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


async def _contexto(telefone: str) -> str:
    """Últimas mensagens de texto da conversa, para a IA não perder o fio."""
    try:
        from db import historico
        msgs = await historico(telefone, limite=400)
    except Exception:
        return ""
    linhas = []
    for m in msgs[-10:]:
        texto = (m.get("conteudo") or "").strip()
        if not texto or m.get("tipo") not in ("text", "interactive", None):
            continue
        quem = "Cliente" if m.get("direcao") == "recebida" else "Sítio"
        linhas.append(f"{quem}: {texto[:300]}")
    return "\n".join(linhas[:-1])  # a última é a própria pergunta


async def responder(telefone: str, nome: str, pergunta: str):
    """
    Devolve {"resposta", "acao", "material"} ou None se a IA não puder
    responder (desligada, limite do dia, erro, recusa).
    """
    if not ativo or not pergunta.strip():
        return None
    if not _pode_usar(telefone):
        log.info("IA: limite diário atingido para %s", telefone)
        return None

    historico_txt = await _contexto(telefone)
    conteudo = ""
    if historico_txt:
        conteudo += f"<conversa_recente>\n{historico_txt}\n</conversa_recente>\n\n"
    if nome and nome not in ("cliente", "tudo bem"):
        conteudo += f"Nome do cliente: {nome}\n"
    conteudo += f"Mensagem do cliente:\n{pergunta[:1000]}"

    try:
        r = await _cliente.messages.create(
            model=MODELO,
            max_tokens=2048,  # sobra para o raciocínio interno + a resposta curta
            system=[{"type": "text", "text": SISTEMA,
                     "cache_control": {"type": "ephemeral"}}],
            output_config={
                "effort": "low",
                "format": {"type": "json_schema", "schema": ESQUEMA},
            },
            messages=[{"role": "user", "content": conteudo}],
        )
    except Exception as e:
        log.error("IA: falha na chamada — %s", e)
        return None

    if r.stop_reason != "end_turn":
        log.warning("IA: resposta interrompida (%s)", r.stop_reason)
        return None

    texto = next((b.text for b in r.content if b.type == "text"), "")
    try:
        dados = json.loads(texto)
    except (ValueError, TypeError):
        dados = None
    if (not isinstance(dados, dict)
            or dados.get("acao") not in ("responder", "atendente")
            or dados.get("material") not in MATERIAIS):
        log.error("IA: resposta fora do formato — %r", texto[:200])
        return None

    u = r.usage
    log.info("IA: %s → %s/%s (in=%s cache=%s out=%s)", telefone, dados.get("acao"),
             dados.get("material"), u.input_tokens,
             getattr(u, "cache_read_input_tokens", 0), u.output_tokens)

    if not (dados.get("resposta") or "").strip():
        return None
    return dados
