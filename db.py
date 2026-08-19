"""
Persistência em Postgres (use Supabase ou Neon — NÃO o Postgres free do
Render, que é deletado após 30 dias e leva seus leads junto).
"""
import os
import logging
import asyncpg

log = logging.getLogger("sitio-bot")
DATABASE_URL = os.getenv("DATABASE_URL", "")

_pool = None


async def pool():
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=3)
    return _pool


async def init_db():
    if not DATABASE_URL:
        log.warning("DATABASE_URL ausente — rodando SEM persistência")
        return
    p = await pool()
    async with p.acquire() as c:
        await c.execute("""
            CREATE TABLE IF NOT EXISTS mensagens_processadas (
                message_id TEXT PRIMARY KEY,
                criado_em  TIMESTAMPTZ DEFAULT now()
            );
            CREATE TABLE IF NOT EXISTS leads (
                telefone         TEXT PRIMARY KEY,
                nome             TEXT,
                primeiro_contato TIMESTAMPTZ DEFAULT now(),
                ultimo_contato   TIMESTAMPTZ DEFAULT now(),
                interesses       TEXT[] DEFAULT '{}',
                status           TEXT DEFAULT 'bot'
            );
        """)
        # Limpeza da tabela de deduplicação
        await c.execute(
            "DELETE FROM mensagens_processadas "
            "WHERE criado_em < now() - interval '3 days'"
        )


async def ja_processada(message_id: str) -> bool:
    """
    INSERT que falha por PK duplicada é atômico — funciona mesmo com
    3 requisições simultâneas, que é exatamente o cenário do cold start.
    """
    if not DATABASE_URL:
        return False
    p = await pool()
    try:
        async with p.acquire() as c:
            await c.execute(
                "INSERT INTO mensagens_processadas (message_id) VALUES ($1)",
                message_id,
            )
        return False
    except asyncpg.UniqueViolationError:
        return True
    except Exception as e:
        log.error("Erro na deduplicação: %s", e)
        return False


async def registrar_interesse(telefone: str, nome: str, interesse: str):
    if not DATABASE_URL:
        return
    p = await pool()
    async with p.acquire() as c:
        await c.execute("""
            INSERT INTO leads (telefone, nome, interesses)
                 VALUES ($1, $2, ARRAY[$3]::text[])
            ON CONFLICT (telefone) DO UPDATE
               SET ultimo_contato = now(),
                   nome = COALESCE(leads.nome, EXCLUDED.nome),
                   interesses = CASE
                       WHEN $3 = ANY(leads.interesses) THEN leads.interesses
                       ELSE array_append(leads.interesses, $3)
                   END
        """, telefone, nome, interesse)


async def get_status(telefone: str) -> str:
    if not DATABASE_URL:
        return "bot"
    p = await pool()
    async with p.acquire() as c:
        r = await c.fetchval("SELECT status FROM leads WHERE telefone = $1", telefone)
    return r or "bot"


async def marcar_humano(telefone: str, nome: str):
    if not DATABASE_URL:
        return
    p = await pool()
    async with p.acquire() as c:
        await c.execute("""
            INSERT INTO leads (telefone, nome, status) VALUES ($1, $2, 'humano')
            ON CONFLICT (telefone) DO UPDATE SET status = 'humano', ultimo_contato = now()
        """, telefone, nome)


async def get_interesses(telefone: str) -> list:
    if not DATABASE_URL:
        return []
    p = await pool()
    async with p.acquire() as c:
        r = await c.fetchval("SELECT interesses FROM leads WHERE telefone = $1", telefone)
    return list(r or [])


async def get_nome(telefone: str):
    """Nome já confirmado pelo cliente, se houver."""
    if not DATABASE_URL:
        return None
    p = await pool()
    async with p.acquire() as c:
        return await c.fetchval("SELECT nome FROM leads WHERE telefone = $1", telefone)


async def set_nome(telefone: str, nome: str):
    """Grava o nome informado e devolve o bot ao fluxo normal."""
    if not DATABASE_URL:
        return
    p = await pool()
    async with p.acquire() as c:
        await c.execute("""
            INSERT INTO leads (telefone, nome, status) VALUES ($1, $2, 'bot')
            ON CONFLICT (telefone) DO UPDATE
               SET nome = EXCLUDED.nome, status = 'bot', ultimo_contato = now()
        """, telefone, nome)


async def marcar_aguardando_nome(telefone: str):
    if not DATABASE_URL:
        return
    p = await pool()
    async with p.acquire() as c:
        await c.execute("""
            INSERT INTO leads (telefone, status) VALUES ($1, 'aguardando_nome')
            ON CONFLICT (telefone) DO UPDATE
               SET status = 'aguardando_nome', ultimo_contato = now()
        """, telefone)
