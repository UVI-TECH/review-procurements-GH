from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.motor.catalogo import cargar_catalogo
from apps.motor.cliente_claude import ClienteClaude
from apps.motor.servicio import exigir_api_real, exigir_migraciones


class Command(BaseCommand):
    help = (
        "Analiza un solo PDF con la API real de Claude y muestra el resultado. "
        "Lo ejecuta John en su terminal; gasta tokens."
    )

    def add_arguments(self, parser):
        parser.add_argument("ruta", help="Ruta del PDF")
        parser.add_argument(
            "--profesor", help="Nombre de la carpeta del profesor (por defecto, la del PDF)"
        )

    def handle(self, *args, ruta, profesor, **opciones):
        exigir_api_real()
        ruta = Path(ruta).expanduser()
        if not ruta.is_file():
            raise CommandError(f"No existe el archivo: {ruta}")
        exigir_migraciones()

        cliente = ClienteClaude(cargar_catalogo())
        resultado = cliente.analizar(ruta, profesor or ruta.parent.name)

        filas = [
            ("Archivo", resultado.nombre_archivo),
            ("Modelo", resultado.modelo),
        ]
        if resultado.es_error:
            filas.append(("ERROR", resultado.error))
        else:
            filas += [
                ("Tipo detectado", resultado.tipo_detectado),
                ("Es válido", resultado.es_valido),
                ("Número de documento", resultado.numero_documento),
                ("Nombre", resultado.nombre_persona),
                ("Firma", resultado.tiene_firma),
                ("Fecha de expedición", resultado.fecha_expedicion),
                ("Cubre", resultado.cubre or "—"),
                ("Logo oficial", resultado.tiene_logo_oficial),
                ("Plantilla institucional", resultado.es_plantilla_institucional),
                ("Observaciones", resultado.observaciones),
            ]
        uso = resultado.uso
        filas.append(
            (
                "Tokens",
                f"entrada {uso.entrada}, salida {uso.salida}, "
                f"caché leída {uso.cache_lectura}, caché creada {uso.cache_creacion}",
            )
        )
        for etiqueta, valor in filas:
            self.stdout.write(f"{etiqueta}: {valor}")
