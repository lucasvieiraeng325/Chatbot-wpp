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

# Mensagem enviada ao CLIENTE quando ele pede atendente
def texto_atendente() -> str:
    base = (
        "Dentro de instantes um atendente dará continuidade. 🌻\n\n"
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
            "• Vasos no caminho da noiva\n"
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
