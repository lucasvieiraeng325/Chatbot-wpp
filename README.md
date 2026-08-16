# Bot de Atendimento — Sítio de Eventos (Fase 1)

Bot de catálogo no WhatsApp: menu de interesses, envio de panfletos e captura de leads.
**Sem IA e sem integração com calendário** — isso fica para a Fase 2.

Stack: FastAPI + WhatsApp Cloud API + Render (free) + Postgres externo.

---

## Arquivos

| Arquivo | Papel |
|---|---|
| `app.py` | Webhook (verificação + recebimento) |
| `whatsapp.py` | Envio via Graph API |
| `menu.py` | Menus interativos |
| `content.py` | **Textos, PDFs e fotos — edite só aqui no dia a dia** |
| `handlers.py` | Roteamento e notificação |
| `db.py` | Leads, deduplicação, pausa do bot |

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

## 3. Materiais

Coloque PDFs e fotos em `public/media/`. Eles ficam públicos em
`https://SEU-APP.onrender.com/media/arquivo.pdf` — que é a URL HTTPS que a Meta exige.

Limites: imagem 5 MB · PDF 100 MB · vídeo 16 MB (comprima para 720p/60s).

## 4. Deploy no Render

```bash
git add . && git commit -m "Fase 1: bot de catálogo" && git push
```

Render → New → Blueprint → conecta o repo → preenche as variáveis do painel.

Copie a URL gerada e coloque em `BASE_URL`.

## 5. Webhook na Meta

- Callback URL: `https://SEU-APP.onrender.com/webhook`
- Verify Token: o mesmo valor de `VERIFY_TOKEN`
- Assine o campo **messages**

## 6. Ping do cron (obrigatório no free tier)

Em [cron-job.org](https://cron-job.org):

```
URL:      https://SEU-APP.onrender.com/health
Schedule: */10 7-21 * * *
Timezone: America/Fortaleza
```

Por que só das 7h às 21h: o free tier dá **750 horas/mês** e um mês tem 730.
Pingar 24/7 consome toda a cota e não sobra margem para redeploys.
Das 7h às 22h dá ~450h/mês, com folga confortável.

Ative o alerta por e-mail do cron-job — ele te avisa se o serviço cair.

---

## Editando o conteúdo

Só `content.py`. Cada opção do menu tem uma lista de `blocos`:

```python
"casamento": {"blocos": [
    {"tipo": "pdf", "url": f"{BASE}/casamentos.pdf",
     "arquivo": "Casamentos.pdf", "legenda": "Nosso material 💒"},
    {"tipo": "imagem", "url": f"{BASE}/cerimonia.jpg", "legenda": "Cerimônia ao ar livre"},
]},
```

Tipos: `texto`, `pdf`, `imagem`, `localizacao`.

Para adicionar uma opção nova, inclua a chave em `CONTEUDO` **e** uma row em `menu.py`
(limite de 10 rows no total).

---

## Consultando os leads

```sql
SELECT nome, telefone, interesses, ultimo_contato
  FROM leads
 WHERE 'casamento' = ANY(interesses)
 ORDER BY ultimo_contato DESC;
```

Quem pediu o PDF de casamento **e** as fotos é um lead bem mais quente que
quem só viu "como chegar". Use isso para priorizar as ligações da semana.

---

## Segurança

- `.env` está no `.gitignore` — **nunca** comite o token
- Um token permanente vazado em repo público = sequestro do número.
  A Meta varre o GitHub procurando exatamente isso
- Se vazar: revogue o token no Business Settings imediatamente

---

## Checklist antes de ir ao ar

- [ ] Token permanente (teste depois de 48h)
- [ ] `render.yaml` — nome correto, não `render.ymal`
- [ ] Banco no Supabase/Neon, não no Render
- [ ] Cron rodando das 7h às 21h
- [ ] Todos os PDFs abrindo no celular, com nome correto
- [ ] Aviso de LGPD e de "atendimento automatizado" nas mensagens
- [ ] Rota para atendente humano testada

---

## Fase 2

Duas coisas baratas de fazer agora que economizam retrabalho depois:

1. Os interesses já estão sendo gravados — a base chega segmentada na Fase 2
2. Cadastre os templates na Meta desde já (`retomada_material`, `lembrete_visita`),
   porque aprovação leva até 24h
