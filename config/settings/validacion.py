"""Equipo de John: abre un respaldo importado en modo solo lectura.

Bloquea escrituras y llamadas a la API (se hace cumplir desde la Fase 6).
"""

from .base import *  # noqa: F403

DEBUG = False
MODO_SOLO_LECTURA = True
MOTOR_SIMULADO = True
