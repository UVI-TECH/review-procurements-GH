"""Requisitos de Gestión Humana 2026-2 (ADR 0006).

- certificados_eps_afp se divide en certificado_eps y certificado_afp, ambos obligatorios.
  El tipo viejo queda inactivo: tiene historial (análisis y revisiones), no se borra.
- Las alternativas de pensión son alias de certificado_afp con etiqueta propia y sin
  vigencia: resolución de pensión por vejez y carta de bono pensional.
- Vigencia de 30 días en los certificados que la tienen según Gestión Humana.

Los datos van copiados aquí (no importados) para que la migración no cambie si el
código de la app cambia después.
"""

from django.db import migrations

VIEJO = "certificados_eps_afp"
NUEVOS = [
    ("certificado_eps", "Certificado de EPS", 8),
    ("certificado_afp", "Certificado de fondo de pensiones (AFP)", 9),
]
MEDICO = "certificado_medico_laboral"
CON_VIGENCIA_30 = [
    "certificado_antecedentes_disciplinarios",
    "boletin_responsabilidades_fiscales",
    "certificado_antecedentes_judiciales",
    "certificado_registro_nacional_medidas_correctivas",
    "consulta_inhabilidades_delitos_sexuales",
    "certificado_registro_deudores_morosos",
    "certificado_eps",
    "certificado_afp",
]
ALIAS_PENSION = [
    ("resolucion_pension_vejez", "Resolución o certificado de pensión por vejez", ""),
    (
        "carta_bono_pensional",
        "Carta de bono pensional",
        "Carta de bono pensional: declaración del profesor, no certificado de una entidad",
    ),
]
ETIQUETA_DOTC = ("examen_medico_laboral_dotc", "Examen médico laboral DOTC")


def aplicar(apps, schema_editor):
    TipoDocumento = apps.get_model("contrataciones", "TipoDocumento")
    AliasTipoDocumento = apps.get_model("contrataciones", "AliasTipoDocumento")

    TipoDocumento.objects.filter(codigo=VIEJO).update(activo=False, orden=90)
    TipoDocumento.objects.filter(codigo=MEDICO).update(orden=10)
    for codigo, etiqueta, orden in NUEVOS:
        TipoDocumento.objects.create(
            codigo=codigo, etiqueta=etiqueta, orden=orden, obligatorio=True, activo=True
        )
    TipoDocumento.objects.filter(codigo__in=CON_VIGENCIA_30).update(vigencia_dias=30)

    afp = TipoDocumento.objects.get(codigo="certificado_afp")
    for codigo, etiqueta, observacion in ALIAS_PENSION:
        AliasTipoDocumento.objects.create(
            tipo=afp,
            codigo=codigo,
            etiqueta=etiqueta,
            hereda_vigencia=False,
            vigencia_dias=None,
            observacion=observacion,
        )
    AliasTipoDocumento.objects.filter(codigo=ETIQUETA_DOTC[0]).update(etiqueta=ETIQUETA_DOTC[1])


def revertir(apps, schema_editor):
    TipoDocumento = apps.get_model("contrataciones", "TipoDocumento")
    AliasTipoDocumento = apps.get_model("contrataciones", "AliasTipoDocumento")

    AliasTipoDocumento.objects.filter(codigo__in=[c for c, _, _ in ALIAS_PENSION]).delete()
    TipoDocumento.objects.filter(codigo__in=[c for c, _, _ in NUEVOS]).delete()
    TipoDocumento.objects.update(vigencia_dias=None)
    TipoDocumento.objects.filter(codigo=VIEJO).update(activo=True, orden=8)
    TipoDocumento.objects.filter(codigo=MEDICO).update(orden=9)


class Migration(migrations.Migration):
    dependencies = [("contrataciones", "0007_requisitos_gh")]

    operations = [migrations.RunPython(aplicar, revertir)]
