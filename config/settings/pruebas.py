"""Settings de pytest. No dependen del .env salvo DJANGO_SECRET_KEY.

MOTOR_SIMULADO va fijo: las pruebas nunca llaman a la API ni gastan tokens,
aunque el .env de desarrollo tenga MOTOR_SIMULADO=False.
"""

import tempfile
from pathlib import Path

from .base import *  # noqa: F403
from .base import env

DEBUG = False
MOTOR_SIMULADO = True
ES_ENTORNO_DE_PRUEBAS = True
MODO_SOLO_LECTURA = False

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        # En memoria; las pruebas que lanzan el worker como subproceso indican un archivo.
        "NAME": env.str("RUTA_BASE_DATOS_PRUEBAS", default="") or ":memory:",
    }
}

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# La base de pruebas está en memoria: el bloqueo del worker va al directorio temporal,
# salvo que el entorno indique otro (las pruebas con subprocesos lo hacen).
RUTA_BLOQUEO_WORKER = Path(
    env.str("RUTA_BLOQUEO_WORKER", default="")
    or Path(tempfile.gettempdir()) / "revision-pruebas-worker.lock"
)
