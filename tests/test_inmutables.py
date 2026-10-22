"""Analisis, Revision y RegistroAuditoria: solo se agregan filas, nunca se modifican ni borran."""

import pytest

from apps.comun.inmutables import ErrorInmutable
from apps.contrataciones.models import Analisis, Revision
from apps.cuentas.auditoria import registrar
from apps.cuentas.models import RegistroAuditoria

pytestmark = pytest.mark.django_db


@pytest.fixture
def revision(analisis, usuario):
    return Revision.objects.create(analisis=analisis, usuario=usuario, decision="aprobado")


@pytest.fixture
def registro(usuario):
    return registrar(usuario, "prueba")


@pytest.fixture(params=["analisis", "revision", "registro"])
def inmutable(request):
    return request.getfixturevalue(request.param)


def test_no_se_edita_despues_de_creado(inmutable):
    with pytest.raises(ErrorInmutable):
        inmutable.save()


def test_no_se_borra(inmutable):
    with pytest.raises(ErrorInmutable):
        inmutable.delete()
    assert type(inmutable).objects.filter(pk=inmutable.pk).exists()


def test_no_se_actualiza_en_bloque(inmutable):
    with pytest.raises(ErrorInmutable):
        type(inmutable).objects.filter(pk=inmutable.pk).update(pk=inmutable.pk)


def test_no_se_borra_en_bloque(inmutable):
    with pytest.raises(ErrorInmutable):
        type(inmutable).objects.all().delete()
    assert type(inmutable).objects.filter(pk=inmutable.pk).exists()


def test_no_se_actualiza_desde_un_manager_relacionado(analisis):
    with pytest.raises(ErrorInmutable):
        analisis.documento.analisis.update(es_valido=False)


def test_analisis_conserva_su_sha256(analisis):
    analisis.refresh_from_db()
    assert analisis.sha256 == analisis.documento.sha256


def test_se_pueden_agregar_varias_revisiones_al_mismo_analisis(revision, crear_usuario):
    Revision.objects.create(
        analisis=revision.analisis,
        usuario=crear_usuario("otro"),
        decision="rechazado",
        comentario="Cambio de criterio",
    )
    assert revision.analisis.revisiones.count() == 2


def test_modelos_inmutables_sin_permisos_de_cambio():
    for modelo in (Analisis, Revision, RegistroAuditoria):
        assert "change" not in modelo._meta.default_permissions
        assert "delete" not in modelo._meta.default_permissions
