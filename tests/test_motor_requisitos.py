"""Requisitos de Gestión Humana 2026-2 en las reglas puras (ADR 0006).

EPS y AFP por separado (un PDF puede cubrir los dos), alternativas de pensión y vigencia
de los certificados contra una fecha de referencia explícita.
"""

from dataclasses import replace
from datetime import date, timedelta

import pytest

from apps.motor.reglas import (
    EstadoProfesor,
    aplicar_vigencia,
    evaluar_profesor,
    revalidar_por_cedula,
)
from apps.motor.resultado import ResultadoDocumento
from tests.fixtures.catalogo import (
    AFP,
    BONO,
    CODIGOS,
    EPS,
    FORMATO,
    MEDICO,
    PENSION,
    catalogo_inicial,
)

CEDULA = "1000000001"
HOY = date(2026, 10, 24)


def doc(tipo, *, dias=3, valido=True, cedula=CEDULA, archivo=None, cubre="", firma=None):
    """dias: hace cuántos días se expidió (None: la IA no pudo leer la fecha)."""
    return ResultadoDocumento(
        nombre_archivo=archivo or f"{tipo}.pdf",
        tipo_detectado=tipo,
        es_valido=valido,
        numero_documento=cedula,
        tiene_firma=True if tipo == FORMATO else firma,
        fecha_expedicion=None if dias is None else HOY - timedelta(days=dias),
        cubre=cubre,
    )


def completos(**reemplazos):
    """Un documento vigente por tipo; reemplazos: {codigo: ResultadoDocumento | None}."""
    docs = []
    for codigo in CODIGOS:
        if codigo in reemplazos:
            if reemplazos[codigo] is not None:
                docs.append(reemplazos[codigo])
            continue
        docs.append(doc(codigo, cubre={EPS: "eps", AFP: "afp"}.get(codigo, "")))
    return docs


def procesar(docs, hoy=HOY):
    catalogo = catalogo_inicial()
    revalidados = aplicar_vigencia(revalidar_por_cedula(docs, catalogo), catalogo, hoy)
    return revalidados, evaluar_profesor(revalidados, catalogo)


def test_completo_con_eps_y_afp_separados():
    _, evaluacion = procesar(completos())
    assert evaluacion.estado == EstadoProfesor.COMPLETO
    assert {EPS, AFP} <= set(evaluacion.vigentes)


# --- EPS y AFP ---


def test_solo_eps_queda_incompleto_sin_afp():
    _, evaluacion = procesar(completos(**{AFP: None}))
    assert evaluacion.estado == EstadoProfesor.INCOMPLETO
    assert [t.codigo for t in evaluacion.faltantes] == [AFP]


@pytest.mark.parametrize("tipo", [EPS, AFP])
def test_un_pdf_con_ambas_afiliaciones_cumple_los_dos(tipo):
    combinado = doc(tipo, archivo="seguridad social.pdf", cubre="ambos")
    _, evaluacion = procesar([*completos(**{EPS: None, AFP: None}), combinado])
    assert evaluacion.estado == EstadoProfesor.COMPLETO
    assert evaluacion.vigentes[EPS] is evaluacion.vigentes[AFP]
    assert evaluacion.vigentes[EPS].nombre_archivo == "seguridad social.pdf"


def test_cubre_eps_no_cumple_afp():
    solo_eps = doc(EPS, cubre="eps")
    _, evaluacion = procesar([*completos(**{EPS: None, AFP: None}), solo_eps])
    assert [t.codigo for t in evaluacion.faltantes] == [AFP]


def test_combinado_invalido_es_problema_en_los_dos():
    combinado = doc(EPS, cubre="ambos", valido=False, cedula="")
    _, evaluacion = procesar([*completos(**{EPS: None, AFP: None}), combinado])
    assert evaluacion.estado == EstadoProfesor.CON_PROBLEMAS


@pytest.mark.parametrize("alias", [PENSION, BONO])
def test_alternativas_de_pension_cumplen_afp_y_conservan_su_codigo(alias):
    alternativa = doc(alias, cubre="afp")
    revalidados, evaluacion = procesar([*completos(**{AFP: None}), alternativa])
    assert evaluacion.estado == EstadoProfesor.COMPLETO
    assert evaluacion.vigentes[AFP].tipo_detectado == alias  # con qué se cumplió
    assert revalidados[-1].es_valido


# --- Vigencia ---


def test_vigente_hasta_el_dia_30():
    eps = doc(EPS, dias=30, cubre="eps")
    revalidados, evaluacion = procesar(completos(**{EPS: eps}))
    assert evaluacion.estado == EstadoProfesor.COMPLETO
    assert not revalidados[CODIGOS.index(EPS)].vencido


def test_vencido_al_dia_31_queda_con_problemas_y_observacion_accionable():
    eps = doc(EPS, dias=31, cubre="eps")
    revalidados, evaluacion = procesar(completos(**{EPS: eps}))
    vencido = revalidados[CODIGOS.index(EPS)]
    assert vencido.vencido and not vencido.es_valido
    assert vencido.observaciones.startswith(
        "Certificado expedido el 23/09/2026 (31 días; máximo 30): solicitar uno nuevo."
    )
    assert evaluacion.estado == EstadoProfesor.CON_PROBLEMAS
    assert evaluacion.problemas == (vencido,)


def test_la_cedula_que_coincide_no_rescata_un_vencido():
    # La IA lo marcó inválido sin razón; la cédula lo rescataría, pero está vencido.
    judicial = doc("certificado_antecedentes_judiciales", dias=40, valido=False)
    revalidados, _ = procesar(completos(certificado_antecedentes_judiciales=judicial))
    assert not revalidados[CODIGOS.index("certificado_antecedentes_judiciales")].es_valido


@pytest.mark.parametrize("tipo", [FORMATO, MEDICO])
def test_tipos_sin_vigencia_no_vencen(tipo):
    viejo = doc(tipo, dias=400)
    revalidados, evaluacion = procesar(completos(**{tipo: viejo}))
    assert evaluacion.estado == EstadoProfesor.COMPLETO
    assert not revalidados[CODIGOS.index(tipo)].vencido


@pytest.mark.parametrize("alias", [PENSION, BONO])
def test_alternativas_de_pension_no_vencen(alias):
    _, evaluacion = procesar([*completos(**{AFP: None}), doc(alias, dias=900, cubre="afp")])
    assert evaluacion.estado == EstadoProfesor.COMPLETO


def test_por_vencer_cuando_faltan_7_dias_o_menos():
    eps = doc(EPS, dias=23, cubre="eps")  # vence el 31/10: faltan 7
    afp = doc(AFP, dias=22, cubre="afp")  # vence el 1/11: faltan 8
    revalidados, evaluacion = procesar(completos(**{EPS: eps, AFP: afp}))
    assert revalidados[CODIGOS.index(EPS)].vence_el == date(2026, 10, 31)
    assert revalidados[CODIGOS.index(EPS)].por_vencer
    assert not revalidados[CODIGOS.index(AFP)].por_vencer
    assert evaluacion.estado == EstadoProfesor.COMPLETO
    assert [r.tipo_detectado for r in evaluacion.por_vencer] == [EPS]


@pytest.mark.parametrize("dias", [None, -2])  # sin fecha, o fecha posterior a hoy
def test_fecha_que_no_se_lee_no_invalida_pero_queda_senalada(dias):
    eps = doc(EPS, dias=dias, cubre="eps")
    revalidados, evaluacion = procesar(completos(**{EPS: eps}))
    resultado = revalidados[CODIGOS.index(EPS)]
    assert resultado.es_valido and resultado.fecha_sin_leer and not resultado.vencido
    assert "revisar a mano" in resultado.observaciones
    assert evaluacion.estado == EstadoProfesor.COMPLETO
    assert evaluacion.fechas_sin_leer == (resultado,)


def test_sin_fecha_de_referencia_no_se_evalua_la_vigencia():
    catalogo = catalogo_inicial()
    docs = completos(**{EPS: doc(EPS, dias=90, cubre="eps")})
    assert aplicar_vigencia(docs, catalogo, None) == docs


def test_el_paso_del_tiempo_vence_un_certificado():
    docs = completos()
    _, hoy = procesar(docs)
    _, en_un_mes = procesar(docs, hoy=HOY + timedelta(days=28))
    assert hoy.estado == EstadoProfesor.COMPLETO
    assert en_un_mes.estado == EstadoProfesor.CON_PROBLEMAS


def test_errores_ilegibles_y_pendientes_no_se_evaluan():
    catalogo = catalogo_inicial()
    otros = [
        ResultadoDocumento.con_error("a.pdf", "Red caída."),
        ResultadoDocumento.ilegible("b.pdf", "Dañado."),
        ResultadoDocumento.pendiente_de_analisis("c.pdf"),
    ]
    assert aplicar_vigencia(otros, catalogo, HOY) == otros


def test_un_vencido_validado_por_revisor_cuenta_como_valido():
    vencido = aplicar_vigencia([doc(EPS, dias=60, cubre="eps")], catalogo_inicial(), HOY)[0]
    aprobado = replace(vencido, es_valido=True, validado_por_revisor=True)
    _, evaluacion = procesar(completos(**{EPS: None}) + [aprobado])
    # procesar vuelve a aplicar la vigencia: la decisión humana prevalece.
    assert evaluacion.estado == EstadoProfesor.COMPLETO
