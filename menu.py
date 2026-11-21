"""
Menus interativos.

Limites da Cloud API (estourar = erro 400 sem explicação clara):
  - list: até 10 rows no total; title <= 24 chars; description <= 72; button <= 20
  - button: no máximo 3 botões; title <= 20 chars
"""
import os

from content import texto_apresentacao

NOME_SITIO = os.getenv("NOME_SITIO", "Sítio Girassol")


# Itens do menu que não são pacotes da aba Preços (sem tabela de valores).
# Um pacote com a mesma chave toma o lugar do item fixo.
ITENS_FIXOS = [
    {"id": "confraternizacao", "title": "Aniversários",
     "description": "Aniversários e confraternizações"},
    {"id": "decorado", "title": "Espaço decorado",
     "description": "Locação do espaço decorado, sem buffet"},
]

# Menu de antes da aba Preços: usado quando o banco não responde.
PACOTES_PADRAO = [
    {"chave": "casamento", "nome": "Casamento", "descricao": "Pacotes, decoração e cerimônia"},
    {"chave": "quinze", "nome": "15 anos", "descricao": "Pacotes para debutantes"},
    {"chave": "infantil", "nome": "Evento infantil", "descricao": "Pacotes para festas infantis"},
    {"chave": "locacao", "nome": "Locação do espaço",
     "descricao": "Só o espaço, 10h (9h às 19h), sem buffet"},
]
DESCRICAO_PADRAO = {p["chave"]: p["descricao"] for p in PACOTES_PADRAO}

# Fotos + representante ocupam 2 das 10 linhas que a Cloud API aceita.
MAX_TIPOS = 8


def _corta(texto: str, limite: int) -> str:
    texto = (texto or "").strip()
    return texto if len(texto) <= limite else texto[:limite - 1].rstrip() + "…"


def linhas_tipo_evento(pacotes=None) -> list:
    """Pacotes ativos e marcados para o menu (na ordem da aba Preços) +
    os itens fixos que nenhum pacote substitui."""
    if pacotes is None:
        pacotes = PACOTES_PADRAO
    linhas = []
    for p in pacotes:
        if not p.get("ativo", True) or not p.get("no_menu", True):
            continue
        linhas.append({
            "id": p["chave"],
            "title": _corta(p.get("nome"), 24),
            "description": _corta(p.get("descricao") or DESCRICAO_PADRAO.get(p["chave"])
                                  or "Pacotes e valores", 72),
        })
    ids = {l["id"] for l in linhas}
    linhas += [i for i in ITENS_FIXOS if i["id"] not in ids]
    return linhas[:MAX_TIPOS]


def menu_principal(para: str, nome: str, pacotes=None) -> dict:
    """pacotes: lista da aba Preços (db.listar_pacotes). Sem ela, usa o
    menu padrão."""
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
                        "rows": linhas_tipo_evento(pacotes),
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
