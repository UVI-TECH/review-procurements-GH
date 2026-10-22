"""Helper registrar(usuario, accion, objeto, detalle)."""

import pytest
from django.contrib.auth.models import AnonymousUser
from django.contrib.contenttypes.models import ContentType
from django.db.models import ProtectedError

from apps.contrataciones.models import Profesor
from apps.cuentas.auditoria import registrar
from apps.cuentas.models import RegistroAuditoria

pytestmark = pytest.mark.django_db


def test_registra_accion_sobre_un_objeto(usuario, profesor):
    registro = registrar(usuario, "verificar_profesor", profesor, {"nota": "ok"})

    registro.refresh_from_db()
    assert registro.usuario == usuario
    assert registro.accion == "verificar_profesor"
    assert registro.content_type == ContentType.objects.get_for_model(Profesor)
    assert registro.objeto_id == str(profesor.pk)
    assert registro.objeto == profesor
    assert registro.objeto_repr == str(profesor)
    assert registro.detalle == {"nota": "ok"}
    assert registro.fecha is not None


def test_registra_accion_sin_objeto_ni_detalle(usuario):
    registro = registrar(usuario, "inicio_sesion")
    assert registro.content_type is None
    assert registro.objeto_id == ""
    assert registro.objeto_repr == ""
    assert registro.detalle == {}


def test_accion_del_sistema_sin_usuario():
    registro = registrar(None, "respaldo_programado")
    assert registro.usuario is None


def test_inicio_fallido_con_usuario_anonimo_va_sin_usuario():
    registro = registrar(AnonymousUser(), "inicio_sesion_fallido", detalle={"usuario": "intento"})
    assert registro.usuario is None
    assert registro.detalle == {"usuario": "intento"}


def test_no_se_borra_usuario_con_registros(usuario):
    registrar(usuario, "inicio_sesion")
    with pytest.raises(ProtectedError):
        usuario.delete()


def test_no_se_borra_content_type_con_registros(usuario, profesor):
    registrar(usuario, "ver", profesor)
    with pytest.raises(ProtectedError):
        ContentType.objects.get_for_model(Profesor).delete()


def test_registros_mas_recientes_primero(usuario):
    primero = registrar(usuario, "uno")
    segundo = registrar(usuario, "dos")
    assert list(RegistroAuditoria.objects.all()) == [segundo, primero]
