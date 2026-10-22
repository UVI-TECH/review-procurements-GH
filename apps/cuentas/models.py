from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from apps.comun.inmutables import ModeloInmutable


class Usuario(AbstractUser):
    """Usuario propio desde la primera migración, para extenderlo sin migraciones costosas.

    Los campos de Entra ID (oid, etc.) se agregan en la Fase 8.
    """

    class Meta:
        verbose_name = "usuario"
        verbose_name_plural = "usuarios"


class RegistroAuditoria(ModeloInmutable):
    """Quién vio, aprobó o cambió qué. Solo se agregan filas; se crean con auditoria.registrar."""

    # Nulo en acciones del sistema (worker, respaldo programado) y en inicios fallidos.
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="registros_auditoria",
    )
    accion = models.CharField("acción", max_length=50, db_index=True)
    content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT, null=True, blank=True)
    objeto_id = models.CharField(max_length=64, blank=True)
    objeto = GenericForeignKey("content_type", "objeto_id")
    # Texto del objeto al momento de la acción, por si después cambia.
    objeto_repr = models.CharField("objeto", max_length=200, blank=True)
    detalle = models.JSONField(default=dict, blank=True)
    fecha = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-fecha", "-id"]
        verbose_name = "registro de auditoría"
        verbose_name_plural = "registros de auditoría"
        default_permissions = ("view",)
        indexes = [models.Index(fields=["content_type", "objeto_id"], name="auditoria_objeto_idx")]

    def __str__(self):
        return f"{self.fecha:%Y-%m-%d %H:%M} {self.usuario or 'sistema'}: {self.accion}"
