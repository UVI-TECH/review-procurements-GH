"""Equipo de John: abre un respaldo importado en modo solo lectura.

Bloquea escrituras y llamadas a la API (se hace cumplir desde la Fase 6).
"""

from .base import *  # noqa: F403

DEBUG = False
MODO_SOLO_LECTURA = True
MOTOR_SIMULADO = True

# El clon se actualiza con git pull: los estáticos salen directo de static/, sin
# collectstatic. Si no, quedaba servido un app.css viejo (el tooltip del tablero se veía
# siempre, ADR 0006).
STATIC_ROOT = None
WHITENOISE_USE_FINDERS = True
