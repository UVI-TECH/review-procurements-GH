"""Lectura y validación de un PDF antes de enviarlo a la API.

Los PDFs no son de confianza: los suben los profesores y los generan portales de
terceros. Por eso el tamaño se revisa antes de abrirlo con pypdf, y cualquier fallo de
pypdf se convierte en ErrorPdf. El tiempo límite por documento lo pone el worker
(Fase 3), para que un PDF que cuelgue a pypdf no bloquee la corrida.
"""

import io
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from pypdf import PasswordType, PdfReader

logger = logging.getLogger(__name__)


class _AvisosDePypdfEnDebug(logging.Handler):
    """pypdf avisa con logging.warning cada arreglo que hace a un PDF no conforme (p. ej.
    "Ignoring wrong pointing object"). Son normales en certificados de portales: se
    reemiten en DEBUG en este logger, en vez de salir en pantalla.
    """

    def emit(self, record):
        logger.debug("pypdf: %s", record.getMessage())


_logger_pypdf = logging.getLogger("pypdf")
if not any(isinstance(h, _AvisosDePypdfEnDebug) for h in _logger_pypdf.handlers):
    _logger_pypdf.addHandler(_AvisosDePypdfEnDebug())
_logger_pypdf.propagate = False


class ErrorPdf(Exception):
    """El archivo no se pudo leer del disco (p. ej. OneDrive aún no lo descarga).

    Es transitorio: se resuelve reanalizando.
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
    modificado_en: datetime


def leer_pdf(ruta, *, max_bytes, max_paginas):
    try:
        estado = ruta.stat()
    except OSError as error:
        raise ErrorPdf(f"No se pudo leer el archivo ({type(error).__name__}).") from None
    modificado_en = datetime.fromtimestamp(estado.st_mtime, tz=UTC)
    if estado.st_size > max_bytes:
        raise PdfIlegible(
            f"El PDF pesa {estado.st_size / 2**20:.1f} MB y el máximo es "
            f"{max_bytes / 2**20:.1f} MB: solicitar un archivo más liviano.",
            modificado_en,
        )
    try:
        datos = ruta.read_bytes()
    except OSError as error:
        raise ErrorPdf(f"No se pudo leer el archivo ({type(error).__name__}).") from None
    paginas = _contar_paginas(datos, modificado_en)
    if paginas > max_paginas:
        raise PdfIlegible(
            f"El PDF tiene {paginas} páginas y el máximo es {max_paginas}: "
            "solicitar un archivo solo con el certificado.",
            modificado_en,
        )
    if paginas == 0:
        raise PdfIlegible("El PDF no tiene páginas: solicitar un nuevo archivo.", modificado_en)
    return PdfLeido(datos=datos, paginas=paginas, modificado_en=modificado_en)


def _contar_paginas(datos, modificado_en):
    try:
        lector = PdfReader(io.BytesIO(datos), strict=False)
        if lector.is_encrypted:
            # Muchos certificados oficiales solo traen contraseña de propietario
            # (restricciones de edición o impresión) y se abren con la de usuario vacía.
            if lector.decrypt("") == PasswordType.NOT_DECRYPTED:
                raise PdfIlegible(
                    "PDF protegido con contraseña: solicitar un nuevo archivo sin contraseña.",
                    modificado_en,
                )
        return len(lector.pages)
    except PdfIlegible:
        raise
    except Exception:  # pypdf lanza muchos tipos ante archivos dañados o maliciosos
        raise PdfIlegible(
            "El archivo no es un PDF válido o está dañado: solicitar un nuevo archivo.",
            modificado_en,
        ) from None
