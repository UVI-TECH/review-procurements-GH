"""PC de Gestión Humana: Waitress en 127.0.0.1:8000, sin DEBUG y con la API real."""

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403
from .base import MOTOR_SIMULADO, MOTOR_SIMULADO_PAUSA_SEGUNDOS

DEBUG = False

# Un motor simulado aquí daría validaciones falsas sin que nadie lo note.
if MOTOR_SIMULADO:
    raise ImproperlyConfigured("Producción no arranca con MOTOR_SIMULADO=True.")
if MOTOR_SIMULADO_PAUSA_SEGUNDOS:
    raise ImproperlyConfigured(
        "Producción no arranca con MOTOR_SIMULADO_PAUSA_SEGUNDOS distinto de 0."
    )
