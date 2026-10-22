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
