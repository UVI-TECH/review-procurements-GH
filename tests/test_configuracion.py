"""Configuración que viene del .env: carpeta raíz, base de datos y modo WAL."""

import os
import subprocess
import sys

from config.entorno import BASE_DIR


def _cargar_base(**variables):
    entorno = {**os.environ, **variables}
    return subprocess.run(
        [sys.executable, "-c", "import config.settings.base"],
        cwd=BASE_DIR,
        env=entorno,
        capture_output=True,
        text=True,
    )


def test_base_de_datos_dentro_de_la_carpeta_de_contrataciones_no_arranca(tmp_path):
    raiz = tmp_path / "OneDrive - UNIAJC" / "Contrataciones"
    resultado = _cargar_base(
        CARPETA_CONTRATACIONES=str(raiz), RUTA_BASE_DATOS=str(raiz / "app" / "revision.db")
    )
    assert resultado.returncode != 0
    assert "no puede estar dentro de CARPETA_CONTRATACIONES" in resultado.stderr


def test_base_de_datos_fuera_de_la_carpeta_arranca(tmp_path):
    resultado = _cargar_base(
        CARPETA_CONTRATACIONES=str(tmp_path / "Contrataciones"),
        RUTA_BASE_DATOS=str(tmp_path / "datos" / "revision.db"),
    )
    assert resultado.returncode == 0, resultado.stderr


def test_sqlite_en_modo_wal_con_espera_y_transacciones_inmediatas():
    from config.settings import base

    opciones = base.DATABASES["default"]["OPTIONS"]
    assert "journal_mode=WAL" in opciones["init_command"]
    assert opciones["transaction_mode"] == "IMMEDIATE"
    assert opciones["timeout"] >= 10


def test_bloqueo_del_worker_junto_a_la_base_por_defecto():
    from config.settings import base

    assert base.RUTA_BLOQUEO_WORKER.name == "worker.lock"
    assert base.RUTA_BLOQUEO_WORKER.parent == base.DATABASES["default"]["NAME"].parent


def test_ruta_de_base_vacia_usa_el_valor_por_defecto():
    """.env.example trae RUTA_BASE_DATOS= vacía."""
    resultado = subprocess.run(
        [
            sys.executable,
            "-c",
            "from config.settings import base; print(base.DATABASES['default']['NAME'].name)",
        ],
        cwd=BASE_DIR,
        env={**os.environ, "RUTA_BASE_DATOS": "", "CARPETA_CONTRATACIONES": ""},
        capture_output=True,
        text=True,
    )
    assert resultado.stdout.strip() == "revision.db", resultado.stderr
