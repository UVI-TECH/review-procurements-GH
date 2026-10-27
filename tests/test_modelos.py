"""Restricciones del modelo: unicidad, PROTECT, validaciones de Revision y Corrida."""

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.utils import timezone

from apps.contrataciones.models import (
    Corrida,
    Documento,
    EstadoProfesor,
    Profesor,
    Revision,
    TipoDocumento,
)

pytestmark = pytest.mark.django_db


# --- Profesor y Documento ---


def test_profesor_empieza_sin_analizar(profesor):
    assert profesor.estado == EstadoProfesor.SIN_ANALIZAR


def test_estados_del_profesor():
    assert set(EstadoProfesor.values) == {
        "SIN_ANALIZAR",
        "COMPLETO",
        "INCOMPLETO",
        "CON_PROBLEMAS",
        "SIN_DOCUMENTOS",
        "PENDIENTE_ANALISIS",
        "ERROR",
    }


def test_carpeta_de_profesor_unica(profesor):
    with pytest.raises(IntegrityError):
        Profesor.objects.create(carpeta=profesor.carpeta, nombre="Otro")


def test_cedula_es_texto_e_indexada():
    campo = Profesor._meta.get_field("cedula")
    assert campo.get_internal_type() == "CharField"
    assert campo.db_index


def test_cedula_admite_formato_de_extranjeria():
    profesor = Profesor.objects.create(carpeta="EXTRANJERO", nombre="Ext", cedula="E-0012345")
    profesor.refresh_from_db()
    assert profesor.cedula == "E-0012345"


def test_verificacion_exige_usuario_y_fecha_juntos(profesor, usuario):
    profesor.verificado_por = usuario
    with pytest.raises(IntegrityError), transaction.atomic():
        profesor.save()


def test_documento_unico_por_profesor_y_ruta(documento):
    with pytest.raises(IntegrityError):
        Documento.objects.create(
            profesor=documento.profesor,
            ruta_relativa=documento.ruta_relativa,
            nombre_archivo="otro.pdf",
            sha256="b" * 64,
            tamano=1,
            modificado_en=timezone.now(),
        )


def test_misma_ruta_en_otro_profesor_es_valida(documento):
    otro = Profesor.objects.create(carpeta="PROFESOR FICTICIO DOS", nombre="Dos")
    Documento.objects.create(
        profesor=otro,
        ruta_relativa=documento.ruta_relativa,
        nombre_archivo=documento.nombre_archivo,
        sha256=documento.sha256,
        tamano=1,
        modificado_en=timezone.now(),
    )


def test_sha256_indexado():
    assert Documento._meta.get_field("sha256").db_index
    assert Documento._meta.get_field("sha256").max_length == 64


def test_documento_nuevo_esta_presente(documento):
    assert documento.presente is True


# --- PROTECT: nada borra en cascada el historial ---


def test_no_se_borra_profesor_con_documentos(documento):
    with pytest.raises(ProtectedError):
        documento.profesor.delete()


def test_no_se_borra_documento_con_analisis(analisis):
    with pytest.raises(ProtectedError):
        analisis.documento.delete()


def test_no_se_borra_corrida_con_analisis(analisis):
    with pytest.raises(ProtectedError):
        analisis.corrida.delete()


def test_no_se_borra_profesor_con_corridas(profesor, usuario):
    Corrida.objects.create(
        iniciada_por=usuario, alcance=Corrida.Alcance.UN_PROFESOR, profesor=profesor
    )
    with pytest.raises(ProtectedError):
        profesor.delete()


def test_no_se_borra_usuario_con_corridas(corrida):
    with pytest.raises(ProtectedError):
        corrida.iniciada_por.delete()


def test_no_se_borra_usuario_con_revisiones(analisis, crear_usuario):
    revisor = crear_usuario("revisor")
    Revision.objects.create(analisis=analisis, usuario=revisor, decision="aprobado")
    with pytest.raises(ProtectedError):
        revisor.delete()


def test_no_se_borra_usuario_que_verifico_un_profesor(profesor, crear_usuario):
    revisor = crear_usuario("revisor")
    profesor.verificado_por = revisor
    profesor.verificado_en = timezone.now()
    profesor.save()
    with pytest.raises(ProtectedError):
        revisor.delete()


def test_no_se_borra_tipo_usado_en_una_revision(analisis, usuario, tipo_medico):
    Revision.objects.create(
        analisis=analisis,
        usuario=usuario,
        decision=Revision.Decision.CORREGIDO,
        tipo_corregido=tipo_medico,
        comentario="Es el examen médico",
    )
    with pytest.raises(ProtectedError):
        tipo_medico.delete()


# --- Validaciones de Revision ---


def test_aprobado_sin_comentario_es_valido(analisis, usuario):
    revision = Revision.objects.create(analisis=analisis, usuario=usuario, decision="aprobado")
    assert revision.pk


@pytest.mark.parametrize("decision", ["rechazado", "corregido"])
def test_rechazado_o_corregido_exige_comentario(analisis, usuario, tipo_medico, decision):
    revision = Revision(
        analisis=analisis,
        usuario=usuario,
        decision=decision,
        tipo_corregido=tipo_medico if decision == "corregido" else None,
        comentario="   ",
    )
    with pytest.raises(ValidationError) as error:
        revision.save()
    assert "comentario" in error.value.message_dict
    assert not Revision.objects.exists()


def test_corregido_exige_tipo_corregido(analisis, usuario):
    revision = Revision(analisis=analisis, usuario=usuario, decision="corregido", comentario="x")
    with pytest.raises(ValidationError) as error:
        revision.save()
    assert "tipo_corregido" in error.value.message_dict


@pytest.mark.parametrize("decision", ["aprobado", "rechazado"])
def test_tipo_corregido_solo_si_corregido(analisis, usuario, tipo_medico, decision):
    revision = Revision(
        analisis=analisis,
        usuario=usuario,
        decision=decision,
        tipo_corregido=tipo_medico,
        comentario="x",
    )
    with pytest.raises(ValidationError) as error:
        revision.save()
    assert "tipo_corregido" in error.value.message_dict


def test_no_se_corrige_hacia_un_tipo_inactivo(analisis, usuario):
    retirado = TipoDocumento.objects.create(
        codigo="tipo_retirado", etiqueta="Retirado", orden=50, activo=False
    )
    revision = Revision(
        analisis=analisis,
        usuario=usuario,
        decision="corregido",
        tipo_corregido=retirado,
        comentario="x",
    )
    with pytest.raises(ValidationError) as error:
        revision.save()
    assert "tipo_corregido" in error.value.message_dict


def test_la_base_de_datos_rechaza_corregido_sin_tipo(analisis, usuario):
    """La regla también vive en la BD, por si algo salta la validación del modelo."""
    with pytest.raises(IntegrityError):
        Revision.objects.bulk_create(
            [Revision(analisis=analisis, usuario=usuario, decision="corregido", comentario="x")]
        )


def test_la_base_de_datos_rechaza_rechazado_sin_comentario(analisis, usuario):
    with pytest.raises(IntegrityError):
        Revision.objects.bulk_create(
            [Revision(analisis=analisis, usuario=usuario, decision="rechazado")]
        )


def test_revision_desplegable_solo_tipos_activos():
    campo = Revision._meta.get_field("tipo_corregido")
    assert campo.get_limit_choices_to() == {"activo": True}


# --- Corrida ---


def test_estados_y_alcances_de_corrida():
    assert set(Corrida.Estado.values) == {
        "pendiente",
        "en_proceso",
        "completada",
        "fallida",
        "cancelada",
    }
    assert set(Corrida.Alcance.values) == {
        "todos",
        "nuevos_y_modificados",
        "un_profesor",
        "desactualizados",
    }


def test_corrida_empieza_pendiente(corrida):
    assert corrida.estado == Corrida.Estado.PENDIENTE


def test_corrida_de_un_profesor_exige_profesor(usuario):
    with pytest.raises(IntegrityError):
        Corrida.objects.create(iniciada_por=usuario, alcance=Corrida.Alcance.UN_PROFESOR)


def test_corrida_de_todos_no_lleva_profesor(usuario, profesor):
    with pytest.raises(IntegrityError):
        Corrida.objects.create(
            iniciada_por=usuario, alcance=Corrida.Alcance.TODOS, profesor=profesor
        )


def test_corrida_valida_alcance_en_el_modelo(usuario):
    corrida = Corrida(iniciada_por=usuario, alcance=Corrida.Alcance.UN_PROFESOR)
    with pytest.raises(ValidationError):
        corrida.full_clean()
