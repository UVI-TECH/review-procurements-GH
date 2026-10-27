"""Documentos con su análisis, creados directo en la base (sin worker), para las pruebas."""

from datetime import timedelta

from django.utils import timezone

from apps.contrataciones.models import Analisis, Documento
from apps.motor.prompts import VERSION_PROMPT
from tests.fixtures.catalogo import AFP, CODIGOS, EPS, FORMATO

CEDULA = "1000000001"


def documento(
    profesor,
    corrida,
    tipo,
    *,
    valido=True,
    cedula=CEDULA,
    nombre=None,
    sha=None,
    dias=3,
    cubre=None,
    version=VERSION_PROMPT,
):
    """dias: hace cuántos días se expidió (None: fecha que la IA no leyó).
    version: la del prompt con que se analizó (None: anterior a guardarla)."""
    nombre = nombre or f"{tipo or 'x'}.pdf"
    doc = Documento.objects.create(
        profesor=profesor,
        ruta_relativa=f"{profesor.carpeta}/{nombre}",
        nombre_archivo=nombre,
        sha256=sha or (nombre.encode().hex() * 4)[:64].ljust(64, "0"),
        tamano=100,
        modificado_en=timezone.now(),
    )
    Analisis.objects.create(
        documento=doc,
        corrida=corrida,
        sha256=doc.sha256,
        modelo="simulado",
        version_prompt=version,
        tipo_detectado=tipo,
        es_valido=valido,
        numero_documento=cedula,
        tiene_firma=True if tipo == FORMATO else None,
        fecha_expedicion=None if dias is None else timezone.localdate() - timedelta(days=dias),
        cubre=cubre if cubre is not None else {EPS: "eps", AFP: "afp"}.get(tipo, ""),
        observaciones="Error simulado." if tipo == Analisis.TIPO_ERROR else "",
    )
    return doc


def completo(profesor, corrida, **cambios):
    """Un documento por tipo; cambios: {codigo: dict de documento()} o None para omitirlo."""
    docs = {}
    for codigo in CODIGOS:
        if codigo in cambios and cambios[codigo] is None:
            continue
        docs[codigo] = documento(profesor, corrida, codigo, **cambios.get(codigo, {}))
    return docs
