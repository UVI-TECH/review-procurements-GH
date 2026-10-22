"""Un solo worker por equipo. El rechazo se prueba con un subproceso real (también en
Windows, en CI), no con un mock."""

import os
import subprocess
import sys

import pytest

from apps.corridas.bloqueo import BloqueoWorker, WorkerOcupado
from config.entorno import BASE_DIR


def lanzar_worker(ruta_bloqueo):
    entorno = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "config.settings.pruebas",
        "RUTA_BLOQUEO_WORKER": str(ruta_bloqueo),
    }
    return subprocess.run(
        [sys.executable, "manage.py", "worker", "--una-vez"],
        cwd=BASE_DIR,
        env=entorno,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_segundo_worker_se_niega_con_el_pid_del_primero(tmp_path):
    ruta = tmp_path / "worker.lock"
    with BloqueoWorker(ruta):
        resultado = lanzar_worker(ruta)
    assert resultado.returncode != 0
    assert f"Ya hay un worker en ejecución (pid {os.getpid()})" in resultado.stderr


def test_el_bloqueo_se_libera_al_terminar(tmp_path):
    ruta = tmp_path / "worker.lock"
    with BloqueoWorker(ruta):
        pass
    with BloqueoWorker(ruta):
        assert (tmp_path / "worker.pid").read_text() == str(os.getpid())
    assert not (tmp_path / "worker.pid").exists()


def test_dos_bloqueos_en_el_mismo_proceso_tambien_chocan(tmp_path):
    ruta = tmp_path / "worker.lock"
    with BloqueoWorker(ruta), pytest.raises(WorkerOcupado), BloqueoWorker(ruta):
        pass


def test_el_bloqueo_se_libera_si_el_proceso_muere(tmp_path):
    """El sistema operativo suelta el bloqueo de un proceso muerto: no hay que esperar."""
    ruta = tmp_path / "worker.lock"
    codigo = (
        "import os, sys; sys.path.insert(0, sys.argv[1]);"
        "from apps.corridas.bloqueo import BloqueoWorker;"
        "BloqueoWorker(sys.argv[2]).adquirir(); os._exit(0)"
    )
    subprocess.run([sys.executable, "-c", codigo, str(BASE_DIR), str(ruta)], check=True, timeout=60)
    with BloqueoWorker(ruta):
        pass


def test_sin_archivo_pid_el_mensaje_igual_es_claro(tmp_path):
    ruta = tmp_path / "worker.lock"
    with BloqueoWorker(ruta):
        (tmp_path / "worker.pid").unlink()
        with pytest.raises(WorkerOcupado, match="pid desconocido"):
            BloqueoWorker(ruta).adquirir()
