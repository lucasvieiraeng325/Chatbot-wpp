"""
Teste de carga do webhook.

Dispara webhooks simulando clientes reais e mede quanto tempo o servidor
leva para responder. A Meta espera resposta rápida — acima de ~5s ela
reenvia o evento, o que gera mensagem duplicada para o cliente.

    python teste_carga.py                  # 20 simultâneos, padrão
    python teste_carga.py --n 50           # 50 simultâneos
    python teste_carga.py --rampa          # sobe de 5 até 100
    python teste_carga.py --url https://...

IMPORTANTE
- Use números de teste (55219XXXXXXX gerados aqui), nunca números reais.
- O bot vai TENTAR responder cada um. Com token válido, isso consome
  mensagens da sua cota e a Meta pode marcar como spam.
- Rode com WHATSAPP_TOKEN inválido no Render, ou aceite os erros 401 no log.
"""
import argparse
import asyncio
import statistics
import time
import uuid

import httpx

PADRAO = "https://chatbot-wpp-593m.onrender.com"


def payload(indice: int, texto: str = "oi") -> dict:
    """Monta um webhook igual ao que a Meta envia."""
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "0",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": "5521999999999",
                                 "phone_number_id": "0"},
                    "contacts": [{
                        "profile": {"name": f"Teste Carga {indice}"},
                        "wa_id": f"5521{900000000 + indice}",
                    }],
                    "messages": [{
                        "from": f"5521{900000000 + indice}",
                        "id": f"wamid.CARGA{uuid.uuid4().hex[:16]}",
                        "timestamp": str(int(time.time())),
                        "type": "text",
                        "text": {"body": texto},
                    }],
                },
            }],
        }],
    }


async def uma(cliente: httpx.AsyncClient, url: str, i: int, texto: str):
    inicio = time.perf_counter()
    try:
        r = await cliente.post(f"{url}/webhook", json=payload(i, texto), timeout=30)
        return (time.perf_counter() - inicio, r.status_code)
    except httpx.TimeoutException:
        return (time.perf_counter() - inicio, "timeout")
    except Exception as e:
        return (time.perf_counter() - inicio, type(e).__name__)


def relatorio(nome: str, tempos: list):
    ok = [t for t, s in tempos if s == 200]
    falhas = [s for _, s in tempos if s != 200]

    if not ok:
        print(f"  {nome:>12} | nenhuma resposta bem-sucedida | falhas: {falhas[:3]}")
        return None

    ok.sort()
    p50 = statistics.median(ok)
    p95 = ok[int(len(ok) * 0.95)] if len(ok) > 1 else ok[0]
    pior = max(ok)

    alerta = ""
    if pior > 5:
        alerta = "  ⚠️  acima de 5s: a Meta reenviaria"
    elif pior > 2:
        alerta = "  ⚠️  latência alta"

    print(f"  {nome:>12} | ok {len(ok):>3}/{len(tempos):<3} | "
          f"mediana {p50:5.2f}s | p95 {p95:5.2f}s | pior {pior:5.2f}s{alerta}")
    if falhas:
        print(f"               | falhas: {falhas[:5]}")
    return pior


async def rajada(url: str, n: int, texto: str = "oi"):
    limites = httpx.Limits(max_connections=n + 10, max_keepalive_connections=n)
    async with httpx.AsyncClient(limits=limites) as c:
        return await asyncio.gather(*[uma(c, url, i, texto) for i in range(n)])


async def principal():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=PADRAO)
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--rampa", action="store_true")
    args = ap.parse_args()

    url = args.url.rstrip("/")
    print(f"\nAlvo: {url}")

    # Acorda o serviço antes de medir (cold start distorce tudo)
    print("Acordando o serviço...", end=" ", flush=True)
    t0 = time.perf_counter()
    async with httpx.AsyncClient() as c:
        try:
            await c.get(f"{url}/health", timeout=90)
            espera = time.perf_counter() - t0
            print(f"pronto em {espera:.1f}s"
                  + ("  (estava hibernando)" if espera > 5 else ""))
        except Exception as e:
            print(f"FALHOU: {e}")
            return

    print("\n" + "=" * 74)
    print("TESTE DE CARGA — webhooks simultâneos")
    print("=" * 74)

    niveis = [5, 10, 20, 40, 70, 100] if args.rampa else [args.n]

    for n in niveis:
        tempos = await rajada(url, n)
        pior = relatorio(f"{n} simult.", tempos)
        if pior and pior > 8:
            print("\n  Parando: o servidor já não responde a tempo neste nível.")
            break
        if len(niveis) > 1:
            await asyncio.sleep(6)   # deixa a fila drenar entre os níveis

    print("=" * 74)
    print("\nReferência:")
    print("  até 2s   → folgado")
    print("  2s a 5s  → funciona, mas sem margem")
    print("  acima 5s → a Meta reenvia o evento; risco de mensagem duplicada")
    print("\nObs.: a deduplicação por message_id protege contra o reenvio,")
    print("mas o cliente ainda espera a resposta todo esse tempo.\n")


if __name__ == "__main__":
    asyncio.run(principal())
