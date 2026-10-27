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
    assert 30 <= profesores.count() <= 40
    estados = set(profesores.values_list("estado", flat=True))
    assert {
        EstadoProfesor.COMPLETO,
        EstadoProfesor.INCOMPLETO,
        EstadoProfesor.CON_PROBLEMAS,
        EstadoProfesor.SIN_DOCUMENTOS,
        EstadoProfesor.PENDIENTE_ANALISIS,
    } <= estados
    assert Analisis.objects.filter(tipo_detectado=Analisis.TIPO_ILEGIBLE).exists()
    assert Analisis.objects.filter(tipo_detectado="otro").exists()
    assert Documento.objects.filter(reintentos_agotados=True).exists()
    assert profesores.filter(requiere_atencion=True).exists()
    assert any(
        len([d for d in p.documentos.all() if d.nombre_archivo.startswith("certificado_afp")]) > 1
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


def test_pendientes_de_analisis_en_la_demo(entorno):
    """Un completo con un archivo nuevo queda PENDIENTE_ANALISIS; un incompleto, INCOMPLETO."""
    call_command("sembrar_demo", "--usuario", "revisor")
    sin_analizar = Documento.objects.filter(presente=True, analisis__isnull=True)
    profesores = {d.profesor for d in sin_analizar}
    assert {p.estado for p in profesores} == {
        EstadoProfesor.PENDIENTE_ANALISIS,
        EstadoProfesor.INCOMPLETO,
    }
    assert not Profesor.objects.filter(estado=EstadoProfesor.ERROR, documentos__in=sin_analizar)


def test_casos_de_los_requisitos_2026_2(entorno):
    """EPS/AFP separados y combinados, pensión, bono, vencido, por vencer y fecha ilegible."""
    from apps.contrataciones.servicios.estado import evaluar
    from apps.motor.catalogo import cargar_catalogo

    call_command("sembrar_demo", "--usuario", "revisor")
    catalogo = cargar_catalogo()
    por_nombre = {p.carpeta.split(" - ", 1)[1]: p for p in Profesor.objects.all()}

    def caso(nombre):
        profesor = por_nombre[nombre]
        return profesor, *evaluar(profesor, catalogo)

    profesor, evaluacion, _ = caso("Fernanda Ejemplo Cerro")  # combinado
    assert profesor.estado == EstadoProfesor.COMPLETO
    assert evaluacion.vigentes["certificado_eps"] is evaluacion.vigentes["certificado_afp"]
    for nombre, alias in [
        ("Gustavo Prueba Delta", "resolucion_pension_vejez"),
        ("Helena Muestra Bahia", "carta_bono_pensional"),
    ]:
        profesor, evaluacion, _ = caso(nombre)
        assert profesor.estado == EstadoProfesor.COMPLETO
        assert evaluacion.vigentes["certificado_afp"].tipo_detectado == alias
    profesor, evaluacion, _ = caso("Ivan Ficticio Meseta")  # solo EPS
    assert profesor.estado == EstadoProfesor.INCOMPLETO
    assert [t.codigo for t in evaluacion.faltantes] == ["certificado_afp"]
    profesor, _, evaluados = caso("Juana Demo Laguna")
    assert profesor.estado == EstadoProfesor.CON_PROBLEMAS
    assert any(e.resultado_ia.vencido for e in evaluados)
    profesor, evaluacion, _ = caso("Kevin Simulado Ribera")
    assert profesor.estado == EstadoProfesor.COMPLETO and evaluacion.por_vencer
    profesor, evaluacion, _ = caso("Lorena Ejemplo Pradera")
    assert profesor.estado == EstadoProfesor.COMPLETO and evaluacion.fechas_sin_leer
    assert profesor.requiere_atencion


def test_semaforo_del_tablero_con_la_demo(entorno, client):
    """Cada celda muestra ✓, ✗ o !: nunca "·" (sin dato) en profesores ya analizados."""
    import re

    from django.contrib.auth import get_user_model
    from django.urls import reverse

    call_command("sembrar_demo", "--usuario", "revisor")
    client.force_login(get_user_model().objects.get(username="revisor"))
    iconos = set()
    for pagina in (1, 2):
        html = client.get(reverse("tablero"), {"ocultos": "1", "pagina": pagina}).content.decode()
        iconos |= set(
            re.findall(r'class="semaforo semaforo-\w+"><span aria-hidden="true">(.)', html)
        )
    assert iconos == {"✓", "✗", "!"}
