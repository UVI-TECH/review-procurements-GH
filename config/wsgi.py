"""Punto de entrada WSGI para Waitress.

Por defecto usa producción: si se arranca sin DJANGO_SETTINGS_MODULE, nunca
queda con DEBUG=True en el PC de Gestión Humana.
"""

import os

from django.core.wsgi import get_wsgi_application

from config.entorno import cargar_env

cargar_env()
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.produccion")

application = get_wsgi_application()
