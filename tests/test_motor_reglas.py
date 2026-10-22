"""Reglas puras del motor: port del legado y diferencias intencionales (ADR 0003)."""

from datetime import UTC, datetime, timedelta

import pytest

from apps.motor.reglas import (
    OBS_CEDULA_AMBIGUA,
    EstadoProfesor,
    cedula_ambigua,
    cedula_modal,
    evaluar_profesor,
    norm,
    revalidar_por_cedula,
    solo_digitos,
)
from apps.motor.resultado import ResultadoDocumento
from tests.fixtures.catalogo import CODIGOS, DOTC, FORMATO, MEDICO, catalogo_inicial

CEDULA = "1000000001"
OTRA = "1000000099"
BASE = datetime(2026, 10, 1, tzinfo=UTC)


def doc(tipo, valido=True, cedula=CEDULA, *, archivo=None, firma=None, minutos=0, error=""):
    return ResultadoDocumento(
        nombre_archivo=archivo or f"{tipo}_{minutos}.pdf",
        tipo_detectado=tipo,
        es_valido=valido,
        numero_documento=cedula,
        tiene_firma=firma,
        error=error,
        modificado_en=BASE + timedelta(minutes=minutos),
    )


def completos(cedula=CEDULA, **reemplazos):
    """Un documento válido por tipo; reemplazos: {codigo: ResultadoDocumento | None}."""
    docs = []
    for codigo in CODIGOS:
        if codigo in reemplazos:
            if reemplazos[codigo] is not None:
                docs.append(reemplazos[codigo])
            continue
        docs.append(doc(codigo, firma=True if codigo == FORMATO else None, cedula=cedula))
    return docs


def procesar(docs, catalogo=None):
    catalogo = catalogo or catalogo_inicial()
    revalidados = revalidar_por_cedula(docs, catalogo)
    return revalidados, evaluar_profesor(revalidados, catalogo)


# --- Port fiel de las funciones auxiliares ---


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("CERTIFICADO_MEDICO_LABORAL", "certificado_medico_laboral"),
        ("  Boletín Responsabilidades-Fiscales.pdf ", "boletin_responsabilidades_fiscales"),
        ("examen médico  laboral", "examen_medico_laboral"),
        (None, ""),
    ],
)
def test_norm(entrada, esperado):
    assert norm(entrada) == esperado


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [("C.C. 1.000.000.001", "1000000001"), ("E-0012345", "0012345"), (None, ""), ("", "")],
)
def test_solo_digitos(entrada, esperado):
    assert solo_digitos(entrada) == esperado


def test_cedula_modal_es_la_mas_frecuente():
    docs = [doc("a", cedula=CEDULA), doc("b", cedula=CEDULA), doc("c", cedula=OTRA)]
    assert cedula_modal(docs) == CEDULA


def test_cedula_modal_sin_cedulas():
    assert cedula_modal([doc("a", cedula=""), doc("b", cedula="N/A")]) is None


def test_cedula_ambigua_por_empate():
    docs = [doc("a"), doc("b"), doc("c", cedula=OTRA), doc("d", cedula=OTRA)]
    assert cedula_ambigua(docs)


def test_sin_empate_no_es_ambigua():
    assert not cedula_ambigua([doc("a"), doc("b"), doc("c", cedula=OTRA)])
    assert not cedula_ambigua([doc("a")])
    assert not cedula_ambigua([])


# --- Casos del legado (tabla) ---


def test_todo_valido_es_completo():
    _, evaluacion = procesar(completos())
    assert evaluacion.estado == EstadoProfesor.COMPLETO
    assert evaluacion.faltantes == ()
    assert evaluacion.problemas == ()


def test_extranjero_sin_nombre_con_cedula_de_extranjeria_es_valido():
    """La IA lo marcó inválido por no tener nombre; la cédula coincide, así que vale."""
    cedula_ce = "E-0012345"
    sin_nombre = doc("certificado_antecedentes_judiciales", valido=False, cedula=cedula_ce)
    docs = completos(cedula=cedula_ce, certificado_antecedentes_judiciales=sin_nombre)
    revalidados, evaluacion = procesar(docs)
    judicial = next(r for r in revalidados if r.tipo_detectado == sin_nombre.tipo_detectado)
    assert judicial.es_valido is True
    assert judicial.observaciones.startswith("Válido (verificado por cédula")
    assert evaluacion.estado == EstadoProfesor.COMPLETO


def test_cedula_de_otra_persona_invalida_el_documento():
    ajeno = doc("certificado_registro_deudores_morosos", cedula=OTRA)
    revalidados, evaluacion = procesar(completos(certificado_registro_deudores_morosos=ajeno))
    redam = next(r for r in revalidados if r.numero_documento == OTRA)
    assert redam.es_valido is False
    assert f"La cédula {OTRA} no coincide con la del profesor ({CEDULA})" in redam.observaciones
    assert evaluacion.estado == EstadoProfesor.CON_PROBLEMAS
    assert evaluacion.problemas == (redam,)


def test_formato_con_cedula_correcta_sin_firma_sigue_invalido():
    sin_firma = doc(FORMATO, valido=False, firma=False)
    revalidados, evaluacion = procesar(completos(**{FORMATO: sin_firma}))
    formato = next(r for r in revalidados if r.tipo_detectado == FORMATO)
    assert formato.es_valido is False
    assert evaluacion.estado == EstadoProfesor.CON_PROBLEMAS


def test_formato_con_cedula_correcta_y_firma_es_valido():
    firmado = doc(FORMATO, valido=False, firma=True)
    revalidados, evaluacion = procesar(completos(**{FORMATO: firmado}))
    formato = next(r for r in revalidados if r.tipo_detectado == FORMATO)
    assert formato.es_valido is True
    assert formato.observaciones.startswith("Válido (cédula coincide y documento firmado)")
    assert evaluacion.estado == EstadoProfesor.COMPLETO


def test_dotc_cuenta_como_certificado_medico():
    _, evaluacion = procesar(completos(**{MEDICO: doc(DOTC)}))
    assert evaluacion.estado == EstadoProfesor.COMPLETO
    assert evaluacion.vigentes[MEDICO].tipo_detectado == DOTC


def test_sin_ninguna_cedula_no_se_revalida():
    docs = [doc(codigo, valido=False, cedula="") for codigo in CODIGOS]
    revalidados, evaluacion = procesar(docs)
    assert revalidados == docs
    assert evaluacion.estado == EstadoProfesor.CON_PROBLEMAS


def test_documento_sin_cedula_no_se_toca_si_otros_la_tienen():
    sin_cedula = doc("certificados_eps_afp", valido=False, cedula="")
    revalidados, _ = procesar(completos(certificados_eps_afp=sin_cedula))
    assert sin_cedula in revalidados


def test_falta_un_tipo_obligatorio_es_incompleto():
    _, evaluacion = procesar(completos(certificados_eps_afp=None))
    assert evaluacion.estado == EstadoProfesor.INCOMPLETO
    assert [t.codigo for t in evaluacion.faltantes] == ["certificados_eps_afp"]


def test_faltante_gana_sobre_problema():
    ajeno = doc("certificado_antecedentes_judiciales", cedula=OTRA)
    docs = completos(certificados_eps_afp=None, certificado_antecedentes_judiciales=ajeno)
    _, evaluacion = procesar(docs)
    assert evaluacion.estado == EstadoProfesor.INCOMPLETO
    assert len(evaluacion.problemas) == 1


def test_sin_documentos():
    _, evaluacion = procesar([])
    assert evaluacion.estado == EstadoProfesor.SIN_DOCUMENTOS
    assert len(evaluacion.faltantes) == 9


# --- Diferencia intencional 1: duplicados ---


def test_duplicado_invalido_no_deja_con_problemas_si_hay_uno_valido():
    viejo_valido = doc("certificado_antecedentes_judiciales", minutos=1)
    nuevo_invalido = doc("certificado_antecedentes_judiciales", valido=False, cedula="", minutos=5)
    docs = completos(certificado_antecedentes_judiciales=viejo_valido) + [nuevo_invalido]
    _, evaluacion = procesar(docs)
    assert evaluacion.estado == EstadoProfesor.COMPLETO
    assert evaluacion.vigentes["certificado_antecedentes_judiciales"] == viejo_valido


def test_entre_duplicados_iguales_cuenta_el_mas_reciente():
    viejo = doc("certificados_eps_afp", minutos=1)
    nuevo = doc("certificados_eps_afp", minutos=9)
    _, evaluacion = procesar(completos(certificados_eps_afp=viejo) + [nuevo])
    assert evaluacion.vigentes["certificados_eps_afp"] == nuevo


def test_duplicados_todos_invalidos_quedan_con_problemas():
    a = doc("certificados_eps_afp", valido=False, cedula="", minutos=1)
    b = doc("certificados_eps_afp", valido=False, cedula="", minutos=2)
    _, evaluacion = procesar(completos(certificados_eps_afp=a) + [b])
    assert evaluacion.estado == EstadoProfesor.CON_PROBLEMAS
    assert evaluacion.problemas == (b,)


# --- Diferencia intencional 2: cédula ambigua ---


def test_empate_de_cedulas_no_invalida_nada_y_queda_con_problemas():
    """2 documentos con X y 2 con Y, todos válidos según la IA: nunca COMPLETO."""
    docs = completos()
    docs = [
        doc(d.tipo_detectado, cedula="", firma=d.tiene_firma) if i >= 4 else d
        for i, d in enumerate(docs)
    ]
    docs[2] = doc(docs[2].tipo_detectado, cedula=OTRA)
    docs[3] = doc(docs[3].tipo_detectado, cedula=OTRA, firma=True)
    revalidados, evaluacion = procesar(docs)

    assert all(r.es_valido for r in revalidados)
    con_cedula = [r for r in revalidados if r.numero_documento]
    assert len(con_cedula) == 4
    assert all(r.observaciones.startswith(OBS_CEDULA_AMBIGUA) for r in con_cedula)
    assert evaluacion.cedula_ambigua
    assert evaluacion.estado == EstadoProfesor.CON_PROBLEMAS


def test_empate_tampoco_rescata_invalidos():
    docs = completos(cedula="")
    docs[0] = doc(docs[0].tipo_detectado, valido=False, cedula=CEDULA)
    docs[1] = doc(docs[1].tipo_detectado, cedula=OTRA)
    revalidados, _ = procesar(docs)
    assert revalidados[0].es_valido is False


# --- Diferencia intencional 3: OTRO o desconocido ---


@pytest.mark.parametrize("tipo", ["otro", "carta_de_recomendacion"])
def test_otro_no_cuenta_para_requisitos_y_queda_senalado(tipo):
    extra = doc(tipo, valido=False)
    _, evaluacion = procesar(completos(certificados_eps_afp=None) + [extra])
    assert evaluacion.estado == EstadoProfesor.INCOMPLETO
    assert evaluacion.no_reconocidos == (extra,)
    assert extra not in evaluacion.problemas


def test_otro_no_impide_completo():
    extra = doc("otro", valido=False)
    _, evaluacion = procesar(completos() + [extra])
    assert evaluacion.estado == EstadoProfesor.COMPLETO
    assert evaluacion.no_reconocidos == (extra,)


def test_tipo_inactivo_se_trata_como_otro():
    catalogo = catalogo_inicial(certificados_eps_afp={"activo": False})
    _, evaluacion = procesar(completos(), catalogo)
    assert evaluacion.estado == EstadoProfesor.COMPLETO
    assert [r.tipo_detectado for r in evaluacion.no_reconocidos] == ["certificados_eps_afp"]


def test_tipo_no_obligatorio_ausente_no_es_faltante():
    catalogo = catalogo_inicial(certificados_eps_afp={"obligatorio": False})
    _, evaluacion = procesar(completos(certificados_eps_afp=None), catalogo)
    assert evaluacion.estado == EstadoProfesor.COMPLETO


def test_tipo_no_obligatorio_invalido_impide_completo():
    catalogo = catalogo_inicial(certificados_eps_afp={"obligatorio": False})
    invalido = doc("certificados_eps_afp", valido=False, cedula="")
    _, evaluacion = procesar(completos(certificados_eps_afp=invalido), catalogo)
    assert evaluacion.estado == EstadoProfesor.CON_PROBLEMAS


# --- Documentos con ERROR ---


def test_error_en_duplicado_no_impide_completo():
    fallido = doc("", valido=False, cedula="", error="La API respondió 500")
    _, evaluacion = procesar(completos() + [fallido])
    assert evaluacion.estado == EstadoProfesor.COMPLETO
    assert evaluacion.errores == (fallido,)


def test_error_sin_completo_es_error():
    fallido = doc("", valido=False, cedula="", error="Tiempo agotado")
    _, evaluacion = procesar(completos(certificados_eps_afp=None) + [fallido])
    assert evaluacion.estado == EstadoProfesor.ERROR
    assert [t.codigo for t in evaluacion.faltantes] == ["certificados_eps_afp"]


def test_error_nunca_es_vigente():
    fallido = doc(MEDICO, valido=False, cedula="", error="Respuesta fuera del esquema")
    _, evaluacion = procesar(completos(**{MEDICO: None}) + [fallido])
    assert MEDICO not in evaluacion.vigentes
    assert evaluacion.estado == EstadoProfesor.ERROR


def test_revalidar_no_modifica_la_entrada():
    docs = completos(
        certificado_antecedentes_judiciales=doc("certificado_antecedentes_judiciales", valido=False)
    )
    copia = list(docs)
    revalidar_por_cedula(docs, catalogo_inicial())
    assert docs == copia


def test_estados_coinciden_con_el_modelo():
    from apps.contrataciones.models import EstadoProfesor as EstadoModelo

    assert {e.value for e in EstadoProfesor} == set(EstadoModelo.values)


def test_la_cedula_no_rescata_un_documento_otro():
    """El legado lo marcaría "Válido (verificado por cédula)"; aquí sigue inválido."""
    extra = doc("otro", valido=False)
    revalidados, _ = procesar(completos() + [extra])
    assert revalidados[-1] == extra


def test_la_cedula_si_invalida_un_documento_otro_ajeno():
    extra = doc("otro", valido=True, cedula=OTRA)
    revalidados, _ = procesar(completos() + [extra])
    assert revalidados[-1].es_valido is False
