import json
import os
import time
from pathlib import Path

import anthropic
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.motor.catalogo import cargar_catalogo
from apps.motor.cliente_claude import ClienteClaude
from apps.motor.comparacion import (
    cargar_legado,
    comparar_profesor,
    resumir,
    validar_ruta_salida,
)
from apps.motor.servicio import exigir_api_real, exigir_migraciones, listar_pdfs


class _ContadorDeTokens:
    """Envuelve client.messages del legado para sumar sus tokens sin modificarlo."""

    def __init__(self, cliente):
        self._cliente = cliente
        self.entrada = 0
        self.salida = 0
        self.messages = self

    def create(self, **kwargs):
        respuesta = self._cliente.messages.create(**kwargs)
        self.entrada += respuesta.usage.input_tokens or 0
        self.salida += respuesta.usage.output_tokens or 0
        return respuesta


class Command(BaseCommand):
    help = (
        "Corre el motor del legado y el nuevo sobre los mismos profesores y compara los "
        "resultados. Lo ejecuta John en su terminal; gasta tokens de los dos motores. "
        "El informe detallado (con datos reales) va a --salida, fuera del repositorio; "
        "en pantalla solo salen conteos."
    )

    def add_arguments(self, parser):
        parser.add_argument("carpeta", help="Carpeta raíz con una subcarpeta por profesor")
        parser.add_argument("--limite", type=int, required=True, help="Cuántos profesores comparar")
        parser.add_argument(
            "--salida", required=True, help="Ruta del informe JSON, fuera del repositorio"
        )

    def handle(self, *args, carpeta, limite, salida, **opciones):
        exigir_api_real()
        raiz = Path(carpeta).expanduser()
        if not raiz.is_dir():
            raise CommandError(f"No existe la carpeta: {raiz}")
        if limite < 1:
            raise CommandError("--limite debe ser al menos 1.")
        ruta_salida = validar_ruta_salida(salida)
        exigir_migraciones()

        catalogo = cargar_catalogo()
        cliente_nuevo = ClienteClaude(catalogo)
        legado = cargar_legado()
        contador = _ContadorDeTokens(anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"]))
        legado.client = contador
        pausa = settings.MOTOR_PAUSA_ENTRE_LLAMADAS

        informes = []
        tokens_nuevo = {"entrada": 0, "salida": 0, "cache_lectura": 0, "cache_creacion": 0}
        profesores = sorted(c for c in raiz.iterdir() if c.is_dir())[:limite]
        for indice, carpeta_profesor in enumerate(profesores, start=1):
            self.stdout.write(f"[{indice}/{len(profesores)}] analizando…")
            pdfs = listar_pdfs(carpeta_profesor)
            viejos, nuevos = [], []
            for pdf in pdfs:
                viejos.append(legado.analizar_con_reintentos(pdf, carpeta_profesor.name))
                time.sleep(pausa)
                nuevo = cliente_nuevo.analizar(pdf, carpeta_profesor.name)
                nuevos.append(nuevo)
                for campo in tokens_nuevo:
                    tokens_nuevo[campo] += getattr(nuevo.uso, campo)
                time.sleep(pausa)
            informes.append(
                comparar_profesor(carpeta_profesor.name, viejos, nuevos, catalogo, legado)
            )

        resumen = {
            **resumir(informes),
            "tokens_legado": {"entrada": contador.entrada, "salida": contador.salida},
            "tokens_nuevo": tokens_nuevo,
        }
        ruta_salida.write_text(
            json.dumps(
                {"resumen": resumen, "profesores": informes},
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

        for clave, valor in resumen.items():
            self.stdout.write(f"{clave}: {valor}")
        self.stdout.write(f"Informe detallado: {ruta_salida}")
