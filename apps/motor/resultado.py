"""Estructuras de datos del motor. No dependen del ORM."""

from dataclasses import dataclass, field
from datetime import datetime

# tipo_detectado de un archivo que no se pudo analizar por un problema del propio archivo
# (contraseña, dañado, demasiado grande). No es un código del catálogo ni de la IA.
TIPO_ILEGIBLE = "ilegible"


@dataclass(frozen=True)
class Uso:
    """Tokens de una llamada; las fases siguientes los suman por corrida."""

    entrada: int = 0
    salida: int = 0
    cache_lectura: int = 0
    cache_creacion: int = 0


@dataclass(frozen=True)
class ResultadoDocumento:
    """Lo que el motor sabe de un PDF.

    Con error no vacío, el análisis falló por algo transitorio (API, red) y se resuelve
    reanalizando. Un archivo ilegible no es un error: es un problema del documento, con
    una observación que dice qué pedir.
    """

    nombre_archivo: str
    tipo_detectado: str = ""
    es_valido: bool = False
    numero_documento: str = ""
    nombre_persona: str = ""
    tiene_firma: bool | None = None
    datos_extra: dict = field(default_factory=dict)
    observaciones: str = ""
    error: str = ""
    # Un revisor lo aprobó o corrigió: es el vigente de su tipo antes que el de la IA.
    validado_por_revisor: bool = False
    modificado_en: datetime | None = None
    modelo: str = ""
    uso: Uso = field(default_factory=Uso)
    respuesta_cruda: dict = field(default_factory=dict)

    @property
    def es_error(self):
        return bool(self.error)

    @property
    def es_ilegible(self):
        return self.tipo_detectado == TIPO_ILEGIBLE

    @classmethod
    def con_error(cls, nombre_archivo, mensaje, **extra):
        return cls(nombre_archivo=nombre_archivo, es_valido=False, error=mensaje, **extra)

    @classmethod
    def ilegible(cls, nombre_archivo, observacion, **extra):
        return cls(
            nombre_archivo=nombre_archivo,
            tipo_detectado=TIPO_ILEGIBLE,
            es_valido=False,
            observaciones=observacion,
            **extra,
        )
