"""Crea los grupos Administrador, Revisor GH y Consulta con sus permisos.

Los permisos se listan aquí (no se importan) para que la migración quede fija. Un
modelo o permiso nuevo en una fase posterior se asigna con su propia migración.
La matriz y sus motivos están en docs/decisiones/0002.
"""

from django.contrib.auth.management import create_permissions
from django.db import migrations


def _crud(modelo):
    return [f"{accion}_{modelo}" for accion in ("add", "change", "delete", "view")]


ROLES = {
    "Administrador": {
        "contrataciones": [
            *_crud("tipodocumento"),
            *_crud("aliastipodocumento"),
            *_crud("profesor"),
            *_crud("documento"),
            *_crud("corrida"),
            "view_analisis",
            "add_revision",
            "view_revision",
            "ver_pdf",
            "verificar_profesor",
            "exportar_informes",
        ],
        "cuentas": [*_crud("usuario"), "view_registroauditoria"],
        "respaldos": _crud("respaldo"),
        # Ve los grupos para asignarlos, pero no los edita: los roles salen de migraciones.
        "auth": ["view_group"],
    },
    "Revisor GH": {
        "contrataciones": [
            "view_tipodocumento",
            "view_aliastipodocumento",
            "view_profesor",
            "verificar_profesor",
            "exportar_informes",
            "view_documento",
            "ver_pdf",
            "view_analisis",
            "view_revision",
            "add_revision",
            "view_corrida",
            "add_corrida",
        ],
        "respaldos": ["view_respaldo"],
    },
    # Sin ver_pdf ni view_analisis: el análisis repite la cédula y los datos del PDF.
    "Consulta": {
        "contrataciones": ["view_profesor", "view_documento", "exportar_informes"],
    },
}


def crear_roles(apps, schema_editor):
    # En una base nueva, Django crea los permisos después de todas las migraciones
    # (señal post_migrate); aquí hacen falta antes.
    for app_config in apps.get_app_configs():
        app_config.models_module = True
        create_permissions(app_config, apps=apps, verbosity=0)
        app_config.models_module = None

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    for nombre, por_app in ROLES.items():
        grupo, _ = Group.objects.get_or_create(name=nombre)
        permisos = []
        for app_label, codenames in por_app.items():
            encontrados = list(
                Permission.objects.filter(
                    content_type__app_label=app_label, codename__in=codenames
                )
            )
            faltantes = set(codenames) - {p.codename for p in encontrados}
            if faltantes:
                raise RuntimeError(f"Permisos inexistentes en {app_label}: {sorted(faltantes)}")
            permisos.extend(encontrados)
        grupo.permissions.set(permisos)


def quitar_roles(apps, schema_editor):
    apps.get_model("auth", "Group").objects.filter(name__in=ROLES).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("cuentas", "0002_registroauditoria"),
        ("contrataciones", "0002_catalogo_inicial"),
        ("respaldos", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(crear_roles, quitar_roles),
    ]
