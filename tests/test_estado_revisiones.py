"""Estado con revisiones humanas, verificación con huella y cédula confirmada (ADR 0005)."""

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.contrataciones.models import (
    Analisis,
    Documento,
    EstadoProfesor,
    Profesor,
    Revision,
    TipoDocumento,
)
from apps.contrataciones.servicios.estado import (
    actualizar_huella,
    evaluar,
    filtrar_por_verificacion,
    recalcular_estado,
)
from apps.contrataciones.servicios.revisiones import (
    confirmar_cedula,
    crear_revision,
    verificar_profesor,
)
from apps.cuentas.models import RegistroAuditoria
from apps.motor.catalogo import cargar_catalogo
from tests.fixtures.catalogo import CODIGOS
from tests.fixtures.datos import completo, documento

pytestmark = pytest.mark.django_db

CEDULA = "1000000001"
OTRA = "1000000099"
Verificacion = Profesor.Verificacion


@pytest.fixture
def catalogo(db):
    return cargar_catalogo()


@pytest.fixture
def revisor(crear_usuario):
    return crear_usuario("revisor", grupo="Revisor GH")


@pytest.fixture
def prof(db):
    return Profesor.objects.create(carpeta="PROFESOR FICTICIO", nombre="Profesor Ficticio")


def estado(profesor, catalogo):
    recalcular_estado(profesor, catalogo)
    profesor.refresh_from_db()
    return profesor.estado


# --- Resultado efectivo ---


def test_sin_revision_cuenta_la_ia(prof, corrida, catalogo):
    completo(prof, corrida)
    assert estado(prof, catalogo) == EstadoProfesor.COMPLETO


def test_aprobar_vuelve_valido_un_documento(prof, corrida, catalogo, revisor):
    docs = completo(prof, corrida, certificado_afp={"valido": False, "cedula": ""})
    assert estado(prof, catalogo) == EstadoProfesor.CON_PROBLEMAS
    crear_revision(docs["certificado_afp"], revisor, Revision.Decision.APROBADO)
    prof.refresh_from_db()
    assert prof.estado == EstadoProfesor.COMPLETO


def test_rechazar_vuelve_invalido_un_documento(prof, corrida, catalogo, revisor):
    docs = completo(prof, corrida)
    crear_revision(docs[CODIGOS[0]], revisor, "rechazado", comentario="Vencido")
    prof.refresh_from_db()
    assert prof.estado == EstadoProfesor.CON_PROBLEMAS


def test_corregir_el_tipo_lo_hace_contar_para_el_requisito(prof, corrida, catalogo, revisor):
    from apps.contrataciones.models import TipoDocumento

    completo(prof, corrida, certificado_afp=None)
    otro = documento(prof, corrida, "otro", valido=False, nombre="seguridad social.pdf")
    assert estado(prof, catalogo) == EstadoProfesor.INCOMPLETO
    crear_revision(
        otro,
        revisor,
        "corregido",
        comentario="Es el certificado de EPS",
        tipo_corregido=TipoDocumento.objects.get(codigo="certificado_afp"),
    )
    prof.refresh_from_db()
    assert prof.estado == EstadoProfesor.COMPLETO


def test_descartar_un_duplicado_ilegible(prof, corrida, catalogo, revisor):
    completo(prof, corrida)
    duplicado = documento(prof, corrida, Analisis.TIPO_ILEGIBLE, valido=False, cedula="")
    assert estado(prof, catalogo) == EstadoProfesor.CON_PROBLEMAS
    crear_revision(duplicado, revisor, "descartado", comentario="Copia protegida de la EPS")
    prof.refresh_from_db()
    assert prof.estado == EstadoProfesor.COMPLETO


def test_la_ultima_revision_prevalece(prof, corrida, catalogo, revisor):
    docs = completo(prof, corrida)
    crear_revision(docs[CODIGOS[0]], revisor, "rechazado", comentario="Dudoso")
    crear_revision(docs[CODIGOS[0]], revisor, "aprobado")
    prof.refresh_from_db()
    assert prof.estado == EstadoProfesor.COMPLETO


def test_la_revision_no_aplica_si_el_archivo_cambio(prof, corrida, catalogo, revisor):
    docs = completo(prof, corrida, certificado_afp={"valido": False, "cedula": ""})
    eps = docs["certificado_afp"]
    crear_revision(eps, revisor, "aprobado")
    eps.sha256 = "f" * 64  # el profesor subió otro archivo con el mismo nombre
    eps.save()
    Analisis.objects.create(
        documento=eps,
        corrida=corrida,
        sha256=eps.sha256,
        modelo="simulado",
        tipo_detectado="certificado_afp",
        es_valido=False,
    )
    assert estado(prof, catalogo) == EstadoProfesor.CON_PROBLEMAS


def test_el_aprobado_por_un_revisor_es_el_vigente(prof, corrida, catalogo, revisor):
    docs = completo(prof, corrida, certificado_afp={"valido": False, "cedula": ""})
    documento(prof, corrida, "certificado_afp", nombre="eps nuevo.pdf")
    crear_revision(docs["certificado_afp"], revisor, "aprobado")
    evaluacion, _ = evaluar(prof, catalogo)
    assert evaluacion.vigentes["certificado_afp"].nombre_archivo == "certificado_afp.pdf"


# --- Cédula: la decisión humana prevalece, y la evidencia excluye rechazados y descartados ---


def test_aprobado_con_cedula_ajena_queda_valido(prof, corrida, catalogo, revisor):
    docs = completo(prof, corrida, certificado_afp={"cedula": OTRA})
    assert estado(prof, catalogo) == EstadoProfesor.CON_PROBLEMAS
    crear_revision(
        docs["certificado_afp"], revisor, "aprobado", comentario="La IA leyó mal un dígito"
    )
    prof.refresh_from_db()
    assert prof.estado == EstadoProfesor.COMPLETO


def test_aprobar_con_cedula_ajena_exige_comentario(prof, corrida, catalogo, revisor):
    docs = completo(prof, corrida, certificado_afp={"cedula": OTRA})
    recalcular_estado(prof, catalogo)
    with pytest.raises(ValidationError, match=f"{OTRA}.*{CEDULA}"):
        crear_revision(docs["certificado_afp"], revisor, "aprobado")
    assert not Revision.objects.exists()


def test_rechazados_y_descartados_no_votan_la_cedula(prof, corrida, catalogo, revisor):
    completo(prof, corrida, **{c: {"cedula": ""} for c in CODIGOS[2:]})  # 2 con la propia
    a = documento(prof, corrida, "otro", cedula=OTRA, nombre="ajeno a.pdf")
    b = documento(prof, corrida, "otro", cedula=OTRA, nombre="ajeno b.pdf")
    documento(prof, corrida, "otro", cedula=OTRA, nombre="ajeno c.pdf")
    evaluacion, _ = evaluar(prof, catalogo)
    assert evaluacion.cedula == OTRA  # 3 ajenos ganan...
    assert evaluacion.vigentes[CODIGOS[0]].es_valido is False  # ...e invalidan los propios
    crear_revision(a, revisor, "rechazado", comentario="No es del profesor")
    crear_revision(b, revisor, "descartado", comentario="Documento de otra persona")
    evaluacion, _ = evaluar(prof, catalogo)
    assert evaluacion.cedula == CEDULA  # 2 propios contra 1 ajeno
    assert evaluacion.vigentes[CODIGOS[0]].es_valido is True  # la revalidación usó la propia


def test_rechazados_no_crean_ambiguedad(prof, corrida, catalogo, revisor):
    docs = completo(prof, corrida, **{c: {"cedula": ""} for c in CODIGOS[2:]})
    a = documento(prof, corrida, "otro", cedula=OTRA, nombre="ajeno a.pdf")
    b = documento(prof, corrida, "otro", cedula=OTRA, nombre="ajeno b.pdf")
    assert evaluar(prof, catalogo)[0].cedula_ambigua  # 2 contra 2
    crear_revision(a, revisor, "rechazado", comentario="Ajeno")
    crear_revision(b, revisor, "rechazado", comentario="Ajeno")
    assert not evaluar(prof, catalogo)[0].cedula_ambigua
    assert docs  # los documentos propios siguen ahí


def test_confirmar_la_cedula_resuelve_el_2_contra_2(prof, corrida, catalogo, revisor):
    completo(prof, corrida, **{c: {"cedula": ""} for c in CODIGOS[2:]})
    documento(prof, corrida, "otro", cedula=OTRA, nombre="ajeno a.pdf")
    documento(prof, corrida, "otro", cedula=OTRA, nombre="ajeno b.pdf")
    assert estado(prof, catalogo) == EstadoProfesor.CON_PROBLEMAS
    confirmar_cedula(prof, revisor, CEDULA)
    prof.refresh_from_db()
    assert (prof.cedula_confirmada, prof.cedula_confirmada_por) == (CEDULA, revisor)
    assert prof.estado == EstadoProfesor.COMPLETO
    assert prof.cedula == CEDULA
    assert RegistroAuditoria.objects.filter(accion="cedula_confirmada").exists()


# --- Validaciones de las acciones ---


@pytest.mark.parametrize("tipo", ["otro", Analisis.TIPO_ILEGIBLE, Analisis.TIPO_ERROR])
def test_no_se_aprueba_un_documento_sin_tipo_del_catalogo(prof, corrida, revisor, tipo):
    doc = documento(prof, corrida, tipo, valido=False, cedula="")
    with pytest.raises(ValidationError, match="tipo"):
        crear_revision(doc, revisor, "aprobado")


def test_descartar_exige_comentario(prof, corrida, revisor):
    doc = documento(prof, corrida, "otro", valido=False)
    with pytest.raises(ValidationError, match="comentario"):
        crear_revision(doc, revisor, "descartado")


def test_corregir_exige_tipo(prof, corrida, revisor):
    doc = documento(prof, corrida, "otro", valido=False)
    with pytest.raises(ValidationError, match="tipo"):
        crear_revision(doc, revisor, "corregido", comentario="x")


def test_no_se_revisa_un_documento_no_presente(prof, corrida, revisor):
    doc = documento(prof, corrida, CODIGOS[0])
    Documento.objects.filter(pk=doc.pk).update(presente=False)
    doc.refresh_from_db()
    with pytest.raises(ValidationError, match="no está"):
        crear_revision(doc, revisor, "aprobado")


def test_crear_revision_audita(prof, corrida, revisor):
    doc = documento(prof, corrida, CODIGOS[0])
    revision = crear_revision(doc, revisor, "aprobado")
    registro = RegistroAuditoria.objects.get(accion="revision_creada")
    assert registro.usuario == revisor
    assert registro.objeto == doc
    assert registro.detalle == {"decision": "aprobado", "revision": revision.pk}


# --- Verificación y huella ---


def test_solo_se_verifica_un_profesor_completo(prof, corrida, catalogo, revisor):
    completo(prof, corrida, certificado_afp=None)
    with pytest.raises(ValidationError, match="COMPLETO"):
        verificar_profesor(prof, revisor)
    prof.refresh_from_db()
    assert prof.verificacion == Verificacion.PENDIENTE


def test_verificar_queda_vigente_y_en_auditoria(prof, corrida, revisor):
    completo(prof, corrida)
    verificar_profesor(prof, revisor)
    prof.refresh_from_db()
    assert prof.verificacion == Verificacion.VIGENTE
    assert prof.verificado_por == revisor
    assert RegistroAuditoria.objects.filter(accion="profesor_verificado", usuario=revisor).exists()


def test_rechazar_y_volver_a_aprobar_deja_la_verificacion_desactualizada(prof, corrida, revisor):
    docs = completo(prof, corrida)
    verificar_profesor(prof, revisor)
    crear_revision(docs[CODIGOS[0]], revisor, "rechazado", comentario="Dudoso")
    prof.refresh_from_db()
    assert prof.verificacion == Verificacion.DESACTUALIZADA
    crear_revision(docs[CODIGOS[0]], revisor, "aprobado")
    prof.refresh_from_db()
    assert prof.estado == EstadoProfesor.COMPLETO
    assert prof.verificacion == Verificacion.DESACTUALIZADA  # no vuelve a vigente sola
    assert prof.verificado_por == revisor  # y no se borra quién verificó


@pytest.mark.parametrize("cambio", ["sha256", "nuevo", "desaparece"])
def test_cambios_de_archivos_desactualizan_la_verificacion(prof, corrida, revisor, cambio):
    docs = completo(prof, corrida)
    verificar_profesor(prof, revisor)
    if cambio == "sha256":
        Documento.objects.filter(pk=docs[CODIGOS[0]].pk).update(sha256="e" * 64)
    elif cambio == "nuevo":
        documento(prof, corrida, "otro", nombre="nuevo.pdf")
    else:
        Documento.objects.filter(pk=docs[CODIGOS[0]].pk).update(presente=False)
    actualizar_huella(prof)  # lo que hace el escaneo
    prof.refresh_from_db()
    assert prof.verificacion == Verificacion.DESACTUALIZADA


def test_confirmar_la_cedula_despues_de_verificar_la_desactualiza(prof, corrida, revisor):
    completo(prof, corrida)
    verificar_profesor(prof, revisor)
    confirmar_cedula(prof, revisor, CEDULA)
    prof.refresh_from_db()
    assert prof.verificacion == Verificacion.DESACTUALIZADA


def test_volver_a_verificar_la_deja_vigente(prof, corrida, revisor):
    docs = completo(prof, corrida)
    verificar_profesor(prof, revisor)
    crear_revision(docs[CODIGOS[0]], revisor, "aprobado")
    verificar_profesor(prof, revisor)
    prof.refresh_from_db()
    assert prof.verificacion == Verificacion.VIGENTE


def test_filtro_por_verificacion(corrida, revisor, catalogo):
    vigente = Profesor.objects.create(carpeta="A", nombre="A")
    desactualizado = Profesor.objects.create(carpeta="B", nombre="B")
    pendiente = Profesor.objects.create(carpeta="C", nombre="C")
    completo(vigente, corrida)
    docs = completo(desactualizado, corrida)
    completo(pendiente, corrida)
    verificar_profesor(vigente, revisor)
    verificar_profesor(desactualizado, revisor)
    crear_revision(docs[CODIGOS[0]], revisor, "aprobado")
    todos = Profesor.objects.all()
    assert list(filtrar_por_verificacion(todos, "vigente")) == [vigente]
    assert list(filtrar_por_verificacion(todos, "desactualizada")) == [desactualizado]
    assert list(filtrar_por_verificacion(todos, "pendiente")) == [pendiente]


# --- Resumen para el tablero ---


def test_resumen_por_tipo_y_requiere_atencion(prof, corrida, catalogo):
    completo(
        prof,
        corrida,
        certificado_afp=None,
        certificado_medico_laboral={"valido": False, "cedula": ""},
    )
    documento(prof, corrida, Analisis.TIPO_ILEGIBLE, valido=False, cedula="")
    recalcular_estado(prof, catalogo)
    prof.refresh_from_db()
    assert prof.resumen["tipos"]["certificado_afp"] == "faltante"
    assert prof.resumen["tipos"]["certificado_medico_laboral"] == "invalido"
    assert prof.resumen["tipos"][CODIGOS[0]] == "valido"
    assert prof.requiere_atencion


def test_reintentos_agotados_requiere_atencion(prof, corrida, catalogo):
    docs = completo(prof, corrida)
    Documento.objects.filter(pk=docs[CODIGOS[0]].pk).update(reintentos_agotados=True)
    recalcular_estado(prof, catalogo)
    prof.refresh_from_db()
    assert prof.requiere_atencion


def test_sin_analisis_conserva_sin_analizar(prof, catalogo):
    Documento.objects.create(
        profesor=prof,
        ruta_relativa="P/x.pdf",
        nombre_archivo="x.pdf",
        sha256="a" * 64,
        tamano=1,
        modificado_en=timezone.now(),
    )
    assert estado(prof, catalogo) == EstadoProfesor.SIN_ANALIZAR


# --- Pendiente de análisis ---


def _pendiente(profesor, nombre="nuevo.pdf"):
    return Documento.objects.create(
        profesor=profesor,
        ruta_relativa=f"{profesor.carpeta}/{nombre}",
        nombre_archivo=nombre,
        sha256="e" * 64,
        tamano=1,
        modificado_en=timezone.now(),
    )


def test_completo_con_un_pendiente_no_es_error_ni_completo(prof, corrida, catalogo):
    completo(prof, corrida)
    _pendiente(prof)
    assert estado(prof, catalogo) == EstadoProfesor.PENDIENTE_ANALISIS


def test_pendiente_de_analisis_no_se_puede_verificar(prof, corrida, catalogo, revisor):
    completo(prof, corrida)
    _pendiente(prof)
    with pytest.raises(ValidationError, match="COMPLETO"):
        verificar_profesor(prof, revisor)
    prof.refresh_from_db()
    assert prof.verificado_por is None


def test_incompleto_con_pendiente_sigue_incompleto(prof, corrida, catalogo):
    completo(prof, corrida, **{CODIGOS[0]: None})
    _pendiente(prof)
    assert estado(prof, catalogo) == EstadoProfesor.INCOMPLETO


# --- Vigencia (ADR 0006) ---


def test_certificado_vencido_deja_con_problemas(prof, corrida, catalogo):
    completo(prof, corrida, certificado_eps={"dias": 45})
    assert estado(prof, catalogo) == EstadoProfesor.CON_PROBLEMAS


def test_la_cedula_no_rescata_un_vencido_en_la_base(prof, corrida, catalogo):
    # La IA lo marcó inválido; la cédula coincide, pero está vencido.
    judicial = "certificado_antecedentes_judiciales"
    docs = completo(prof, corrida, **{judicial: {"dias": 40, "valido": False}})
    evaluacion, evaluados = evaluar(prof, catalogo)
    [evaluado] = [e for e in evaluados if e.documento == docs[judicial]]
    assert evaluado.resultado.vencido and not evaluado.resultado.es_valido
    assert evaluacion.estado == EstadoProfesor.CON_PROBLEMAS


def test_fecha_sin_leer_no_invalida_pero_requiere_atencion(prof, corrida, catalogo):
    completo(prof, corrida, certificado_afp={"dias": None})
    assert estado(prof, catalogo) == EstadoProfesor.COMPLETO
    assert prof.requiere_atencion


def test_aprobar_un_vencido_exige_comentario_y_luego_prevalece(prof, corrida, catalogo, revisor):
    docs = completo(prof, corrida, certificado_eps={"dias": 45})
    with pytest.raises(ValidationError, match="venció el"):
        crear_revision(docs["certificado_eps"], revisor, "aprobado")
    crear_revision(
        docs["certificado_eps"], revisor, "aprobado", comentario="GH aceptó la prórroga."
    )
    assert estado(prof, catalogo) == EstadoProfesor.COMPLETO


def test_al_vencerse_un_certificado_la_verificacion_queda_desactualizada(
    prof, corrida, catalogo, revisor, monkeypatch
):
    from datetime import timedelta

    from apps.contrataciones.servicios import estado as servicio_estado

    completo(prof, corrida)  # expedidos hace 3 días
    verificar_profesor(prof, revisor)
    prof.refresh_from_db()
    assert prof.verificacion == Verificacion.VIGENTE

    dentro_de_un_mes = servicio_estado.hoy() + timedelta(days=28)
    monkeypatch.setattr(servicio_estado, "hoy", lambda: dentro_de_un_mes)
    servicio_estado.recalcular_todos(catalogo)
    prof.refresh_from_db()
    assert prof.estado == EstadoProfesor.CON_PROBLEMAS
    assert prof.verificacion == Verificacion.DESACTUALIZADA


def test_recalcular_todos_salta_las_carpetas_desaparecidas(prof, corrida, catalogo):
    completo(prof, corrida, certificado_eps={"dias": 45})
    Profesor.objects.filter(pk=prof.pk).update(
        carpeta_presente=False, estado=EstadoProfesor.COMPLETO
    )
    from apps.contrataciones.servicios.estado import recalcular_todos

    assert recalcular_todos(catalogo) == 0
    prof.refresh_from_db()
    assert prof.estado == EstadoProfesor.COMPLETO  # conserva su último estado (ADR 0004)


def test_formato_sin_diligenciar_requiere_atencion(prof, corrida, catalogo):
    completo(
        prof,
        corrida,
        formato_autorizacion_consulta_inhabilidades={"formato": {"cedula_firma": CEDULA}},
    )
    assert estado(prof, catalogo) == EstadoProfesor.COMPLETO
    assert prof.requiere_atencion


def test_formato_a_nombre_de_otra_persona_queda_con_problemas(prof, corrida, catalogo):
    datos = {"cedula_texto": OTRA, "cedula_firma": CEDULA}
    completo(prof, corrida, formato_autorizacion_consulta_inhabilidades={"formato": datos})
    assert estado(prof, catalogo) == EstadoProfesor.CON_PROBLEMAS


@pytest.mark.parametrize(
    ("decision", "tipo"), [("aprobado", None), ("corregido", "certificado_afp")]
)
def test_un_ilegible_solo_se_rechaza_o_se_descarta_en_el_modelo(
    prof, corrida, revisor, decision, tipo
):
    roto = documento(prof, corrida, Analisis.TIPO_ILEGIBLE, valido=False, nombre="roto.pdf")
    analisis = roto.analisis.get()
    revision = Revision(
        analisis=analisis,
        usuario=revisor,
        decision=decision,
        comentario="Lo leí igual.",
        tipo_corregido=TipoDocumento.objects.get(codigo=tipo) if tipo else None,
    )
    with pytest.raises(ValidationError, match="solo se puede rechazar o descartar"):
        revision.save()
    for permitida in ("rechazado", "descartado"):
        Revision(
            analisis=analisis, usuario=revisor, decision=permitida, comentario="Pedir otro."
        ).save()
