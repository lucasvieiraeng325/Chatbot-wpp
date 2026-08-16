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
        {"tipo": "texto", "texto": (
            "*Estrutura do Sítio Girassol* 🏡\n\n"
            "• Capacidade para até *500 pessoas*\n"
            "• Área de festa coberta (evento garantido mesmo com chuva)\n"
            "• Deck e piscina\n"
            "• Campo aberto para atividades\n"
            "• Cozinha industrial: geladeira, freezers, fogões e micro-ondas\n"
            "• Estacionamento externo amplo, comporta o evento inteiro\n\n"
            "Ideal para casamentos, aniversários e confraternizações."
        )},
        {"tipo": "imagem", "url": f"{IMG}/area-festa-deck.png",
         "legenda": "Área de festa coberta"},
    ]},

    "localizacao": {"blocos": [
        {"tipo": "texto", "texto": "Estamos a 10 minutos do West Shopping 🚗"},
        {"tipo": "localizacao", "lat": -22.8726748, "lng": -43.5375258,
         "nome": "Sítio Girassol",
         "endereco": "Estrada da Serra Alta 1837 - Campo Grande, Rio de Janeiro - RJ"},
        {"tipo": "texto", "texto": "Toque no mapa acima para abrir no Waze ou Google Maps."},
    ]},

    "geral": {"blocos": [
        {"tipo": "pdf", "url": f"{PDF}/pacotes.pdf",
         "arquivo": "Pacotes Sitio Girassol 2026.pdf",
         "legenda": "Nossa tabela completa de pacotes 🌿"},
        {"tipo": "texto", "texto": (
            "Trabalhamos com *festa completa* (buffet incluso, sem limite de horário) "
            "e *locação do espaço* (das 9h às 19h, com opção de buffet externo).\n\n"
            "Os valores variam conforme a data e o número de convidados. "
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
        {"tipo": "texto", "texto": (
            "*Como funciona* 📋\n\n"
            "Trabalhamos em duas modalidades:\n\n"
            "*1. Festa completa* (com buffet)\n"
            "Sem limite de horário para o evento.\n\n"
            "*2. Locação do espaço* (sem buffet)\n"
            "Das 9h às 19h. Você pode contratar buffet externo, se preferir.\n\n"
            "*Reserva*\n"
            "• Sinal de R$ 2.000 garante a data\n"
            "• Restante quitado até 15 dias antes do evento\n\n"
            "*Outras informações*\n"
            "• Decoração própria permitida\n"
            "• Capacidade para até 500 pessoas\n\n"
            "Dúvidas sobre sua data ou pacote? Fale com nosso atendente."
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
    "horario": "regras", "horário": "regras", "buffet": "regras", "sinal": "regras",
    "reserva": "regras", "capacidade": "estrutura", "quantas pessoas": "estrutura",
    "atendente": "humano", "humano": "humano", "pessoa": "humano", "falar": "humano",
}
