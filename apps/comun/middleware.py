"""Cabeceras de seguridad y avisos para HTMX (ADR 0005)."""

import json

from django.contrib import messages

POLITICA = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self'",
        "font-src 'self'",
        "frame-src 'self'",  # el visor de PDF del detalle
        "frame-ancestors 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
    ]
)


class CabecerasDeSeguridad:
    """Cache-Control: no-store en todo (son datos de Gestión Humana) y una CSP estricta.

    Sin scripts ni estilos en línea: HTMX va en static/ y se configura sin eval. El admin
    de Django queda fuera de la CSP (usa atributos style). Una vista puede fijar su propia
    CSP antes (el visor de PDF).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        respuesta = self.get_response(request)
        respuesta["Cache-Control"] = "no-store"
        if not request.path.startswith("/admin/"):
            respuesta.headers.setdefault("Content-Security-Policy", POLITICA)
        return respuesta


class AvisosHtmx:
    """En una respuesta a HTMX, los mensajes pendientes viajan en HX-Trigger.

    El fragmento que HTMX inserta no trae la región de avisos de base.html, así que sin
    esto el mensaje se perdería o aparecería en la página siguiente. static/js/app.js
    escucha el evento "avisos" y muestra cada uno. Va después de MessageMiddleware en
    MIDDLEWARE para consumir los mensajes antes de que este los guarde. Las redirecciones
    se saltan: los mensajes los recibe la página de destino.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        respuesta = self.get_response(request)
        if not request.headers.get("HX-Request") or 300 <= respuesta.status_code < 400:
            return respuesta
        avisos = [{"nivel": m.level_tag, "texto": str(m)} for m in messages.get_messages(request)]
        if avisos:
            disparadores = json.loads(respuesta.headers.get("HX-Trigger", "{}") or "{}")
            disparadores["avisos"] = avisos
            # ensure_ascii: las cabeceras HTTP solo admiten latin-1; HTMX decodifica el JSON.
            respuesta["HX-Trigger"] = json.dumps(disparadores)
        return respuesta
