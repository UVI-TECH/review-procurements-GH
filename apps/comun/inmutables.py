"""Modelos de solo agregar: una fila creada no se modifica ni se borra desde el ORM.

Cubre save(), delete() y las operaciones en bloque del QuerySet (update, bulk_update,
delete), también desde managers relacionados. Las borradas en cascada desde otros
modelos las impide on_delete=PROTECT en las FK. No hay vía para saltarse esto: la
futura purga por retención irá en un comando dedicado (ver docs/decisiones/0002).
"""

from django.db import models


class ErrorInmutable(Exception):
    """Se intentó modificar o borrar un registro de solo agregar."""


class InmutableQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ErrorInmutable(
            f"Los registros de {self.model._meta.verbose_name_plural} no se modifican."
        )

    def delete(self):
        raise ErrorInmutable(
            f"Los registros de {self.model._meta.verbose_name_plural} no se borran."
        )


class ModeloInmutable(models.Model):
    objects = InmutableQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ErrorInmutable(f"{self._meta.verbose_name.capitalize()} no se modifica.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ErrorInmutable(f"{self._meta.verbose_name.capitalize()} no se borra.")
