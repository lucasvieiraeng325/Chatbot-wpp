"""
Valida os menus contra os limites da WhatsApp Cloud API.

Rode ANTES de cada deploy:  python validar_menu.py

A Meta devolve erro 400 sem explicar qual campo estourou — este script diz.
"""
import sys
import json
from menu import menu_principal, voltar_menu
from content import CONTEUDO

LIMITES = {
    "list_button": 20,      # texto do botão que abre a lista
    "row_title": 24,
    "row_description": 72,
    "section_title": 24,
    "header": 60,
    "body": 1024,
    "footer": 60,
    "reply_title": 20,      # botão de resposta rápida
    "max_rows": 10,         # total de rows na lista inteira
    "max_sections": 10,
    "max_buttons": 3,
}

erros, avisos = [], []


def check(valor, limite_nome, contexto):
    lim = LIMITES[limite_nome]
    n = len(valor)
    if n > lim:
        erros.append(f"❌ {contexto}: {n}/{lim} chars → \"{valor}\"")
    elif n > lim * 0.9:
        avisos.append(f"⚠️  {contexto}: {n}/{lim} chars (perto do limite)")


def validar_lista(payload):
    it = payload["interactive"]
    a = it["action"]

    check(a["button"], "list_button", "botão da lista")
    if "header" in it:
        check(it["header"]["text"], "header", "header")
    check(it["body"]["text"], "body", "body")
    if "footer" in it:
        check(it["footer"]["text"], "footer", "footer")

    secoes = a["sections"]
    if len(secoes) > LIMITES["max_sections"]:
        erros.append(f"❌ {len(secoes)} seções (máx {LIMITES['max_sections']})")

    total_rows, ids = 0, []
    for s in secoes:
        check(s["title"], "section_title", f"seção \"{s['title']}\"")
        for r in s["rows"]:
            total_rows += 1
            ids.append(r["id"])
            check(r["title"], "row_title", f"row \"{r['id']}\" title")
            if r.get("description"):
                check(r["description"], "row_description", f"row \"{r['id']}\" desc")

    if total_rows > LIMITES["max_rows"]:
        erros.append(f"❌ {total_rows} rows no total (máx {LIMITES['max_rows']})")

    dups = {i for i in ids if ids.count(i) > 1}
    if dups:
        erros.append(f"❌ IDs duplicados: {dups}")

    return ids, total_rows


def validar_botoes(payload):
    b = payload["interactive"]["action"]["buttons"]
    if len(b) > LIMITES["max_buttons"]:
        erros.append(f"❌ {len(b)} botões (máx {LIMITES['max_buttons']})")
    for x in b:
        check(x["reply"]["title"], "reply_title", f"botão \"{x['reply']['id']}\"")


def main():
    print("=" * 60)
    print("VALIDAÇÃO DOS MENUS")
    print("=" * 60)

    p = menu_principal("5598999999999", "Maria")
    ids, total = validar_lista(p)
    print(f"\nMenu principal: {total} rows em {len(p['interactive']['action']['sections'])} seções")

    validar_botoes(voltar_menu("5598999999999"))

    # Todo ID do menu precisa existir no CONTEUDO (exceto os especiais)
    especiais = {"humano", "menu"}
    orfaos = [i for i in ids if i not in CONTEUDO and i not in especiais]
    if orfaos:
        erros.append(f"❌ IDs no menu sem conteúdo em content.py: {orfaos}")

    # E todo conteúdo deveria estar acessível pelo menu
    inacessiveis = [k for k in CONTEUDO if k not in ids]
    if inacessiveis:
        avisos.append(f"⚠️  Conteúdo sem row no menu (só por texto livre): {inacessiveis}")

    # Blocos de conteúdo
    validos = {"texto", "pdf", "imagem", "localizacao"}
    for chave, item in CONTEUDO.items():
        for i, b in enumerate(item["blocos"]):
            t = b.get("tipo")
            if t not in validos:
                erros.append(f"❌ {chave}[{i}]: tipo inválido \"{t}\"")
            if t == "texto" and len(b.get("texto", "")) > 4096:
                erros.append(f"❌ {chave}[{i}]: texto > 4096 chars")
            if t == "pdf" and not b.get("arquivo"):
                erros.append(f"❌ {chave}[{i}]: PDF sem 'arquivo' (chega sem nome)")
            if t in ("pdf", "imagem") and not b.get("url", "").startswith("https://"):
                erros.append(f"❌ {chave}[{i}]: URL precisa ser HTTPS pública")

    print("\n" + "-" * 60)
    for a in avisos:
        print(a)
    for e in erros:
        print(e)

    if not erros:
        print("\n✅ Tudo dentro dos limites da Cloud API")
    print("-" * 60)

    if "--json" in sys.argv:
        print("\nPayload do menu principal:\n")
        print(json.dumps(p, indent=2, ensure_ascii=False))

    sys.exit(1 if erros else 0)


if __name__ == "__main__":
    main()
