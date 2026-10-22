"""Herramienta registrar_resultado y validación de su entrada.

La API ya hace cumplir el esquema con strict: true, pero la entrada se valida de nuevo
aquí: una respuesta fuera del esquema es un resultado con ERROR, nunca una excepción.
"""

from .reglas import norm
from .resultado import ResultadoDocumento

NOMBRE_HERRAMIENTA = "registrar_resultado"
TIPO_OTRO = "otro"

_TEXTO = {"type": "string"}
_BOOLEANO = {"type": "boolean"}
_TEXTO_O_NULO = {"anyOf": [{"type": "string"}, {"type": "null"}]}
_BOOLEANO_O_NULO = {"anyOf": [{"type": "boolean"}, {"type": "null"}]}

# Campo -> (esquema, tipos de Python aceptados al validar). El enum de tipo_detectado
# sale del catálogo.
_CAMPOS = {
    "tipo_detectado": (None, (str,)),
    "es_valido": (_BOOLEANO, (bool,)),
    "numero_documento": (_TEXTO, (str,)),
    "nombre_persona": (_TEXTO, (str,)),
    "tiene_firma": (_BOOLEANO_O_NULO, (bool, type(None))),
    "fecha_emision_eps": (_TEXTO_O_NULO, (str, type(None))),
    "fecha_emision_afp": (_TEXTO_O_NULO, (str, type(None))),
    "es_certificado_afiliacion": (_BOOLEANO_O_NULO, (bool, type(None))),
    "observaciones": (_TEXTO, (str,)),
}
_DATOS_EXTRA = ("fecha_emision_eps", "fecha_emision_afp", "es_certificado_afiliacion")


def codigos_permitidos(catalogo):
    return [*catalogo.codigos_reconocidos, TIPO_OTRO]


def construir_herramienta(catalogo):
    propiedades = {nombre: esquema for nombre, (esquema, _) in _CAMPOS.items()}
    propiedades["tipo_detectado"] = {"type": "string", "enum": codigos_permitidos(catalogo)}
    return {
        "name": NOMBRE_HERRAMIENTA,
        "description": (
            "Registra el análisis de un documento de contratación. Úsala una sola vez por "
            "documento, con todos los campos."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": propiedades,
            "required": list(propiedades),
            "additionalProperties": False,
        },
    }


def _problema(entrada, catalogo):
    if not isinstance(entrada, dict):
        return "no es un objeto"
    faltan = [c for c in _CAMPOS if c not in entrada]
    if faltan:
        return f"faltan campos ({', '.join(faltan)})"
    sobran = sorted(set(entrada) - set(_CAMPOS))
    if sobran:
        return f"campos no permitidos ({', '.join(sobran)})"
    for campo, (_, tipos) in _CAMPOS.items():
        if not isinstance(entrada[campo], tipos):
            return f"tipo incorrecto en {campo}"
    if entrada["tipo_detectado"] not in codigos_permitidos(catalogo):
        return "tipo_detectado fuera del catálogo"
    return None


def interpretar_entrada(entrada, catalogo, *, nombre_archivo, **metadatos):
    """Convierte la entrada de la herramienta en un ResultadoDocumento (o uno con ERROR)."""
    problema = _problema(entrada, catalogo)
    if problema:
        return ResultadoDocumento.con_error(
            nombre_archivo,
            f"Respuesta fuera del esquema: {problema}.",
            respuesta_cruda=entrada if isinstance(entrada, dict) else {"entrada": repr(entrada)},
            **metadatos,
        )
    return ResultadoDocumento(
        nombre_archivo=nombre_archivo,
        tipo_detectado=norm(entrada["tipo_detectado"]),
        es_valido=entrada["es_valido"],
        numero_documento=entrada["numero_documento"],
        nombre_persona=entrada["nombre_persona"],
        tiene_firma=entrada["tiene_firma"],
        datos_extra={campo: entrada[campo] for campo in _DATOS_EXTRA},
        observaciones=entrada["observaciones"],
        respuesta_cruda=dict(entrada),
        **metadatos,
    )
