"""Un Administrador gestiona usuarios y grupos, pero no otorga superusuario ni permisos sueltos."""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.urls import reverse

pytestmark = pytest.mark.django_db


@pytest.fixture
def administrador(crear_usuario):
    return crear_usuario("admin.prueba", grupo="Administrador")


@pytest.fixture
def cliente_admin(client, administrador):
    client.force_login(administrador)
    return client


def _cambiar(usuario):
    return reverse("admin:cuentas_usuario_change", args=[usuario.pk])


def _datos(usuario, **extra):
    """POST completo del formulario de cambio de usuario."""
    return {
        "username": usuario.username,
        "first_name": "",
        "last_name": "",
        "email": "",
        "is_active": "on",
        "is_staff": "on",
        "date_joined_0": "2026-10-22",
        "date_joined_1": "08:00:00",
        "initial-date_joined_0": "2026-10-22",
        "initial-date_joined_1": "08:00:00",
        **extra,
    }


def _guardado(respuesta):
    """El admin aceptó el formulario (y no redirigió al login)."""
    return respuesta.status_code == 302 and "/login/" not in respuesta.url


def _permiso_suelto():
    return Permission.objects.get(codename="change_group")


# --- is_staff automático ---


@pytest.mark.parametrize("rol", ["Administrador", "Revisor GH"])
def test_asignar_rol_con_acceso_al_admin_marca_is_staff(crear_usuario, rol):
    usuario = crear_usuario("nuevo")
    usuario.groups.add(Group.objects.get(name=rol))
    usuario.refresh_from_db()
    assert usuario.is_staff


def test_asignar_desde_el_grupo_tambien_marca_is_staff(crear_usuario):
    usuario = crear_usuario("nuevo")
    Group.objects.get(name="Revisor GH").user_set.add(usuario)
    usuario.refresh_from_db()
    assert usuario.is_staff


def test_consulta_no_recibe_is_staff(crear_usuario):
    usuario = crear_usuario("nuevo", grupo="Consulta")
    usuario.refresh_from_db()
    assert not usuario.is_staff


def test_asignar_rol_desde_el_admin_marca_is_staff(cliente_admin, crear_usuario):
    usuario = crear_usuario("nuevo")
    datos = _datos(usuario, groups=[Group.objects.get(name="Revisor GH").pk])
    del datos["is_staff"]
    assert _guardado(cliente_admin.post(_cambiar(usuario), datos))
    usuario.refresh_from_db()
    assert usuario.is_staff


# --- Sin escalamiento ---


def test_administrador_no_ve_campos_de_superusuario_ni_permisos(cliente_admin, crear_usuario):
    formulario = cliente_admin.get(_cambiar(crear_usuario("otro"))).context["adminform"].form
    assert "is_superuser" not in formulario.fields
    assert "user_permissions" not in formulario.fields
    assert "groups" in formulario.fields
    assert "is_staff" in formulario.fields


def test_administrador_no_se_hace_superusuario_con_post_manual(cliente_admin, administrador):
    datos = _datos(
        administrador,
        groups=[Group.objects.get(name="Administrador").pk],
        is_superuser="on",
        user_permissions=[_permiso_suelto().pk],
    )
    assert _guardado(cliente_admin.post(_cambiar(administrador), datos))
    administrador.refresh_from_db()
    assert not administrador.is_superuser
    assert not administrador.user_permissions.exists()
    assert not administrador.has_perm("auth.change_group")


def test_administrador_no_otorga_superusuario_ni_permisos_a_otro(cliente_admin, crear_usuario):
    otro = crear_usuario("otro")
    datos = _datos(otro, is_superuser="on", user_permissions=[_permiso_suelto().pk])
    assert _guardado(cliente_admin.post(_cambiar(otro), datos))
    otro.refresh_from_db()
    assert not otro.is_superuser
    assert not otro.user_permissions.exists()


def test_administrador_no_crea_superusuarios(cliente_admin):
    respuesta = cliente_admin.post(
        reverse("admin:cuentas_usuario_add"),
        {
            "username": "nuevo",
            "password1": "una-frase-larga-de-prueba-9",
            "password2": "una-frase-larga-de-prueba-9",
            "usable_password": "true",
            "is_superuser": "on",
        },
    )
    assert _guardado(respuesta)
    assert not get_user_model().objects.get(username="nuevo").is_superuser


def test_administrador_no_edita_una_cuenta_superusuario(cliente_admin, crear_usuario):
    jefe = crear_usuario("jefe", is_superuser=True, is_staff=True)
    respuesta = cliente_admin.post(_cambiar(jefe), _datos(jefe, username="tomada"))
    assert respuesta.status_code == 403
    jefe.refresh_from_db()
    assert jefe.username == "jefe"


def test_administrador_no_cambia_la_clave_de_un_superusuario(cliente_admin, crear_usuario):
    jefe = crear_usuario("jefe", is_superuser=True, is_staff=True)
    respuesta = cliente_admin.post(
        reverse("admin:auth_user_password_change", args=[jefe.pk]),
        {"password1": "otra-frase-larga-9x", "password2": "otra-frase-larga-9x"},
    )
    assert respuesta.status_code == 403
    jefe.refresh_from_db()
    assert not jefe.has_usable_password()


def test_administrador_no_borra_un_superusuario(cliente_admin, crear_usuario):
    jefe = crear_usuario("jefe", is_superuser=True, is_staff=True)
    url = reverse("admin:cuentas_usuario_delete", args=[jefe.pk])
    assert cliente_admin.post(url, {"post": "yes"}).status_code == 403
    assert get_user_model().objects.filter(pk=jefe.pk).exists()


def test_superusuario_si_gestiona_superusuario_y_permisos(client, crear_usuario):
    client.force_login(crear_usuario("raiz", is_superuser=True, is_staff=True))
    otro = crear_usuario("otro")
    formulario = client.get(_cambiar(otro)).context["adminform"].form
    assert "is_superuser" in formulario.fields
    assert "user_permissions" in formulario.fields
