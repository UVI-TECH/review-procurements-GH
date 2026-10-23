"""Cabeceras de seguridad para toda página de la app (ADR 0005)."""

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
