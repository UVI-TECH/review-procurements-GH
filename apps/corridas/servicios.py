"""Crear, seleccionar, estimar y cancelar corridas. El worker está en procesamiento.py."""

from dataclasses import dataclass

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import CommandError
from django.db.models import Avg, Exists, OuterRef
from django.utils import timezone

from apps.contrataciones.models import Analisis, Corrida, Documento
from apps.contrataciones.servicios.estado import analisis_desactualizado
from apps.cuentas.auditoria import registrar
from apps.motor.fuentes import FuenteCarpetaLocal


def crear_fuente():
    if not settings.CARPETA_CONTRATACIONES:
        raise CommandError(
            "Define CARPETA_CONTRATACIONES en el archivo de entorno (ver .env.example)."
        )
    return FuenteCarpetaLocal(settings.CARPETA_CONTRATACIONES)


def usuario_por_nombre(nombre):
    try:
        return get_user_model().objects.get(username=nombre)
    except get_user_model().DoesNotExist:
        raise CommandError(f"No existe el usuario «{nombre}».") from None


def documentos_a_analizar(alcance, profesor=None, corrida=None):
    """Documentos que la corrida analizaría, en orden de profesor y ruta.

    - todos: los presentes, salvo los de reintentos agotados.
    - nuevos_y_modificados: además, solo los cuyo sha256 actual no tiene ningún
      Analisis exitoso o ilegible (un error no cuenta: se reintenta).
    - un_profesor: todos los del profesor, incluidos los de reintentos agotados
      (es la vía manual para volver a probar).
    - desactualizados: solo los cuyo análisis vigente es de una versión anterior del
      prompt (ADR 0006); así un cambio de prompt no obliga a reanalizar todo.
    Con una corrida, se excluye lo que ya analizó (reanudación).
    """
    documentos = Documento.objects.filter(presente=True, profesor__carpeta_presente=True)
    if alcance == Corrida.Alcance.UN_PROFESOR:
        documentos = documentos.filter(profesor=profesor)
    else:
        documentos = documentos.exclude(reintentos_agotados=True)
    if alcance == Corrida.Alcance.DESACTUALIZADOS:
        documentos = documentos.filter(analisis_desactualizado())
    if alcance == Corrida.Alcance.NUEVOS_Y_MODIFICADOS:
        con_resultado = Analisis.objects.filter(
            documento=OuterRef("pk"), sha256=OuterRef("sha256")
        ).exclude(tipo_detectado=Analisis.TIPO_ERROR)
        documentos = documentos.exclude(Exists(con_resultado))
    if corrida is not None:
        documentos = documentos.exclude(
            Exists(Analisis.objects.filter(documento=OuterRef("pk"), corrida=corrida))
        )
    return documentos.select_related("profesor").order_by("profesor__carpeta", "ruta_relativa")


@dataclass(frozen=True)
class Estimacion:
    documentos: int
    tokens_entrada: int
    tokens_salida: int
    costo_usd: float
    analisis_de_referencia: int  # 0 = sin historial, se usó la estimación por defecto


def estimar(cantidad):
    historial = Analisis.objects.filter(tokens_entrada__gt=0)
    promedios = historial.aggregate(entrada=Avg("tokens_entrada"), salida=Avg("tokens_salida"))
    referencia = historial.count()
    entrada = promedios["entrada"] or settings.MOTOR_TOKENS_ESTIMADOS_ENTRADA
    salida = promedios["salida"] or settings.MOTOR_TOKENS_ESTIMADOS_SALIDA
    tokens_entrada, tokens_salida = round(entrada * cantidad), round(salida * cantidad)
    costo = (
        tokens_entrada * settings.MOTOR_PRECIO_ENTRADA_MTOK
        + tokens_salida * settings.MOTOR_PRECIO_SALIDA_MTOK
    ) / 1_000_000
    return Estimacion(cantidad, tokens_entrada, tokens_salida, costo, referencia)


def crear_corrida(alcance, usuario, profesor=None):
    corrida = Corrida.objects.create(iniciada_por=usuario, alcance=alcance, profesor=profesor)
    registrar(usuario, "corrida_creada", corrida, {"alcance": alcance})
    return corrida


def solicitar_cancelacion(corrida, usuario):
    """Pendiente: se cancela ya. En proceso: el worker la cancela entre documentos."""
    if corrida.estado not in (Corrida.Estado.PENDIENTE, Corrida.Estado.EN_PROCESO):
        raise ValueError(f"La corrida ya está {corrida.get_estado_display().lower()}.")
    corrida.cancelacion_solicitada = True
    corrida.cancelacion_solicitada_por = usuario
    corrida.cancelacion_solicitada_en = timezone.now()
    campos = ["cancelacion_solicitada", "cancelacion_solicitada_por", "cancelacion_solicitada_en"]
    registrar(usuario, "cancelacion_solicitada", corrida)
    if corrida.estado == Corrida.Estado.PENDIENTE:
        corrida.estado = Corrida.Estado.CANCELADA
        corrida.fin = timezone.now()
        campos += ["estado", "fin"]
        registrar(usuario, "corrida_cancelada", corrida)
    corrida.save(update_fields=campos)
