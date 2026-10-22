"""Punto de entrada del motor: elige el cliente y analiza la carpeta de un profesor."""

import time
from dataclasses import dataclass

from django.conf import settings
from django.core.management import CommandError
from django.db import DEFAULT_DB_ALIAS, connections
from django.db.migrations.executor import MigrationExecutor

from .reglas import evaluar_profesor, revalidar_por_cedula


def crear_cliente(catalogo, *, inspector=None):
    """Simulado en desarrollo y pruebas; el real solo con MOTOR_SIMULADO=False."""
    if settings.MOTOR_SIMULADO:
        from .simulado import ClienteSimulado

        return ClienteSimulado(catalogo, inspector=inspector)
    from .cliente_claude import ClienteClaude

    return ClienteClaude(catalogo, inspector=inspector)


def exigir_api_real():
    """Para los comandos que gastan tokens: nunca con settings de pruebas ni simulado."""
    if settings.ES_ENTORNO_DE_PRUEBAS:
        raise CommandError("Este comando no corre con los settings de pruebas.")
    if settings.MOTOR_SIMULADO:
        raise CommandError("Este comando usa la API real: pon MOTOR_SIMULADO=False en el .env.")


def hay_migraciones_pendientes():
    executor = MigrationExecutor(connections[DEFAULT_DB_ALIAS])
    return bool(executor.migration_plan(executor.loader.graph.leaf_nodes()))


def exigir_migraciones():
    """El catálogo sale de la base de datos: sin migraciones no hay tablas."""
    if hay_migraciones_pendientes():
        raise CommandError(
            "Faltan migraciones en la base de datos. Ejecuta manage.py migrate primero."
        )


def listar_pdfs(carpeta):
    return sorted(p for p in carpeta.iterdir() if p.is_file() and p.suffix.lower() == ".pdf")


@dataclass(frozen=True)
class ResultadoProfesor:
    carpeta: str
    documentos: tuple  # ResultadoDocumento ya revalidados por cédula
    evaluacion: object  # reglas.EvaluacionProfesor


def analizar_carpeta(cliente, carpeta, catalogo, pausa=0.0):
    resultados = []
    for indice, pdf in enumerate(listar_pdfs(carpeta)):
        if indice and pausa:
            time.sleep(pausa)
        resultados.append(cliente.analizar(pdf, carpeta.name))
    revalidados = revalidar_por_cedula(resultados, catalogo)
    return ResultadoProfesor(
        carpeta=carpeta.name,
        documentos=tuple(revalidados),
        evaluacion=evaluar_profesor(revalidados, catalogo),
    )
