"""Cliente real de Claude: un PDF entra, un ResultadoDocumento sale, nunca una excepción.

La clave sale solo del entorno (.env) y nunca aparece en logs, errores ni resultados:
los errores del SDK se traducen a "tipo + código HTTP", sin su mensaje.
"""

import base64
import logging
import os

import anthropic
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .cliente_base import ClienteBase
from .esquema import NOMBRE_HERRAMIENTA, construir_herramienta, interpretar_entrada
from .prompts import construir_contenido, construir_system
from .resultado import ResultadoDocumento, Uso

logger = logging.getLogger(__name__)


def _crear_sdk():
    if settings.MOTOR_SIMULADO:
        raise ImproperlyConfigured(
            "El cliente real de Claude no se usa con MOTOR_SIMULADO=True (desarrollo y pruebas)."
        )
    clave = os.environ.get("ANTHROPIC_API_KEY", "")
    if not clave:
        raise ImproperlyConfigured("Define ANTHROPIC_API_KEY en el .env (ver .env.example)")
    return anthropic.Anthropic(
        api_key=clave,
        max_retries=settings.MOTOR_MAX_REINTENTOS,
        timeout=settings.MOTOR_TIMEOUT_SEGUNDOS,
    )


def _uso(respuesta):
    usage = respuesta.usage
    return Uso(
        entrada=usage.input_tokens or 0,
        salida=usage.output_tokens or 0,
        cache_lectura=usage.cache_read_input_tokens or 0,
        cache_creacion=usage.cache_creation_input_tokens or 0,
    )


def _mensaje_de_error_api(error):
    if isinstance(error, anthropic.APIStatusError):
        return f"La API respondió {error.status_code} ({type(error).__name__})."
    if isinstance(error, anthropic.APITimeoutError):
        return "Tiempo de espera agotado al llamar a la API."
    return "Sin conexión con la API."


class ClienteClaude(ClienteBase):
    def __init__(self, catalogo, *, sdk=None, modelo=None, inspector=None):
        super().__init__(catalogo, inspector=inspector)
        # sdk solo se inyecta en pruebas; sin él se crea el cliente real.
        self._sdk = sdk if sdk is not None else _crear_sdk()
        self.modelo = modelo or settings.MODELO_CLAUDE
        self._system = construir_system(catalogo)
        self._herramienta = construir_herramienta(catalogo)

    def _analizar_pdf(self, pdf, nombre_archivo, profesor):
        metadatos = {"modificado_en": pdf.modificado_en, "modelo": self.modelo}
        try:
            respuesta = self._sdk.messages.create(
                model=self.modelo,
                max_tokens=settings.MOTOR_MAX_TOKENS,
                system=self._system,
                tools=[self._herramienta],
                tool_choice={"type": "tool", "name": NOMBRE_HERRAMIENTA},
                messages=[
                    {
                        "role": "user",
                        "content": construir_contenido(
                            base64.standard_b64encode(pdf.datos).decode(), nombre_archivo, profesor
                        ),
                    }
                ],
            )
        except anthropic.APIError as error:
            logger.warning("Error de la API: %s", type(error).__name__)
            return ResultadoDocumento.con_error(
                nombre_archivo, _mensaje_de_error_api(error), **metadatos
            )

        uso = _uso(respuesta)
        logger.info(
            "Análisis: modelo=%s entrada=%d salida=%d cache_lectura=%d cache_creacion=%d",
            self.modelo,
            uso.entrada,
            uso.salida,
            uso.cache_lectura,
            uso.cache_creacion,
        )
        metadatos["uso"] = uso
        if respuesta.stop_reason == "refusal":
            return ResultadoDocumento.con_error(
                nombre_archivo, "El modelo se negó a analizar el documento.", **metadatos
            )
        if respuesta.stop_reason == "max_tokens":
            return ResultadoDocumento.con_error(
                nombre_archivo, "La respuesta se cortó por max_tokens.", **metadatos
            )
        bloque = next(
            (b for b in respuesta.content if b.type == "tool_use" and b.name == NOMBRE_HERRAMIENTA),
            None,
        )
        if bloque is None:
            return ResultadoDocumento.con_error(
                nombre_archivo, "El modelo no usó la herramienta de resultado.", **metadatos
            )
        return interpretar_entrada(
            bloque.input, self.catalogo, nombre_archivo=nombre_archivo, **metadatos
        )
