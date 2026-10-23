"""Funciones para el proceso hijo de las pruebas de tiempo límite.

Van en un módulo propio, sin Django: con spawn, el hijo lo importa desde cero.
"""

import time


def colgarse(datos):
    time.sleep(120)


def contar(datos):
    return (1, "ok", [])


def colgarse_si_marcado(datos):
    """Se cuelga solo con los PDFs cuya marca dice COLGAR; los demás se leen normal."""
    if b"COLGAR" in datos:
        time.sleep(120)
    from apps.motor.lector_pdf import inspeccionar

    return inspeccionar(datos)


def ignora_interrupciones(datos):
    """Corre en el hijo del pool: ¿ignora Ctrl+C (y Ctrl+Break en Windows)?"""
    import signal

    ignora = signal.getsignal(signal.SIGINT) == signal.SIG_IGN
    if hasattr(signal, "SIGBREAK"):
        ignora = ignora and signal.getsignal(signal.SIGBREAK) == signal.SIG_IGN
    return ignora
