"""
Conversão de áudio para o formato que o WhatsApp aceita.

O navegador grava em WebM/Opus; a Cloud API exige OGG/Opus.
O ffmpeg vem embutido no pacote imageio-ffmpeg — não precisa
instalar nada no sistema.
"""
import asyncio
import logging
import os
import subprocess
import tempfile

log = logging.getLogger("sitio-bot")


def _ffmpeg() -> str:
    try:
        from imageio_ffmpeg import get_ffmpeg_exe
        return get_ffmpeg_exe()
    except Exception as e:
        log.error("ffmpeg indisponível: %s", e)
        return ""


def _converter(dados: bytes):
    exe = _ffmpeg()
    if not exe:
        return None

    entrada = saida = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
            f.write(dados)
            entrada = f.name
        saida = entrada.replace(".webm", ".ogg")

        r = subprocess.run(
            [exe, "-y", "-loglevel", "error", "-i", entrada,
             "-c:a", "libopus", "-b:a", "32k", "-ar", "48000", "-ac", "1",
             saida],
            capture_output=True, timeout=90,
        )
        if r.returncode != 0:
            log.error("ffmpeg falhou: %s", r.stderr.decode()[:300])
            return None
        with open(saida, "rb") as f:
            return f.read()
    except subprocess.TimeoutExpired:
        log.error("Conversão de áudio demorou demais")
        return None
    except Exception as e:
        log.error("Erro na conversão: %s", e)
        return None
    finally:
        for p in (entrada, saida):
            if p and os.path.exists(p):
                try:
                    os.unlink(p)
                except OSError:
                    pass


async def para_ogg(dados: bytes):
    """Converte para OGG/Opus sem travar o servidor."""
    return await asyncio.to_thread(_converter, dados)
