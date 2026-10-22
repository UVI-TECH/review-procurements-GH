"""Lo común a los clientes real y simulado: leer y validar el PDF antes de analizarlo."""

from django.conf import settings

from .pdf import ErrorPdf, PdfIlegible, leer_pdf, leer_ruta
from .resultado import ResultadoDocumento


class ClienteBase:
    modelo = ""

    def __init__(self, catalogo, *, inspector=None):
        # inspector: abre el PDF; el worker pasa uno aislado con tiempo límite.
        self.catalogo = catalogo
        self.inspector = inspector

    def analizar(self, ruta, profesor):
        """Un archivo local (comandos de validación)."""
        try:
            datos, modificado_en = leer_ruta(ruta)
        except ErrorPdf as error:
            return ResultadoDocumento.con_error(ruta.name, str(error), modelo=self.modelo)
        return self.analizar_datos(datos, ruta.name, profesor, modificado_en=modificado_en)

    def analizar_datos(self, datos, nombre_archivo, profesor, *, modificado_en=None):
        """Bytes que vienen de una fuente (worker)."""
        try:
            pdf = leer_pdf(
                datos,
                max_bytes=settings.MOTOR_MAX_BYTES_PDF,
                max_paginas=settings.MOTOR_MAX_PAGINAS_PDF,
                modificado_en=modificado_en,
                inspector=self.inspector,
            )
        except PdfIlegible as problema:
            return ResultadoDocumento.ilegible(
                nombre_archivo, str(problema), modificado_en=modificado_en
            )
        except ErrorPdf as error:
            return ResultadoDocumento.con_error(
                nombre_archivo, str(error), modelo=self.modelo, modificado_en=modificado_en
            )
        return self._analizar_pdf(pdf, nombre_archivo, profesor)

    def _analizar_pdf(self, pdf, nombre_archivo, profesor):
        raise NotImplementedError
