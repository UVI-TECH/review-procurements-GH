"""Estructuras de datos del motor. No dependen del ORM."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class Uso:
    """Tokens de una llamada; las fases siguientes los suman por corrida."""

    entrada: int = 0
    salida: int = 0
    cache_lectura: int = 0
    cache_creacion: int = 0


@dataclass(frozen=True)
class ResultadoDocumento:
    """Lo que el motor sabe de un PDF. Con error no vacío, el análisis no sirvió."""

    nombre_archivo: str
    tipo_detectado: str = ""
    es_valido: bool = False
    numero_documento: str = ""
    nombre_persona: str = ""
    tiene_firma: bool | None = None
    datos_extra: dict = field(default_factory=dict)
    observaciones: str = ""
    error: str = ""
    modificado_en: datetime | None = None
    modelo: str = ""
    uso: Uso = field(default_factory=Uso)
    respuesta_cruda: dict = field(default_factory=dict)

    @property
    def es_error(self):
        return bool(self.error)

    @classmethod
    def con_error(cls, nombre_archivo, mensaje, **extra):
        return cls(nombre_archivo=nombre_archivo, es_valido=False, error=mensaje, **extra)
