"""Ctrl+C (Linux) / Ctrl+Break (Windows) sobre un worker real a mitad de una corrida.

Corre el comando como subproceso, con los settings de pruebas, una base en archivo, una
carpeta sintética y una pausa del cliente simulado para poder interrumpirlo a mitad.
"""

import os
import signal
import subprocess
import sys
import threading
import time

import pytest

from config.entorno import BASE_DIR
from tests.fixtures.carpetas import crear_profesor

PREPARAR = (
    "from django.contrib.auth.models import Group;"
    "from apps.cuentas.models import Usuario;"
    "from apps.corridas.servicios import crear_corrida;"
    "u = Usuario.objects.create_user('revisor');"
    "u.groups.add(Group.objects.get(name='Revisor GH'));"
    "print(crear_corrida('todos', u).pk)"
)
VERIFICAR = (
    "from django.db.models import Count;"
    "from apps.contrataciones.models import Corrida;"
    "c = Corrida.objects.get();"
    "por_doc = c.analisis.values('documento').annotate(n=Count('id'));"
    "print(c.estado, c.analisis.count(), max(d['n'] for d in por_doc))"
)


@pytest.fixture
def entorno(tmp_path):
    raiz = tmp_path / "Contrataciones"
    crear_profesor(raiz, "PROFESOR UNO")
    crear_profesor(raiz, "PROFESOR DOS")
    return {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "config.settings.pruebas",
        "RUTA_BASE_DATOS_PRUEBAS": str(tmp_path / "pruebas.sqlite"),
        "RUTA_BLOQUEO_WORKER": str(tmp_path / "worker.lock"),
        "CARPETA_CONTRATACIONES": str(raiz),
        "MOTOR_SIMULADO_PAUSA_SEGUNDOS": "0.3",
        "PYTHONUNBUFFERED": "1",
    }


def manage(entorno, *argumentos):
    resultado = subprocess.run(
        [sys.executable, "manage.py", *argumentos],
        cwd=BASE_DIR,
        env=entorno,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert resultado.returncode == 0, resultado.stderr
    return resultado.stdout


def interrumpir(proceso):
    """Como la terminal: a todo el grupo de procesos (el worker y el hijo del pool)."""
    if sys.platform == "win32":
        os.kill(proceso.pid, signal.CTRL_BREAK_EVENT)
    else:
        os.killpg(proceso.pid, signal.SIGINT)


def test_ctrl_c_detiene_limpio_y_la_corrida_se_reanuda(entorno):
    manage(entorno, "migrate", "--verbosity", "0")
    corrida = manage(entorno, "shell", "--no-imports", "-c", PREPARAR).strip()

    opciones = (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        if sys.platform == "win32"
        else {"start_new_session": True}
    )
    worker = subprocess.Popen(
        [sys.executable, "manage.py", "worker"],
        cwd=BASE_DIR,
        env=entorno,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        **opciones,
    )
    vigilante = threading.Timer(120, worker.kill)
    vigilante.start()
    try:
        salida = []
        for linea in worker.stdout:
            salida.append(linea)
            if " · 3/18 · " in linea:
                break
        else:
            pytest.fail(
                "El worker terminó antes de llegar al tercer documento:\n" + "".join(salida)
            )
        time.sleep(0.1)
        interrumpir(worker)
        resto, errores = worker.communicate(timeout=60)
    finally:
        vigilante.cancel()

    salida = "".join(salida) + resto
    assert worker.returncode == 0, errores
    assert "Traceback" not in errores and "Traceback" not in salida
    assert (
        f"Worker detenido. La corrida {corrida} se reanudará al volver a iniciar el worker."
        in salida
    )
    estado, cantidad, _ = manage(entorno, "shell", "--no-imports", "-c", VERIFICAR).split()
    assert estado == "en_proceso" and 3 <= int(cantidad) < 18

    manage(entorno, "worker", "--una-vez")
    assert manage(entorno, "shell", "--no-imports", "-c", VERIFICAR).split() == [
        "completada",
        "18",
        "1",
    ]
