"""Estado del profesor calculado desde la base de datos con las reglas del motor.

Para cada documento presente:
- Resultado de la IA: el último Analisis de su sha256 actual que NO sea error. Un error
  solo cuenta si no hay ningún resultado útil para ese archivo (ADR 0004).
- Revisión vigente: la última Revision cuyo analisis.sha256 coincide con el sha256
  actual del documento (ADR 0002). Si el archivo cambió, la revisión deja de aplicar.
- Resultado efectivo: la revisión prevalece sobre la IA y sobre la regla de la cédula
  (ADR 0005). Aprobado y corregido son válidos; rechazado, inválido; descartado no cuenta
  para nada.

La cédula modal y la ambigüedad se calculan sin los documentos rechazados ni
descartados; si un revisor confirmó la cédula, se compara contra ella.
"""

import hashlib
from dataclasses import dataclass, replace

from django.db.models import Exists, F, OuterRef, Q
from django.utils import timezone

from apps.motor.prompts import VERSION_PROMPT
from apps.motor.reglas import (
    EstadoProfesor,
    aplicar_vigencia,
    evaluar_profesor,
    revalidar_por_cedula,
)
from apps.motor.resultado import ResultadoDocumento

from ..models import Analisis, Documento, Profesor, Revision

Decision = Revision.Decision


@dataclass(frozen=True)
class DocumentoEvaluado:
    documento: Documento
    analisis: Analisis | None  # el que cuenta (útil, o el último error); None = pendiente
    revision: Revision | None  # la vigente
    resultado_ia: ResultadoDocumento  # tras la revalidación por cédula
    resultado: ResultadoDocumento | None  # efectivo; None si está descartado


def resultado_de_analisis(analisis, documento):
    if analisis.tipo_detectado == Analisis.TIPO_ERROR:
        return ResultadoDocumento.con_error(
            documento.nombre_archivo,
            analisis.observaciones or "Error al analizar.",
            modificado_en=documento.modificado_en,
            modelo=analisis.modelo,
        )
    return ResultadoDocumento(
        nombre_archivo=documento.nombre_archivo,
        tipo_detectado=analisis.tipo_detectado,
        es_valido=bool(analisis.es_valido),
        numero_documento=analisis.numero_documento,
        nombre_persona=analisis.nombre_persona,
        tiene_firma=analisis.tiene_firma,
        fecha_expedicion=analisis.fecha_expedicion,
        cubre=analisis.cubre,
        tiene_logo_oficial=analisis.tiene_logo_oficial,
        es_plantilla_institucional=analisis.es_plantilla_institucional,
        datos_extra=analisis.datos_extra,
        observaciones=analisis.observaciones,
        modificado_en=documento.modificado_en,
        modelo=analisis.modelo,
        # Un ilegible lo decide el lector de PDF, no el prompt: nunca está desactualizado.
        desactualizado=analisis.tipo_detectado != Analisis.TIPO_ILEGIBLE
        and (analisis.version_prompt or 0) < VERSION_PROMPT,
    )


def _efectivo(resultado, revision):
    if revision is None:
        return resultado
    if revision.decision == Decision.DESCARTADO:
        return None
    if revision.decision == Decision.RECHAZADO:
        return replace(resultado, es_valido=False, error="")
    tipo = (
        revision.tipo_corregido.codigo
        if revision.decision == Decision.CORREGIDO
        else resultado.tipo_detectado
    )
    return replace(
        resultado, tipo_detectado=tipo, es_valido=True, error="", validado_por_revisor=True
    )


def _documentos_presentes(profesor):
    """(documento, analisis que cuenta, revisión vigente) de cada documento presente."""
    documentos = list(profesor.documentos.filter(presente=True).order_by("ruta_relativa"))
    analisis = {}
    for a in Analisis.objects.filter(documento__in=documentos).order_by("-creado_en", "-id"):
        analisis.setdefault(a.documento_id, []).append(a)
    revisiones = {}
    for r in (
        Revision.objects.filter(analisis__documento__in=documentos)
        .select_related("analisis", "tipo_corregido", "usuario")
        .order_by("-fecha", "-id")
    ):
        revisiones.setdefault(r.analisis.documento_id, []).append(r)

    filas = []
    for documento in documentos:
        actuales = [a for a in analisis.get(documento.pk, []) if a.sha256 == documento.sha256]
        util = next((a for a in actuales if a.tipo_detectado != Analisis.TIPO_ERROR), None)
        revision = next(
            (r for r in revisiones.get(documento.pk, []) if r.analisis.sha256 == documento.sha256),
            None,
        )
        filas.append((documento, util or (actuales[0] if actuales else None), revision))
    return filas


def hoy():
    """Fecha de referencia de la vigencia: hoy en America/Bogota (TIME_ZONE, ADR 0006)."""
    return timezone.localdate()


def evaluar(profesor, catalogo):
    """(EvaluacionProfesor, [DocumentoEvaluado]) del profesor, con las revisiones."""
    filas = _documentos_presentes(profesor)
    ia = [
        resultado_de_analisis(analisis, documento)
        if analisis
        else ResultadoDocumento.pendiente_de_analisis(
            documento.nombre_archivo, modificado_en=documento.modificado_en
        )
        for documento, analisis, _ in filas
    ]
    # Rechazados y descartados no son evidencia confiable de la identidad del profesor.
    no_vota = {Decision.RECHAZADO, Decision.DESCARTADO}
    evidencia = [
        resultado
        for resultado, (_, _, revision) in zip(ia, filas, strict=True)
        if revision is None or revision.decision not in no_vota
    ]
    confirmada = profesor.cedula_confirmada or None
    # La vigencia va después de la cédula: si no, la cédula rescataría a un vencido.
    revalidados = aplicar_vigencia(
        revalidar_por_cedula(ia, catalogo, cedula_confirmada=confirmada, evidencia=evidencia),
        catalogo,
        hoy(),
    )
    evaluados = [
        DocumentoEvaluado(documento, analisis, revision, resultado, _efectivo(resultado, revision))
        for resultado, (documento, analisis, revision) in zip(revalidados, filas, strict=True)
    ]
    evaluacion = evaluar_profesor(
        [e.resultado for e in evaluados if e.resultado is not None],
        catalogo,
        cedula_confirmada=confirmada,
        evidencia=[
            e.resultado
            for e in evaluados
            if e.resultado is not None
            and (e.revision is None or e.revision.decision != Decision.RECHAZADO)
        ],
    )
    return evaluacion, evaluados


def calcular_huella(profesor, filas=None):
    """Huella de (ruta, sha256, revisión vigente) de los presentes y la cédula confirmada."""
    filas = filas if filas is not None else _documentos_presentes(profesor)
    lineas = sorted(
        f"{documento.ruta_relativa}|{documento.sha256}|"
        f"{revision.pk if revision else 'sin revisión'}"
        for documento, _, revision in filas
    )
    lineas.append(f"cedula confirmada|{profesor.cedula_confirmada}")
    return hashlib.sha256("\n".join(lineas).encode()).hexdigest()


def actualizar_huella(profesor):
    """Para el escaneo: cambiaron los archivos, aunque aún no haya análisis nuevos."""
    profesor.huella_actual = calcular_huella(profesor)
    profesor.save(update_fields=["huella_actual", "actualizado_en"])


def _resumen(evaluacion, catalogo):
    tipos = {}
    for tipo in catalogo.activos:
        vigente = evaluacion.vigentes.get(tipo.codigo)
        if vigente is None:
            tipos[tipo.codigo] = "faltante" if tipo.obligatorio else "ausente"
        else:
            tipos[tipo.codigo] = "valido" if vigente.es_valido else "invalido"
    return {"tipos": tipos}


def recalcular_estado(profesor, catalogo):
    evaluacion, evaluados = evaluar(profesor, catalogo)
    profesor.estado = evaluacion.estado.value
    profesor.cedula = evaluacion.cedula or ""
    profesor.huella_actual = calcular_huella(
        profesor, [(e.documento, e.analisis, e.revision) for e in evaluados]
    )
    profesor.resumen = _resumen(evaluacion, catalogo)
    profesor.requiere_atencion = bool(
        evaluacion.ilegibles
        or evaluacion.cedula_ambigua
        or evaluacion.fechas_sin_leer
        or evaluacion.formatos_sin_cedula
        or any(e.documento.reintentos_agotados for e in evaluados)
    )
    profesor.save(
        update_fields=[
            "estado",
            "cedula",
            "huella_actual",
            "resumen",
            "requiere_atencion",
            "actualizado_en",
        ]
    )
    return evaluacion


def filtrar_por_verificacion(profesores, valor):
    """pendiente, vigente (huella igual y COMPLETO) o desactualizada."""
    vigente = Q(
        verificado_por__isnull=False,
        verificado_huella=F("huella_actual"),
        estado=EstadoProfesor.COMPLETO,
    )
    if valor == "pendiente":
        return profesores.filter(verificado_por__isnull=True)
    if valor == "vigente":
        return profesores.filter(vigente)
    if valor == "desactualizada":
        return profesores.filter(verificado_por__isnull=False).exclude(vigente)
    return profesores


def recalcular_todos(catalogo):
    """Recalcula el estado de los profesores presentes. La vigencia cambia con los días
    aunque no cambien los archivos: el worker lo llama al arrancar y cada 24 h (ADR 0006).
    Una carpeta que desapareció conserva su último estado (ADR 0004)."""
    profesores = Profesor.objects.filter(carpeta_presente=True)
    for profesor in profesores:
        recalcular_estado(profesor, catalogo)
    return profesores.count()


def analisis_desactualizado():
    """Condición sobre Documento: su análisis vigente es de una versión anterior del prompt.

    Tiene un resultado útil (no error) para su sha256 actual, ninguno con la versión actual,
    y no es ilegible (ese lo decide el lector de PDF, no el prompt). Un documento sin
    análisis no está desactualizado: está pendiente (ADR 0005). Lo usan el tablero y la
    corrida "desactualizados" (ADR 0006).
    """
    utiles = Analisis.objects.filter(documento=OuterRef("pk"), sha256=OuterRef("sha256")).exclude(
        tipo_detectado=Analisis.TIPO_ERROR
    )
    return (
        Exists(utiles)
        & ~Exists(utiles.filter(version_prompt=VERSION_PROMPT))
        & ~Exists(utiles.filter(tipo_detectado=Analisis.TIPO_ILEGIBLE))
    )


def documentos_desactualizados():
    """Documentos presentes, de carpetas presentes, con el análisis desactualizado."""
    return Documento.objects.filter(presente=True, profesor__carpeta_presente=True).filter(
        analisis_desactualizado()
    )
