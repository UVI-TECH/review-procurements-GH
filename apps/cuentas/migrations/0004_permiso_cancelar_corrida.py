"""Asigna contrataciones.cancelar_corrida al Administrador y al Revisor GH (Fase 3).

Consulta no cancela corridas. Como en 0003_roles, los permisos se crean antes porque en
una base nueva Django los crea después de todas las migraciones.
"""

from django.contrib.auth.management import create_permissions
from django.db import migrations

GRUPOS = ("Administrador", "Revisor GH")


def _permiso(apps):
    for app_config in apps.get_app_configs():
        app_config.models_module = True
        create_permissions(app_config, apps=apps, verbosity=0)
        app_config.models_module = None
    return apps.get_model("auth", "Permission").objects.get(
        content_type__app_label="contrataciones", codename="cancelar_corrida"
    )


def asignar(apps, schema_editor):
    permiso = _permiso(apps)
    for grupo in apps.get_model("auth", "Group").objects.filter(name__in=GRUPOS):
        grupo.permissions.add(permiso)


def quitar(apps, schema_editor):
    permiso = _permiso(apps)
    for grupo in apps.get_model("auth", "Group").objects.filter(name__in=GRUPOS):
        grupo.permissions.remove(permiso)


class Migration(migrations.Migration):
    dependencies = [
        ("cuentas", "0003_roles"),
        ("contrataciones", "0004_corridas_y_escaneo"),
    ]

    operations = [
        migrations.RunPython(asignar, quitar),
    ]
