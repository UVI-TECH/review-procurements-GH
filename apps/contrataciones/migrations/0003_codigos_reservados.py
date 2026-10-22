"""Reserva los códigos "otro", "ilegible" (motor) y "error" (legado) en el catálogo.

Si ya existe un tipo o alias con alguno de ellos, la migración se detiene con un
mensaje claro: no renombra nada, porque el código puede estar en revisiones históricas.
"""

from django.db import migrations, models

RESERVADOS = ("otro", "ilegible", "error")


def verificar_codigos_reservados(apps, schema_editor):
    choques = []
    for modelo in ("TipoDocumento", "AliasTipoDocumento"):
        Modelo = apps.get_model("contrataciones", modelo)
        condicion = models.Q()
        for codigo in RESERVADOS:
            condicion |= models.Q(codigo__iexact=codigo)
        choques += [
            f"{modelo} «{codigo}»"
            for codigo in Modelo.objects.filter(condicion).values_list("codigo", flat=True)
        ]
    if choques:
        raise RuntimeError(
            f"Hay códigos reservados en el catálogo: {', '.join(choques)}. Los códigos "
            f"{', '.join(RESERVADOS)} están reservados para el motor: renómbralo desde el "
            "admin y vuelve a ejecutar migrate."
        )


class Migration(migrations.Migration):
    dependencies = [
        ("contrataciones", "0002_catalogo_inicial"),
    ]

    operations = [
        migrations.RunPython(verificar_codigos_reservados, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="aliastipodocumento",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("codigo__iexact", "otro"), _negated=True),
                    models.Q(("codigo__iexact", "ilegible"), _negated=True),
                    models.Q(("codigo__iexact", "error"), _negated=True),
                ),
                name="alias_codigo_no_reservado",
                violation_error_message="Ese código está reservado para el motor.",
            ),
        ),
        migrations.AddConstraint(
            model_name="tipodocumento",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("codigo__iexact", "otro"), _negated=True),
                    models.Q(("codigo__iexact", "ilegible"), _negated=True),
                    models.Q(("codigo__iexact", "error"), _negated=True),
                ),
                name="tipodocumento_codigo_no_reservado",
                violation_error_message="Ese código está reservado para el motor.",
            ),
        ),
    ]
