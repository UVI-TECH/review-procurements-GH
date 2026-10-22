"""Settings comunes a todos los entornos. Los secretos salen solo del .env."""

from pathlib import Path

import environ
from django.core.exceptions import ImproperlyConfigured

from config.entorno import BASE_DIR, cargar_env

cargar_env()
env = environ.Env()

SECRET_KEY = env.str("DJANGO_SECRET_KEY", default="")
if not SECRET_KEY:
    raise ImproperlyConfigured("Define DJANGO_SECRET_KEY en el .env (ver .env.example)")

DEBUG = False
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.cuentas",
    "apps.contrataciones",
    "apps.motor",
    "apps.corridas",
    "apps.reportes",
    "apps.respaldos",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": Path(env.str("RUTA_BASE_DATOS", default=str(BASE_DIR / "revision.db"))),
    }
}

AUTH_USER_MODEL = "cuentas.Usuario"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# La sesión expira tras 30 minutos de inactividad.
SESSION_COOKIE_AGE = 30 * 60
SESSION_SAVE_EVERY_REQUEST = True

LANGUAGE_CODE = "es-co"
TIME_ZONE = "America/Bogota"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Dominio
MOTOR_SIMULADO = env.bool("MOTOR_SIMULADO", default=False)
MODO_SOLO_LECTURA = False
# Mismo id que el legado, para que la comparación sea con el mismo modelo.
MODELO_CLAUDE = env.str("MODELO_CLAUDE", default="claude-haiku-4-5-20251001")
MOTOR_MAX_TOKENS = 1024
MOTOR_MAX_REINTENTOS = 3  # reintentos del SDK: 408, 409, 429, 5xx y conexión
MOTOR_TIMEOUT_SEGUNDOS = 120
MOTOR_PAUSA_ENTRE_LLAMADAS = 0.5
# La API acepta 32 MB por petición y 100 páginas en modelos de 200K de contexto; el
# base64 agrega un tercio al tamaño del PDF.
MOTOR_MAX_BYTES_PDF = 22 * 1024 * 1024
MOTOR_MAX_PAGINAS_PDF = 100

# Solo pruebas.py lo pone en True; los comandos que gastan tokens se niegan a correr.
ES_ENTORNO_DE_PRUEBAS = False
