"""
=============================================================
  ÚNICO ARQUIVO QUE PRECISA SER EDITADO NO DIA A DIA
=============================================================

Mídias reais do projeto:
    images/area-festa-deck.png
    images/piscina.png
    images/campo.png
    pdfs/pacotes.pdf

Blocos: texto | pdf | imagem | localizacao
Um bloco = uma mensagem, com 1,5s de intervalo entre elas.

Limites da Cloud API: imagem 5 MB - PDF 100 MB

[AJUSTAR] marca o que precisa ser confirmado antes de ir ao ar.
"""
import os

BASE = os.getenv("BASE_URL", "https://chatbot-wpp-593m.onrender.com")
IMG = f"{BASE}/images"
PDF = f"{BASE}/pdfs"

NOME = "Sítio Girassol"

CONTEUDO = {

    "fotos": {"blocos": [
        {"tipo": "texto", "texto": "Que bom que quer conhecer o espaço! 🌿\nVeja um pouco do nosso sítio:"},
        {"tipo": "imagem", "url": f"{IMG}/area-festa-deck.png",
         "legenda": "Área de festa com deck"},
        {"tipo": "imagem", "url": f"{IMG}/piscina.png",
         "legenda": "Piscina"},
        {"tipo": "imagem", "url": f"{IMG}/campo.png",
         "legenda": "Campo aberto"},
    ]},

    "estrutura": {"blocos": [
        # [AJUSTAR] confirme cada item com o dono do sítio
        {"tipo": "texto", "texto": (
            "*Estrutura do Sítio Girassol* 🏡\n\n"
            "• Área de festa com deck coberto\n"
            "• Piscina\n"
            "• Campo aberto para atividades\n"
            "• Cozinha equipada\n"
            "• Estacionamento\n\n"
            "Capacidade e itens inclusos variam por pacote — "
            "veja a tabela em *Pacotes e valores*."
        )},
        {"tipo": "imagem", "url": f"{IMG}/area-festa-deck.png",
         "legenda": "Área de festa com deck"},
    ]},

    "localizacao": {"blocos": [
        {"tipo": "texto", "texto": "Estamos a 10 minutos do West Shopping 🚗"},
        # [AJUSTAR] coordenadas ainda são de São Luís — pegue as reais no Google Maps
        {"tipo": "localizacao", "lat": -22.9057, "lng": -43.5613,
         "nome": "Sítio Girassol",
         "endereco": "Estrada da Serra Alta 1837 - Campo Grande, Rio de Janeiro - RJ"},
        {"tipo": "texto", "texto": "Toque no mapa acima para abrir no Waze ou Google Maps."},
    ]},

    "geral": {"blocos": [
        {"tipo": "pdf", "url": f"{PDF}/pacotes.pdf",
         "arquivo": "Pacotes Sitio Girassol 2026.pdf",
         "legenda": "Nossa tabela completa de pacotes 🌿"},
        {"tipo": "texto", "texto": (
            "Os valores variam conforme data e número de convidados.\n"
            "Para um orçamento fechado, fale com nosso atendente!"
        )},
    ]},

    # Um PDF só serve as três opções abaixo, com abertura e foto específicas.
    "casamento": {"blocos": [
        {"tipo": "texto", "texto": "Que alegria! 💒 O Sítio Girassol é lindo para casamentos."},
        {"tipo": "pdf", "url": f"{PDF}/pacotes.pdf",
         "arquivo": "Pacotes Sitio Girassol 2026.pdf",
         "legenda": "Nossa tabela de pacotes"},
        {"tipo": "imagem", "url": f"{IMG}/campo.png",
         "legenda": "Campo aberto — ideal para cerimônia"},
        {"tipo": "texto", "texto": "Para casamentos, recomendamos agendar uma visita ao espaço."},
    ]},

    "aniversario": {"blocos": [
        {"tipo": "texto", "texto": "Vamos comemorar! 🎉 Veja o que o Sítio Girassol oferece:"},
        {"tipo": "pdf", "url": f"{PDF}/pacotes.pdf",
         "arquivo": "Pacotes Sitio Girassol 2026.pdf",
         "legenda": "Nossa tabela de pacotes"},
        {"tipo": "imagem", "url": f"{IMG}/piscina.png",
         "legenda": "Piscina — sucesso garantido com a criançada"},
    ]},

    "corporativo": {"blocos": [
        {"tipo": "texto", "texto": "Ótima escolha para confraternizações! 💼"},
        {"tipo": "pdf", "url": f"{PDF}/pacotes.pdf",
         "arquivo": "Pacotes Sitio Girassol 2026.pdf",
         "legenda": "Nossa tabela de pacotes"},
        {"tipo": "imagem", "url": f"{IMG}/area-festa-deck.png",
         "legenda": "Área de festa com deck"},
    ]},

    "regras": {"blocos": [
        # [AJUSTAR] confirme cada regra antes de publicar
        {"tipo": "texto", "texto": (
            "*Regras do Sítio Girassol* 📋\n\n"
            "• Som liberado até 2h (com limitador após 22h)\n"
            "• Pets bem-vindos, com aviso prévio\n"
            "• Decoração própria permitida\n"
            "• Buffet próprio ou terceirizado\n"
            "• Check-in 14h / check-out 12h\n"
            "• Reserva confirmada com 30% de sinal\n"
            "• Cancelamento até 60 dias: devolução de 50%\n\n"
            "Dúvidas específicas? Fale com nosso atendente."
        )},
    ]},
}

# Sinônimos digitados livremente pelo cliente
ATALHOS = {
    "preco": "geral", "preço": "geral", "valor": "geral", "valores": "geral",
    "orcamento": "geral", "orçamento": "geral", "quanto": "geral",
    "tabela": "geral", "pacote": "geral",
    "foto": "fotos", "fotos": "fotos", "imagens": "fotos", "conhecer": "fotos",
    "onde": "localizacao", "endereco": "localizacao", "endereço": "localizacao",
    "local": "localizacao", "localizacao": "localizacao", "chegar": "localizacao",
    "estrutura": "estrutura", "capacidade": "estrutura", "piscina": "estrutura",
    "casamento": "casamento", "noivado": "casamento", "casar": "casamento",
    "aniversario": "aniversario", "aniversário": "aniversario", "festa": "aniversario",
    "empresa": "corporativo", "corporativo": "corporativo",
    "confraternizacao": "corporativo", "confraternização": "corporativo",
    "regras": "regras", "regra": "regras", "som": "regras", "pet": "regras",
    "atendente": "humano", "humano": "humano", "pessoa": "humano", "falar": "humano",
}
