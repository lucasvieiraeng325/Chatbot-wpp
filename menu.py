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
                            {"id": "decorado", "title": "Espaço decorado",
                             "description": "Locação do espaço decorado, sem buffet"},
                        ],
                    },
                    {
                        "title": "Conheça o sítio",
                        "rows": [
                            {"id": "fotos", "title": "Fotos do espaço",
                             "description": "Veja fotos das nossas áreas e montagens"},
                        ],
                    },
                    {
                        "title": "Atendimento",
                        "rows": [
                            # Título de linha: máx. 24 caracteres na Cloud API
                            {"id": "humano", "title": "Falar c/ representante",
                             "description": "Falar com um de nossos representantes"},
                        ],
                    },
                ],
            },
        },
    }


def voltar_menu(para: str, texto: str = "Posso ajudar em mais alguma coisa? 🌻") -> dict:
    """
    Mensagem com o botão Menu. Também é o formato de toda resposta da IA:
    o texto vai no corpo e o Menu fica sempre à mão. Falar com um
    representante fica só dentro do Menu, para não confundir com a IA.
    O corpo do botão aceita até 1024 caracteres.
    """
    if len(texto) > 1024:
        texto = texto[:1020].rstrip() + "…"
    return {
        "to": para,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": texto},
            "action": {"buttons": [
                {"type": "reply", "reply": {"id": "menu", "title": "Menu"}},
            ]},
        },
    }


# Depois de um material, convida o cliente a seguir para a qualificação
# (usado quando a IA está ligada para conduzir o resto da conversa).
CONVITE_QUALIFICAR = (
    "Quer verificar se sua data está livre? 🌻 Me conta a *data de interesse* "
    "(com o ano) e o *número de convidados*."
)
