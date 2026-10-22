from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import RegistroAuditoria, Usuario


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    """Solo un superusuario otorga superusuario o permisos sueltos, o toca a otro superusuario.

    Un Administrador gestiona usuarios y les asigna roles (grupos), sin salirse de ellos.
    """

    def get_readonly_fields(self, request, obj=None):
        campos = super().get_readonly_fields(request, obj)
        if not request.user.is_superuser:
            # Al ser de solo lectura salen del formulario: un POST manual se ignora.
            campos = [*campos, "is_superuser", "user_permissions"]
        return campos

    def has_change_permission(self, request, obj=None):
        # Cubre también el cambio de contraseña, que comprueba este mismo permiso.
        if obj is not None and obj.is_superuser and not request.user.is_superuser:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.is_superuser and not request.user.is_superuser:
            return False
        return super().has_delete_permission(request, obj)


@admin.register(RegistroAuditoria)
class RegistroAuditoriaAdmin(admin.ModelAdmin):
    """Solo lectura, también para el superusuario."""

    list_display = ["fecha", "usuario", "accion", "content_type", "objeto_repr"]
    list_filter = ["accion", "content_type"]
    search_fields = ["accion", "objeto_repr", "usuario__username"]
    date_hierarchy = "fecha"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
