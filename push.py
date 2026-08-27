"""
Notificações push para o painel (Web Push / VAPID).

Dois níveis de urgência:
  urgente=True  → cliente pediu atendente: vibra forte, fica na tela até tocarem
  urgente=False → mensagem nova durante o atendimento: aviso discreto

Gere o par de chaves uma vez com:  python gerar_chaves_push.py
"""
import os
import json
import logging
import asyncio

from pywebpush import webpush, WebPushException

log = logging.getLogger("sitio-bot")

CHAVE_PUBLICA = os.getenv("VAPID_PUBLICA", "")
CHAVE_PRIVADA = os.getenv("VAPID_PRIVADA", "")
CONTATO = os.getenv("VAPID_CONTATO", "mailto:contato@sitiogirassol.com.br")

ativo = bool(CHAVE_PUBLICA and CHAVE_PRIVADA)
if not ativo:
    log.warning("Push desativado — defina VAPID_PUBLICA e VAPID_PRIVADA")


def _envia(inscricao: dict, payload: dict, urgencia: str):
    webpush(
        subscription_info=inscricao,
        data=json.dumps(payload),
        vapid_private_key=CHAVE_PRIVADA,
        vapid_claims={"sub": CONTATO},
        ttl=3600,
        headers={"Urgency": urgencia},
    )


async def notificar(titulo: str, corpo: str, telefone: str = "",
                    urgente: bool = False, aba: str = ""):
    """Dispara para todos os aparelhos inscritos. Remove os que expiraram."""
    if not ativo:
        return

    from db import listar_inscricoes, remover_inscricao

    inscricoes = await listar_inscricoes()
    if not inscricoes:
        return

    payload = {
        "titulo": titulo,
        "corpo": corpo[:160],
        "telefone": telefone,
        "urgente": urgente,
        "aba": aba,                       # "agenda" abre o painel já na agenda
        "tag": f"conversa-{telefone}" if telefone else (aba or "geral"),
    }
    urgencia = "high" if urgente else "normal"

    for insc in inscricoes:
        try:
            dados = json.loads(insc["dados"])
            await asyncio.to_thread(_envia, dados, payload, urgencia)
        except WebPushException as e:
            codigo = getattr(e.response, "status_code", None)
            # 404/410 = o navegador cancelou a inscrição
            if codigo in (404, 410):
                await remover_inscricao(insc["endpoint"])
                log.info("Inscrição expirada removida")
            else:
                log.error("Falha no push (%s): %s", codigo, e)
        except Exception as e:
            log.error("Erro inesperado no push: %s", e)


async def nova_mensagem(telefone: str, nome: str, texto: str):
    """Mensagem recebida enquanto o atendente cuida da conversa."""
    await notificar(
        titulo=nome or f"+{telefone}",
        corpo=texto or "Enviou um arquivo",
        telefone=telefone,
        urgente=False,
    )


async def pediu_atendente(telefone: str, nome: str, interesses: str = ""):
    """Cliente pediu para falar com uma pessoa. Prioridade máxima."""
    corpo = f"{nome or 'Cliente'} quer falar com a equipe"
    if interesses:
        corpo += f" · {interesses}"
    await notificar(
        titulo="🌻 Atendimento solicitado",
        corpo=corpo,
        telefone=telefone,
        urgente=True,
    )
