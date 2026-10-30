"""Versión del prompt, análisis desactualizados y la corrida "desactualizados" (ADR 0006)."""

import hashlib
import json

import pytest
from django.urls import reverse

from apps.contrataciones.models import Analisis, Corrida, Documento, Profesor
from apps.contrataciones.servicios.estado import documentos_desactualizados, recalcular_estado
from apps.corridas.servicios import crear_corrida, documentos_a_analizar
from apps.motor.catalogo import cargar_catalogo
from apps.motor.esquema import construir_herramienta
from apps.motor.prompts import VERSION_PROMPT, construir_system
from tests.fixtures.catalogo import catalogo_inicial
from tests.fixtures.datos import completo, documento

# Huella del prompt y del esquema de cada versión. Si esta prueba falla, cambiaste el
# prompt o el esquema: sube VERSION_PROMPT en apps/motor/prompts.py y agrega aquí la huella
# nueva (la que muestra el fallo).
HUELLAS = {
    2: "3f7fef7b547f9cb6576634f6d734a2cbbc02fa0442294d015a8c5c9610e70840",
    3: "249f0336764e14e03ce9a93e7a008870d63cb7b6199de0475911005d5845f6ec",
}


def huella_actual():
    catalogo = catalogo_inicial()
    texto = json.dumps(
        {
            "system": construir_system(catalogo)[0]["text"],
            "herramienta": construir_herramienta(catalogo),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(texto.encode()).hexdigest()


def test_cambiar_el_prompt_obliga_a_subir_la_version():
    assert HUELLAS.get(VERSION_PROMPT) == huella_actual(), (
        f"El prompt o el esquema cambiaron: sube VERSION_PROMPT y agrega la huella "
        f"{huella_actual()}"
    )


# --- Con base de datos ---


@pytest.fixture
def prof(db):
    return Profesor.objects.create(carpeta="DEMO DORA", nombre="Dora Version")


@pytest.fixture
def revisor(crear_usuario):
    return crear_usuario("revisor", grupo="Revisor GH")


@pytest.fixture
def consulta(crear_usuario):
    return crear_usuario("consulta", grupo="Consulta")


def _docs(prof, corrida):
    """Uno vigente con versión actual, uno anterior, uno sin versión, uno ilegible viejo,
    uno con error y uno pendiente."""
    docs = completo(prof, corrida)
    viejo = documento(prof, corrida, "otro", nombre="viejo.pdf", version=VERSION_PROMPT - 1)
    sin_version = documento(prof, corrida, "otro", nombre="sin_version.pdf", version=None)
    ilegible = documento(
        prof, corrida, Analisis.TIPO_ILEGIBLE, valido=False, nombre="roto.pdf", version=None
    )
    error = documento(prof, corrida, Analisis.TIPO_ERROR, valido=False, nombre="error.pdf")
    Documento.objects.create(
        profesor=prof,
        ruta_relativa="DEMO DORA/nuevo.pdf",
        nombre_archivo="nuevo.pdf",
        sha256="f" * 64,
        tamano=1,
        modificado_en=error.modificado_en,
    )
    return docs, viejo, sin_version, ilegible


def test_solo_los_de_version_anterior_estan_desactualizados(prof, corrida):
    _, viejo, sin_version, _ = _docs(prof, corrida)
    assert set(documentos_desactualizados()) == {viejo, sin_version}


def test_un_reanalisis_con_la_version_actual_lo_pone_al_dia(prof, corrida):
    _, viejo, _, _ = _docs(prof, corrida)
    Analisis.objects.create(
        documento=viejo,
        corrida=corrida,
        sha256=viejo.sha256,
        modelo="simulado",
        version_prompt=VERSION_PROMPT,
        tipo_detectado="otro",
        es_valido=False,
    )
    assert viejo not in documentos_desactualizados()


def test_un_error_con_la_version_actual_no_lo_pone_al_dia(prof, corrida):
    _, viejo, _, _ = _docs(prof, corrida)
    Analisis.objects.create(
        documento=viejo,
        corrida=corrida,
        sha256=viejo.sha256,
        modelo="simulado",
        version_prompt=VERSION_PROMPT,
        tipo_detectado=Analisis.TIPO_ERROR,
        es_valido=False,
    )
    assert viejo in documentos_desactualizados()


def test_la_corrida_desactualizados_solo_toma_esos(prof, corrida, revisor):
    _, viejo, sin_version, _ = _docs(prof, corrida)
    a_analizar = documentos_a_analizar(Corrida.Alcance.DESACTUALIZADOS)
    assert set(a_analizar) == {viejo, sin_version}
    nueva = crear_corrida(Corrida.Alcance.DESACTUALIZADOS, revisor)
    assert nueva.alcance == "desactualizados"


def test_el_worker_guarda_la_version(tmp_path, settings, revisor):
    from apps.corridas.procesamiento import ejecutar_worker
    from apps.motor.fuentes import FuenteCarpetaLocal
    from tests.fixtures.carpetas import crear_profesor

    raiz = tmp_path / "Contrataciones"
    crear_profesor(raiz, "PROFESOR UNO", ["certificado_eps.pdf"])
    settings.CARPETA_CONTRATACIONES = raiz
    settings.RUTA_BLOQUEO_WORKER = tmp_path / "worker.lock"
    crear_corrida(Corrida.Alcance.TODOS, revisor)
    ejecutar_worker(una_vez=True, fuente=FuenteCarpetaLocal(raiz))
    assert set(Analisis.objects.values_list("version_prompt", flat=True)) == {VERSION_PROMPT}


def test_desactualizado_sin_fecha_no_es_fecha_sin_leer_ni_requiere_atencion(prof, corrida):
    completo(prof, corrida, certificado_eps={"dias": None, "version": None})
    recalcular_estado(prof, cargar_catalogo())
    prof.refresh_from_db()
    assert not prof.requiere_atencion
    assert prof.estado == "COMPLETO"


def test_tablero_avisa_y_filtra_desactualizados(client, prof, corrida, revisor, consulta):
    _docs(prof, corrida)
    otro = Profesor.objects.create(carpeta="DEMO EVA", nombre="Eva Al Dia")
    completo(otro, corrida)
    client.force_login(revisor)
    html = client.get(reverse("tablero")).content.decode()
    assert "2 documentos fueron analizados con una versión anterior del prompt." in html
    assert "--alcance desactualizados" in html
    html = client.get(reverse("tablero"), {"desactualizados": "1"}).content.decode()
    assert "Dora Version" in html and "Eva Al Dia" not in html
    client.force_login(consulta)
    assert "versión anterior del prompt" not in client.get(reverse("tablero")).content.decode()


def test_detalle_avisa_el_reanalisis(client, prof, corrida, revisor):
    docs = completo(prof, corrida, certificado_eps={"dias": None, "version": None})
    eps = docs["certificado_eps"]
    client.force_login(revisor)
    html = client.get(reverse("detalle", args=[prof.pk]), {"documento": eps.pk}).content.decode()
    assert "Analizado con un prompt anterior: requiere reanálisis." in html
    assert "Fecha sin leer" not in html
    assert "Sin dato (prompt anterior)" in html
