"""Cliente simulado: respuestas deterministas según el nombre del archivo, sin la API.

Convenciones (sobre el nombre normalizado, sin .pdf):
- El tipo es el código o alias del catálogo que aparezca (el más largo gana); si no
  aparece ninguno, "otro" e inválido.
- "cc_<dígitos>" fija la cédula; "sin_cedula" la deja vacía; si no, CEDULA_SIMULADA.
- "otra_persona": cédula de otra persona.
- "invalido": la IA lo marca inválido (p. ej. por no traer nombre).
- "sin_firma": en un tipo que exige firma, sin firma e inválido.
- "error_api": error de la API. "respuesta_malformada": respuesta fuera del esquema.
"""

import re
import time
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .cliente_base import ClienteBase
from .esquema import TIPO_OTRO, interpretar_entrada
from .reglas import norm
from .resultado import ResultadoDocumento

CEDULA_SIMULADA = "1000000001"
CEDULA_OTRA_PERSONA = "1000000099"
MODELO_SIMULADO = "simulado"


class ClienteSimulado(ClienteBase):
    modelo = MODELO_SIMULADO

    def __init__(self, catalogo, *, inspector=None):
        super().__init__(catalogo, inspector=inspector)
        self._codigos = sorted(catalogo.codigos_reconocidos, key=len, reverse=True)

    def _analizar_pdf(self, pdf, nombre_archivo, profesor):
        if settings.MOTOR_SIMULADO_PAUSA_SEGUNDOS:
            time.sleep(settings.MOTOR_SIMULADO_PAUSA_SEGUNDOS)
        metadatos = {"modificado_en": pdf.modificado_en, "modelo": self.modelo}
        nombre = norm(nombre_archivo)
        if "error_api" in nombre:
            return ResultadoDocumento.con_error(
                nombre_archivo, "Error simulado de la API.", **metadatos
            )
        entrada = self._respuesta(nombre)
        if "respuesta_malformada" in nombre:
            del entrada["es_valido"]
        return interpretar_entrada(
            entrada, self.catalogo, nombre_archivo=nombre_archivo, **metadatos
        )

    def _respuesta(self, nombre):
        codigo = next((c for c in self._codigos if c in nombre), TIPO_OTRO)
        tipo = self.catalogo.resolver(codigo)
        exige_firma = tipo is not None and tipo.requiere_firma
        sin_firma = exige_firma and "sin_firma" in nombre

        cedula = CEDULA_SIMULADA
        if "otra_persona" in nombre:
            cedula = CEDULA_OTRA_PERSONA
        elif "sin_cedula" in nombre:
            cedula = ""
        elif coincidencia := re.search(r"cc_(\d+)", nombre):
            cedula = coincidencia.group(1)

        es_valido = not (
            codigo == TIPO_OTRO or sin_firma or "invalido" in nombre or "otra_persona" in nombre
        )
        cubre = (
            {"certificado_eps": "eps", "certificado_afp": "afp"}.get(tipo.codigo) if tipo else None
        )
        # Expedido hace pocos días (America/Bogota): vigente.
        expedicion = timezone.localdate() - timedelta(days=3)
        return {
            "tipo_detectado": codigo,
            "es_valido": es_valido,
            "numero_documento": cedula,
            "nombre_persona": "Persona Ficticia" if "otra_persona" in nombre else "",
            "tiene_firma": (not sin_firma) if exige_firma else None,
            "fecha_expedicion": expedicion.isoformat(),
            "cubre": cubre,
            "tiene_logo_oficial": True,
            "es_plantilla_institucional": True if exige_firma else None,
            "observaciones": "Respuesta simulada.",
        }
