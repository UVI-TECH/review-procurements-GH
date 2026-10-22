"""La migración de roles crea los 3 grupos con exactamente sus permisos."""

import pytest
from django.contrib.auth.models import Group

pytestmark = pytest.mark.django_db


def _crud(app, modelo):
    return {f"{app}.{accion}_{modelo}" for accion in ("add", "change", "delete", "view")}


PERMISOS_ADMINISTRADOR = (
    _crud("contrataciones", "tipodocumento")
    | _crud("contrataciones", "aliastipodocumento")
    | _crud("contrataciones", "profesor")
    | _crud("contrataciones", "documento")
    | _crud("contrataciones", "corrida")
    | _crud("cuentas", "usuario")
    | _crud("respaldos", "respaldo")
    | {
        "contrataciones.view_analisis",
        "contrataciones.add_revision",
        "contrataciones.view_revision",
        "contrataciones.ver_pdf",
        "contrataciones.verificar_profesor",
        "contrataciones.exportar_informes",
        "contrataciones.cancelar_corrida",
        "cuentas.view_registroauditoria",
        "auth.view_group",
    }
)

PERMISOS_REVISOR = {
    "contrataciones.view_tipodocumento",
    "contrataciones.view_aliastipodocumento",
    "contrataciones.view_profesor",
    "contrataciones.verificar_profesor",
    "contrataciones.exportar_informes",
    "contrataciones.view_documento",
    "contrataciones.ver_pdf",
    "contrataciones.view_analisis",
    "contrataciones.view_revision",
    "contrataciones.add_revision",
    "contrataciones.view_corrida",
    "contrataciones.add_corrida",
    "contrataciones.cancelar_corrida",
    "respaldos.view_respaldo",
}

PERMISOS_CONSULTA = {
    "contrataciones.view_profesor",
    "contrataciones.view_documento",
    "contrataciones.exportar_informes",
}

ROLES = {
    "Administrador": PERMISOS_ADMINISTRADOR,
    "Revisor GH": PERMISOS_REVISOR,
    "Consulta": PERMISOS_CONSULTA,
}

# Permisos que pueden aparecer en un has_perm de las fases siguientes.
PERMISOS_RELEVANTES = sorted(PERMISOS_ADMINISTRADOR | {"auth.change_group"})


def _permisos_del_grupo(nombre):
    grupo = Group.objects.get(name=nombre)
    return {
        f"{p.content_type.app_label}.{p.codename}"
        for p in grupo.permissions.select_related("content_type")
    }


def test_existen_exactamente_los_3_grupos():
    assert set(Group.objects.values_list("name", flat=True)) == set(ROLES)


@pytest.mark.parametrize("rol", ROLES)
def test_grupo_tiene_exactamente_sus_permisos(rol):
    assert _permisos_del_grupo(rol) == ROLES[rol]


def test_nadie_puede_modificar_ni_borrar_el_historial():
    """Analisis, Revision y RegistroAuditoria no tienen permisos change ni delete."""
    from django.contrib.auth.models import Permission

    codenames = set(
        Permission.objects.filter(
            codename__regex=r"^(change|delete)_(analisis|revision|registroauditoria)$"
        ).values_list("codename", flat=True)
    )
    assert codenames == set()


@pytest.mark.parametrize("rol", ROLES)
@pytest.mark.parametrize("permiso", PERMISOS_RELEVANTES)
def test_has_perm_por_rol(crear_usuario, rol, permiso):
    usuario = crear_usuario(grupo=rol)
    assert usuario.has_perm(permiso) is (permiso in ROLES[rol])


def test_consulta_no_ve_pdf_ni_analisis_ni_revisiones(crear_usuario):
    usuario = crear_usuario(grupo="Consulta")
    assert not usuario.has_perm("contrataciones.ver_pdf")
    assert not usuario.has_perm("contrataciones.view_analisis")
    assert not usuario.has_perm("contrataciones.view_revision")


def test_revisor_no_edita_catalogo_ni_usuarios_ni_ve_auditoria(crear_usuario):
    usuario = crear_usuario(grupo="Revisor GH")
    assert not usuario.has_perm("contrataciones.change_tipodocumento")
    assert not usuario.has_perm("contrataciones.add_aliastipodocumento")
    assert not usuario.has_perm("cuentas.view_usuario")
    assert not usuario.has_perm("cuentas.change_usuario")
    assert not usuario.has_perm("cuentas.view_registroauditoria")


def test_consulta_no_cancela_corridas(crear_usuario):
    assert not crear_usuario(grupo="Consulta").has_perm("contrataciones.cancelar_corrida")
