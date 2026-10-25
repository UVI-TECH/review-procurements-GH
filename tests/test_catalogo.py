"""Catálogo: el legado (migración 0002) más los requisitos de Gestión Humana 2026-2 (0008)."""

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from apps.contrataciones.models import AliasTipoDocumento, TipoDocumento
from apps.motor.catalogo import cargar_catalogo
from tests.fixtures.catalogo import DOCS, OBS_BONO, catalogo_inicial

pytestmark = pytest.mark.django_db


def test_tipos_activos_en_orden_iguales_al_catalogo_de_pruebas():
    tipos = TipoDocumento.objects.filter(activo=True).order_by("orden")
    assert list(tipos.values_list("codigo", "etiqueta")) == DOCS


def test_diez_tipos_activos_y_obligatorios():
    assert TipoDocumento.objects.filter(obligatorio=True, activo=True).count() == 10


def test_eps_afp_viejo_queda_inactivo_con_su_historial():
    viejo = TipoDocumento.objects.get(codigo="certificados_eps_afp")
    assert not viejo.activo
    assert viejo.etiqueta == "Certificados EPS/AFP"


def test_solo_el_formato_de_autorizacion_requiere_firma():
    con_firma = TipoDocumento.objects.filter(requiere_firma=True).values_list("codigo", flat=True)
    assert list(con_firma) == ["formato_autorizacion_consulta_inhabilidades"]


def test_vigencia_de_30_dias_salvo_formato_y_examen_medico():
    sin_vigencia = TipoDocumento.objects.filter(activo=True, vigencia_dias__isnull=True)
    assert set(sin_vigencia.values_list("codigo", flat=True)) == {
        "formato_autorizacion_consulta_inhabilidades",
        "certificado_medico_laboral",
    }
    assert set(
        TipoDocumento.objects.filter(activo=True, vigencia_dias__isnull=False).values_list(
            "vigencia_dias", flat=True
        )
    ) == {30}


def test_ningun_tipo_exige_logo_todavia():
    assert not TipoDocumento.objects.filter(requiere_logo=True).exists()


def test_alias_de_pension_con_etiqueta_propia_y_sin_vigencia():
    pension = AliasTipoDocumento.objects.get(codigo="resolucion_pension_vejez")
    bono = AliasTipoDocumento.objects.get(codigo="carta_bono_pensional")
    for alias in (pension, bono):
        assert alias.tipo.codigo == "certificado_afp"
        assert alias.etiqueta and not alias.hereda_vigencia and alias.vigencia_dias is None
    assert bono.observacion == OBS_BONO
    assert pension.observacion == ""


def test_catalogo_de_la_base_igual_al_de_pruebas():
    base, prueba = cargar_catalogo(), catalogo_inicial()
    assert base.activos == prueba.activos


def test_catalogo_resuelve_etiqueta_vigencia_y_observacion_del_alias():
    catalogo = catalogo_inicial()
    assert catalogo.resolver("carta_bono_pensional").codigo == "certificado_afp"
    assert catalogo.etiqueta_de("carta_bono_pensional") == "Carta de bono pensional"
    assert catalogo.etiqueta_de("certificado_afp") == "Certificado de fondo de pensiones (AFP)"
    assert catalogo.vigencia_de("certificado_afp") == 30
    assert catalogo.vigencia_de("carta_bono_pensional") is None
    assert catalogo.vigencia_de("examen_medico_laboral_dotc") is None  # hereda del médico
    assert catalogo.observacion_de("carta_bono_pensional") == OBS_BONO
    assert catalogo.observacion_de("certificado_afp") == ""
    assert catalogo.etiqueta_de("otro") is None and catalogo.vigencia_de("otro") is None


def test_alias_dotc_apunta_al_certificado_medico(tipo_medico):
    alias = AliasTipoDocumento.objects.get(codigo="examen_medico_laboral_dotc")
    assert alias.tipo == tipo_medico


def test_codigo_de_tipo_unico():
    with pytest.raises(IntegrityError):
        TipoDocumento.objects.create(codigo="certificados_eps_afp", etiqueta="Duplicado", orden=99)


def test_codigo_de_alias_unico_en_la_base_de_datos(tipo_medico):
    with pytest.raises(IntegrityError):
        AliasTipoDocumento.objects.create(tipo=tipo_medico, codigo="examen_medico_laboral_dotc")


def test_alias_no_puede_repetir_el_codigo_de_un_tipo(tipo_medico):
    alias = AliasTipoDocumento(tipo=tipo_medico, codigo="certificados_eps_afp")
    with pytest.raises(ValidationError) as error:
        alias.full_clean()
    assert "codigo" in error.value.message_dict


def test_tipo_no_puede_repetir_el_codigo_de_un_alias():
    tipo = TipoDocumento(codigo="examen_medico_laboral_dotc", etiqueta="Choca con alias", orden=10)
    with pytest.raises(ValidationError) as error:
        tipo.full_clean()
    assert "codigo" in error.value.message_dict


def test_codigo_solo_minusculas_digitos_y_guion_bajo():
    tipo = TipoDocumento(codigo="Tipo Nuevo", etiqueta="Inválido", orden=10)
    with pytest.raises(ValidationError) as error:
        tipo.full_clean()
    assert "codigo" in error.value.message_dict


# --- Códigos reservados: "otro" e "ilegible" (motor) y "error" (legado) ---

RESERVADOS = ["otro", "ilegible", "error"]


def test_codigos_reservados_coinciden_con_el_motor():
    from apps.contrataciones.models import CODIGOS_RESERVADOS
    from apps.motor.esquema import TIPO_OTRO
    from apps.motor.resultado import TIPO_ILEGIBLE

    assert set(CODIGOS_RESERVADOS) == {TIPO_OTRO, TIPO_ILEGIBLE, "error"}


@pytest.mark.parametrize("codigo", RESERVADOS)
def test_tipo_no_admite_codigo_reservado(codigo):
    tipo = TipoDocumento(codigo=codigo, etiqueta="Reservado", orden=10)
    with pytest.raises(ValidationError) as error:
        tipo.full_clean()
    assert "reservado" in str(error.value.message_dict["codigo"])


@pytest.mark.parametrize("codigo", RESERVADOS)
def test_alias_no_admite_codigo_reservado(tipo_medico, codigo):
    alias = AliasTipoDocumento(tipo=tipo_medico, codigo=codigo)
    with pytest.raises(ValidationError) as error:
        alias.full_clean()
    assert "reservado" in str(error.value.message_dict["codigo"])


@pytest.mark.parametrize("codigo", [*RESERVADOS, "OTRO", "Ilegible"])
def test_la_base_de_datos_rechaza_tipo_con_codigo_reservado(codigo):
    with pytest.raises(IntegrityError):
        TipoDocumento.objects.create(codigo=codigo, etiqueta="Reservado", orden=10)


@pytest.mark.parametrize("codigo", [*RESERVADOS, "ERROR"])
def test_la_base_de_datos_rechaza_alias_con_codigo_reservado(tipo_medico, codigo):
    with pytest.raises(IntegrityError):
        AliasTipoDocumento.objects.create(tipo=tipo_medico, codigo=codigo)


def _verificacion_de_la_migracion():
    import importlib

    return importlib.import_module(
        "apps.contrataciones.migrations.0003_codigos_reservados"
    ).verificar_codigos_reservados


def test_migracion_falla_con_mensaje_claro_si_ya_existe_un_codigo_reservado(monkeypatch):
    """La migración no renombra nada: se detiene y dice qué cambiar."""
    filas = {"TipoDocumento": ["Otro"], "AliasTipoDocumento": []}

    class Consulta:
        def __init__(self, modelo):
            self.modelo = modelo

        def filter(self, *args, **kwargs):
            return self

        def values_list(self, *args, **kwargs):
            return filas[self.modelo]

    class AppsFalsas:
        def get_model(self, app, modelo):
            return type(modelo, (), {"objects": Consulta(modelo)})

    with pytest.raises(RuntimeError) as error:
        _verificacion_de_la_migracion()(AppsFalsas(), None)
    mensaje = str(error.value)
    assert "Otro" in mensaje
    assert "reservados" in mensaje
    assert "renómbralo" in mensaje


def test_migracion_pasa_con_el_catalogo_sembrado():
    from django.apps import apps

    _verificacion_de_la_migracion()(apps, None)
