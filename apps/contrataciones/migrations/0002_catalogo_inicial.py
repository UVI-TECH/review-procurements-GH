"""Siembra los 9 tipos de DOCS de legado/revisar_contrataciones.py, con su código y orden.

Los datos van copiados aquí (no importados) para que la migración no cambie si el
código de la app cambia después.
"""

from django.db import migrations

TIPOS = [
    ("certificado_antecedentes_disciplinarios", "Antecedentes Disciplinarios (Procuraduría)"),
    ("boletin_responsabilidades_fiscales", "Responsabilidades Fiscales (Contraloría)"),
    ("certificado_antecedentes_judiciales", "Antecedentes Judiciales (Policía)"),
    ("certificado_registro_nacional_medidas_correctivas", "Medidas Correctivas"),
    ("formato_autorizacion_consulta_inhabilidades", "Formato Autorización Consulta"),
    ("consulta_inhabilidades_delitos_sexuales", "Consulta Inhabilidades Delitos Sexuales"),
    ("certificado_registro_deudores_morosos", "REDAM (Deudores Morosos)"),
    ("certificados_eps_afp", "Certificados EPS/AFP"),
    ("certificado_medico_laboral", "Certificado Médico Laboral"),
]

CON_FIRMA = "formato_autorizacion_consulta_inhabilidades"

# El examen DOTC y el certificado médico laboral son el mismo documento operativo.
ALIAS = [("examen_medico_laboral_dotc", "certificado_medico_laboral")]


def sembrar(apps, schema_editor):
    TipoDocumento = apps.get_model("contrataciones", "TipoDocumento")
    AliasTipoDocumento = apps.get_model("contrataciones", "AliasTipoDocumento")
    for orden, (codigo, etiqueta) in enumerate(TIPOS, start=1):
        TipoDocumento.objects.create(
            codigo=codigo,
            etiqueta=etiqueta,
            orden=orden,
            obligatorio=True,
            activo=True,
            requiere_firma=codigo == CON_FIRMA,
        )
    for alias, codigo in ALIAS:
        AliasTipoDocumento.objects.create(
            codigo=alias, tipo=TipoDocumento.objects.get(codigo=codigo)
        )


def quitar(apps, schema_editor):
    AliasTipoDocumento = apps.get_model("contrataciones", "AliasTipoDocumento")
    TipoDocumento = apps.get_model("contrataciones", "TipoDocumento")
    AliasTipoDocumento.objects.filter(codigo__in=[a for a, _ in ALIAS]).delete()
    TipoDocumento.objects.filter(codigo__in=[c for c, _ in TIPOS]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("contrataciones", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(sembrar, quitar),
    ]
