from django.contrib import admin

from .models import (
    AliasTipoDocumento,
    Analisis,
    Corrida,
    Documento,
    Profesor,
    Revision,
    TipoDocumento,
)


class AliasInline(admin.TabularInline):
    model = AliasTipoDocumento
    extra = 0


@admin.register(TipoDocumento)
class TipoDocumentoAdmin(admin.ModelAdmin):
    list_display = ["orden", "codigo", "etiqueta", "obligatorio", "activo", "requiere_firma"]
    list_display_links = ["codigo"]
    list_filter = ["activo", "obligatorio"]
    inlines = [AliasInline]


@admin.register(Profesor)
class ProfesorAdmin(admin.ModelAdmin):
    list_display = ["nombre", "cedula", "carpeta", "estado", "verificado_por", "verificado_en"]
    list_filter = ["estado"]
    search_fields = ["nombre", "cedula", "carpeta"]
    raw_id_fields = ["verificado_por"]


@admin.register(Documento)
class DocumentoAdmin(admin.ModelAdmin):
    list_display = ["ruta_relativa", "profesor", "tamano", "modificado_en", "presente"]
    list_filter = ["presente"]
    search_fields = ["ruta_relativa", "profesor__nombre", "profesor__cedula", "sha256"]
    raw_id_fields = ["profesor"]


@admin.register(Corrida)
class CorridaAdmin(admin.ModelAdmin):
    list_display = ["id", "creada_en", "iniciada_por", "alcance", "estado", "total_documentos"]
    list_filter = ["estado", "alcance"]
    raw_id_fields = ["iniciada_por", "profesor"]
    # Cancelar solo por el comando cancelar_corrida, que audita (ADR 0004); también
    # para el superusuario.
    readonly_fields = [
        "cancelacion_solicitada",
        "cancelacion_solicitada_por",
        "cancelacion_solicitada_en",
    ]


@admin.register(Analisis)
class AnalisisAdmin(admin.ModelAdmin):
    """Solo lectura, también para el superusuario: el análisis es inmutable."""

    list_display = ["id", "documento", "tipo_detectado", "es_valido", "modelo", "creado_en"]
    list_filter = ["es_valido", "tipo_detectado"]
    search_fields = ["documento__ruta_relativa", "sha256"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Revision)
class RevisionAdmin(admin.ModelAdmin):
    """Se agregan revisiones, nunca se editan: cambiar de opinión es crear otra."""

    list_display = ["fecha", "analisis", "usuario", "decision", "tipo_corregido"]
    list_filter = ["decision"]
    fields = ["analisis", "decision", "tipo_corregido", "comentario", "usuario", "fecha"]
    readonly_fields = ["usuario", "fecha"]
    raw_id_fields = ["analisis"]

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        obj.usuario = request.user
        super().save_model(request, obj, form, change)
