from collections import Counter

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.contrataciones.models import Profesor
from apps.corridas.demo import sembrar
from apps.corridas.servicios import crear_fuente, usuario_por_nombre
from apps.motor.catalogo import cargar_catalogo
from apps.motor.servicio import exigir_migraciones


class Command(BaseCommand):
    help = (
        "Genera unos 30 profesores ficticios con PDFs sintéticos en CARPETA_CONTRATACIONES "
        "(que debe estar vacía) y los procesa con el motor simulado, para demostraciones y "
        "pruebas de usabilidad. Nunca con datos reales ni en producción."
    )

    def add_arguments(self, parser):
        parser.add_argument("--usuario", required=True, help="Quién inicia las corridas")

    def handle(self, *args, usuario, **opciones):
        if str(getattr(settings, "SETTINGS_MODULE", "")).endswith("produccion"):
            raise CommandError("sembrar_demo no corre con los settings de producción.")
        if not settings.MOTOR_SIMULADO:
            raise CommandError("sembrar_demo solo corre con MOTOR_SIMULADO=True.")
        fuente = crear_fuente()
        raiz = fuente.raiz
        if raiz.exists() and any(raiz.iterdir()):
            raise CommandError(
                f"La carpeta {raiz} no está vacía. sembrar_demo solo escribe en una carpeta "
                "vacía, para no mezclar nunca con datos reales."
            )
        exigir_migraciones()
        quien = usuario_por_nombre(usuario)
        raiz.mkdir(parents=True, exist_ok=True)
        codigos = [t.codigo for t in cargar_catalogo().activos]
        cantidad = sembrar(raiz, quien, fuente, codigos)

        self.stdout.write(f"{cantidad} profesores ficticios generados en {raiz}.")
        estados = Counter(Profesor.objects.values_list("estado", flat=True))
        for estado, total in sorted(estados.items()):
            self.stdout.write(f"  {estado}: {total}")
