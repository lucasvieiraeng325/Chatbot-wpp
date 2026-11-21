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
            -- Qualificação capturada pela IA (ia.py) e dúvidas livres já
            -- respondidas depois dela.
            ALTER TABLE leads ADD COLUMN IF NOT EXISTS tipo_evento    TEXT DEFAULT '';
            ALTER TABLE leads ADD COLUMN IF NOT EXISTS convidados     INT  DEFAULT 0;
            ALTER TABLE leads ADD COLUMN IF NOT EXISTS data_interesse DATE;
            ALTER TABLE leads ADD COLUMN IF NOT EXISTS duvidas_ia     INT  DEFAULT 0;
            -- Ficha do painel: resumo da IA, foco, bloqueio e contrato
            ALTER TABLE leads ADD COLUMN IF NOT EXISTS resumo_ia      TEXT DEFAULT '';
            ALTER TABLE leads ADD COLUMN IF NOT EXISTS desvios_ia     INT  DEFAULT 0;
            ALTER TABLE leads ADD COLUMN IF NOT EXISTS ia_pausa_ate   TIMESTAMPTZ;
            ALTER TABLE leads ADD COLUMN IF NOT EXISTS bloqueado      BOOLEAN DEFAULT false;
            ALTER TABLE leads ADD COLUMN IF NOT EXISTS contrato_enviado_em TIMESTAMPTZ;
            -- Materiais já enviados ao cliente (PDF vai uma vez só)
            ALTER TABLE leads ADD COLUMN IF NOT EXISTS materiais_enviados TEXT[] DEFAULT '{}';
            -- Etapa do funil (ver ETAPAS) e quando mudou
            ALTER TABLE leads ADD COLUMN IF NOT EXISTS etapa    TEXT DEFAULT 'novo';
            ALTER TABLE leads ADD COLUMN IF NOT EXISTS etapa_em TIMESTAMPTZ;
            -- Regra atual: só conversa com atendente tem não lida. Limpa o
            -- acumulado antigo de quem só falou com o bot.
            UPDATE leads SET nao_lidas = 0
             WHERE status <> 'humano' AND COALESCE(nao_lidas, 0) <> 0;

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

            -- ID do evento espelhado na agenda compartilhada do Google
            -- (gcal.py). Vazio = ainda não foi para o Google.
            ALTER TABLE agendamentos ADD COLUMN IF NOT EXISTS gcal_id TEXT DEFAULT '';

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
        # O pedido de atendente em si já é a primeira pendência: a mensagem
        # que o disparou foi gravada antes do status virar 'humano'.
        await c.execute("""
            INSERT INTO leads (telefone, nome, status, nao_lidas)
                 VALUES ($1, $2, 'humano', 1)
            ON CONFLICT (telefone) DO UPDATE
               SET status = 'humano', ultimo_contato = now(),
                   nao_lidas = GREATEST(COALESCE(leads.nao_lidas, 0), 1)
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

        # Não lida = cliente esperando pessoa. Quem só conversa com o bot
        # não gera pendência; e a resposta do atendente zera a conta.
        if direcao == "recebida":
            await c.execute(
                "UPDATE leads SET nao_lidas = COALESCE(nao_lidas,0) + 1 "
                "WHERE telefone = $1 AND status = 'humano'", telefone)
        elif autor == "atendente":
            await c.execute(
                "UPDATE leads SET nao_lidas = 0 WHERE telefone = $1", telefone)


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
                   COALESCE(l.bloqueado, false) AS bloqueado,
                   COALESCE(l.etapa, 'novo') AS etapa,
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
        # Devolver ao bot encerra o atendimento: nada fica pendente.
        # Devolver ao bot também reabre as dúvidas livres da IA.
        await c.execute("""
            INSERT INTO leads (telefone, status) VALUES ($1, $2)
            ON CONFLICT (telefone) DO UPDATE
               SET status = $2,
                   nao_lidas = CASE WHEN $2 = 'humano' THEN leads.nao_lidas ELSE 0 END,
                   duvidas_ia = CASE WHEN $2 = 'humano' THEN leads.duvidas_ia ELSE 0 END
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
           COALESCE(a.gcal_id, '') AS gcal_id, COALESCE(a.uid, '') AS uid,
           l.nome AS nome_lead
      FROM agendamentos a
      LEFT JOIN leads l ON l.telefone = a.telefone
"""


async def definir_gcal_id(id_: int, gcal_id: str):
    if not DATABASE_URL:
        return
    p = await pool()
    async with p.acquire() as c:
        await c.execute("UPDATE agendamentos SET gcal_id = $2 WHERE id = $1",
                        id_, gcal_id or "")


async def agendamentos_sem_gcal(desde):
    """Futuros, ativos, criados no painel e ainda fora do Google Agenda."""
    if not DATABASE_URL:
        return []
    p = await pool()
    async with p.acquire() as c:
        rows = await c.fetch(
            _SELECT_AGENDA +
            " WHERE a.dia >= $1 AND a.status <> 'cancelado'"
            "   AND COALESCE(a.gcal_id, '') = '' AND COALESCE(a.uid, '') = ''"
            " ORDER BY a.dia, a.hora NULLS FIRST LIMIT 200", desde)
    return [dict(r) for r in rows]


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
            # Strings cruas (r""): sem elas \1 vira caractere de controle e
            # TODO telefone casa com TODO agendamento.
            r" WHERE a.telefone <> ''"
            r"   AND regexp_replace(a.telefone, '^(55)(\d{2})9(\d{8})$', '\1\2\3')"
            r"     = regexp_replace($1, '^(55)(\d{2})9(\d{8})$', '\1\2\3')"
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


# ---------------------------------------------------------------
# Qualificação do cliente (IA) e disponibilidade de datas
# ---------------------------------------------------------------

async def get_qualificacao(telefone: str) -> dict:
    vazio = {"tipo_evento": "", "convidados": 0, "data_interesse": None, "duvidas_ia": 0}
    if not DATABASE_URL:
        return vazio
    p = await pool()
    async with p.acquire() as c:
        r = await c.fetchrow("""
            SELECT COALESCE(tipo_evento, '') AS tipo_evento,
                   COALESCE(convidados, 0)   AS convidados,
                   data_interesse,
                   COALESCE(duvidas_ia, 0)   AS duvidas_ia
              FROM leads WHERE telefone = $1
        """, telefone)
    return dict(r) if r else vazio


async def salvar_qualificacao(telefone: str, tipo_evento: str = "",
                              convidados: int = 0, data_interesse=None,
                              somar_duvida: bool = False):
    """Grava só o que veio preenchido — nunca apaga o que já se sabia."""
    if not DATABASE_URL:
        return
    p = await pool()
    async with p.acquire() as c:
        await c.execute("""
            INSERT INTO leads (telefone) VALUES ($1) ON CONFLICT DO NOTHING
        """, telefone)
        await c.execute("""
            UPDATE leads SET
                tipo_evento    = COALESCE(NULLIF($2, ''), tipo_evento),
                convidados     = CASE WHEN $3 > 0 THEN $3 ELSE convidados END,
                data_interesse = COALESCE($4, data_interesse),
                duvidas_ia     = COALESCE(duvidas_ia, 0) + CASE WHEN $5 THEN 1 ELSE 0 END
             WHERE telefone = $1
        """, telefone, tipo_evento or "", int(convidados or 0), data_interesse, somar_duvida)


async def zerar_duvidas(telefone: str):
    if not DATABASE_URL:
        return
    p = await pool()
    async with p.acquire() as c:
        await c.execute("UPDATE leads SET duvidas_ia = 0 WHERE telefone = $1", telefone)


async def dias_com_evento(inicio, fim) -> set:
    """Dias que já têm evento (visita não ocupa o espaço)."""
    if not DATABASE_URL:
        return set()
    p = await pool()
    async with p.acquire() as c:
        rows = await c.fetch("""
            SELECT DISTINCT dia FROM agendamentos
             WHERE dia BETWEEN $1 AND $2
               AND tipo = 'evento' AND status IN ('confirmado', 'pendente')
        """, inicio, fim)
    return {r["dia"] for r in rows}


# ---------------------------------------------------------------
# Ficha do cliente no painel: foco da IA, resumo, bloqueio, reset
# ---------------------------------------------------------------

async def get_ficha(telefone: str) -> dict:
    if not DATABASE_URL:
        return {}
    p = await pool()
    async with p.acquire() as c:
        r = await c.fetchrow("""
            SELECT telefone, nome, status, interesses,
                   COALESCE(tipo_evento, '') AS tipo_evento,
                   COALESCE(convidados, 0)   AS convidados,
                   data_interesse,
                   COALESCE(resumo_ia, '')   AS resumo_ia,
                   COALESCE(desvios_ia, 0)   AS desvios_ia,
                   ia_pausa_ate,
                   COALESCE(bloqueado, false) AS bloqueado,
                   contrato_enviado_em,
                   COALESCE(etapa, 'novo') AS etapa, etapa_em
              FROM leads WHERE telefone = $1
        """, telefone)
    return dict(r) if r else {}


async def salvar_resumo_ia(telefone: str, resumo: str):
    if not DATABASE_URL or not resumo:
        return
    p = await pool()
    async with p.acquire() as c:
        await c.execute("UPDATE leads SET resumo_ia = $2 WHERE telefone = $1",
                        telefone, resumo[:600])


async def registrar_desvio(telefone: str, limite: int, pausa_min: int) -> bool:
    """Soma um desvio de foco. Ao chegar no limite, pausa a IA e zera a
    contagem. Devolve True se a pausa começou agora."""
    if not DATABASE_URL:
        return False
    p = await pool()
    async with p.acquire() as c:
        n = await c.fetchval("""
            UPDATE leads SET desvios_ia = COALESCE(desvios_ia, 0) + 1
             WHERE telefone = $1 RETURNING desvios_ia
        """, telefone)
        if n is not None and n >= limite:
            await c.execute("""
                UPDATE leads SET desvios_ia = 0,
                       ia_pausa_ate = now() + make_interval(mins => $2)
                 WHERE telefone = $1
            """, telefone, pausa_min)
            return True
    return False


async def ia_pausada(telefone: str) -> bool:
    if not DATABASE_URL:
        return False
    p = await pool()
    async with p.acquire() as c:
        return bool(await c.fetchval(
            "SELECT ia_pausa_ate > now() FROM leads WHERE telefone = $1", telefone))


async def esta_bloqueado(telefone: str) -> bool:
    if not DATABASE_URL or not telefone:
        return False
    p = await pool()
    async with p.acquire() as c:
        return bool(await c.fetchval(
            "SELECT bloqueado FROM leads WHERE telefone = $1", telefone))


async def definir_bloqueio(telefone: str, bloqueado: bool):
    if not DATABASE_URL:
        return
    p = await pool()
    async with p.acquire() as c:
        await c.execute("""
            INSERT INTO leads (telefone, bloqueado) VALUES ($1, $2)
            ON CONFLICT (telefone) DO UPDATE
               SET bloqueado = $2,
                   nao_lidas = CASE WHEN $2 THEN 0 ELSE leads.nao_lidas END
        """, telefone, bloqueado)


async def resetar_cliente(telefone: str):
    """Zera tudo o que o bot e a IA sabem do cliente. O histórico de
    mensagens e os agendamentos ficam."""
    if not DATABASE_URL:
        return
    p = await pool()
    async with p.acquire() as c:
        await c.execute("""
            UPDATE leads SET status = 'bot', nao_lidas = 0, interesses = '{}',
                   tipo_evento = '', convidados = 0, data_interesse = NULL,
                   duvidas_ia = 0, desvios_ia = 0, ia_pausa_ate = NULL,
                   resumo_ia = '', materiais_enviados = '{}',
                   etapa = 'novo', etapa_em = now()
             WHERE telefone = $1
        """, telefone)


async def materiais_enviados(telefone: str) -> set:
    if not DATABASE_URL:
        return set()
    p = await pool()
    async with p.acquire() as c:
        r = await c.fetchval(
            "SELECT materiais_enviados FROM leads WHERE telefone = $1", telefone)
    return set(r or [])


async def marcar_material(telefone: str, chave: str):
    if not DATABASE_URL:
        return
    p = await pool()
    async with p.acquire() as c:
        await c.execute("""
            UPDATE leads SET materiais_enviados = CASE
                WHEN $2 = ANY(COALESCE(materiais_enviados, '{}')) THEN materiais_enviados
                ELSE array_append(COALESCE(materiais_enviados, '{}'), $2) END
             WHERE telefone = $1
        """, telefone, chave)


# ---------------------------------------------------------------
# Funil: etapa do cliente até o contrato assinado e pago
# ---------------------------------------------------------------
# Ordem importa: o bot só avança sozinho (nunca volta). O representante
# muda para qualquer etapa pelo painel. "perdido" fica fora da ordem.
ETAPAS = [
    ("novo",              "Novo contato"),
    ("qualificando",      "Em qualificação"),
    ("qualificado",       "Qualificado"),
    ("com_representante", "Com representante"),
    ("visita_agendada",   "Visita agendada"),
    ("orcamento_enviado", "Orçamento enviado"),
    ("contrato_enviado",  "Contrato enviado"),
    ("contrato_assinado", "Contrato assinado"),
    ("entrada_paga",      "Entrada paga · data reservada"),
    ("quitado",           "Assinado e pago"),
    ("perdido",           "Perdido"),
]
ORDEM_ETAPAS = [e for e, _ in ETAPAS if e != "perdido"]


async def avancar_etapa(telefone: str, etapa: str):
    """Avanço automático: só se a etapa nova vier depois da atual.
    Cliente marcado como perdido não é mexido pelo bot."""
    if not DATABASE_URL or etapa not in ORDEM_ETAPAS:
        return
    p = await pool()
    async with p.acquire() as c:
        await c.execute("""
            UPDATE leads SET etapa = $2, etapa_em = now()
             WHERE telefone = $1
               AND COALESCE(etapa, 'novo') <> 'perdido'
               AND COALESCE(array_position($3::text[], COALESCE(etapa, 'novo')), 0)
                   < array_position($3::text[], $2)
        """, telefone, etapa, ORDEM_ETAPAS)


async def atualizar_ficha(telefone: str, campos: dict):
    """Edição manual pelo representante. Só altera as chaves presentes;
    valor vazio limpa o campo."""
    if not DATABASE_URL or not campos:
        return
    sets, valores = [], [telefone]
    def add(col, val):
        valores.append(val)
        sets.append(f"{col} = ${len(valores)}")
    if "nome" in campos:
        add("nome", (campos["nome"] or "").strip()[:80] or None)
    if "tipo_evento" in campos:
        add("tipo_evento", campos["tipo_evento"] or "")
    if "convidados" in campos:
        add("convidados", int(campos["convidados"] or 0))
    if "data_interesse" in campos:
        add("data_interesse", campos["data_interesse"])
    if "resumo_ia" in campos:
        add("resumo_ia", (campos["resumo_ia"] or "")[:600])
    if "etapa" in campos:
        add("etapa", campos["etapa"])
        sets.append("etapa_em = now()")
        if campos["etapa"] in ("contrato_enviado", "contrato_assinado", "entrada_paga", "quitado"):
            sets.append("contrato_enviado_em = COALESCE(contrato_enviado_em, now())")
    if not sets:
        return
    p = await pool()
    async with p.acquire() as c:
        await c.execute("INSERT INTO leads (telefone) VALUES ($1) ON CONFLICT DO NOTHING", telefone)
        await c.execute(f"UPDATE leads SET {', '.join(sets)} WHERE telefone = $1", *valores)


# ---------------------------------------------------------------
# Pacotes e tabela de preços estimados (editável pelo painel)
# ---------------------------------------------------------------
# Cada pacote é um JSON:
#   chave, nome, ativo, variacao ("dia" | "livre"), colunas, menus,
#   faixas (nº máximo de convidados de cada faixa, crescente),
#   precos[menu][coluna][faixa] (reais, inteiro ou null),
#   adicionais [{nome, valor}] (por convidado)
# variacao "dia": colunas = [segunda a sexta, fim de semana/feriado] e a
# IA escolhe pela data; "livre": colunas quaisquer (ex: sem/com decoração),
# todas mostradas ao cliente.

def _pacotes_iniciais() -> list:
    """Converte a tabela dos PDFs (content.PRECOS) no formato do banco."""
    from content import PRECOS, ADICIONAL_CALDO, ADICIONAL_JANTAR
    nomes = {"casamento": "Casamento", "quinze": "15 anos", "infantil": "Evento infantil"}
    descricoes = {"casamento": "Pacotes, decoração e cerimônia",
                  "quinze": "Pacotes para debutantes",
                  "infantil": "Pacotes para festas infantis"}
    adicionais = [{"nome": "Mais uma opção de caldo", "valor": ADICIONAL_CALDO},
                  {"nome": "Mais uma opção de prato principal (Standard)",
                   "valor": ADICIONAL_JANTAR}]
    saida = []
    for chave, menus in PRECOS.items():
        primeiro = next(iter(menus.values()))
        cols = list(primeiro.keys())
        faixas = sorted(next(iter(primeiro.values())).keys())
        por_dia = cols == ["semana", "fim_de_semana"]
        saida.append({
            "chave": chave, "nome": nomes.get(chave, chave), "ativo": True,
            "no_menu": True, "descricao": descricoes.get(chave, ""),
            "variacao": "dia" if por_dia else "livre",
            "colunas": (["Segunda a sexta", "Fim de semana e feriado"] if por_dia
                        else [c.replace("_", " ").replace("decoracao", "decoração").capitalize()
                              for c in cols]),
            "menus": [m.capitalize() for m in menus],
            "faixas": faixas,
            "precos": [[[menus[m][c][f] for f in faixas] for c in cols] for m in menus],
            "adicionais": adicionais,
            "materiais": materiais_padrao(chave),
        })
    return saida


def materiais_padrao(chave: str) -> list:
    """Material que o bot já envia hoje para esse tipo (content.CONTEUDO)."""
    from content import CONTEUDO
    saida = []
    for b in (CONTEUDO.get(chave) or {}).get("blocos", []):
        if b["tipo"] in ("pdf", "imagem", "texto"):
            saida.append({k: b.get(k, "") for k in ("tipo", "url", "arquivo", "legenda", "texto")})
    return saida


# Pacotes acrescentados depois do primeiro boot. Cada um entra uma única
# vez: se o representante excluir, não volta no próximo deploy.
def _sementes_extras() -> dict:
    from content import PACOTE_LOCACAO
    return {"locacao_espaco_v1": PACOTE_LOCACAO}


async def iniciar_pacotes():
    """
    Ordem importa:
      1. tabelas;
      2. banco vazio → pacotes dos PDFs (só na primeira vez);
      3. pacotes acrescentados depois (cada um uma vez — excluído não volta);
      4. ajustes pontuais em pacotes já existentes (cada um uma vez).
    """
    if not DATABASE_URL:
        return
    import json
    p = await pool()
    async with p.acquire() as c:
        await c.execute("""
            CREATE TABLE IF NOT EXISTS pacotes_preco (
                chave         TEXT PRIMARY KEY,
                dados         JSONB NOT NULL,
                ordem         INT DEFAULT 0,
                atualizado_em TIMESTAMPTZ DEFAULT now()
            );
            CREATE TABLE IF NOT EXISTS sementes_aplicadas (
                nome TEXT PRIMARY KEY,
                em   TIMESTAMPTZ DEFAULT now()
            );
        """)

        async def aplicada(nome):
            return bool(await c.fetchval(
                "SELECT 1 FROM sementes_aplicadas WHERE nome = $1", nome))

        async def marcar(nome):
            await c.execute("INSERT INTO sementes_aplicadas (nome) VALUES ($1) "
                            "ON CONFLICT DO NOTHING", nome)

        # 2. primeira vez: tabela dos PDFs
        if not await c.fetchval("SELECT COUNT(*) FROM pacotes_preco"):
            for i, pac in enumerate(_pacotes_iniciais()):
                await c.execute(
                    "INSERT INTO pacotes_preco (chave, dados, ordem) VALUES ($1, $2::jsonb, $3)",
                    pac["chave"], json.dumps(pac, ensure_ascii=False), i)

        # 3. pacotes acrescentados depois
        for nome, pac in _sementes_extras().items():
            if await aplicada(nome):
                continue
            await c.execute("""
                INSERT INTO pacotes_preco (chave, dados, ordem)
                VALUES ($1, $2::jsonb, (SELECT COALESCE(MAX(ordem), 0) + 1 FROM pacotes_preco))
                ON CONFLICT DO NOTHING
            """, pac["chave"], json.dumps(pac, ensure_ascii=False))
            await marcar(nome)

        # 4. folheto da locação para quem recebeu o pacote sem ele
        if not await aplicada("locacao_folheto_v1"):
            from content import FOLHETO_LOCACAO
            r = await c.fetchrow("SELECT dados FROM pacotes_preco WHERE chave = 'locacao'")
            if r:
                d = json.loads(r["dados"]) if isinstance(r["dados"], str) else dict(r["dados"])
                mats = d.get("materiais") or []
                if not any("locacao_espaco" in (m.get("url") or "") for m in mats):
                    d["materiais"] = [FOLHETO_LOCACAO] + mats
                    await c.execute(
                        "UPDATE pacotes_preco SET dados = $1::jsonb, atualizado_em = now() "
                        "WHERE chave = 'locacao'", json.dumps(d, ensure_ascii=False))
            await marcar("locacao_folheto_v1")


async def listar_pacotes(so_ativos: bool = False) -> list:
    if not DATABASE_URL:
        return [] if not so_ativos else [p for p in _pacotes_iniciais()]
    import json
    p = await pool()
    async with p.acquire() as c:
        rows = await c.fetch(
            "SELECT dados, atualizado_em FROM pacotes_preco ORDER BY ordem, chave")
    out = []
    for r in rows:
        d = json.loads(r["dados"]) if isinstance(r["dados"], str) else dict(r["dados"])
        d["atualizado_em"] = r["atualizado_em"].isoformat() if r["atualizado_em"] else None
        if "materiais" not in d:   # pacote antigo: usa o material atual do bot
            d["materiais"] = materiais_padrao(d["chave"])
        if not so_ativos or d.get("ativo", True):
            out.append(d)
    return out


async def salvar_pacote(pacote: dict, novo: bool = False) -> bool:
    """Grava o pacote. novo=True falha se a chave já existir."""
    if not DATABASE_URL:
        return False
    import json
    pacote = {k: v for k, v in pacote.items() if k != "atualizado_em"}
    p = await pool()
    async with p.acquire() as c:
        if novo:
            r = await c.execute("""
                INSERT INTO pacotes_preco (chave, dados, ordem)
                VALUES ($1, $2::jsonb, (SELECT COALESCE(MAX(ordem), 0) + 1 FROM pacotes_preco))
                ON CONFLICT DO NOTHING
            """, pacote["chave"], json.dumps(pacote, ensure_ascii=False))
            return r.endswith("1")
        r = await c.execute("""
            UPDATE pacotes_preco SET dados = $2::jsonb, atualizado_em = now()
             WHERE chave = $1
        """, pacote["chave"], json.dumps(pacote, ensure_ascii=False))
        return r.endswith("1")


async def remover_pacote(chave: str) -> bool:
    if not DATABASE_URL:
        return False
    p = await pool()
    async with p.acquire() as c:
        r = await c.execute("DELETE FROM pacotes_preco WHERE chave = $1", chave)
    return r.endswith("1")


# ---------------------------------------------------------------
# Arquivos enviados pelo painel (PDF/imagem dos pacotes)
# ---------------------------------------------------------------
# Ficam no banco porque o disco do Render free é apagado a cada deploy.

async def salvar_arquivo(nome: str, mime: str, conteudo: bytes) -> str:
    import uuid
    if not DATABASE_URL:
        return ""
    id_ = uuid.uuid4().hex
    p = await pool()
    async with p.acquire() as c:
        await c.execute("""
            CREATE TABLE IF NOT EXISTS arquivos (
                id        TEXT PRIMARY KEY,
                nome      TEXT NOT NULL,
                mime      TEXT NOT NULL,
                conteudo  BYTEA NOT NULL,
                criado_em TIMESTAMPTZ DEFAULT now()
            )
        """)
        await c.execute(
            "INSERT INTO arquivos (id, nome, mime, conteudo) VALUES ($1, $2, $3, $4)",
            id_, nome, mime, conteudo)
    return id_


async def obter_arquivo(id_: str):
    if not DATABASE_URL:
        return None
    p = await pool()
    async with p.acquire() as c:
        try:
            r = await c.fetchrow("SELECT nome, mime, conteudo FROM arquivos WHERE id = $1", id_)
        except asyncpg.UndefinedTableError:
            return None
    return dict(r) if r else None


async def obter_pacote(chave: str):
    for p in await listar_pacotes():
        if p["chave"] == chave:
            return p
    return None
