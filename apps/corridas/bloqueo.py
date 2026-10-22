"""Un solo worker por equipo, con un bloqueo del sistema operativo (ADR 0004).

El sistema operativo libera el bloqueo cuando el proceso muere, aunque sea por un cierre
forzado: al reiniciar no hay que esperar a que venza nada. En Windows, msvcrt.locking
bloquea un rango de bytes que otro proceso no puede leer, así que el PID va en un
archivo aparte (worker.pid) y el bloqueo, sobre worker.lock, que no tiene datos.
"""

import os
from pathlib import Path


class WorkerOcupado(Exception):
    """Ya hay otro worker con el bloqueo."""


def _bloquear(descriptor):
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _desbloquear(descriptor):
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_UN)


class BloqueoWorker:
    def __init__(self, ruta):
        self.ruta = Path(ruta)
        self.ruta_pid = self.ruta.with_suffix(".pid")
        self._archivo = None

    def adquirir(self):
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        archivo = open(self.ruta, "a+b")  # noqa: SIM115 (se cierra en liberar)
        try:
            _bloquear(archivo.fileno())
        except OSError:
            archivo.close()
            try:
                pid = self.ruta_pid.read_text().strip() or "desconocido"
            except OSError:
                pid = "desconocido"
            raise WorkerOcupado(
                f"Ya hay un worker en ejecución (pid {pid}). Ciérralo antes de iniciar otro."
            ) from None
        self._archivo = archivo
        self.ruta_pid.write_text(str(os.getpid()))

    def liberar(self):
        if self._archivo is None:
            return
        try:
            self.ruta_pid.unlink(missing_ok=True)
        finally:
            _desbloquear(self._archivo.fileno())
            self._archivo.close()
            self._archivo = None

    def __enter__(self):
        self.adquirir()
        return self

    def __exit__(self, *excepcion):
        self.liberar()
