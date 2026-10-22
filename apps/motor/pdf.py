"""Lectura y validación de un PDF antes de enviarlo a la API.

Los PDFs no son de confianza: los suben los profesores y los generan portales de
terceros. Por eso el tamaño se revisa antes de abrirlo con pypdf, y cualquier fallo de
pypdf se convierte en ErrorPdf. El tiempo límite por documento lo pone el worker
(Fase 3), para que un PDF que cuelgue a pypdf no bloquee la corrida.
"""

import io
from dataclasses import dataclass
from datetime import UTC, datetime

from pypdf import PasswordType, PdfReader


class ErrorPdf(Exception):
    """El PDF no se puede enviar; el mensaje es para el revisor."""


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
    if estado.st_size > max_bytes:
        raise ErrorPdf(
            f"El PDF pesa {estado.st_size / 2**20:.1f} MB; el máximo es {max_bytes / 2**20:.1f} MB."
        )
    datos = ruta.read_bytes()
    paginas = _contar_paginas(datos)
    if paginas > max_paginas:
        raise ErrorPdf(f"El PDF tiene {paginas} páginas; el máximo es {max_paginas}.")
    if paginas == 0:
        raise ErrorPdf("El PDF no tiene páginas.")
    return PdfLeido(
        datos=datos,
        paginas=paginas,
        modificado_en=datetime.fromtimestamp(estado.st_mtime, tz=UTC),
    )


def _contar_paginas(datos):
    try:
        lector = PdfReader(io.BytesIO(datos), strict=False)
        if lector.is_encrypted:
            # Muchos certificados oficiales solo traen contraseña de propietario
            # (restricciones de edición o impresión) y se abren con la de usuario vacía.
            if lector.decrypt("") == PasswordType.NOT_DECRYPTED:
                raise ErrorPdf("El PDF pide contraseña para abrirse.")
        return len(lector.pages)
    except ErrorPdf:
        raise
    except Exception:  # pypdf lanza muchos tipos ante archivos dañados o maliciosos
        raise ErrorPdf("El archivo no es un PDF válido o está dañado.") from None
