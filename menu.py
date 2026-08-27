"""
Menus interativos.

Limites da Cloud API (estourar = erro 400 sem explicação clara):
  - list: até 10 rows no total; title <= 24 chars; description <= 72; button <= 20
  - button: no máximo 3 botões; title <= 20 chars
"""
import os

from content import texto_apresentacao

NOME_SITIO = os.getenv("NOME_SITIO", "Sítio Girassol")


def menu_principal(para: str, nome: str) -> dict:
    return {
        "to": para,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "header": {"type": "text", "text": NOME_SITIO},
            "body": {"text": texto_apresentacao(nome)},
            "footer": {"text": "Atendimento automatizado"},
            "action": {
                "button": "Ver opções",
                "sections": [
                    {
                        "title": "Tipo de evento",
                        "rows": [
                            {"id": "casamento", "title": "Casamento",
                             "description": "Pacotes, decoração e cerimônia"},
                            {"id": "quinze", "title": "15 anos",
                             "description": "Pacotes para debutantes"},
                            {"id": "infantil", "title": "Evento infantil",
                             "description": "Pacotes para festas infantis"},
                            {"id": "confraternizacao", "title": "Aniversários",
                             "description": "Aniversários e confraternizações"},
                        ],
                    },
                    {
                        "title": "Conhecer o espaço",
                        "rows": [
                            {"id": "decorado", "title": "Espaço decorado",
                             "description": "Veja como fica montado"},
                        ],
                    },
                    {
                        "title": "Atendimento",
                        "rows": [
                            {"id": "humano", "title": "Falar com atendente",
                             "description": "Tirar dúvidas e orçamento"},
                        ],
                    },
                ],
            },
        },
    }


def voltar_menu(para: str) -> dict:
    return {
        "to": para,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": "Posso ajudar em mais alguma coisa? 🌻"},
            "action": {"buttons": [
                {"type": "reply", "reply": {"id": "menu", "title": "Menu"}},
                {"type": "reply", "reply": {"id": "humano", "title": "Falar c/ atendente"}},
            ]},
        },
    }
