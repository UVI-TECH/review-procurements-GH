"""Estado del profesor calculado desde la base de datos con las reglas del motor.

Para cada documento presente se toma el último Analisis de su sha256 actual que NO sea
error. Un error solo cuenta si no hay ningún resultado útil para ese archivo: así una
caída de la API durante un reanálisis no hace retroceder a nadie a ERROR (ADR 0004).
La capa de revisiones humanas se suma en la Fase 4.
"""

from apps.motor.reglas import evaluar_profesor, revalidar_por_cedula
from apps.motor.resultado import ResultadoDocumento

from ..models import Analisis


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
        datos_extra=analisis.datos_extra,
        observaciones=analisis.observaciones,
        modificado_en=documento.modificado_en,
        modelo=analisis.modelo,
    )


def resultados_actuales(profesor):
    documentos = list(profesor.documentos.filter(presente=True).order_by("ruta_relativa"))
    por_documento = {}
    for analisis in Analisis.objects.filter(documento__in=documentos).order_by("-creado_en", "-id"):
        por_documento.setdefault(analisis.documento_id, []).append(analisis)

    resultados = []
    for documento in documentos:
        del_archivo_actual = [
            a for a in por_documento.get(documento.pk, []) if a.sha256 == documento.sha256
        ]
        util = next(
            (a for a in del_archivo_actual if a.tipo_detectado != Analisis.TIPO_ERROR), None
        )
        elegido = util or (del_archivo_actual[0] if del_archivo_actual else None)
        if elegido is None:
            resultados.append(
                ResultadoDocumento.con_error(
                    documento.nombre_archivo,
                    "Pendiente de análisis.",
                    modificado_en=documento.modificado_en,
                )
            )
        else:
            resultados.append(resultado_de_analisis(elegido, documento))
    return resultados


def recalcular_estado(profesor, catalogo):
    revalidados = revalidar_por_cedula(resultados_actuales(profesor), catalogo)
    evaluacion = evaluar_profesor(revalidados, catalogo)
    profesor.estado = evaluacion.estado.value
    profesor.cedula = evaluacion.cedula or ""
    profesor.save(update_fields=["estado", "cedula", "actualizado_en"])
    return evaluacion
