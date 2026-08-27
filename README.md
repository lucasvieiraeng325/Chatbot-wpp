# Bot de Atendimento — Sítio de Eventos

Bot de catálogo no WhatsApp + painel de atendimento humano + agenda de visitas e eventos.

Stack: FastAPI + WhatsApp Cloud API + Render (free) + Postgres externo.

| Fase | O que entrou |
|---|---|
| 1 | Menu de interesses, envio de panfletos, captura de leads |
| 2 | Painel do atendente (`/painel`), PWA instalável, notificações push |
| 3 | **Agenda de visitas e eventos**, aviso diário no WhatsApp da equipe, anexos de acesso rápido |

---

## Arquivos

| Arquivo | Papel |
|---|---|
| `app.py` | Webhook (verificação + recebimento) |
| `whatsapp.py` | Envio via Graph API |
| `menu.py` | Menus interativos |
| `content.py` | **Textos, PDFs, fotos e atalhos de anexo — edite só aqui no dia a dia** |
| `handlers.py` | Roteamento e notificação |
| `db.py` | Leads, mensagens, agendamentos |
| `painel.py` | API do painel (login, conversas, mídia) |
| `painel.html` | Painel: aba Conversas + aba Agenda |
| `agenda.py` | **API da agenda, atalhos de anexo e o aviso diário da equipe** |
| `push.py` | Notificações Web Push |

---

## 1. Meta — configuração

1. `developers.facebook.com` → Criar App → tipo **Negócios** → adicionar produto **WhatsApp**
2. Anote o **Phone Number ID**
3. **Token permanente** (o inicial expira em 24h e é inútil em produção):
   Business Settings → Usuários do sistema → criar usuário Admin → atribuir o App e a conta do WhatsApp → Gerar token com `whatsapp_business_messaging` + `whatsapp_business_management` → **nunca expira**
4. Adicione o número real do sítio (precisa ser um número **sem** WhatsApp ativo)

## 2. Banco de dados

Crie um projeto grátis no **Supabase** ou **Neon** e copie a connection string.

> Não use o Postgres free do Render: ele é **deletado após 30 dias**, e leva seus leads junto.

As tabelas são criadas sozinhas no primeiro boot, inclusive as da agenda
(`agendamentos` e `agenda_avisos`). Não precisa rodar migração à mão.

## 3. Materiais

Coloque PDFs em `pdfs/` e fotos em `images/`. Eles ficam públicos em
`https://SEU-APP.onrender.com/pdfs/arquivo.pdf` — que é a URL HTTPS que a Meta exige.

Limites: imagem 5 MB · PDF 100 MB · vídeo 16 MB (comprima para 720p/60s).

## 4. Deploy no Render

```bash
git add . && git commit -m "Fase 3: agenda e anexos rápidos" && git push
```

Render → New → Blueprint → conecta o repo → preenche as variáveis do painel.

Copie a URL gerada e coloque em `BASE_URL`.

## 5. Webhook na Meta

- Callback URL: `https://SEU-APP.onrender.com/webhook`
- Verify Token: o mesmo valor de `VERIFY_TOKEN`
- Assine o campo **messages**

## 6. Pings do cron (obrigatório no free tier)

Em [cron-job.org](https://cron-job.org), dois jobs:

```
1) Manter o serviço acordado
   URL:      https://SEU-APP.onrender.com/health
   Schedule: */10 7-21 * * *
   Timezone: o mesmo de TIMEZONE

2) Agenda do dia para a equipe (Fase 3)
   URL:      https://SEU-APP.onrender.com/api/cron/agenda?chave=SEU_CRON_SEGREDO
   Schedule: 30 7 * * *
   Timezone: o mesmo de TIMEZONE
```

Por que o `/health` só das 7h às 21h: o free tier dá **750 horas/mês** e um mês tem 730.
Pingar 24/7 consome toda a cota e não sobra margem para redeploys.

O job das 7h30 cai dentro da janela do `/health`, então o serviço já está quente
quando ele chega — nada de cold start de 50s bem na hora do aviso.

Ative o alerta por e-mail do cron-job — ele te avisa se o serviço cair.

---

# Fase 3

## Agenda de visitas e eventos

Segunda aba do painel. Calendário do mês com um pontinho por compromisso
(verde = visita ao sítio, dourado = evento), a lista do dia escolhido abaixo,
e um formulário para criar ou editar.

Cada agendamento guarda: tipo (visita/evento), título, data, hora (opcional —
sem hora vira "dia todo"), cliente, WhatsApp, observações e situação
(confirmado, a confirmar, já aconteceu, cancelado).

Quando o agendamento tem WhatsApp, o cartão mostra **abrir conversa** e pula
direto para o histórico daquele cliente. No sentido inverso, o botão de
calendário no topo da conversa abre o formulário já preenchido com o nome e o
número de quem está falando — que é como a maioria das visitas nasce.

## Aviso diário no WhatsApp da equipe

Às 7h30 o cron chama `/api/cron/agenda` e cada número em `NUMEROS_EQUIPE`
recebe algo assim:

```
🌻 *Agenda de 27 de agosto*

*🎉 Eventos*
• *16:00* — Casamento Marina & João

*🚗 Visitas ao sítio*
• *10:00* — Visita casal Ana e Rui
  wa.me/5521999991234
  _Querem ver a capela_
  ⚠️ ainda não confirmado

Bom trabalho! 🌻
```

Detalhes que importam:

- **Dias vazios não geram mensagem.** Para avisar também nos dias sem nada,
  ponha `AGENDA_AVISO_VAZIO=1`.
- **O aviso é idempotente por dia.** Se o cron repetir a chamada, ninguém
  recebe duas vezes. O botão *Avisar equipe* no painel força o reenvio.
- O mesmo resumo vira **push no painel instalado**, e tocar na notificação
  abre direto a aba Agenda. Desligue com `AGENDA_PUSH=0`.

### A janela de 24h (leia isto)

A Meta só deixa mandar texto livre para quem escreveu para o número nas
últimas 24h. O número de trabalho da atendente é uma pessoa como outra
qualquer aos olhos da Meta.

Duas saídas:

1. **Grátis e manual:** cada atendente manda um "oi" para o número do bot uma
   vez por dia. Enquanto a janela estiver aberta, o resumo chega inteiro.
2. **Definitivo:** cadastre um modelo na Meta com **uma** variável no corpo,
   por exemplo `agenda_do_dia`:

   > 🌻 Agenda de hoje no Sítio Girassol: {{1}}

   Ponha o nome dele em `TEMPLATE_AGENDA`. Quando o texto livre for recusado,
   o sistema reenvia pelo modelo automaticamente.

   ⚠️ Variáveis de modelo **não aceitam quebra de linha** — por isso o modelo
   recebe a versão de uma linha só (`10:00 Visita Ana | 16:00 Evento Casamento`).
   Quem quiser o detalhe completo responde a mensagem, o que reabre a janela.

   A aprovação leva até 24h. Cadastre antes de precisar.

## Anexos de acesso rápido

O botão de clipe na conversa abre uma folha com um ícone para cada material
que já existe no projeto: os 3 PDFs de pacotes, as 2 fotos, a localização e as
informações gerais — além de "Do aparelho", que é o envio de arquivo de sempre.

Um toque manda exatamente o que o bot mandaria, com a mesma legenda, assinado
como atendente. Nada de procurar PDF na galeria do celular.

Para acrescentar um material novo: crie a chave em `CONTEUDO` **e** adicione
uma linha em `ANEXOS_RAPIDOS`, reaproveitando um dos ícones existentes
(`casamento`, `quinze`, `infantil`, `decorado`, `festa`, `local`, `info`).
Ícone novo = um `<symbol id="ic-...">` no topo de `painel.html`.

---

## Variáveis de ambiente

| Variável | Para quê |
|---|---|
| `WHATSAPP_TOKEN`, `PHONE_NUMBER_ID`, `VERIFY_TOKEN` | Cloud API |
| `DATABASE_URL` | Postgres do Supabase/Neon |
| `BASE_URL` | URL pública do app (monta os links dos PDFs e fotos) |
| `TIMEZONE` | `America/Sao_Paulo` — usado pela agenda e pelo horário de atendimento |
| `PAINEL_SENHA`, `PAINEL_SEGREDO` | Acesso ao painel |
| `VAPID_PUBLICA`, `VAPID_PRIVADA` | Push (gere com `python gerar_chaves_push.py`) |
| `NUMERO_ATENDENTE` | Número que recebe o aviso de lead novo |
| **`NUMEROS_EQUIPE`** | Números que recebem a agenda do dia, separados por vírgula. Vazio = usa `NUMERO_ATENDENTE` |
| **`CRON_SEGREDO`** | Senha da rota `/api/cron/agenda`. Sem ela a rota fica fechada |
| **`TEMPLATE_AGENDA`** | Modelo aprovado na Meta, usado quando a janela de 24h fechou |
| **`TEMPLATE_IDIOMA`** | Idioma do modelo (padrão `pt_BR`) |
| **`AGENDA_AVISO_VAZIO`** | `1` avisa também nos dias sem compromisso |
| **`AGENDA_PUSH`** | `0` desliga o espelho do resumo no push do painel |

---

## Editando o conteúdo

Só `content.py`. Cada opção do menu tem uma lista de `blocos`:

```python
"casamento": {"blocos": [
    {"tipo": "pdf", "url": f"{PDF}/pacotes_casamento.pdf",
     "arquivo": "Pacotes Casamento.pdf", "legenda": "Nosso material 💒"},
    {"tipo": "imagem", "url": f"{IMG}/cerimonia.jpg", "legenda": "Cerimônia ao ar livre"},
]},
```

Tipos: `texto`, `pdf`, `imagem`, `localizacao`.

Para adicionar uma opção nova, inclua a chave em `CONTEUDO` **e** uma row em `menu.py`
(limite de 10 rows no total).

---

## Consultando os dados

```sql
-- leads mais quentes
SELECT nome, telefone, interesses, ultimo_contato
  FROM leads
 WHERE 'casamento' = ANY(interesses)
 ORDER BY ultimo_contato DESC;

-- agenda das próximas semanas
SELECT dia, hora, tipo, titulo, cliente, status
  FROM agendamentos
 WHERE dia >= current_date
 ORDER BY dia, hora;

-- quantas visitas viraram evento fechado
SELECT telefone, count(*) FILTER (WHERE tipo='visita') AS visitas,
       count(*) FILTER (WHERE tipo='evento') AS eventos
  FROM agendamentos WHERE telefone <> '' GROUP BY telefone;
```

Quem pediu o PDF de casamento **e** as fotos é um lead bem mais quente que
quem só viu "como chegar". Use isso para priorizar as ligações da semana.

---

## Segurança

- `.env` está no `.gitignore` — **nunca** comite o token
- Um token permanente vazado em repo público = sequestro do número.
  A Meta varre o GitHub procurando exatamente isso
- Se vazar: revogue o token no Business Settings imediatamente
- `/api/cron/agenda` é pública por natureza (o cron externo precisa alcançá-la).
  É o `CRON_SEGREDO` que a protege — use um valor longo e aleatório

---

## Checklist antes de ir ao ar

- [ ] Token permanente (teste depois de 48h)
- [ ] Banco no Supabase/Neon, não no Render
- [ ] Cron do `/health` das 7h às 21h
- [ ] Cron da agenda às 7h30, com `chave=` correta
- [ ] `NUMEROS_EQUIPE` preenchido e testado pelo botão *Avisar equipe*
- [ ] Modelo `agenda_do_dia` cadastrado na Meta (ou combinado o "oi" diário)
- [ ] Todos os PDFs abrindo no celular, com nome correto
- [ ] Cada atalho de anexo testado numa conversa real
- [ ] Aviso de LGPD e de "atendimento automatizado" nas mensagens
- [ ] Rota para atendente humano testada

---

## Fase 4 — ideias que já estão meio prontas

1. Lembrete para o **cliente** na véspera da visita (o modelo `lembrete_visita`
   já estava previsto na Fase 1)
2. Bloquear datas já vendidas no calendário e responder disponibilidade no bot
3. Relatório mensal: visitas realizadas × eventos fechados por origem
