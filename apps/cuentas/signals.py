from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.db.models.signals import m2m_changed
from django.dispatch import receiver

from .auditoria import registrar
from .models import Usuario

# Roles que trabajan desde el admin; Consulta no entra.
ROLES_CON_ACCESO_AL_ADMIN = {"Administrador", "Revisor GH"}


@receiver(m2m_changed, sender=Usuario.groups.through)
def marcar_staff_al_asignar_rol(sender, instance, action, reverse, pk_set, **kwargs):
    """Al asignar un rol con acceso al admin se marca is_staff; quitarlo no lo desmarca."""
    if action != "post_add" or not pk_set:
        return
    if reverse:  # group.user_set.add(...): instance es el grupo y pk_set, usuarios
        if instance.name in ROLES_CON_ACCESO_AL_ADMIN:
            Usuario.objects.filter(pk__in=pk_set, is_staff=False).update(is_staff=True)
    elif (
        not instance.is_staff
        and Group.objects.filter(pk__in=pk_set, name__in=ROLES_CON_ACCESO_AL_ADMIN).exists()
    ):
        instance.is_staff = True
        instance.save(update_fields=["is_staff"])


@receiver(user_logged_in)
def auditar_inicio_de_sesion(sender, request, user, **kwargs):
    registrar(user, "inicio_sesion")


@receiver(user_logged_out)
def auditar_cierre_de_sesion(sender, request, user, **kwargs):
    registrar(user, "cierre_sesion")  # user es None si la sesión ya había expirado


@receiver(user_login_failed)
def auditar_inicio_fallido(sender, credentials, request=None, **kwargs):
    # Solo el nombre intentado: Django ya oculta la contraseña, y no se guarda.
    registrar(None, "inicio_sesion_fallido", detalle={"usuario": credentials.get("username", "")})
