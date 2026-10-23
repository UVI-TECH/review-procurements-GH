"""sembrar_demo: profesores ficticios que cubren todos los estados, con el motor simulado."""

import pytest
from django.core.management import CommandError, call_command

from apps.contrataciones.models import Analisis, Documento, EstadoProfesor, Profesor

pytestmark = pytest.mark.django_db


@pytest.fixture
def entorno(tmp_path, settings, crear_usuario):
    settings.CARPETA_CONTRATACIONES = tmp_path / "Contrataciones"
    settings.RUTA_BLOQUEO_WORKER = tmp_path / "worker.lock"
    crear_usuario("revisor", grupo="Revisor GH")
    return tmp_path / "Contrataciones"


def test_genera_todos_los_estados(entorno, capsys):
    call_command("sembrar_demo", "--usuario", "revisor")
    profesores = Profesor.objects.all()
    assert 25 <= profesores.count() <= 35
    estados = set(profesores.values_list("estado", flat=True))
    assert {
        EstadoProfesor.COMPLETO,
        EstadoProfesor.INCOMPLETO,
        EstadoProfesor.CON_PROBLEMAS,
        EstadoProfesor.SIN_DOCUMENTOS,
    } <= estados
    assert Analisis.objects.filter(tipo_detectado=Analisis.TIPO_ILEGIBLE).exists()
    assert Analisis.objects.filter(tipo_detectado="otro").exists()
    assert Documento.objects.filter(reintentos_agotados=True).exists()
    assert profesores.filter(requiere_atencion=True).exists()
    assert any(
        len([d for d in p.documentos.all() if d.nombre_archivo.startswith("certificados_eps_afp")])
        > 1
        for p in profesores
    ), "debe haber duplicados"
    salida = capsys.readouterr().out
    assert "profesores ficticios" in salida


def test_nombres_y_cedulas_claramente_ficticios(entorno):
    call_command("sembrar_demo", "--usuario", "revisor")
    for profesor in Profesor.objects.all():
        assert profesor.carpeta.startswith("DEMO ")
        assert not profesor.cedula or profesor.cedula.startswith("999")


def test_cedula_ambigua_presente(entorno):
    from apps.contrataciones.servicios.estado import evaluar
    from apps.motor.catalogo import cargar_catalogo

    call_command("sembrar_demo", "--usuario", "revisor")
    catalogo = cargar_catalogo()
    assert any(evaluar(p, catalogo)[0].cedula_ambigua for p in Profesor.objects.all())


def test_se_niega_con_motor_real(entorno, settings):
    settings.MOTOR_SIMULADO = False
    with pytest.raises(CommandError, match="MOTOR_SIMULADO"):
        call_command("sembrar_demo", "--usuario", "revisor")


def test_se_niega_en_produccion(entorno, settings):
    settings.SETTINGS_MODULE = "config.settings.produccion"
    with pytest.raises(CommandError, match="producción"):
        call_command("sembrar_demo", "--usuario", "revisor")


def test_se_niega_si_la_carpeta_no_esta_vacia(entorno):
    entorno.mkdir(parents=True)
    (entorno / "PROFESOR REAL").mkdir()
    with pytest.raises(CommandError, match="vacía"):
        call_command("sembrar_demo", "--usuario", "revisor")
    assert not Profesor.objects.exists()


def test_sin_carpeta_configurada(settings, crear_usuario):
    settings.CARPETA_CONTRATACIONES = None
    crear_usuario("revisor", grupo="Revisor GH")
    with pytest.raises(CommandError, match="CARPETA_CONTRATACIONES"):
        call_command("sembrar_demo", "--usuario", "revisor")
