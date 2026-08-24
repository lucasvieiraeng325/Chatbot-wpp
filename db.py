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
            CREATE TABLE IF NOT EXISTS mensagens (
                id        BIGSERIAL PRIMARY KEY,
                telefone  TEXT NOT NULL,
                direcao   TEXT NOT NULL,          -- recebida | enviada
                autor     TEXT NOT NULL,          -- cliente | bot | atendente
                tipo      TEXT DEFAULT 'text',
                conteudo  TEXT,
                url       TEXT,
                criado_em TIMESTAMPTZ DEFAULT now()
            );
            CREATE INDEX IF NOT EXISTS idx_msg_tel  ON mensagens (telefone, criado_em);
            CREATE INDEX IF NOT EXISTS idx_lead_ult ON leads (ultimo_contato DESC);
            ALTER TABLE leads ADD COLUMN IF NOT EXISTS nao_lidas INT DEFAULT 0;
            CREATE TABLE IF NOT EXISTS push_inscricoes (
                endpoint  TEXT PRIMARY KEY,
                dados     TEXT NOT NULL,
                criado_em TIMESTAMPTZ DEFAULT now()
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


# ---------------------------------------------------------------
# Histórico de mensagens (para o painel do atendente)
# ---------------------------------------------------------------

async def salvar_mensagem(telefone: str, direcao: str, autor: str,
                          conteudo: str = "", tipo: str = "text", url: str = ""):
    if not DATABASE_URL:
        return
    p = await pool()
    async with p.acquire() as c:
        await c.execute("""
            INSERT INTO mensagens (telefone, direcao, autor, tipo, conteudo, url)
            VALUES ($1, $2, $3, $4, $5, $6)
        """, telefone, direcao, autor, tipo, conteudo, url)
        if direcao == "recebida":
            await c.execute(
                "UPDATE leads SET nao_lidas = COALESCE(nao_lidas,0) + 1, "
                "ultimo_contato = now() WHERE telefone = $1", telefone)


async def listar_conversas(limite: int = 100):
    if not DATABASE_URL:
        return []
    p = await pool()
    async with p.acquire() as c:
        rows = await c.fetch("""
            SELECT l.telefone, l.nome, l.status, l.interesses,
                   COALESCE(l.nao_lidas,0) AS nao_lidas, l.ultimo_contato,
                   (SELECT conteudo FROM mensagens m
                     WHERE m.telefone = l.telefone
                     ORDER BY m.criado_em DESC LIMIT 1) AS ultima
              FROM leads l
             ORDER BY l.ultimo_contato DESC
             LIMIT $1
        """, limite)
    return [dict(r) for r in rows]


async def historico(telefone: str, limite: int = 200):
    if not DATABASE_URL:
        return []
    p = await pool()
    async with p.acquire() as c:
        rows = await c.fetch("""
            SELECT direcao, autor, tipo, conteudo, url, criado_em
              FROM mensagens WHERE telefone = $1
             ORDER BY criado_em ASC LIMIT $2
        """, telefone, limite)
    return [dict(r) for r in rows]


async def marcar_lidas(telefone: str):
    if not DATABASE_URL:
        return
    p = await pool()
    async with p.acquire() as c:
        await c.execute("UPDATE leads SET nao_lidas = 0 WHERE telefone = $1", telefone)


async def definir_status(telefone: str, status: str):
    if not DATABASE_URL:
        return
    p = await pool()
    async with p.acquire() as c:
        await c.execute("""
            INSERT INTO leads (telefone, status) VALUES ($1, $2)
            ON CONFLICT (telefone) DO UPDATE SET status = $2
        """, telefone, status)


async def total_nao_lidas() -> int:
    if not DATABASE_URL:
        return 0
    p = await pool()
    async with p.acquire() as c:
        return await c.fetchval("SELECT COALESCE(SUM(nao_lidas),0) FROM leads") or 0


# ---------------------------------------------------------------
# Notificações push
# ---------------------------------------------------------------

async def salvar_inscricao(endpoint: str, dados: str):
    if not DATABASE_URL:
        return
    p = await pool()
    async with p.acquire() as c:
        await c.execute("""
            INSERT INTO push_inscricoes (endpoint, dados) VALUES ($1, $2)
            ON CONFLICT (endpoint) DO UPDATE SET dados = EXCLUDED.dados
        """, endpoint, dados)


async def listar_inscricoes():
    if not DATABASE_URL:
        return []
    p = await pool()
    async with p.acquire() as c:
        rows = await c.fetch("SELECT endpoint, dados FROM push_inscricoes")
    return [dict(r) for r in rows]


async def remover_inscricao(endpoint: str):
    if not DATABASE_URL:
        return
    p = await pool()
    async with p.acquire() as c:
        await c.execute("DELETE FROM push_inscricoes WHERE endpoint = $1", endpoint)
