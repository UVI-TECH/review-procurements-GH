"""Settings de pytest. No dependen del .env salvo DJANGO_SECRET_KEY.

MOTOR_SIMULADO va fijo: las pruebas nunca llaman a la API ni gastan tokens,
aunque el .env de desarrollo tenga MOTOR_SIMULADO=False.
"""

from .base import *  # noqa: F403

DEBUG = False
MOTOR_SIMULADO = True
MODO_SOLO_LECTURA = False

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
