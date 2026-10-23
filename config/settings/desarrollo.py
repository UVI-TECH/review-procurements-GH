"""Equipo de desarrollo (Fedora): DEBUG activo y motor simulado por defecto."""

from .base import *  # noqa: F403
from .base import env

DEBUG = env.bool("DJANGO_DEBUG", default=True)
MOTOR_SIMULADO = env.bool("MOTOR_SIMULADO", default=True)

# Sin collectstatic en desarrollo: WhiteNoise sirve directo desde static/.
STATIC_ROOT = None
WHITENOISE_USE_FINDERS = True
