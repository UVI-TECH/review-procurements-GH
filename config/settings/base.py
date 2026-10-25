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
    # Waitress no sirve estáticos: WhiteNoise los sirve, antes del resto de middleware.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    # CSP estricta y Cache-Control: no-store en toda página (ADR 0005).
    "apps.comun.middleware.CabecerasDeSeguridad",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    # Después de MessageMiddleware: en respuestas HTMX, los mensajes van en HX-Trigger.
    "apps.comun.middleware.AvisosHtmx",
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
        # Vacía en el .env (como en .env.example) = valor por defecto.
        "NAME": Path(env.str("RUTA_BASE_DATOS", default="") or BASE_DIR / "revision.db"),
        # El web y el worker escriben a la vez: WAL deja leer mientras otro escribe,
        # timeout espera al bloqueo en vez de fallar, e IMMEDIATE toma el bloqueo de
        # escritura al empezar la transacción (evita "database is locked" a mitad).
        "OPTIONS": {
            "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;",
            "transaction_mode": "IMMEDIATE",
            "timeout": 20,
        },
    }
}

# Carpeta de Contrataciones (OneDrive sincronizado), con una subcarpeta por profesor.
_carpeta = env.str("CARPETA_CONTRATACIONES", default="")
CARPETA_CONTRATACIONES = Path(_carpeta) if _carpeta else None

# La base nunca va dentro de una carpeta sincronizada: OneDrive la corrompería con el
# modo WAL activo. Solo los respaldos (Fase 6) van a OneDrive.
if CARPETA_CONTRATACIONES and (
    Path(DATABASES["default"]["NAME"]).resolve().is_relative_to(CARPETA_CONTRATACIONES.resolve())
):
    raise ImproperlyConfigured(
        "RUTA_BASE_DATOS no puede estar dentro de CARPETA_CONTRATACIONES: OneDrive "
        "corrompería la base de datos. Muévela a una carpeta local (ver .env.example)."
    )

# Un solo worker por equipo: bloqueo del sistema operativo sobre este archivo (ADR 0004).
RUTA_BLOQUEO_WORKER = Path(
    env.str("RUTA_BLOQUEO_WORKER", default="")
    or Path(DATABASES["default"]["NAME"]).parent / "worker.lock"
)

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
SESSION_EXPIRE_AT_BROWSER_CLOSE = True

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "tablero"
LOGOUT_REDIRECT_URL = "login"
# HTMX manda el token en la cabecera X-CSRFToken (hx-headers del <body>): la cookie no
# necesita ser legible desde JavaScript.
CSRF_COOKIE_HTTPONLY = True
SECURE_CONTENT_TYPE_NOSNIFF = True

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
# Solo para pruebas y demostraciones: el cliente simulado espera esto por documento.
# Producción se niega a arrancar si no es 0.
MOTOR_SIMULADO_PAUSA_SEGUNDOS = env.float("MOTOR_SIMULADO_PAUSA_SEGUNDOS", default=0.0)
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
# Tiempo límite para abrir un PDF con pypdf en el proceso aislado del worker.
MOTOR_TIMEOUT_PDF_SEGUNDOS = 30
# Estimación de costo de crear_corrida --en-seco. Precios por millón de tokens de
# Haiku 4.5; cámbialos si cambia el modelo o la tarifa. Sin historial, se usa la
# estimación de tokens por documento.
MOTOR_PRECIO_ENTRADA_MTOK = env.float("MOTOR_PRECIO_ENTRADA_MTOK", default=1.0)
MOTOR_PRECIO_SALIDA_MTOK = env.float("MOTOR_PRECIO_SALIDA_MTOK", default=5.0)
MOTOR_TOKENS_ESTIMADOS_ENTRADA = 4000
MOTOR_TOKENS_ESTIMADOS_SALIDA = 200

# Escaneo: si en un escaneo desaparece más de esta fracción de las carpetas conocidas,
# se aborta sin cambiar nada (OneDrive desconectado, carpeta movida). Solo --forzar sigue.
ESCANEO_MAX_DESAPARECIDAS = 0.20

# Worker: cada cuánto busca corridas pendientes cuando no hay trabajo.
WORKER_INTERVALO_SEGUNDOS = 5

# Solo pruebas.py lo pone en True; los comandos que gastan tokens se niegan a correr.
ES_ENTORNO_DE_PRUEBAS = False
