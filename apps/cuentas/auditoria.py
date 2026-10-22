"""Única puerta de entrada al registro de auditoría."""

from django.contrib.contenttypes.models import ContentType

from .models import RegistroAuditoria


def registrar(usuario, accion, objeto=None, detalle=None):
    """Agrega un registro. usuario puede ser None o anónimo (sistema, inicio fallido)."""
    registro = RegistroAuditoria(
        usuario=usuario if getattr(usuario, "is_authenticated", False) else None,
        accion=accion,
        detalle=detalle or {},
    )
    if objeto is not None:
        registro.content_type = ContentType.objects.get_for_model(objeto)
        registro.objeto_id = str(objeto.pk)
        registro.objeto_repr = str(objeto)[:200]
    registro.save()
    return registro
