"""
=============================================================
  ÚNICO ARQUIVO QUE PRECISA SER EDITADO NO DIA A DIA
=============================================================

Arquivos esperados no projeto:

  pdfs/pacotes_casamento.pdf
  pdfs/pacotes_15anos.pdf
  pdfs/pacotes_infantil.pdf
  images/imagem_espaco_decorado.jpeg
  images/imagem_confraternizacao.jpeg

Blocos: texto | pdf | imagem | localizacao
Um bloco = uma mensagem, com 1,5s de intervalo entre elas.

Limites da Cloud API: imagem 5 MB - PDF 100 MB
"""
import os

BASE = os.getenv("BASE_URL", "https://chatbot-wpp-593m.onrender.com")
IMG = f"{BASE}/images"
PDF = f"{BASE}/pdfs"

# Número do atendente humano (só dígitos, com DDI). Ex: 5521999999999
NUMERO_ATENDENTE = os.getenv("NUMERO_ATENDENTE", "")

# Números de trabalho que recebem a agenda do dia (separados por vírgula).
# Ex: NUMEROS_EQUIPE=5521999999999,5521888888888
NUMEROS_EQUIPE = [n.strip() for n in os.getenv("NUMEROS_EQUIPE", "").split(",") if n.strip()]
if not NUMEROS_EQUIPE and NUMERO_ATENDENTE:
    NUMEROS_EQUIPE = [NUMERO_ATENDENTE]

# Nome do assistente virtual, usado nas saudações e nas confirmações
NOME_ASSISTENTE = os.getenv("NOME_ASSISTENTE", "Sol")

# Cartão de contato do sítio — o bot envia isso quando o cliente pede.
# Também é a base do vCard baixado do painel.
CONTATO_SITIO = {
    "nome": os.getenv("SITIO_NOME", "Sítio Girassol"),
    "telefone": os.getenv("SITIO_TELEFONE", NUMERO_ATENDENTE),
    "endereco": os.getenv(
        "SITIO_ENDERECO",
        "Estrada da Serra Alta 1837, Campo Grande, Rio de Janeiro - RJ"),
    "email": os.getenv("SITIO_EMAIL", ""),
}


def texto_saudacao() -> str:
    """Primeira mensagem de quem nunca falou com o bot."""
    return (
        f"Olá! 🌻 Eu sou a *{NOME_ASSISTENTE}*, assistente virtual do Sítio Girassol.\n\n"
        "Estou aqui para te mostrar nossos espaços, pacotes e valores — "
        "e, se preferir, chamo alguém da equipe a qualquer momento.\n\n"
        "Para começar, como posso te chamar?"
    )


def texto_apresentacao(nome: str) -> str:
    """Cabeçalho do menu principal."""
    return (
        f"Olá, {nome}! 🌻\n\n"
        f"Eu sou a *{NOME_ASSISTENTE}*, assistente virtual do Sítio Girassol. "
        "Posso te enviar nossos pacotes, fotos do espaço e informações de "
        "pagamento — e chamar um atendente quando você quiser.\n\n"
        "Escolha abaixo a opção que mais combina com o seu evento:"
    )


def texto_confirmacao(tipo: str, quando: str, nome: str = "",
                      remarcado: bool = False) -> str:
    """
    Confirmação enviada ao cliente quando a visita ou o evento é marcado
    no painel. `quando` já vem escrito por extenso.
    """
    saudacao = f"Olá, {nome}! 🌻" if nome else "Olá! 🌻"
    if tipo == "visita":
        frase = ("Sua visita ao sítio foi *remarcada* para"
                 if remarcado else "Sua visita ao sítio está marcada para")
        fecho = ("Vai dar tempo de conhecer o espaço com calma. "
                 "Se precisar remarcar, é só responder por aqui. Até lá! 🌻")
    else:
        frase = ("Seu evento foi *remarcado* para"
                 if remarcado else "Seu evento está reservado para")
        fecho = ("Qualquer dúvida até lá, é só responder esta mensagem. "
                 "Vai ser lindo! 🌻")

    corpo = (
        f"{saudacao} Aqui é a {NOME_ASSISTENTE}, do Sítio Girassol.\n\n"
        f"{frase} *{quando}*.\n\n"
    )
    if tipo == "visita":
        corpo += (
            "📍 Estrada da Serra Alta 1837 — Campo Grande, Rio de Janeiro\n"
            "A 10 minutos do West Shopping.\n\n"
        )
    return corpo + fecho


# Mensagem enviada ao CLIENTE quando ele pede atendente
def texto_atendente() -> str:
    base = (
        "Dentro de instantes um atendente dará continuidade. 🌻\n\n"
        "Atenção que nossos horários de atendimento são das 9h às 18h. 🌻\n\n"
        "Para agilizar seu atendimento, me informe:\n\n"
        "• Sua data de interesse\n"
        "• Quantidade de convidados\n"
        "• Tipo de evento"
    )
    if NUMERO_ATENDENTE:
        base += (
            "\n\nSe preferir, fale agora mesmo com nossa equipe:\n"
            f"https://wa.me/{NUMERO_ATENDENTE}"
        )
    return base

CONTEUDO = {

    "casamento": {"blocos": [
        {"tipo": "pdf", "url": f"{PDF}/pacotes_casamento.pdf",
         "arquivo": "Pacotes Casamento - Sitio Girassol.pdf",
         "legenda": "Nossos pacotes para casamento 💒"},
        {"tipo": "texto", "texto": (
            "Nele temos à disposição:\n\n"
            "*5h de evento*, sendo 1h de cerimônia e 4h de buffet.\n\n"
            "*Decoração principal*\n"
            "• Armários de madeira\n"
            "• Mesas em madeira de 3m a 5m\n"
            "• Bolo fake\n"
            "• Decoração de chão\n"
            "• Lustres\n"
            "• Muro inglês\n"
            "• Louças e suportes\n"
            "• Arranjos de flores naturais\n"
            "• Suporte para bolo suspenso\n\n"
            "*Decoração da cerimônia*\n"
            "• Vasos de flores para o caminho da noiva\n"
            "• Mesa do celebrante\n"
            "• Pergolado em madeira\n"
            "• Portal em madeira\n"
            "• Decoração de flores\n\n"
            "*Para os convidados*\n"
            "• Mesas e cadeiras em madeira\n"
            "• Toalhas luxo\n"
            "• Voal na cor do evento\n"
            "• Espaço lounge\n"
            "• Espaços instagramáveis\n\n"
            "E ainda não acabou... como cortesia temos "
            "*300 doces gourmet* e *bolo de corte*! 🌻"
        )},
    ]},

    "quinze": {"blocos": [
        {"tipo": "pdf", "url": f"{PDF}/pacotes_15anos.pdf",
         "arquivo": "Pacotes 15 Anos - Sitio Girassol.pdf",
         "legenda": "Nossos pacotes para 15 anos 👑"},
    ]},

    "infantil": {"blocos": [
        {"tipo": "pdf", "url": f"{PDF}/pacotes_infantil.pdf",
         "arquivo": "Pacotes Infantil - Sitio Girassol.pdf",
         "legenda": "Nossos pacotes para eventos infantis 🎈"},
    ]},

    "decorado": {"blocos": [
        {"tipo": "imagem", "url": f"{IMG}/imagem_espaco_decorado.jpeg",
         "legenda": "Nosso espaço decorado 🌻"},
    ]},

    "confraternizacao": {"blocos": [
        {"tipo": "imagem", "url": f"{IMG}/imagem_confraternizacao.jpeg",
         "legenda": "Aniversários e confraternizações 🎉"},
    ]},

    # --- Acessíveis apenas por texto livre (não ocupam row no menu) ---

    "localizacao": {"blocos": [
        {"tipo": "texto", "texto": "Estamos a 10 minutos do West Shopping 🚗"},
        {"tipo": "localizacao", "lat": -22.8726748, "lng": -43.5375258,
         "nome": "Sítio Girassol",
         "endereco": "Estrada da Serra Alta 1837 - Campo Grande, Rio de Janeiro - RJ"},
    ]},

    "contato": {"blocos": [
        {"tipo": "contato", "dados": CONTATO_SITIO},
    ]},

    "regras": {"blocos": [
        {"tipo": "texto", "texto": (
            "*Informações gerais* 📋\n\n"
            "*Crianças*\n"
            "• 0 a 5 anos: não pagam\n"
            "• 5 a 10 anos: pagam meia\n"
            "• A partir de 11 anos: pagam inteira\n\n"
            "*Pagamento*\n"
            "• Entrada de R$ 2.000 garante a data\n"
            "• Restante até 30 dias antes do evento\n"
            "• Pix, débito e crédito (juros da operadora)\n"
            "• Trabalhamos com contrato\n\n"
            "Para valores e disponibilidade, fale com nosso atendente."
        )},
    ]},
}

# ---------------------------------------------------------------
# Anexos de acesso rápido no painel
# ---------------------------------------------------------------
# Cada item vira um ícone dentro do botão "+" da conversa. Ao tocar,
# o atendente envia exatamente o mesmo material que o bot enviaria —
# sem procurar arquivo no celular.
#
#   chave  → a chave correspondente em CONTEUDO
#   icone  → id do desenho no painel (ver <symbol> em painel.html)
#
# Para acrescentar um material novo: crie a chave em CONTEUDO e
# adicione uma linha aqui reaproveitando um dos ícones existentes.

ANEXOS_RAPIDOS = [
    {"chave": "casamento",        "rotulo": "Casamento",
     "resumo": "PDF de pacotes + descrição", "icone": "casamento"},
    {"chave": "quinze",           "rotulo": "15 anos",
     "resumo": "PDF de pacotes", "icone": "quinze"},
    {"chave": "infantil",         "rotulo": "Infantil",
     "resumo": "PDF de pacotes", "icone": "infantil"},
    {"chave": "decorado",         "rotulo": "Espaço decorado",
     "resumo": "Foto do espaço", "icone": "decorado"},
    {"chave": "confraternizacao", "rotulo": "Confraternização",
     "resumo": "Foto de aniversários", "icone": "festa"},
    {"chave": "localizacao",      "rotulo": "Como chegar",
     "resumo": "Localização no mapa", "icone": "local"},
    {"chave": "contato",          "rotulo": "Contato do sítio",
     "resumo": "Envia o cartão com telefone e endereço", "icone": "contato"},
    {"chave": "regras",           "rotulo": "Informações",
     "resumo": "Crianças, pagamento e contrato", "icone": "info"},
]


def catalogo_anexos() -> list:
    """Lista enxuta para o painel, já sem os materiais que sumiram do CONTEUDO."""
    saida = []
    for a in ANEXOS_RAPIDOS:
        item = CONTEUDO.get(a["chave"])
        if not item:
            continue
        # Contato do sítio sem telefone configurado não tem o que enviar.
        if a["chave"] == "contato" and not CONTATO_SITIO.get("telefone"):
            continue
        tipos = [b["tipo"] for b in item["blocos"]]
        saida.append({**a, "tipos": tipos, "blocos": len(tipos)})
    return saida


# Sinônimos digitados livremente pelo cliente
ATALHOS = {
    "casamento": "casamento", "casar": "casamento", "noiva": "casamento",
    "noivo": "casamento", "cerimonia": "casamento", "cerimônia": "casamento",
    "15": "quinze", "quinze": "quinze", "debutante": "quinze", "quinzinho": "quinze",
    "infantil": "infantil", "crianca": "infantil", "criança": "infantil",
    "aniversario": "confraternizacao", "aniversário": "confraternizacao",
    "confraternizacao": "confraternizacao", "confraternização": "confraternizacao",
    "empresa": "confraternizacao", "corporativo": "confraternizacao",
    "decorado": "decorado", "decoracao": "decorado", "decoração": "decorado",
    "foto": "decorado", "fotos": "decorado", "espaco": "decorado", "espaço": "decorado",
    "onde": "localizacao", "endereco": "localizacao", "endereço": "localizacao",
    "local": "localizacao", "chegar": "localizacao", "mapa": "localizacao",
    "pagamento": "regras", "pix": "regras", "cartao": "regras", "cartão": "regras",
    "parcel": "regras", "contrato": "regras", "sinal": "regras", "entrada": "regras",
    "atendente": "humano", "humano": "humano", "pessoa": "humano", "falar": "humano",
    "orcamento": "humano", "orçamento": "humano", "valor": "humano",
    "preco": "humano", "preço": "humano", "quanto": "humano", "data": "humano",
}
