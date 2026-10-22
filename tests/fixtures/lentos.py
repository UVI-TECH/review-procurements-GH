"""Funciones para el proceso hijo de las pruebas de tiempo límite.

Van en un módulo propio, sin Django: con spawn, el hijo lo importa desde cero.
"""

import time


def colgarse(datos):
    time.sleep(120)


def contar(datos):
    return (1, "ok", [])
