from django.contrib.auth.models import AbstractUser


class Usuario(AbstractUser):
    """Usuario propio desde la primera migración, para extenderlo sin migraciones costosas.

    Los campos de Entra ID (oid, etc.) se agregan en la Fase 8.
    """

    class Meta:
        verbose_name = "usuario"
        verbose_name_plural = "usuarios"
