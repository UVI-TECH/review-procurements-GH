"""Validación de un PDF antes de enviarlo a la API.

Los PDFs no son de confianza: los suben los profesores y los generan portales de
terceros. Por eso el tamaño se revisa antes de abrirlo con pypdf, y la apertura la
hace un inspector: en proceso (lector_pdf.inspeccionar) o, en el worker, en un proceso
aparte con tiempo límite (aislamiento.InspectorAislado).
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from . import lector_pdf

logger = logging.getLogger(__name__)


class ErrorPdf(Exception):
    """Fallo transitorio: el archivo no se pudo leer del disco (p. ej. OneDrive aún no lo
    descarga) o pypdf tardó demasiado en abrirlo. Se resuelve reanalizando.
    """


class PdfIlegible(Exception):
    """Problema permanente del documento; el mensaje dice qué pedir al profesor."""

    def __init__(self, mensaje, modificado_en=None):
        super().__init__(mensaje)
        self.modificado_en = modificado_en


@dataclass(frozen=True)
class PdfLeido:
    datos: bytes
    paginas: int
    modificado_en: datetime | None


def leer_ruta(ruta):
    """Bytes y fecha de modificación de un archivo local (comandos de validación)."""
    try:
        estado = ruta.stat()
        return ruta.read_bytes(), datetime.fromtimestamp(estado.st_mtime, tz=UTC)
    except OSError as error:
        raise ErrorPdf(f"No se pudo leer el archivo ({type(error).__name__}).") from None


def leer_pdf(datos, *, max_bytes, max_paginas, modificado_en=None, inspector=None):
    if len(datos) > max_bytes:
        raise PdfIlegible(
            f"El PDF pesa {len(datos) / 2**20:.1f} MB y el máximo es "
            f"{max_bytes / 2**20:.1f} MB: solicitar un archivo más liviano.",
            modificado_en,
        )
    try:
        paginas, estado, avisos = (inspector or lector_pdf.inspeccionar)(datos)
    except TimeoutError as error:
        raise ErrorPdf(str(error)) from None
    # Avisos como "Ignoring wrong pointing object" son normales en certificados de
    # portales: van al log en DEBUG, no a la pantalla.
    for aviso in avisos:
        logger.debug("pypdf: %s", aviso)
    if estado == lector_pdf.REQUIERE_CONTRASENA:
        raise PdfIlegible(
            "PDF protegido con contraseña: solicitar un nuevo archivo sin contraseña.",
            modificado_en,
        )
    if estado != lector_pdf.OK:
        raise PdfIlegible(
            "El archivo no es un PDF válido o está dañado: solicitar un nuevo archivo.",
            modificado_en,
        )
    if paginas > max_paginas:
        raise PdfIlegible(
            f"El PDF tiene {paginas} páginas y el máximo es {max_paginas}: "
            "solicitar un archivo solo con el certificado.",
            modificado_en,
        )
    if paginas == 0:
        raise PdfIlegible("El PDF no tiene páginas: solicitar un nuevo archivo.", modificado_en)
    return PdfLeido(datos=datos, paginas=paginas, modificado_en=modificado_en)
