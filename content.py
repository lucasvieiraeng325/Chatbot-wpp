"""
=============================================================
  ÚNICO ARQUIVO QUE PRECISA SER EDITADO NO DIA A DIA
=============================================================

Coloque os PDFs e fotos em public/media/ e referencie por:
    {BASE}/nome-do-arquivo.pdf

Blocos disponíveis: texto | pdf | imagem | localizacao
Um bloco por mensagem, enviados em ordem com 1,5s de intervalo.

Limites de mídia da Cloud API:
    imagem   5 MB
    PDF    100 MB
    vídeo   16 MB  (comprima para 720p / 60s)
"""
import os

BASE = os.getenv("BASE_URL", "https://sitio-bot.onrender.com") + "/media"

CONTEUDO = {

    "fotos": {"blocos": [
        {"tipo": "texto", "texto": "Que bom que quer conhecer o espaço! 🌿\nVeja algumas fotos:"},
        {"tipo": "imagem", "url": f"{BASE}/area-festa.jpg", "legenda": "Área de festa coberta"},
        {"tipo": "imagem", "url": f"{BASE}/piscina.jpg", "legenda": "Piscina com deck"},
        {"tipo": "imagem", "url": f"{BASE}/chales.jpg", "legenda": "Chalés para pernoite"},
    ]},

    "estrutura": {"blocos": [
        {"tipo": "texto", "texto": (
            "*Estrutura do sítio* 🏡\n\n"
            "• Capacidade: até 250 pessoas\n"
            "• Salão coberto de 300m²\n"
            "• Cozinha industrial equipada\n"
            "• Piscina adulto e infantil\n"
            "• 6 chalés (até 24 pessoas para pernoite)\n"
            "• Estacionamento para 60 carros\n"
            "• Gerador de energia\n"
            "• Mesas e cadeiras inclusas"
        )},
        {"tipo": "imagem", "url": f"{BASE}/planta.jpg", "legenda": "Planta do espaço"},
    ]},

    "localizacao": {"blocos": [
        {"tipo": "texto", "texto": "Estamos a 25 minutos do centro de São Luís 🚗"},
        {"tipo": "localizacao", "lat": -2.5297, "lng": -44.3028,
         "nome": "Sítio Recanto", "endereco": "Estrada de ..., São Luís - MA"},
        {"tipo": "texto", "texto": "Toque no mapa acima para abrir no Waze ou Google Maps."},
    ]},

    "geral": {"blocos": [
        {"tipo": "pdf", "url": f"{BASE}/pacotes.pdf",
         "arquivo": "Pacotes Sítio Recanto 2026.pdf",
         "legenda": "Nossa tabela completa de pacotes 🌿"},
        {"tipo": "texto", "texto": (
            "Os valores variam conforme data e número de convidados.\n"
            "Para um orçamento fechado, fale com nosso atendente!"
        )},
    ]},

    "casamento": {"blocos": [
        {"tipo": "pdf", "url": f"{BASE}/casamentos.pdf",
         "arquivo": "Casamentos - Sítio Recanto.pdf",
         "legenda": "Nosso material para casamentos 💒"},
        {"tipo": "imagem", "url": f"{BASE}/casamento-cerimonia.jpg",
         "legenda": "Espaço para cerimônia ao ar livre"},
    ]},

    "aniversario": {"blocos": [
        {"tipo": "pdf", "url": f"{BASE}/aniversarios.pdf",
         "arquivo": "Aniversarios - Sítio Recanto.pdf",
         "legenda": "Material para aniversários 🎉"},
    ]},

    "corporativo": {"blocos": [
        {"tipo": "pdf", "url": f"{BASE}/corporativo.pdf",
         "arquivo": "Eventos Corporativos - Sítio Recanto.pdf",
         "legenda": "Material para eventos corporativos 💼"},
    ]},

    "regras": {"blocos": [
        {"tipo": "texto", "texto": (
            "*Regras do sítio* 📋\n\n"
            "• Som liberado até 2h (com limitador após 22h)\n"
            "• Pets bem-vindos, com aviso prévio\n"
            "• Decoração própria permitida\n"
            "• Buffet próprio ou terceirizado\n"
            "• Check-in 14h / check-out 12h\n"
            "• Reserva confirmada com 30% de sinal\n"
            "• Cancelamento até 60 dias: devolução de 50%"
        )},
    ]},
}

# Sinônimos digitados livremente pelo cliente
ATALHOS = {
    "preco": "geral", "preço": "geral", "valor": "geral", "valores": "geral",
    "orcamento": "geral", "orçamento": "geral", "quanto": "geral",
    "foto": "fotos", "fotos": "fotos", "imagens": "fotos",
    "onde": "localizacao", "endereco": "localizacao", "endereço": "localizacao",
    "local": "localizacao", "localizacao": "localizacao",
    "casamento": "casamento", "noivado": "casamento",
    "aniversario": "aniversario", "aniversário": "aniversario", "festa": "aniversario",
    "empresa": "corporativo", "corporativo": "corporativo", "confraternizacao": "corporativo",
    "regras": "regras", "regra": "regras",
    "atendente": "humano", "humano": "humano", "pessoa": "humano", "falar": "humano",
}
