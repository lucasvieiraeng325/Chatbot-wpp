#!/usr/bin/env python3
"""
Monitora continuamente os processos do sistema e finaliza qualquer um
cujo nome CONTENHA "passatempo" assim que ele for iniciado.

Requisito:  pip install psutil
Uso:        python mata_passatempo.py
Parar:      Ctrl+C
"""

import time
import psutil

ALVO = "passatempo"          # trecho que deve aparecer no nome do processo
INTERVALO = 1.0              # segundos entre cada verificação
FORCAR = False               # True = kill imediato; False = tenta encerrar educadamente


def corresponde(nome_processo: str) -> bool:
    if not nome_processo:
        return False
    # correspondência parcial: basta o nome CONTER o alvo
    return ALVO.lower() in nome_processo.lower()


def finalizar(proc: psutil.Process) -> None:
    try:
        if FORCAR:
            proc.kill()
        else:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except psutil.TimeoutExpired:
                proc.kill()
        print(f"[{time.strftime('%H:%M:%S')}] Finalizado: {proc.info['name']} (PID {proc.pid})")
    except psutil.NoSuchProcess:
        pass
    except psutil.AccessDenied:
        print(f"[{time.strftime('%H:%M:%S')}] Sem permissão para finalizar o PID {proc.pid}. "
              f"Execute como administrador/root.")


def main() -> None:
    print(f"Monitorando o processo '{ALVO}'... (Ctrl+C para parar)")
    while True:
        for proc in psutil.process_iter(["name"]):
            try:
                if corresponde(proc.info["name"]):
                    finalizar(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        time.sleep(INTERVALO)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nMonitoramento encerrado.")
