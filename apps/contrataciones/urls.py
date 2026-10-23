from django.urls import path

from . import views

urlpatterns = [
    path("tablero/", views.tablero, name="tablero"),
    path("profesores/<int:pk>/", views.detalle, name="detalle"),
    path(
        "profesores/<int:pk>/documentos/<int:documento>/revisar/",
        views.revisar,
        name="revisar",
    ),
    path("profesores/<int:pk>/verificar/", views.verificar, name="verificar"),
    path("profesores/<int:pk>/cedula/", views.cedula, name="cedula"),
    path("documentos/<int:pk>/pdf/", views.pdf, name="pdf"),
]
