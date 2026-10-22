"""El catálogo inicial reproduce DOCS de legado/revisar_contrataciones.py."""

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from apps.contrataciones.models import AliasTipoDocumento, TipoDocumento

pytestmark = pytest.mark.django_db

DOCS_LEGADO = [
    ("certificado_antecedentes_disciplinarios", "Antecedentes Disciplinarios (Procuraduría)"),
    ("boletin_responsabilidades_fiscales", "Responsabilidades Fiscales (Contraloría)"),
    ("certificado_antecedentes_judiciales", "Antecedentes Judiciales (Policía)"),
    ("certificado_registro_nacional_medidas_correctivas", "Medidas Correctivas"),
    ("formato_autorizacion_consulta_inhabilidades", "Formato Autorización Consulta"),
    ("consulta_inhabilidades_delitos_sexuales", "Consulta Inhabilidades Delitos Sexuales"),
    ("certificado_registro_deudores_morosos", "REDAM (Deudores Morosos)"),
    ("certificados_eps_afp", "Certificados EPS/AFP"),
    ("certificado_medico_laboral", "Certificado Médico Laboral"),
]


def test_migracion_crea_los_9_tipos_en_orden():
    tipos = list(TipoDocumento.objects.order_by("orden").values_list("codigo", "etiqueta"))
    assert tipos == DOCS_LEGADO


def test_tipos_iniciales_obligatorios_y_activos():
    assert TipoDocumento.objects.filter(obligatorio=True, activo=True).count() == 9


def test_solo_el_formato_de_autorizacion_requiere_firma():
    con_firma = TipoDocumento.objects.filter(requiere_firma=True).values_list("codigo", flat=True)
    assert list(con_firma) == ["formato_autorizacion_consulta_inhabilidades"]


def test_alias_dotc_apunta_al_certificado_medico(tipo_medico):
    alias = AliasTipoDocumento.objects.get()
    assert alias.codigo == "examen_medico_laboral_dotc"
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
