"""Inspección de un PDF con pypdf, pensada para correr en un proceso aparte.

Función pura: recibe bytes y devuelve tipos simples. No importa nada de Django ni de
la app, porque con spawn (Windows) el proceso hijo importa este módulo desde cero.
"""

import io
import logging

from pypdf import PasswordType, PdfReader

OK = "ok"
REQUIERE_CONTRASENA = "requiere_contrasena"
DANADO = "danado"


class _Avisos(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.mensajes = []

    def emit(self, record):
        self.mensajes.append(record.getMessage())


def inspeccionar(datos):
    """Devuelve (páginas | None, estado, avisos de pypdf)."""
    logger = logging.getLogger("pypdf")
    avisos, propagaba = _Avisos(), logger.propagate
    logger.addHandler(avisos)
    logger.propagate = False  # los avisos vuelven al proceso padre, no a la consola
    try:
        lector = PdfReader(io.BytesIO(datos), strict=False)
        if lector.is_encrypted:
            # Muchos certificados oficiales solo traen contraseña de propietario
            # (restricciones de edición o impresión) y se abren con la de usuario vacía.
            if lector.decrypt("") == PasswordType.NOT_DECRYPTED:
                return None, REQUIERE_CONTRASENA, avisos.mensajes
        return len(lector.pages), OK, avisos.mensajes
    except Exception:  # pypdf lanza muchos tipos ante archivos dañados o maliciosos
        return None, DANADO, avisos.mensajes
    finally:
        logger.removeHandler(avisos)
        logger.propagate = propagaba
