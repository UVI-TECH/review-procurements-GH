"""Reglas puras: port de legado/revisar_contrataciones.py y evaluación del profesor.

Las diferencias intencionales frente al legado están en docs/decisiones/0003.
Ninguna función modifica su entrada.
"""

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, replace
from datetime import timedelta
from enum import StrEnum

OBS_CEDULA_AMBIGUA = "Cédula ambigua: requiere revisión humana. "

# Un PDF de EPS o de pensión con cubre="ambos" cumple los dos requisitos (ADR 0006).
EPS = "certificado_eps"
AFP = "certificado_afp"
DIAS_AVISO_POR_VENCER = 7


class EstadoProfesor(StrEnum):
    """Mismos valores que contrataciones.models.EstadoProfesor, sin depender del ORM."""

    SIN_ANALIZAR = "SIN_ANALIZAR"
    COMPLETO = "COMPLETO"
    INCOMPLETO = "INCOMPLETO"
    CON_PROBLEMAS = "CON_PROBLEMAS"
    SIN_DOCUMENTOS = "SIN_DOCUMENTOS"
    PENDIENTE_ANALISIS = "PENDIENTE_ANALISIS"
    ERROR = "ERROR"


def norm(texto):
    texto = (texto or "").lower().strip()
    texto = "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )
    texto = re.sub(r"\.pdf$", "", texto)
    return re.sub(r"[\s\-]+", "_", texto)


def solo_digitos(valor):
    return re.sub(r"\D", "", valor or "")


def _conteo_cedulas(resultados):
    return Counter(
        solo_digitos(r.numero_documento) for r in resultados if solo_digitos(r.numero_documento)
    )


def cedula_modal(resultados):
    """La cédula más frecuente; en empate, la primera que aparece (como el legado)."""
    conteo = _conteo_cedulas(resultados)
    return conteo.most_common(1)[0][0] if conteo else None


def cedula_ambigua(resultados):
    """Dos o más cédulas empatan en el primer lugar: no hay una cédula del profesor."""
    mas_comunes = _conteo_cedulas(resultados).most_common(2)
    return len(mas_comunes) == 2 and mas_comunes[0][1] == mas_comunes[1][1]


def revalidar_por_cedula(resultados, catalogo, *, cedula_confirmada=None, evidencia=None):
    """Cruza cada documento contra la cédula del profesor.

    La cédula del profesor es la confirmada por un revisor o, si no hay, la más frecuente
    de la evidencia (por defecto, todos los resultados; el estado excluye los descartados
    y rechazados, ADR 0005). Identidad por cédula, no por nombre: corrige falsos
    inválidos por falta de nombre y marca como inválidos los documentos cuya cédula
    pertenece a otra persona. Si la cédula es ambigua no cambia ninguna validez; solo lo
    anota (ADR 0003, diferencia 2).
    """
    evidencia = resultados if evidencia is None else evidencia
    if cedula_confirmada:
        modal = solo_digitos(cedula_confirmada)
        return [_revalidar(r, modal, catalogo) for r in resultados]
    if cedula_ambigua(evidencia):
        return [
            replace(r, observaciones=OBS_CEDULA_AMBIGUA + r.observaciones)
            if solo_digitos(r.numero_documento)
            else r
            for r in resultados
        ]
    modal = cedula_modal(evidencia)
    if not modal:
        return list(resultados)
    return [_revalidar(r, modal, catalogo) for r in resultados]


def _revalidar(r, modal, catalogo):
    cedula = solo_digitos(r.numero_documento)
    if not cedula:
        return r
    if cedula != modal:
        if r.es_valido:
            return replace(
                r,
                es_valido=False,
                observaciones=f"La cédula {cedula} no coincide con la del profesor ({modal}). "
                + r.observaciones,
            )
        return r
    if r.es_valido:
        return r
    tipo = catalogo.resolver(r.tipo_detectado)
    if tipo is None:
        # "otro" o desconocido: la cédula no lo vuelve válido (ADR 0003, diferencia 3).
        return r
    if tipo.requiere_firma:
        if r.tiene_firma:
            return replace(
                r,
                es_valido=True,
                observaciones="Válido (cédula coincide y documento firmado). " + r.observaciones,
            )
        return r
    return replace(
        r,
        es_valido=True,
        observaciones="Válido (verificado por cédula; la falta de nombre no invalida). "
        + r.observaciones,
    )


def _fecha(d):
    return d.strftime("%d/%m/%Y")


def aplicar_vigencia(resultados, catalogo, hoy):
    """Marca vencidos, por vencer y fechas sin leer contra hoy (una date; None: no evalúa).

    Se aplica después de revalidar_por_cedula: si no, la cédula que coincide rescataría a
    un vencido. Un vencido queda inválido con una observación que dice qué pedir. Una
    fecha que falta o es posterior a hoy no invalida: queda señalada para revisión humana.
    Lo que validó un revisor no se toca: la decisión humana prevalece.
    """
    if hoy is None:
        return list(resultados)
    salida = []
    for r in resultados:
        dias_maximos = catalogo.vigencia_de(r.tipo_detectado)
        if (
            dias_maximos is None
            or r.es_error
            or r.es_ilegible
            or r.es_pendiente
            or r.validado_por_revisor
            or r.vencido
            or r.fecha_sin_leer
        ):
            salida.append(r)
            continue
        fecha = r.fecha_expedicion
        if fecha is None and r.desactualizado:
            # Un prompt anterior no pedía la fecha: no es una fecha sin leer, es un análisis
            # que hay que repetir (lo dice el detalle; no marca "requiere atención").
            salida.append(r)
            continue
        if fecha is None or fecha > hoy:
            motivo = "no se pudo leer" if fecha is None else "es posterior a hoy"
            salida.append(
                replace(
                    r,
                    fecha_sin_leer=True,
                    observaciones=f"La fecha de expedición {motivo}: revisar a mano la "
                    f"vigencia (máximo {dias_maximos} días). " + r.observaciones,
                )
            )
            continue
        dias = (hoy - fecha).days
        vence_el = fecha + timedelta(days=dias_maximos)
        if dias > dias_maximos:
            salida.append(
                replace(
                    r,
                    es_valido=False,
                    vencido=True,
                    vence_el=vence_el,
                    observaciones=f"Certificado expedido el {_fecha(fecha)} ({dias} días; "
                    f"máximo {dias_maximos}): solicitar uno nuevo. " + r.observaciones,
                )
            )
            continue
        salida.append(
            replace(
                r,
                vence_el=vence_el,
                por_vencer=(vence_el - hoy).days <= DIAS_AVISO_POR_VENCER,
            )
        )
    return salida


def _tipos_que_cumple(r, catalogo):
    """El tipo del documento y, si es EPS o pensión con cubre="ambos", también el otro."""
    tipo = catalogo.resolver(r.tipo_detectado)
    if tipo is None:
        return []
    tipos = [tipo]
    if r.cubre == "ambos" and tipo.codigo in (EPS, AFP):
        otro = catalogo.resolver(AFP if tipo.codigo == EPS else EPS)
        if otro is not None:
            tipos.append(otro)
    return tipos


@dataclass(frozen=True)
class EvaluacionProfesor:
    estado: EstadoProfesor
    faltantes: tuple  # TipoCatalogo obligatorios sin ningún documento
    problemas: tuple  # ResultadoDocumento vigentes e inválidos
    errores: tuple  # ResultadoDocumento cuyo análisis falló (transitorio)
    ilegibles: tuple  # ResultadoDocumento con un problema permanente del archivo
    no_reconocidos: tuple  # "otro", desconocidos o de un tipo inactivo
    vigentes: dict  # codigo -> ResultadoDocumento que cuenta para ese tipo
    cedula: str | None
    cedula_ambigua: bool
    pendientes: tuple = ()  # ResultadoDocumento aún sin analizar (ADR 0005)
    fechas_sin_leer: tuple = ()  # vencen, pero la fecha no se leyó: revisión humana
    por_vencer: tuple = ()  # vigentes que vencen en 7 días o menos


def _clave_vigente(r):
    """Validado por un revisor, luego válido según la IA, luego el más reciente (y el
    nombre, para desempatar)."""
    marca = r.modificado_en.timestamp() if r.modificado_en else float("-inf")
    return (r.validado_por_revisor, r.es_valido is True, marca, r.nombre_archivo)


def evaluar_profesor(resultados, catalogo, *, cedula_confirmada=None, evidencia=None):
    """Estado del profesor según el orden acordado en el ADR 0003."""
    resultados = list(resultados)
    pendientes = tuple(r for r in resultados if r.es_pendiente)
    errores = tuple(r for r in resultados if r.es_error)
    ilegibles = tuple(r for r in resultados if r.es_ilegible)
    analizados = [
        r for r in resultados if not r.es_error and not r.es_ilegible and not r.es_pendiente
    ]
    if evidencia is None:
        evidencia = analizados
    else:
        evidencia = [
            r for r in evidencia if not r.es_error and not r.es_ilegible and not r.es_pendiente
        ]
    ambigua = False if cedula_confirmada else cedula_ambigua(evidencia)

    por_tipo = {}
    no_reconocidos = []
    for r in analizados:
        tipos = _tipos_que_cumple(r, catalogo)
        if not tipos:
            no_reconocidos.append(r)
        for tipo in tipos:
            por_tipo.setdefault(tipo.codigo, []).append(r)
    vigentes = {codigo: max(docs, key=_clave_vigente) for codigo, docs in por_tipo.items()}

    faltantes = tuple(t for t in catalogo.activos if t.obligatorio and t.codigo not in vigentes)
    problemas = tuple(
        vigentes[t.codigo]
        for t in catalogo.activos
        if t.codigo in vigentes and vigentes[t.codigo].es_valido is not True
    )

    hay_problemas = bool(problemas or ambigua or ilegibles)
    if not resultados:
        estado = EstadoProfesor.SIN_DOCUMENTOS
    elif len(pendientes) == len(resultados):
        estado = EstadoProfesor.SIN_ANALIZAR
    elif not faltantes and not hay_problemas and not pendientes:
        estado = EstadoProfesor.COMPLETO
    elif errores:
        estado = EstadoProfesor.ERROR  # solo fallos transitorios: se reanaliza
    elif faltantes:
        estado = EstadoProfesor.INCOMPLETO
    elif hay_problemas:
        estado = EstadoProfesor.CON_PROBLEMAS
    else:
        # No falta nada ni hay problemas, pero aún hay documentos sin analizar.
        estado = EstadoProfesor.PENDIENTE_ANALISIS

    return EvaluacionProfesor(
        estado=estado,
        faltantes=faltantes,
        problemas=problemas,
        errores=errores,
        ilegibles=ilegibles,
        no_reconocidos=tuple(no_reconocidos),
        vigentes=vigentes,
        cedula=cedula_confirmada or (None if ambigua else cedula_modal(evidencia)),
        cedula_ambigua=ambigua,
        pendientes=pendientes,
        fechas_sin_leer=tuple(r for r in analizados if r.fecha_sin_leer),
        # Un combinado es el vigente de EPS y de AFP: cuenta una vez.
        por_vencer=tuple(
            {id(r): r for r in vigentes.values() if r.por_vencer and r.es_valido}.values()
        ),
    )
