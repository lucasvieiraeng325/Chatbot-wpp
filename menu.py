"""
Menus interativos.

Limites da Cloud API (estourar = erro 400 sem explicação clara):
  - list: até 10 rows no total; title <= 24 chars; description <= 72; button <= 20
  - button: no máximo 3 botões; title <= 20 chars
"""
import os

NOME_SITIO = os.getenv("NOME_SITIO", "Sítio Girassol")


def menu_principal(para: str, nome: str) -> dict:
    return {
        "to": para,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "header": {"type": "text", "text": NOME_SITIO},
            "body": {"text": (
                f"Olá, {nome}! 🌿\n\n"
                f"Sou o assistente virtual do {NOME_SITIO}. "
                "Escolha abaixo o que deseja conhecer:"
            )},
            "footer": {"text": "Atendimento automatizado"},
            "action": {
                "button": "Ver opções",
                "sections": [
                    {
                        "title": "Conhecer o espaço",
                        "rows": [
                            {"id": "fotos", "title": "Fotos do espaço",
                             "description": "Área de festa, piscina e campo"},
                            {"id": "estrutura", "title": "Estrutura",
                             "description": "Capacidade, cozinha, espaços"},
                            {"id": "localizacao", "title": "Como chegar",
                             "description": "Endereço e mapa"},
                        ],
                    },
                    {
                        "title": "Pacotes",
                        "rows": [
                            {"id": "geral", "title": "Pacotes e valores",
                             "description": "Tabela completa em PDF"},
                            {"id": "casamento", "title": "Casamentos",
                             "description": "Material exclusivo"},
                            {"id": "aniversario", "title": "Aniversários",
                             "description": "Material exclusivo"},
                            {"id": "corporativo", "title": "Eventos corporativos",
                             "description": "Material exclusivo"},
                        ],
                    },
                    {
                        "title": "Outros",
                        "rows": [
                            {"id": "regras", "title": "Regras do sítio",
                             "description": "Som, pets, decoração"},
                            {"id": "humano", "title": "Falar com atendente",
                             "description": "Tirar dúvidas específicas"},
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
            "body": {"text": "Posso ajudar em mais alguma coisa? 🌿"},
            "action": {"buttons": [
                {"type": "reply", "reply": {"id": "menu", "title": "Ver menu"}},
                {"type": "reply", "reply": {"id": "humano", "title": "Falar c/ atendente"}},
            ]},
        },
    }
