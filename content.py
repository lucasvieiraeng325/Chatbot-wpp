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


def eh_da_equipe(telefone: str) -> bool:
    """True se o número está cadastrado como equipe (não é cliente)."""
    if not telefone:
        return False
    d = "".join(c for c in str(telefone) if c.isdigit())
    return d in NUMEROS_EQUIPE

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
        "e, se preferir, chamo um de nossos representantes.\n\n"
        "Para começar, como posso te chamar?"
    )


def texto_apresentacao(nome: str, qualificar: bool = True) -> str:
    """Cabeçalho do menu principal. Com a IA ligada (qualificar), já pede as
    três informações que definem o atendimento."""
    if not qualificar:
        return (
            f"Olá, {nome}! 🌻\n\n"
            f"Eu sou a *{NOME_ASSISTENTE}*, assistente virtual do Sítio Girassol. "
            "Posso te enviar nossos pacotes, fotos do espaço e informações de "
            "pagamento. Para falar com um de nossos representantes, use o menu.\n\n"
            "Escolha abaixo a opção que mais combina com o seu evento:"
        )
    return (
        f"Olá, {nome}! 🌻\n\n"
        f"Eu sou a *{NOME_ASSISTENTE}*, assistente virtual do Sítio Girassol. "
        "Para eu te ajudar a planejar, me conta:\n\n"
        "🎉 *Tipo de evento*\n"
        "📅 *Data de interesse*\n"
        "👥 *Número de convidados*\n\n"
        "Já verifico se a data está livre! Se preferir, veja as opções no menu abaixo."
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


# ---------------------------------------------------------------
# Representantes (atendimento humano) e assinaturas
# ---------------------------------------------------------------
# Horário comercial dos representantes: segunda a sábado, 8h às 18h.
REP_DIAS = (0, 1, 2, 3, 4, 5)          # seg=0 … sáb=5
REP_ABRE = int(os.getenv("REP_ABRE", "8"))
REP_FECHA = int(os.getenv("REP_FECHA", "18"))
HORARIO_REPRESENTANTES = f"de segunda a sábado, das {REP_ABRE}h às {REP_FECHA}h"

# Quem está falando: a assistente virtual ou uma pessoa da equipe.
ASSINATURA_SOL = f"🌻 *{NOME_ASSISTENTE}* · assistente virtual"
ASSINATURA_REP = "👤 *Representante* · Sítio Girassol"

DIAS_SEMANA_NOME = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
                    "sexta-feira", "sábado", "domingo"]


def em_horario_comercial(agora) -> bool:
    return agora.weekday() in REP_DIAS and REP_ABRE <= agora.hour < REP_FECHA


def previsao_representante(agora) -> str:
    """
    Frase com a previsão de retorno, sem horário exato.
    Ex: sábado 23h → "na segunda-feira pela manhã".
    """
    if em_horario_comercial(agora):
        return "Em instantes um de nossos representantes vai te responder aqui mesmo. 🌻"
    from datetime import timedelta
    dia = agora.date()
    if not (agora.weekday() in REP_DIAS and agora.hour < REP_ABRE):
        dia += timedelta(days=1)
    while dia.weekday() not in REP_DIAS:
        dia += timedelta(days=1)
    dias = (dia - agora.date()).days
    quando = ("hoje pela manhã" if dias == 0 else
              "amanhã pela manhã" if dias == 1 else
              f"na {DIAS_SEMANA_NOME[dia.weekday()]} pela manhã"
              if dia.weekday() < 5 else f"no {DIAS_SEMANA_NOME[dia.weekday()]} pela manhã")
    return (f"Nossos representantes atendem {HORARIO_REPRESENTANTES}, então o "
            f"retorno será {quando}, aqui mesmo nesta conversa. 🌻")


def texto_atendente(agora=None, resumo: str = "") -> str:
    """Mensagem ao CLIENTE quando ele pede para falar com um representante."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    agora = agora or datetime.now(ZoneInfo(os.getenv("TIMEZONE", "America/Sao_Paulo")))
    base = (
        f"{ASSINATURA_SOL}\n\n"
        "Vou chamar um de nossos representantes. "
        f"{previsao_representante(agora)}"
    )
    if resumo:
        base += f"\n\nJá passei para ele o que conversamos: *{resumo}*."
    else:
        base += ("\n\nPara agilizar, me informe:\n"
                 "• Tipo de evento\n"
                 "• Data de interesse (com o ano)\n"
                 "• Quantidade de convidados")
    if NUMERO_ATENDENTE:
        base += (
            "\n\nSe preferir, fale direto com nossa equipe:\n"
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

    # Tipo de evento: locação só do espaço + decoração, sem buffet.
    "decorado": {"blocos": [
        {"tipo": "imagem", "url": f"{IMG}/imagem_espaco_decorado.jpeg",
         "legenda": "Nosso espaço decorado 🌻"},
    ]},

    # Fotos do sítio (Instagram @girassolsitio). Para trocar, substitua os
    # arquivos espaco_decorado_N.jpg em images/ mantendo os nomes.
    "fotos": {"blocos": [
        {"tipo": "texto", "texto": "Olha só um pouco do nosso espaço 🌻"},
        {"tipo": "imagem", "url": f"{IMG}/espaco_decorado_1.jpg",
         "legenda": "Gramado com letreiro iluminado 🌴"},
        {"tipo": "imagem", "url": f"{IMG}/espaco_decorado_2.jpg",
         "legenda": "Mesa principal decorada 🌸"},
        {"tipo": "imagem", "url": f"{IMG}/espaco_decorado_3.jpg",
         "legenda": "Caminho florido até a piscina"},
        {"tipo": "imagem", "url": f"{IMG}/espaco_decorado_4.jpg",
         "legenda": "Varanda com mesas para os convidados"},
        {"tipo": "imagem", "url": f"{IMG}/espaco_decorado_5.jpg",
         "legenda": "Área externa com fonte e ombrelones ☀️"},
        {"tipo": "texto", "texto": (
            "Mais fotos no nosso Instagram: instagram.com/girassolsitio 📸"
        )},
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
     "resumo": "Foto do espaço decorado", "icone": "decorado"},
    {"chave": "fotos",            "rotulo": "Fotos do espaço",
     "resumo": "5 fotos do sítio + Instagram", "icone": "decorado"},
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


# ---------------------------------------------------------------
# Roteiro da IA (perguntas livres) — RASCUNHO para refinar
# ---------------------------------------------------------------
# É tudo o que a IA sabe sobre o sítio. Ela só responde com base nisto;
# o que não estiver aqui ela encaminha para a equipe. Para ensinar algo
# novo (estacionamento, pet, capacidade...), acrescente uma linha.

ROTEIRO_IA = f"""
# Sobre o Sítio Girassol
- Espaço para eventos em Campo Grande, Rio de Janeiro.
- Endereço: Estrada da Serra Alta 1837, Campo Grande, Rio de Janeiro - RJ.
  Fica a 10 minutos do West Shopping.
- Capacidade máxima para eventos: 200 convidados.
- Mobiliário: temos mesas e 200 cadeiras (atende a capacidade máxima).
- Áreas: gramado amplo com palmeiras, piscina, varanda coberta com mesas,
  área externa com fonte e ombrelones, estrutura para cerimônia ao ar livre.
- Instagram com fotos: instagram.com/girassolsitio
- Representantes (atendimento humano): de segunda a sábado, das 8h às 18h.

# Tipos de evento
- Casamento: pacote com 5h de evento (1h de cerimônia + 4h de buffet).
  Decoração principal: armários e mesas de madeira (3 a 5 m), bolo fake,
  decoração de chão, lustres, muro inglês, louças e suportes, arranjos de
  flores naturais, suporte para bolo suspenso.
  Cerimônia: vasos de flores no caminho da noiva, mesa do celebrante,
  pergolado e portal de madeira, decoração de flores.
  Convidados: mesas e cadeiras de madeira, toalhas luxo, voal na cor do
  evento, espaço lounge, espaços instagramáveis.
  Cortesia: 300 doces gourmet e bolo de corte.
- 15 anos: há pacotes para debutantes (detalhes no PDF de 15 anos).
- Infantil: há pacotes para festas infantis (detalhes no PDF infantil).
- Aniversários e confraternizações (inclusive de empresas): atendemos.
- Espaço decorado: locação do espaço do sítio já decorado, SEM buffet —
  o cliente contrata comida e bebida por conta própria.
- Locação do espaço: só o espaço, sem buffet e sem decoração, por um
  período de 10h (das 9h às 19h). Inclui: área de 290 m², campo de futebol,
  piscina, espaço fechado e espaços abertos, cozinha industrial com fogão,
  geladeira e freezer, deck de gelo, mesas e cadeiras para 200 pessoas e
  espaços instagramáveis. Valores na tabela (pacote "Locação do espaço").

# Buffet, horários e regras da festa
- Duração do evento: 5 horas. No casamento são 1h de cerimônia + 4h de buffet.
- O que o buffet inclui e o cardápio de cada pacote estão no PDF do pacote:
  para qualquer dúvida de buffet, cardápio, bebidas ou doces, responda o que
  souber daqui e envie o material do tipo de evento do cliente.
- Espaço decorado não tem buffet (o cliente contrata por conta própria).
- Horário de início e término, hora extra, som/DJ, decoração própria, bebida
  própria, pets, estacionamento e capacidade máxima: ainda não estão neste
  roteiro — diga que a equipe confirma no orçamento.

# Disponibilidade de datas
- Use a ferramenta consultar_disponibilidade para saber se a data está livre.
- Informar que a data está livre NÃO é reserva: a reserva só vale com a
  equipe e a entrada de R$ 2.000.

# Valores e pagamento
- Os valores dependem do tipo de evento, do menu, do número de convidados e
  do dia (ver seção Valores). Desconto e negociação: só com a equipe.
- Crianças: 0 a 5 anos não pagam; 5 a 10 anos pagam meia; a partir de
  11 anos pagam inteira.
- (Só se perguntarem) Entrada de R$ 2.000 garante a data. O restante é pago até 30 dias antes
  do evento.
- Formas de pagamento: Pix, débito e crédito (com juros da operadora).
- Trabalhamos com contrato.

# Materiais que o bot pode enviar (campo "material")
- casamento: PDF de pacotes de casamento + descrição
- quinze: PDF de pacotes de 15 anos
- infantil: PDF de pacotes infantis
- confraternizacao: foto de aniversários e confraternizações
- decorado: foto do espaço decorado
- fotos: 5 fotos do sítio + link do Instagram
- localizacao: endereço com pino no mapa
- regras: informações de crianças, pagamento e contrato
""".strip()


# ---------------------------------------------------------------
# Tabela de valores INICIAL (dos PDFs de pacotes)
# ---------------------------------------------------------------
# Só é usada para preencher o banco no primeiro boot. Depois disso a
# tabela é editada pelo painel (aba Preços) — mudar aqui não tem efeito.
# Valor TOTAL do pacote por faixa de convidados.
#
# Casamento e 15 anos: "semana" = segunda a sexta;
#                      "fim_de_semana" = sábado, domingo e feriados.
# Infantil: o preço varia com ou sem decoração, não pelo dia.

PRECOS = {
    "casamento": {
        "standard": {
            "semana":        {50: 14000, 80: 15500, 100: 18000, 150: 22500, 200: 25000},
            "fim_de_semana": {50: 15500, 80: 17500, 100: 20000, 150: 23500, 200: 25500},
        },
        "premium": {
            "semana":        {50: 16500, 80: 18900, 100: 21000, 150: 24500, 200: 27000},
            "fim_de_semana": {50: 18800, 80: 21900, 100: 23000, 150: 27500, 200: 30000},
        },
    },
    "quinze": {
        "standard": {
            # Atenção: no PDF, 200 pessoas (21 mil) sai mais barato que 150
            # (21.500) — provável erro de digitação. Confirmar com o sítio.
            "semana":        {50: 12500, 80: 14500, 100: 17000, 150: 21500, 200: 21000},
            "fim_de_semana": {50: 13500, 80: 15500, 100: 18300, 150: 22500, 200: 25000},
        },
        "premium": {
            "semana":        {50: 14500, 80: 16900, 100: 20000, 150: 23500, 200: 24000},
            "fim_de_semana": {50: 16500, 80: 18900, 100: 23000, 150: 25500, 200: 27000},
        },
    },
    "infantil": {
        "standard": {
            "sem_decoracao": {50: 7600, 80: 9900, 100: 10000, 150: 12500, 200: 15000},
            "com_decoracao": {50: 9500, 80: 11500, 100: 12000, 150: 14500, 200: 17000},
        },
        "premium": {
            "sem_decoracao": {50: 9500, 80: 10900, 100: 14000, 150: 17000, 200: 18000},
            "com_decoracao": {50: 10500, 80: 12900, 100: 16000, 150: 19500, 200: 20000},
        },
    },
}

# Folheto oficial da locação (images/locacao_espaco.jpg)
FOLHETO_LOCACAO = {"tipo": "imagem", "url": f"{IMG}/locacao_espaco.jpg",
                   "legenda": "Locação do espaço 🌻"}

# Pacotes extras do primeiro boot que não seguem o formato de PRECOS.
# Locação só do espaço: preço fixo (uma faixa até a capacidade do sítio).
PACOTE_LOCACAO = {
    "chave": "locacao", "nome": "Locação do espaço", "ativo": True, "no_menu": True,
    "descricao": "Só o espaço, 10h (9h às 19h), sem buffet",
    "variacao": "livre",
    "colunas": ["À vista com desconto", "Parcelado em 3x"],
    "menus": ["Locação do espaço"],
    "inclui": [""],   # preenchido de INCLUI_PADRAO no boot
    "faixas": [200],
    "precos": [[[2500], [3000]]],
    "adicionais": [],
    "materiais": [FOLHETO_LOCACAO, {"tipo": "texto", "texto": (
        "*Locação do espaço* 🌻\n\n"
        "Período de *10h* (das 9h às 19h), só o espaço — sem buffet e sem decoração.\n\n"
        "• Área de 290 m²\n"
        "• Campo de futebol\n"
        "• Piscina\n"
        "• Espaço fechado e espaços abertos\n"
        "• Cozinha industrial com fogão, geladeira e freezer\n"
        "• Deck de gelo\n"
        "• Mesas e cadeiras para 200 pessoas\n"
        "• Espaços instagramáveis\n\n"
        "Aceitamos débito, Pix ou crédito.")}],
}

# O que cada menu inclui — semente da aba Preços (campo "O que inclui").
# A Sol resume isso ao informar valores. Depois do primeiro boot, editar
# pelo painel.
_FESTA = ("salgados (coxinha, risole de camarão, kibe, bolinha de queijo e mais); "
          "refrigerantes, suco de 2 frutas e água; cortesia de bolo de corte, "
          "sorvete e 300 brigadeiros gourmet; equipe completa")
_STANDARD = ("2 caldos de entrada, 2h de ilha de massas e 1 prato principal à "
             "escolha (carne ao molho madeira, risoto de camarão ou fricassê de frango)")
_PREMIUM = ("2 caldos de entrada e prato principal self-service de carnes "
            "(contra-filé, alcatra, maminha recheada, drumete e linguiça de pernil) "
            "com acompanhamentos variados")
_LANCHES = "mini hambúrguer, mini cachorro-quente e batata frita"
INCLUI_PADRAO = {
    "casamento": {
        "standard": f"5h de evento (1h de cerimônia + 4h de buffet); {_STANDARD}; {_FESTA}; "
                    "decoração com flores naturais e cerimônia decorada",
        "premium": f"5h de evento (1h de cerimônia + 4h de buffet); {_PREMIUM}; {_FESTA}; "
                   "decoração com flores naturais e cerimônia decorada",
    },
    "quinze": {
        "standard": f"5h de festa; {_STANDARD}; lanches ({_LANCHES}); {_FESTA}; "
                    "decoração temática",
        "premium": f"5h de festa; {_PREMIUM}; lanches ({_LANCHES}); {_FESTA}; "
                   "coquetel de morango e maracujá sem álcool; decoração temática",
    },
    "infantil": {
        "standard": f"5h de festa; {_STANDARD}; lanches ({_LANCHES}); {_FESTA}; "
                    "decoração temática",
        "premium": f"5h de festa; {_PREMIUM}; lanches ({_LANCHES}); {_FESTA}; "
                   "decoração temática",
    },
    "locacao": {
        "locação do espaço": "Só o espaço por 10h (9h às 19h), sem buffet e sem "
                             "decoração: área de 290 m², campo de futebol, piscina, "
                             "espaços fechado e abertos, cozinha industrial (fogão, "
                             "geladeira e freezer), deck de gelo, mesas e 200 cadeiras "
                             "e espaços instagramáveis",
    },
}

# Adicionais por convidado (iguais em todos os pacotes)
ADICIONAL_CALDO = 15     # mais uma opção de caldo
ADICIONAL_JANTAR = 20    # mais uma opção de prato principal (menu Standard)

ROTEIRO_IA += """

# Cardápios (iguais em casamento, 15 anos e infantil)
## Menu Standard
- Entradas quentes (2 opções): caldo de alho-poró, feijoadinha, caldo de
  aipim com carne seca, canjiquinha ao molho de costela bovina desfiada.
- 2h de ilha de massas: penne e gravatinha, molhos branco e à bolonhesa,
  com tomate picadinho, orégano e parmesão.
- Prato principal (1 opção): scalopini de carne ao molho madeira com
  cogumelos (com arroz e batata sauté); risoto de camarão (com salada e
  torradinhas); ou fricassê de frango (com arroz, batata palha e parmesão).
## Menu Premium
- Entradas quentes (2 opções): caldo de alho-poró, feijoadinha, canjiquinha.
- Prato principal self-service: contra-filé, alcatra, maminha recheada com
  queijo coalho, drumete e linguiça de pernil. Acompanhamentos: farofa de
  bacon e calabresa, arroz, batata frita, salada de maionese, feijão
  tropeiro, molho à campanha, saladas verdes e cozidas, pão com creme de alho.
## Nos dois menus
- Salgados: coxinha, risole de camarão, kibe, bolinha de queijo, queijo com
  alho, calabresa com catupiry, queijo com presunto.
- Lanches (15 anos e infantil): mini hambúrguer, mini cachorro-quente,
  batata frita.
- Bebidas: Coca-Cola, Fanta laranja, Guaraná, suco (2 frutas da época), água
  sem gás. No Premium de 15 anos: coquetel de morango e maracujá sem álcool.
- Cortesia: bolo de corte com 2 camadas de recheio, sorvete e 300
  brigadeiros gourmet.
- Arranjos 100% naturais (ou decoração temática no 15 anos e infantil), toda
  a equipe inclusa, área principal e cerimonial decorados.
- Adicionais por convidado: mais uma opção de caldo R$ 15; mais uma opção
  de prato principal (Standard) R$ 20.

# Valores
- Informe valores SOMENTE com a ferramenta consultar_valores, nunca de cabeça.
  Os pacotes com tabela são os listados na ferramenta.
- São ESTIMATIVAS de tabela do pacote completo para a faixa de convidados,
  não preço fechado. O valor final e a reserva são definidos pela equipe.
- Evento sem pacote com tabela: um representante faz o orçamento.
"""


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
    "locacao": "locacao", "locação": "locacao", "alugar": "locacao", "aluguel": "locacao",
    "foto": "fotos", "fotos": "fotos", "espaco": "fotos", "espaço": "fotos",
    "piscina": "fotos", "instagram": "fotos",
    "onde": "localizacao", "endereco": "localizacao", "endereço": "localizacao",
    "local": "localizacao", "chegar": "localizacao", "mapa": "localizacao",
    "pagamento": "regras", "pix": "regras", "cartao": "regras", "cartão": "regras",
    "parcel": "regras", "contrato": "regras", "sinal": "regras", "entrada": "regras",
    "atendente": "humano", "humano": "humano", "pessoa": "humano", "falar": "humano",
    "representante": "humano",
    "orcamento": "humano", "orçamento": "humano", "valor": "humano",
    "preco": "humano", "preço": "humano", "quanto": "humano", "data": "humano",
}
