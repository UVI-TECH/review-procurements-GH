from django.core.management.base import BaseCommand, CommandError

from apps.contrataciones.models import Corrida
from apps.corridas.servicios import solicitar_cancelacion, usuario_por_nombre


class Command(BaseCommand):
    help = "Pide cancelar una corrida. Si está en proceso, el worker la detiene entre documentos."

    def add_arguments(self, parser):
        parser.add_argument("corrida", type=int)
        parser.add_argument("--usuario", required=True, help="Quién la cancela")

    def handle(self, *args, corrida, usuario, **opciones):
        quien = usuario_por_nombre(usuario)
        if not quien.has_perm("contrataciones.cancelar_corrida"):
            raise CommandError(f"«{usuario}» no tiene permiso para cancelar corridas.")
        try:
            solicitud = Corrida.objects.get(pk=corrida)
        except Corrida.DoesNotExist:
            raise CommandError(f"No existe la corrida {corrida}.") from None
        try:
            solicitar_cancelacion(solicitud, quien)
        except ValueError as error:
            raise CommandError(str(error)) from None
        self.stdout.write(f"Cancelación de la corrida {corrida} solicitada.")
