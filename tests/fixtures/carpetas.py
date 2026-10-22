"""Carpeta de Contrataciones sintética: una subcarpeta por profesor ficticio."""

from tests.fixtures.catalogo import CODIGOS
from tests.fixtures.pdfs import crear_pdf


def crear_profesor(raiz, carpeta, archivos=None):
    """Por defecto, un PDF por cada tipo del catálogo (el simulado lo da por COMPLETO)."""
    destino = raiz / carpeta
    destino.mkdir(parents=True, exist_ok=True)
    for archivo in archivos if archivos is not None else [f"{c}.pdf" for c in CODIGOS]:
        crear_pdf(destino / archivo, marca=f"{carpeta}/{archivo}")
    return destino
