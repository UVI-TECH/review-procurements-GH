"""Carga del archivo .env, compartida por manage.py, wsgi.py y los settings.

Se llama antes de elegir DJANGO_SETTINGS_MODULE para que esa línea del .env
tenga efecto. Las variables ya definidas en el entorno (p. ej. en CI) no se pisan.
"""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent
RUTA_ENV = BASE_DIR / ".env"


def cargar_env() -> None:
    if RUTA_ENV.is_file():
        environ.Env.read_env(RUTA_ENV)
