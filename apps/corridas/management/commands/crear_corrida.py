from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.contrataciones.models import Corrida, Profesor
from apps.corridas.escaneo import ErrorEscaneo, escanear
from apps.corridas.servicios import (
    crear_corrida,
    crear_fuente,
    documentos_a_analizar,
    estimar,
    usuario_por_nombre,
)
from apps.motor.servicio import exigir_migraciones


class Command(BaseCommand):
    help = (
        "Crea una corrida para el worker (la interfaz web llega en la Fase 4). "
        "Con --en-seco solo informa cuántos documentos analizaría y su costo estimado."
    )

    def add_arguments(self, parser):
        parser.add_argument("--alcance", required=True, choices=Corrida.Alcance.values)
        parser.add_argument("--profesor", help="Carpeta del profesor (solo con un_profesor)")
        parser.add_argument("--usuario", required=True, help="Quién inicia la corrida")
        parser.add_argument(
            "--en-seco", action="store_true", help="No crea nada: solo cuenta y estima"
        )

    def handle(self, *args, alcance, profesor, usuario, en_seco, **opciones):
        exigir_migraciones()
        if (alcance == Corrida.Alcance.UN_PROFESOR) != bool(profesor):
            raise CommandError("--profesor va solo, y siempre, con --alcance un_profesor.")
        quien = usuario_por_nombre(usuario)
        if not quien.has_perm("contrataciones.add_corrida"):
            raise CommandError(f"«{usuario}» no tiene permiso para crear corridas.")
        if en_seco:
            self._en_seco(alcance, profesor)
            return
        elegido = None
        if profesor:
            if not Profesor.objects.filter(carpeta=profesor).exists():
                self._escanear(profesor)  # carpeta aún no escaneada
            elegido = Profesor.objects.filter(carpeta=profesor, carpeta_presente=True).first()
            if elegido is None:
                raise CommandError(f"No hay un profesor presente con la carpeta «{profesor}».")
        corrida = crear_corrida(alcance, quien, elegido)
        self.stdout.write(f"Corrida {corrida.pk} creada. El worker la procesará.")

    def _escanear(self, carpeta=None):
        try:
            escanear(crear_fuente(), carpeta=carpeta)
        except ErrorEscaneo as error:
            raise CommandError(str(error)) from None

    def _en_seco(self, alcance, carpeta):
        # Escanea dentro de una transacción que se deshace: el conteo refleja el disco
        # actual y no queda nada creado ni modificado.
        with transaction.atomic():
            self._escanear(carpeta)
            profesor = Profesor.objects.filter(carpeta=carpeta).first() if carpeta else None
            estimacion = estimar(documentos_a_analizar(alcance, profesor).count())
            transaction.set_rollback(True)

        base = (
            f"promedio de {estimacion.analisis_de_referencia} análisis previos"
            if estimacion.analisis_de_referencia
            else "estimación por defecto, sin historial"
        )
        self.stdout.write(f"Documentos a analizar: {estimacion.documentos}")
        self.stdout.write(
            f"Tokens estimados: entrada {estimacion.tokens_entrada:,}, "
            f"salida {estimacion.tokens_salida:,} ({base})"
        )
        self.stdout.write(f"Costo estimado: US$ {estimacion.costo_usd:.2f}")
        self.stdout.write("En seco: no se creó ni se modificó nada.")
