"""
Simula a conversa no terminal, sem Meta e sem deploy.

    python simular.py            # modo interativo
    python simular.py casamento  # dispara uma opção direto
    python simular.py --tudo     # percorre todas as opções

Lê menu.py e content.py de verdade — reflete suas edições na hora.
"""
import sys
import os

os.environ.setdefault("BASE_URL", "https://sitio-bot.onrender.com")

from menu import menu_principal, voltar_menu
from content import CONTEUDO, ATALHOS

C = "\033[96m"; V = "\033[92m"; A = "\033[93m"; M = "\033[90m"; F = "\033[0m"
L = 46


def balao(linhas, etiqueta=""):
    print(f"{M}    ┌{'─' * L}┐{F}")
    for ln in linhas:
        for p in (ln[i:i + L - 2] for i in range(0, max(len(ln), 1), L - 2)):
            print(f"{M}    │{F} {p:<{L - 2}} {M}│{F}")
    if etiqueta:
        print(f"{M}    │{F} {A}{etiqueta:<{L - 2}}{F} {M}│{F}")
    print(f"{M}    └{'─' * L}┘{F}")


def render_lista(p):
    it = p["interactive"]
    linhas = []
    if "header" in it:
        linhas.append(f"[{it['header']['text']}]")
    linhas += it["body"]["text"].split("\n")
    if "footer" in it:
        linhas.append(it["footer"]["text"])
    balao(linhas, f"▾ {it['action']['button']}")

    print(f"\n{M}    ── painel de opções ──{F}")
    n = 0
    for s in it["action"]["sections"]:
        print(f"{M}    {s['title'].upper()}{F}")
        for r in s["rows"]:
            n += 1
            print(f"    {C}{n:2}.{F} {r['title']}")
            if r.get("description"):
                print(f"        {M}{r['description']}{F}")
    print(f"{M}    ── {n}/10 rows usados ──{F}\n")


def render_botoes(p):
    it = p["interactive"]
    balao(it["body"]["text"].split("\n"))
    b = " ".join(f"[ {x['reply']['title']} ]" for x in it["action"]["buttons"])
    print(f"    {C}{b}{F}\n")


def render_conteudo(chave):
    item = CONTEUDO.get(chave)
    if not item:
        print(f"{A}    (sem conteúdo para '{chave}' — cairia no menu){F}\n")
        return
    print(f"\n{V}    ▶ resposta para '{chave}'{F}\n")
    for i, b in enumerate(item["blocos"], 1):
        t = b["tipo"]
        if t == "texto":
            balao(b["texto"].split("\n"))
        elif t == "pdf":
            balao([f"📄 {b['arquivo']}", b.get("legenda", "")], f"→ {b['url']}")
        elif t == "imagem":
            balao([f"🖼  imagem", b.get("legenda", "")], f"→ {b['url']}")
        elif t == "localizacao":
            balao([f"📍 {b['nome']}", b["endereco"]], f"{b['lat']}, {b['lng']}")
        if i < len(item["blocos"]):
            print(f"{M}         ⋮ 1,5s{F}")
    print()
    render_botoes(voltar_menu("5598999999999"))


def ids_do_menu():
    p = menu_principal("x", "x")
    return [r["id"] for s in p["interactive"]["action"]["sections"] for r in s["rows"]]


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]

    if "--tudo" in sys.argv:
        for i in ids_do_menu():
            if i == "humano":
                continue
            print(f"\n{'=' * 56}\n  {i.upper()}\n{'=' * 56}")
            render_conteudo(i)
        return

    print(f"\n{'=' * 56}\n  SIMULADOR — Bot Sítio de Eventos\n{'=' * 56}\n")

    if args:
        bruto = " ".join(args).lower()
        chave = (bruto if bruto in CONTEUDO else
                 next((d for k, d in ATALHOS.items() if k in bruto), bruto))
        render_conteudo(chave)
        return

    print(f"{C}    você:{F} oi\n")
    render_lista(menu_principal("5598999999999", "Maria"))

    ids = ids_do_menu()
    while True:
        try:
            e = input(f"{C}  escolha (número, id, texto livre ou 'q'): {F}").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if e.lower() in ("q", "sair", ""):
            break

        if e.isdigit() and 1 <= int(e) <= len(ids):
            chave = ids[int(e) - 1]
        elif e in CONTEUDO:
            chave = e
        else:
            chave = next((d for k, d in ATALHOS.items() if k in e.lower()), None)

        print(f"\n{C}    você:{F} {e}")

        if chave == "humano":
            balao(["Perfeito! Um atendente vai te",
                   "responder em instantes. 🌿"])
            print(f"{A}    ⏸  bot pausado — próximas mensagens são ignoradas{F}\n")
            continue

        if not chave:
            print(f"{A}    (não reconhecido → reenvia o menu){F}\n")
            render_lista(menu_principal("5598999999999", "Maria"))
            continue

        render_conteudo(chave)


if __name__ == "__main__":
    main()
