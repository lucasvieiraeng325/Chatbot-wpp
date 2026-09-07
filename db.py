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

            -- ID da mensagem na Meta (para responder com quote no chat)
            -- e o wa_message_id que esta mensagem esta respondendo.
            ALTER TABLE mensagens ADD COLUMN IF NOT EXISTS wa_message_id TEXT;
            ALTER TABLE mensagens ADD COLUMN IF NOT EXISTS resposta_a    TEXT;
            CREATE INDEX IF NOT EXISTS idx_msg_wa_id
                ON mensagens (telefone, wa_message_id)
             WHERE wa_message_id IS NOT NULL;
            CREATE TABLE IF NOT EXISTS push_inscricoes (
                endpoint  TEXT PRIMARY KEY,
                dados     TEXT NOT NULL,
                criado_em TIMESTAMPTZ DEFAULT now()
            );

            -- ----- Fase 3: agenda de visitas e eventos -----
            CREATE TABLE IF NOT EXISTS agendamentos (
                id            BIGSERIAL PRIMARY KEY,
                tipo          TEXT NOT NULL DEFAULT 'visita',   -- visita | evento
                titulo        TEXT NOT NULL,
                dia           DATE NOT NULL,
                hora          TIME,                              -- NULL = dia inteiro
                cliente       TEXT,
                telefone      TEXT,
                observacoes   TEXT,
                status        TEXT NOT NULL DEFAULT 'confirmado', -- confirmado | pendente | cancelado | realizado
                criado_em     TIMESTAMPTZ DEFAULT now(),
                atualizado_em TIMESTAMPTZ DEFAULT now()
            );
            CREATE INDEX IF NOT EXISTS idx_agenda_dia ON agendamentos (dia, hora);
            CREATE INDEX IF NOT EXISTS idx_agenda_tel ON agendamentos (telefone);

            -- Identificador do evento no Google. Vazio para o que nasce aqui.
            -- O índice parcial impede importar o mesmo evento duas vezes.
            ALTER TABLE agendamentos ADD COLUMN IF NOT EXISTS uid TEXT DEFAULT '';
            CREATE UNIQUE INDEX IF NOT EXISTS idx_agenda_uid
                ON agendamentos (uid) WHERE uid <> '';

            -- Um registro por dia avisado: torna o cron idempotente.
            CREATE TABLE IF NOT EXISTS agenda_avisos (
                dia        DATE PRIMARY KEY,
                enviado_em TIMESTAMPTZ DEFAULT now(),
                total      INT DEFAULT 0
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
                          conteudo: str = "", tipo: str = "text", url: str = "",
                          nome: str = "", wa_message_id: str = "",
                          resposta_a: str = ""):
    if not DATABASE_URL or not telefone:
        return
    p = await pool()
    async with p.acquire() as c:
        # Garante o lead: sem ele a conversa não aparece no painel.
        # Quem manda "oi" e não clica em nada também precisa ser listado.
        await c.execute("""
            INSERT INTO leads (telefone, nome) VALUES ($1, NULLIF($2, ''))
            ON CONFLICT (telefone) DO UPDATE
               SET ultimo_contato = now(),
                   nome = COALESCE(leads.nome, NULLIF($2, ''))
        """, telefone, nome)

        await c.execute("""
            INSERT INTO mensagens (telefone, direcao, autor, tipo, conteudo, url,
                                   wa_message_id, resposta_a)
            VALUES ($1, $2, $3, $4, $5, $6, NULLIF($7,''), NULLIF($8,''))
        """, telefone, direcao, autor, tipo, conteudo, url,
             wa_message_id, resposta_a)

        if direcao == "recebida":
            await c.execute(
                "UPDATE leads SET nao_lidas = COALESCE(nao_lidas,0) + 1 "
                "WHERE telefone = $1", telefone)


async def listar_conversas(limite: int = 100, hoje=None):
    """
    Cada conversa vem com o compromisso mais relevante do cliente: o próximo
    que ainda vai acontecer ou, na falta dele, o último que aconteceu.
    É o que permite buscar conversa por agendamento no painel.
    """
    if not DATABASE_URL:
        return []
    from datetime import date as _date
    hoje = hoje or _date.today()
    p = await pool()
    async with p.acquire() as c:
        # String crua: sem o r"" os \1 do regexp viram caracteres de controle
        # e a comparação casa qualquer conversa com qualquer agendamento.
        rows = await c.fetch(r"""
            SELECT l.telefone, l.nome, l.status, l.interesses,
                   COALESCE(l.nao_lidas,0) AS nao_lidas, l.ultimo_contato,
                   (SELECT conteudo FROM mensagens m
                     WHERE m.telefone = l.telefone
                     ORDER BY m.criado_em DESC LIMIT 1) AS ultima,
                   ag.dia AS ag_dia, ag.hora AS ag_hora,
                   ag.tipo AS ag_tipo, ag.titulo AS ag_titulo
              FROM leads l
              LEFT JOIN LATERAL (
                   SELECT a.dia, a.hora, a.tipo, a.titulo
                     FROM agendamentos a
                    WHERE a.telefone <> ''
                      AND regexp_replace(a.telefone, '^(55)(\d{2})9(\d{8})$', '\1\2\3')
                        = regexp_replace(l.telefone, '^(55)(\d{2})9(\d{8})$', '\1\2\3')
                      AND a.status <> 'cancelado'
                    ORDER BY (a.dia >= $2) DESC,
                             CASE WHEN a.dia >= $2 THEN a.dia END ASC,
                             a.dia DESC
                    LIMIT 1
              ) ag ON true
             ORDER BY l.ultimo_contato DESC
             LIMIT $1
        """, limite, hoje)
    return [dict(r) for r in rows]


async def historico(telefone: str, limite: int = 200):
    """
    Devolve as mensagens da conversa. Cada uma que responde a outra vem
    com um resumo da citada (q_autor/q_conteudo/q_tipo), para o painel
    desenhar o quote sem precisar de outra consulta.
    """
    if not DATABASE_URL:
        return []
    p = await pool()
    async with p.acquire() as c:
        rows = await c.fetch("""
            SELECT m.direcao, m.autor, m.tipo, m.conteudo, m.url, m.criado_em,
                   m.wa_message_id, m.resposta_a,
                   q.autor    AS q_autor,
                   q.conteudo AS q_conteudo,
                   q.tipo     AS q_tipo
              FROM mensagens m
              LEFT JOIN LATERAL (
                   SELECT autor, conteudo, tipo
                     FROM mensagens
                    WHERE telefone = m.telefone
                      AND wa_message_id = m.resposta_a
                    LIMIT 1
              ) q ON m.resposta_a IS NOT NULL
             WHERE m.telefone = $1
             ORDER BY m.criado_em ASC LIMIT $2
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


# ---------------------------------------------------------------
# Agenda: visitas ao sítio e datas de evento
# ---------------------------------------------------------------

CAMPOS_AGENDA = ("tipo", "titulo", "dia", "hora", "cliente",
                 "telefone", "observacoes", "status", "uid")

_SELECT_AGENDA = """
    SELECT a.id, a.tipo, a.titulo, a.dia, a.hora, a.cliente, a.telefone,
           a.observacoes, a.status, a.criado_em, a.atualizado_em,
           l.nome AS nome_lead
      FROM agendamentos a
      LEFT JOIN leads l ON l.telefone = a.telefone
"""


async def criar_agendamento(dados: dict):
    """dados usa as chaves de CAMPOS_AGENDA. Devolve a linha criada."""
    if not DATABASE_URL:
        return None
    p = await pool()
    async with p.acquire() as c:
        r = await c.fetchrow("""
            INSERT INTO agendamentos
                   (tipo, titulo, dia, hora, cliente, telefone, observacoes, status, uid)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING id
        """, dados.get("tipo") or "visita", dados.get("titulo") or "",
             dados.get("dia"), dados.get("hora"), dados.get("cliente") or "",
             dados.get("telefone") or "", dados.get("observacoes") or "",
             dados.get("status") or "confirmado", dados.get("uid") or "")
        return await _um(c, r["id"])


async def atualizar_agendamento(id_: int, dados: dict):
    """Atualiza só os campos presentes em `dados`. Devolve a linha ou None."""
    if not DATABASE_URL:
        return None
    campos = [k for k in CAMPOS_AGENDA if k in dados]
    if not campos:
        return None
    sets = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(campos))
    valores = [dados[k] for k in campos]
    p = await pool()
    async with p.acquire() as c:
        r = await c.fetchrow(
            f"UPDATE agendamentos SET {sets}, atualizado_em = now() "
            f"WHERE id = $1 RETURNING id", id_, *valores)
        if not r:
            return None
        return await _um(c, id_)


async def remover_agendamento(id_: int) -> bool:
    if not DATABASE_URL:
        return False
    p = await pool()
    async with p.acquire() as c:
        r = await c.execute("DELETE FROM agendamentos WHERE id = $1", id_)
    return r.endswith("1")


async def _um(conexao, id_: int):
    r = await conexao.fetchrow(_SELECT_AGENDA + " WHERE a.id = $1", id_)
    return dict(r) if r else None


async def obter_agendamento(id_: int):
    if not DATABASE_URL:
        return None
    p = await pool()
    async with p.acquire() as c:
        return await _um(c, id_)


async def listar_agendamentos(inicio, fim, incluir_cancelados: bool = True):
    """Todos os compromissos entre duas datas (inclusive), em ordem."""
    if not DATABASE_URL:
        return []
    filtro = "" if incluir_cancelados else " AND a.status <> 'cancelado'"
    p = await pool()
    async with p.acquire() as c:
        rows = await c.fetch(
            _SELECT_AGENDA +
            f" WHERE a.dia BETWEEN $1 AND $2{filtro}"
            " ORDER BY a.dia, a.hora NULLS FIRST, a.id",
            inicio, fim)
    return [dict(r) for r in rows]


async def agendamentos_do_dia(dia, incluir_cancelados: bool = False):
    return await listar_agendamentos(dia, dia, incluir_cancelados)


async def agenda_por_telefone(telefone: str, limite: int = 20):
    """Compromissos ligados a uma conversa — mostrado no cabeçalho do chat."""
    if not DATABASE_URL or not telefone:
        return []
    p = await pool()
    async with p.acquire() as c:
        rows = await c.fetch(
            _SELECT_AGENDA +
            " WHERE a.telefone <> ''"
            "   AND regexp_replace(a.telefone, '^(55)(\d{2})9(\d{8})$', '\1\2\3')"
            "     = regexp_replace($1, '^(55)(\d{2})9(\d{8})$', '\1\2\3')"
            " ORDER BY a.dia DESC LIMIT $2",
            telefone, limite)
    return [dict(r) for r in rows]


async def uids_conhecidos(uids: list) -> set:
    """Quais desses eventos do Google já foram importados antes."""
    if not DATABASE_URL or not uids:
        return set()
    p = await pool()
    async with p.acquire() as c:
        rows = await c.fetch(
            "SELECT uid FROM agendamentos WHERE uid = ANY($1::text[])", uids)
    return {r["uid"] for r in rows}


async def importar_agendamentos(itens: list) -> int:
    """
    Grava em lote o que veio do .ics. Devolve quantos entraram.

    Quem já tem o mesmo uid é pulado — reimportar o mesmo arquivo não
    duplica nada, o que importa porque a cliente vai errar a mão na
    primeira tentativa.
    """
    if not DATABASE_URL or not itens:
        return 0
    p = await pool()
    async with p.acquire() as c:
        async with c.transaction():
            await c.executemany("""
                INSERT INTO agendamentos
                       (tipo, titulo, dia, hora, cliente, telefone,
                        observacoes, status, uid)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT DO NOTHING
            """, [(i.get("tipo") or "evento", i.get("titulo") or "",
                   i.get("dia"), i.get("hora"), i.get("cliente") or "",
                   i.get("telefone") or "", i.get("observacoes") or "",
                   i.get("status") or "confirmado", i.get("uid") or "")
                  for i in itens])
    return len(itens)


async def aviso_ja_enviado(dia) -> bool:
    if not DATABASE_URL:
        return False
    p = await pool()
    async with p.acquire() as c:
        return bool(await c.fetchval(
            "SELECT 1 FROM agenda_avisos WHERE dia = $1", dia))


# ---------------------------------------------------------------
# Analytics: volume de leads e distribuicao de interesses
# ---------------------------------------------------------------
# As agregacoes usam primeiro_contato dos leads (clientes distintos que
# chegaram), nao mensagens — assim o volume nao infla quando um mesmo
# cliente conversa muito.

async def leads_por_bucket(inicio, fim, tz: str, unidade: str) -> list:
    """
    Conta leads novos entre `inicio` e `fim` agrupados por hora/dia/mes.
    Usa AT TIME ZONE para o corte cair no fuso do sitio, nao no do banco.

    unidade: 'hour' | 'day' | 'month'
    Devolve [{"bucket": datetime, "count": int}, ...] ordenado.
    """
    if not DATABASE_URL:
        return []
    if unidade not in ("hour", "day", "month"):
        raise ValueError("unidade deve ser hour/day/month")
    p = await pool()
    async with p.acquire() as c:
        rows = await c.fetch(f"""
            SELECT date_trunc('{unidade}', primeiro_contato AT TIME ZONE $3) AS bucket,
                   COUNT(*)::int AS total
              FROM leads
             WHERE primeiro_contato >= $1 AND primeiro_contato < $2
             GROUP BY 1
             ORDER BY 1
        """, inicio, fim, tz)
    return [{"bucket": r["bucket"], "count": r["total"]} for r in rows]


async def distribuicao_interesses(inicio, fim) -> list:
    """
    Quantos leads distintos citaram cada interesse no periodo.
    Um lead com 'casamento' + '15 anos' conta em ambos.
    """
    if not DATABASE_URL:
        return []
    p = await pool()
    async with p.acquire() as c:
        rows = await c.fetch("""
            SELECT unnest(interesses) AS interesse, COUNT(*)::int AS total
              FROM leads
             WHERE primeiro_contato >= $1 AND primeiro_contato < $2
               AND interesses IS NOT NULL
               AND array_length(interesses, 1) > 0
             GROUP BY 1
             ORDER BY total DESC
        """, inicio, fim)
    return [{"interesse": r["interesse"], "count": r["total"]} for r in rows]


async def total_leads_periodo(inicio, fim) -> int:
    if not DATABASE_URL:
        return 0
    p = await pool()
    async with p.acquire() as c:
        return await c.fetchval(
            "SELECT COUNT(*) FROM leads "
            "WHERE primeiro_contato >= $1 AND primeiro_contato < $2",
            inicio, fim) or 0


async def leads_para_exportar():
    """Snapshot completo dos leads, para o CSV de backup do painel."""
    if not DATABASE_URL:
        return []
    p = await pool()
    async with p.acquire() as c:
        rows = await c.fetch("""
            SELECT telefone, nome, primeiro_contato, ultimo_contato,
                   interesses, status, COALESCE(nao_lidas, 0) AS nao_lidas
              FROM leads
             ORDER BY primeiro_contato DESC
        """)
    return [dict(r) for r in rows]


async def marcar_aviso_enviado(dia, total: int = 0):
    if not DATABASE_URL:
        return
    p = await pool()
    async with p.acquire() as c:
        await c.execute("""
            INSERT INTO agenda_avisos (dia, total) VALUES ($1, $2)
            ON CONFLICT (dia) DO UPDATE
               SET enviado_em = now(), total = EXCLUDED.total
        """, dia, total)
