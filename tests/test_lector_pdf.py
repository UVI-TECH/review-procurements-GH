"""Lectura del PDF en un proceso aparte, con tiempo límite que funciona en Windows."""

import logging
import multiprocessing
import subprocess
import sys

import pytest

from apps.motor.aislamiento import InspectorAislado
from apps.motor.lector_pdf import inspeccionar
from apps.motor.pdf import ErrorPdf, PdfIlegible, leer_pdf
from config.entorno import BASE_DIR
from tests.fixtures.pdfs import crear_pdf, crear_pdf_cifrado


def test_lector_no_importa_django():
    """Con spawn, el hijo importa el módulo desde cero: no debe arrastrar Django."""
    codigo = (
        "import sys, apps.motor.lector_pdf; "
        "print(sorted(m for m in sys.modules if m.split('.')[0] in ('django', 'config')))"
    )
    salida = subprocess.run(
        [sys.executable, "-c", codigo], cwd=BASE_DIR, capture_output=True, text=True, check=True
    )
    assert salida.stdout.strip() == "[]"


def test_inspeccionar_pdf_normal(tmp_path):
    assert inspeccionar(crear_pdf(tmp_path / "a.pdf", paginas=3).read_bytes())[:2] == (3, "ok")


def test_inspeccionar_pdf_con_clave_de_propietario(tmp_path):
    assert inspeccionar(crear_pdf_cifrado(tmp_path / "a.pdf").read_bytes())[:2] == (1, "ok")


def test_inspeccionar_pdf_con_clave_de_usuario(tmp_path):
    datos = crear_pdf_cifrado(tmp_path / "a.pdf", clave_usuario="secreta").read_bytes()
    assert inspeccionar(datos)[:2] == (None, "requiere_contrasena")


def test_inspeccionar_archivo_danado():
    assert inspeccionar(b"no es un pdf")[:2] == (None, "danado")


def test_avisos_de_pypdf_se_devuelven_y_no_salen_a_la_raiz(monkeypatch):
    import apps.motor.lector_pdf as lector

    class LectorQueAvisa:
        def __init__(self, *args, **kwargs):
            logging.getLogger("pypdf._reader").warning("Ignoring wrong pointing object %d", 7)
            self.is_encrypted = False
            self.pages = [object()]

    capturados = []

    class Lista(logging.Handler):
        def emit(self, record):
            capturados.append(record)

    raiz = logging.getLogger()
    lista = Lista(logging.DEBUG)
    raiz.addHandler(lista)
    monkeypatch.setattr(lector, "PdfReader", LectorQueAvisa)
    try:
        paginas, estado, avisos = lector.inspeccionar(b"%PDF")
    finally:
        raiz.removeHandler(lista)
    assert (paginas, estado) == (1, "ok")
    assert avisos == ["Ignoring wrong pointing object 7"]
    assert capturados == []


def test_leer_pdf_registra_los_avisos_en_debug(caplog, tmp_path):
    caplog.set_level(logging.DEBUG, logger="apps.motor.pdf")
    leer_pdf(
        b"%PDF",
        max_bytes=10**6,
        max_paginas=5,
        inspector=lambda datos: (1, "ok", ["Ignoring wrong pointing object 7"]),
    )
    assert [(r.name, r.levelno) for r in caplog.records] == [("apps.motor.pdf", logging.DEBUG)]


def test_leer_pdf_revisa_el_tamano_antes_de_inspeccionar():
    with pytest.raises(PdfIlegible, match="MB"):
        leer_pdf(b"x" * 100, max_bytes=10, max_paginas=5, inspector=lambda d: pytest.fail("abrió"))


# --- Proceso aislado ---


def test_inspector_aislado_cuenta_paginas(tmp_path):
    with InspectorAislado(timeout=30) as inspector:
        assert inspector(crear_pdf(tmp_path / "a.pdf", paginas=2).read_bytes())[:2] == (2, "ok")


def test_tiempo_limite_mata_al_hijo_y_el_siguiente_documento_sigue():
    from tests.fixtures import lentos

    inspector = InspectorAislado(timeout=1, funcion=lentos.colgarse)
    try:
        with pytest.raises(TimeoutError, match="1 s"):
            inspector(b"%PDF")
        assert multiprocessing.active_children() == []
        inspector.funcion = lentos.contar
        assert inspector(b"%PDF") == (1, "ok", [])
    finally:
        inspector.terminar()
    assert multiprocessing.active_children() == []


def test_leer_pdf_convierte_el_tiempo_agotado_en_error_transitorio():
    def lento(datos):
        raise TimeoutError("El PDF tardó más de 30 s en abrirse.")

    with pytest.raises(ErrorPdf, match="30 s") as error:
        leer_pdf(b"%PDF", max_bytes=10**6, max_paginas=5, inspector=lento)
    assert not isinstance(error.value, PdfIlegible)


def test_cerrar_no_deja_procesos_huerfanos(tmp_path):
    inspector = InspectorAislado(timeout=30)
    inspector(crear_pdf(tmp_path / "a.pdf").read_bytes())
    inspector.cerrar()
    assert multiprocessing.active_children() == []


def test_el_hijo_del_pool_ignora_las_interrupciones():
    """Ctrl+C (o Ctrl+Break) lo maneja solo el padre: el hijo no imprime tracebacks."""
    from tests.fixtures import lentos

    with InspectorAislado(timeout=30, funcion=lentos.ignora_interrupciones) as inspector:
        assert inspector(b"") is True
