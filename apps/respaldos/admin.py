from django.contrib import admin

from .models import Respaldo


@admin.register(Respaldo)
class RespaldoAdmin(admin.ModelAdmin):
    list_display = ["fecha", "origen", "estado", "tamano", "ruta"]
    list_filter = ["estado", "origen"]
    date_hierarchy = "fecha"
