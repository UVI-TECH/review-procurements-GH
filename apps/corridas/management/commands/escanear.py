from dataclasses import asdict

from django.core.management.base import BaseCommand, CommandError

from apps.corridas.escaneo import ErrorEscaneo, escanear
from apps.corridas.servicios import crear_fuente, usuario_por_nombre
from apps.motor.servicio import exigir_migraciones


class Command(BaseCommand):
    help = "Sincroniza profesores y documentos con la carpeta de Contrataciones."

    def add_arguments(self, parser):
        parser.add_argument("--profesor", help="Escanear solo la carpeta de este profesor")
        parser.add_argument(
            "--forzar",
            action="store_true",
            help="Continuar aunque desaparezcan muchas carpetas (queda en auditoría)",
        )
        parser.add_argument("--usuario", help="Quién fuerza el escaneo (para la auditoría)")

    def handle(self, *args, profesor, forzar, usuario, **opciones):
        exigir_migraciones()
        fuente = crear_fuente()
        try:
            resumen = escanear(
                fuente,
                carpeta=profesor,
                forzar=forzar,
                usuario=usuario_por_nombre(usuario) if usuario else None,
            )
        except ErrorEscaneo as error:
            raise CommandError(str(error)) from None
        for campo, valor in asdict(resumen).items():
            self.stdout.write(f"{campo.replace('_', ' ')}: {valor}")
