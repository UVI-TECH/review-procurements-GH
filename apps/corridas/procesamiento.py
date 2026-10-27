"""El worker: toma corridas de la base de datos y las procesa documento por documento.

- Reanudación: cada Analisis se guarda en su propia transacción apenas responde la
  API. Si el proceso muere, al volver a arrancar la corrida sigue sin repetir lo que ya
  analizó (documentos_a_analizar excluye lo que tiene Analisis en esta corrida).
- Un solo worker: BloqueoWorker. Mientras lo tiene, toda corrida "en proceso" es
  huérfana por definición y se reanuda.
- Cancelación: cancelacion_solicitada se revisa entre documentos.
- Tiempo límite por documento: el inspector aislado (proceso aparte); el SDK tiene su
  propio timeout para la llamada a la API.
- Consola: id, alcance y contadores, nunca nombres de profesores ni de archivos.
- Ctrl+C (o Ctrl+Break en Windows): cierra el pool y sale con WorkerDetenido; la corrida
  queda "en proceso" y se reanuda al volver a iniciar el worker.
"""

import hashlib
import logging
import time

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.contrataciones.models import Analisis, Corrida, Documento, Profesor
from apps.contrataciones.servicios.estado import recalcular_estado, recalcular_todos
from apps.cuentas.auditoria import registrar
from apps.motor.aislamiento import InspectorAislado
from apps.motor.catalogo import cargar_catalogo
from apps.motor.fuentes import ErrorFuente
from apps.motor.prompts import VERSION_PROMPT
from apps.motor.resultado import ResultadoDocumento
from apps.motor.servicio import crear_cliente as crear_cliente_del_motor

from .bloqueo import BloqueoWorker
from .escaneo import ErrorEscaneo, escanear
from .servicios import crear_fuente, documentos_a_analizar

logger = logging.getLogger(__name__)


class WorkerDetenido(Exception):
    """Ctrl+C: el worker se detuvo limpio. corrida_id es la que queda por reanudar."""

    def __init__(self, corrida_id=None):
        super().__init__(corrida_id)
        self.corrida_id = corrida_id


RECALCULO_DIARIO_SEGUNDOS = 24 * 60 * 60


def _no_informar(mensaje):
    pass


def _miles(numero):
    return f"{numero:,}".replace(",", ".")


def siguiente_corrida():
    """Primero las huérfanas (en proceso), luego la pendiente más antigua."""
    return (
        Corrida.objects.filter(estado=Corrida.Estado.EN_PROCESO).order_by("creada_en").first()
        or Corrida.objects.filter(estado=Corrida.Estado.PENDIENTE).order_by("creada_en").first()
    )


def ejecutar_worker(
    *,
    una_vez=False,
    intervalo=None,
    fuente=None,
    crear_cliente=None,
    inspector=None,
    antes=None,
    informar=None,
    reloj=time.monotonic,
):
    """Procesa corridas hasta que no quede ninguna (una_vez) o para siempre.

    Al arrancar y cada RECALCULO_DIARIO_SEGUNDOS recalcula el estado de todos los
    profesores: la vigencia cambia con los días aunque no cambien los archivos (ADR 0006).

    antes: se llama ya con el bloqueo tomado (el comando revisa ahí las migraciones).
    informar: recibe los mensajes de progreso para la consola.
    reloj: segundos monótonos; las pruebas lo reemplazan.
    """
    intervalo = settings.WORKER_INTERVALO_SEGUNDOS if intervalo is None else intervalo
    crear_cliente = crear_cliente or crear_cliente_del_motor
    informar = informar or _no_informar
    with BloqueoWorker(settings.RUTA_BLOQUEO_WORKER):
        if antes:
            antes()
        propio = inspector is None
        inspector = inspector or InspectorAislado(settings.MOTOR_TIMEOUT_PDF_SEGUNDOS)
        actual, esperando, ultimo_recalculo = None, False, None
        try:
            while True:
                if ultimo_recalculo is None or reloj() - ultimo_recalculo >= (
                    RECALCULO_DIARIO_SEGUNDOS
                ):
                    total = recalcular_todos(cargar_catalogo())
                    informar(f"Estados recalculados por vigencia: {total} profesores.")
                    ultimo_recalculo = reloj()
                corrida = siguiente_corrida()
                if corrida is None:
                    if una_vez:
                        informar("Sin corridas pendientes.")
                        return
                    if not esperando:
                        informar("Sin corridas pendientes; esperando…")
                        esperando = True
                    time.sleep(intervalo)
                    continue
                esperando, actual = False, corrida.pk
                catalogo = cargar_catalogo()
                procesar_corrida(
                    corrida,
                    fuente=fuente or crear_fuente(),
                    cliente=crear_cliente(catalogo, inspector=inspector),
                    catalogo=catalogo,
                    informar=informar,
                )
                actual = None
        except KeyboardInterrupt:
            if propio:
                inspector.terminar()
            raise WorkerDetenido(actual) from None
        except BaseException:
            if propio:
                inspector.terminar()  # en Windows, que no quede un python.exe huérfano
            raise
        else:
            if propio:
                inspector.cerrar()


def procesar_corrida(corrida, *, fuente, cliente, catalogo, informar=None):
    informar = informar or _no_informar
    reanudada = corrida.estado == Corrida.Estado.EN_PROCESO
    informar(
        f"Corrida {corrida.pk} ({corrida.alcance})"
        f"{' reanudada' if reanudada else ''}: escaneando la carpeta…"
    )
    ahora = timezone.now()
    corrida.estado = Corrida.Estado.EN_PROCESO
    corrida.inicio = corrida.inicio or ahora
    corrida.latido = ahora
    corrida.save(update_fields=["estado", "inicio", "latido"])
    registrar(None, "corrida_reanudada" if reanudada else "corrida_iniciada", corrida)

    try:
        profesor = corrida.profesor if corrida.alcance == Corrida.Alcance.UN_PROFESOR else None
        escanear(fuente, carpeta=profesor.carpeta if profesor else None)

        pendientes = list(documentos_a_analizar(corrida.alcance, profesor, corrida))
        corrida.total_documentos = corrida.analisis.count() + len(pendientes)
        corrida.save(update_fields=["total_documentos"])
        if reanudada:
            informar(
                f"Corrida {corrida.pk} reanudada: {len(pendientes)} de "
                f"{corrida.total_documentos} documentos por analizar."
            )
        else:
            informar(f"Corrida {corrida.pk}: {corrida.total_documentos} documentos por analizar.")
        por_profesor = {}
        for documento in pendientes:
            por_profesor.setdefault(documento.profesor_id, []).append(documento)

        profesores = (
            [profesor]
            if profesor
            else Profesor.objects.filter(carpeta_presente=True).order_by("carpeta")
        )
        for actual in profesores:
            for documento in por_profesor.get(actual.pk, []):
                if Corrida.objects.filter(pk=corrida.pk, cancelacion_solicitada=True).exists():
                    _terminar(corrida, Corrida.Estado.CANCELADA, "corrida_cancelada", informar)
                    return
                _analizar_documento(corrida, documento, fuente, cliente)
                _informar_progreso(corrida, informar)
            recalcular_estado(actual, catalogo)
    except ErrorEscaneo as error:
        _terminar(corrida, Corrida.Estado.FALLIDA, "corrida_fallida", informar, str(error))
        return
    except Exception as error:
        logger.exception("La corrida %s falló", corrida.pk)
        _terminar(
            corrida,
            Corrida.Estado.FALLIDA,
            "corrida_fallida",
            informar,
            f"Error inesperado ({type(error).__name__}). Revisa el log del worker.",
        )
        return
    _terminar(corrida, Corrida.Estado.COMPLETADA, "corrida_completada", informar)


def _informar_progreso(corrida, informar):
    procesados, total, errores, entrada, salida = Corrida.objects.values_list(
        "documentos_procesados",
        "total_documentos",
        "documentos_con_error",
        "tokens_entrada",
        "tokens_salida",
    ).get(pk=corrida.pk)
    informar(
        f"Corrida {corrida.pk} · {procesados}/{total} · errores: {errores} · "
        f"tokens: entrada {_miles(entrada)}, salida {_miles(salida)}"
    )


def _terminar(corrida, estado, accion, informar, mensaje=""):
    corrida.refresh_from_db()
    corrida.estado = estado
    corrida.fin = timezone.now()
    corrida.mensaje = mensaje
    corrida.save(update_fields=["estado", "fin", "mensaje"])
    informar(
        f"Corrida {corrida.pk} {corrida.get_estado_display().lower()}: "
        f"{corrida.documentos_procesados}/{corrida.total_documentos} documentos, "
        f"{corrida.documentos_con_error} con error, tokens entrada "
        f"{_miles(corrida.tokens_entrada)}, salida {_miles(corrida.tokens_salida)}."
        + (f" {mensaje}" if mensaje else "")
    )
    registrar(
        None,
        accion,
        corrida,
        {
            "total_documentos": corrida.total_documentos,
            "documentos_procesados": corrida.documentos_procesados,
            "documentos_con_error": corrida.documentos_con_error,
            "tokens_entrada": corrida.tokens_entrada,
            "tokens_salida": corrida.tokens_salida,
            **({"mensaje": mensaje} if mensaje else {}),
        },
    )


def _analizar_documento(corrida, documento, fuente, cliente):
    try:
        datos = fuente.leer(documento.ruta_relativa)
    except ErrorFuente as error:
        sha256 = documento.sha256
        resultado = ResultadoDocumento.con_error(
            documento.nombre_archivo, str(error), modelo=cliente.modelo
        )
    else:
        sha256 = hashlib.sha256(datos).hexdigest()
        resultado = cliente.analizar_datos(
            datos,
            documento.nombre_archivo,
            documento.profesor.carpeta,
            modificado_en=documento.modificado_en,
        )

    with transaction.atomic():
        if sha256 != documento.sha256:  # el archivo cambió después del escaneo
            documento.sha256 = sha256
            documento.reintentos_agotados = False
            documento.save(update_fields=["sha256", "reintentos_agotados", "actualizado_en"])
        guardar_analisis(documento, corrida, sha256, resultado)
        _actualizar_reintentos(documento, corrida, resultado)
        uso = resultado.uso
        Corrida.objects.filter(pk=corrida.pk).update(
            documentos_procesados=F("documentos_procesados") + 1,
            documentos_con_error=F("documentos_con_error") + int(resultado.es_error),
            tokens_entrada=F("tokens_entrada") + uso.entrada,
            tokens_salida=F("tokens_salida") + uso.salida,
            latido=timezone.now(),
        )
        if resultado.es_error:
            actual = Corrida.objects.get(pk=corrida.pk)
            actual.errores = [
                *actual.errores,
                {
                    "documento": documento.pk,
                    "archivo": documento.nombre_archivo,
                    "error": resultado.error,
                },
            ]
            actual.save(update_fields=["errores"])


def guardar_analisis(documento, corrida, sha256, resultado):
    if resultado.es_error:
        tipo, observaciones = Analisis.TIPO_ERROR, resultado.error
    else:
        tipo, observaciones = resultado.tipo_detectado, resultado.observaciones
    uso = resultado.uso
    return Analisis.objects.create(
        documento=documento,
        corrida=corrida,
        sha256=sha256,
        modelo=(resultado.modelo or "")[:100],
        version_prompt=VERSION_PROMPT,
        tipo_detectado=tipo[:80],
        es_valido=False if resultado.es_error else resultado.es_valido,
        # Recortes defensivos: la IA puede devolver textos más largos que el campo.
        numero_documento=resultado.numero_documento[:30],
        nombre_persona=resultado.nombre_persona[:200],
        tiene_firma=resultado.tiene_firma,
        fecha_expedicion=resultado.fecha_expedicion,
        cubre=resultado.cubre[:5],
        tiene_logo_oficial=resultado.tiene_logo_oficial,
        es_plantilla_institucional=resultado.es_plantilla_institucional,
        datos_extra=resultado.datos_extra,
        observaciones=observaciones,
        respuesta_cruda=resultado.respuesta_cruda,
        tokens_entrada=uso.entrada,
        tokens_salida=uso.salida,
        tokens_cache_lectura=uso.cache_lectura,
        tokens_cache_creacion=uso.cache_creacion,
    )


def _actualizar_reintentos(documento, corrida, resultado):
    """Si el mismo sha256 falla de forma transitoria en 2 corridas seguidas, se marca."""
    if not resultado.es_error:
        if documento.reintentos_agotados:
            documento.reintentos_agotados = False
            documento.save(update_fields=["reintentos_agotados", "actualizado_en"])
        return
    dos_ultimos = list(
        Analisis.objects.filter(documento=documento, sha256=documento.sha256).order_by(
            "-creado_en", "-id"
        )[:2]
    )
    # Una corrida analiza cada documento una sola vez (la reanudación excluye lo ya
    # analizado), así que los dos últimos Analisis son de dos corridas distintas.
    if (
        len(dos_ultimos) == 2
        and all(a.tipo_detectado == Analisis.TIPO_ERROR for a in dos_ultimos)
        and not documento.reintentos_agotados
    ):
        Documento.objects.filter(pk=documento.pk).update(reintentos_agotados=True)
        documento.reintentos_agotados = True
        registrar(
            None,
            "reintentos_agotados",
            documento,
            {"sha256": documento.sha256, "ultimo_error": resultado.error},
        )
