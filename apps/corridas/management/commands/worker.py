import signal

from django.core.management.base import BaseCommand, CommandError

from apps.corridas.bloqueo import WorkerOcupado
from apps.corridas.procesamiento import WorkerDetenido, ejecutar_worker
from apps.motor.servicio import exigir_migraciones


class Command(BaseCommand):
    help = (
        "Procesa las corridas pendientes, de una en una. Reanuda las que quedaron a mitad. "
        "Solo puede haber un worker por equipo. Ctrl+C lo detiene sin perder trabajo."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--una-vez",
            action="store_true",
            help="Termina cuando no quedan corridas, en vez de seguir esperando",
        )
        parser.add_argument("--intervalo", type=float, help="Segundos entre búsquedas")

    def informar(self, mensaje):
        self.stdout.write(mensaje)
        self.stdout.flush()

    def handle(self, *args, una_vez, intervalo, **opciones):
        if hasattr(signal, "SIGBREAK"):
            # Windows: Ctrl+Break (y el cierre de la consola) detienen igual que Ctrl+C.
            signal.signal(signal.SIGBREAK, signal.default_int_handler)
        try:
            # El bloqueo va primero: un segundo worker se niega sin tocar la base.
            ejecutar_worker(
                una_vez=una_vez,
                intervalo=intervalo,
                antes=exigir_migraciones,
                informar=self.informar,
            )
        except WorkerOcupado as error:
            raise CommandError(str(error)) from None
        except WorkerDetenido as detenido:
            if detenido.corrida_id:
                self.informar(
                    f"Worker detenido. La corrida {detenido.corrida_id} se reanudará al "
                    "volver a iniciar el worker."
                )
            else:
                self.informar("Worker detenido.")
