"""El Administrador gestiona catálogo y usuarios desde el admin; el historial es de solo lectura."""

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.contrataciones.models import AliasTipoDocumento, Analisis, Revision, TipoDocumento
from apps.cuentas.models import RegistroAuditoria
from apps.respaldos.models import Respaldo

pytestmark = pytest.mark.django_db

MODELOS_DEL_DOMINIO = {
    "contrataciones.TipoDocumento",
    "contrataciones.Profesor",
    "contrataciones.Documento",
    "contrataciones.Analisis",
    "contrataciones.Revision",
    "contrataciones.Corrida",
    "cuentas.Usuario",
    "cuentas.RegistroAuditoria",
    "respaldos.Respaldo",
}


@pytest.fixture
def cliente_admin(client, crear_usuario):
    """Un Administrador de verdad: staff con el grupo, no superusuario."""
    client.force_login(crear_usuario("admin.prueba", grupo="Administrador", is_staff=True))
    return client


def _url(modelo, vista, *args):
    return reverse(f"admin:{modelo._meta.app_label}_{modelo._meta.model_name}_{vista}", args=args)


def test_todos_los_modelos_del_dominio_registrados():
    registrados = {modelo._meta.label for modelo in admin.site._registry}
    assert MODELOS_DEL_DOMINIO <= registrados


@pytest.mark.parametrize("modelo", list(admin.site._registry), ids=lambda m: m._meta.label)
def test_changelist_carga_para_el_administrador(cliente_admin, modelo):
    assert cliente_admin.get(_url(modelo, "changelist")).status_code == 200


@pytest.mark.parametrize("modelo", [TipoDocumento, get_user_model()], ids=["catalogo", "usuario"])
def test_formulario_de_alta_carga(cliente_admin, modelo):
    assert cliente_admin.get(_url(modelo, "add")).status_code == 200


def test_administrador_crea_tipo_con_alias(cliente_admin):
    respuesta = cliente_admin.post(
        _url(TipoDocumento, "add"),
        {
            "codigo": "hoja_de_vida",
            "etiqueta": "Hoja de vida",
            "orden": 10,
            "obligatorio": "",
            "activo": "on",
            "alias-TOTAL_FORMS": "1",
            "alias-INITIAL_FORMS": "0",
            "alias-0-codigo": "hoja_vida_sigep",
        },
    )
    assert respuesta.status_code == 302
    tipo = TipoDocumento.objects.get(codigo="hoja_de_vida")
    assert tipo.obligatorio is False
    assert AliasTipoDocumento.objects.get(codigo="hoja_vida_sigep").tipo == tipo


def test_administrador_edita_el_catalogo(cliente_admin, tipo_medico):
    alias = tipo_medico.alias.get()
    respuesta = cliente_admin.post(
        _url(TipoDocumento, "change", tipo_medico.pk),
        {
            "codigo": tipo_medico.codigo,
            "etiqueta": "Certificado médico ocupacional",
            "orden": tipo_medico.orden,
            "obligatorio": "on",
            "activo": "on",
            "alias-TOTAL_FORMS": "1",
            "alias-INITIAL_FORMS": "1",
            "alias-0-id": alias.pk,
            "alias-0-tipo": tipo_medico.pk,
            "alias-0-codigo": alias.codigo,
        },
    )
    assert respuesta.status_code == 302
    tipo_medico.refresh_from_db()
    assert tipo_medico.etiqueta == "Certificado médico ocupacional"


def test_administrador_crea_usuario(cliente_admin):
    respuesta = cliente_admin.post(
        _url(get_user_model(), "add"),
        {
            "username": "revisor.nuevo",
            "password1": "una-clave-larga-y-segura-9",
            "password2": "una-clave-larga-y-segura-9",
            "usable_password": "true",
        },
    )
    assert respuesta.status_code == 302
    assert get_user_model().objects.filter(username="revisor.nuevo").exists()


@pytest.mark.parametrize("modelo", [Analisis, RegistroAuditoria])
def test_historial_de_solo_lectura(rf, crear_usuario, modelo):
    request = rf.get("/")
    request.user = crear_usuario("su", is_staff=True, is_superuser=True)
    modelo_admin = admin.site._registry[modelo]
    assert not modelo_admin.has_add_permission(request)
    assert not modelo_admin.has_change_permission(request)
    assert not modelo_admin.has_delete_permission(request)


def test_revisiones_se_crean_pero_no_se_editan_ni_borran(rf, crear_usuario):
    request = rf.get("/")
    request.user = crear_usuario("su", is_staff=True, is_superuser=True)
    modelo_admin = admin.site._registry[Revision]
    assert modelo_admin.has_add_permission(request)
    assert not modelo_admin.has_change_permission(request)
    assert not modelo_admin.has_delete_permission(request)


def test_revision_desde_el_admin_queda_a_nombre_de_quien_la_crea(cliente_admin, analisis):
    respuesta = cliente_admin.post(
        _url(Revision, "add"),
        {"analisis": analisis.pk, "decision": "aprobado", "comentario": ""},
    )
    assert respuesta.status_code == 302
    assert Revision.objects.get().usuario.username == "admin.prueba"


def test_revisor_no_entra_al_catalogo_para_editar(client, crear_usuario, tipo_medico):
    client.force_login(crear_usuario("revisor", grupo="Revisor GH", is_staff=True))
    respuesta = client.post(_url(TipoDocumento, "change", tipo_medico.pk), {"etiqueta": "x"})
    assert respuesta.status_code == 403


def test_respaldo_registrado():
    assert Respaldo in admin.site._registry


@pytest.mark.parametrize("superusuario", [False, True], ids=["administrador", "superusuario"])
def test_la_cancelacion_no_se_edita_desde_el_admin(client, crear_usuario, superusuario):
    """La única vía para cancelar es el comando, que audita (la Fase 4 tendrá su vista)."""
    from apps.contrataciones.models import Corrida

    usuario = crear_usuario(
        "admin.prueba", grupo="Administrador", is_staff=True, is_superuser=superusuario
    )
    client.force_login(usuario)
    corrida = Corrida.objects.create(iniciada_por=usuario, alcance=Corrida.Alcance.TODOS)
    formulario = client.get(_url(Corrida, "change", corrida.pk)).context["adminform"].form
    for campo in (
        "cancelacion_solicitada",
        "cancelacion_solicitada_por",
        "cancelacion_solicitada_en",
    ):
        assert campo not in formulario.fields
