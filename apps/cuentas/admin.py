from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import RegistroAuditoria, Usuario


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    pass


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
