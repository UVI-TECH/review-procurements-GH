"""Fixtures compartidas. Solo datos sintéticos: nunca nombres ni cédulas reales."""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.utils import timezone

from apps.contrataciones.models import Analisis, Corrida, Documento, Profesor, TipoDocumento


@pytest.fixture
def crear_usuario(db):
    def _crear(username="usuario.prueba", grupo=None, **extra):
        # Sin contraseña: las pruebas inician sesión con force_login.
        usuario = get_user_model().objects.create_user(username=username, **extra)
        if grupo:
            usuario.groups.add(Group.objects.get(name=grupo))
        return usuario

    return _crear


@pytest.fixture
def usuario(crear_usuario):
    return crear_usuario()


@pytest.fixture
def profesor(db):
    return Profesor.objects.create(
        carpeta="PROFESOR FICTICIO UNO", nombre="Profesor Ficticio Uno", cedula="1000000001"
    )


@pytest.fixture
def documento(profesor):
    return Documento.objects.create(
        profesor=profesor,
        ruta_relativa="PROFESOR FICTICIO UNO/procuraduria.pdf",
        nombre_archivo="procuraduria.pdf",
        sha256="a" * 64,
        tamano=1024,
        modificado_en=timezone.now(),
    )


@pytest.fixture
def corrida(usuario):
    return Corrida.objects.create(iniciada_por=usuario, alcance=Corrida.Alcance.TODOS)


@pytest.fixture
def analisis(documento, corrida):
    return Analisis.objects.create(
        documento=documento,
        corrida=corrida,
        sha256=documento.sha256,
        modelo="simulado",
        tipo_detectado="certificado_antecedentes_disciplinarios",
        es_valido=True,
        numero_documento="1000000001",
        nombre_persona="Profesor Ficticio Uno",
    )


@pytest.fixture
def tipo_medico(db):
    return TipoDocumento.objects.get(codigo="certificado_medico_laboral")
