from django.core.management.base import BaseCommand, CommandError

from apps.corridas.bloqueo import WorkerOcupado
from apps.corridas.procesamiento import ejecutar_worker
from apps.motor.servicio import exigir_migraciones


class Command(BaseCommand):
    help = (
        "Procesa las corridas pendientes, de una en una. Reanuda las que quedaron a mitad. "
        "Solo puede haber un worker por equipo."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--una-vez",
            action="store_true",
            help="Termina cuando no quedan corridas, en vez de seguir esperando",
        )
        parser.add_argument("--intervalo", type=float, help="Segundos entre búsquedas")

    def handle(self, *args, una_vez, intervalo, **opciones):
        try:
            # El bloqueo va primero: un segundo worker se niega sin tocar la base.
            ejecutar_worker(una_vez=una_vez, intervalo=intervalo, antes=exigir_migraciones)
        except WorkerOcupado as error:
            raise CommandError(str(error)) from None
