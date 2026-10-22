"""Tiempo límite para abrir un PDF, que funciona en Windows (sin signal.alarm).

pypdf corre en un multiprocessing.Pool(1) persistente con spawn. Si se vence el
tiempo, el pool se termina (el proceso colgado muere) y el siguiente documento usa
uno nuevo. maxtasksperchild recicla el hijo para no acumular memoria si pypdf tiene
fugas con archivos raros. Quien lo usa debe cerrarlo al terminar, para que en Windows
no queden procesos python.exe huérfanos.
"""

import multiprocessing

from .lector_pdf import ignorar_interrupciones, inspeccionar


class InspectorAislado:
    def __init__(self, timeout, *, maxtasksperchild=200, funcion=inspeccionar):
        self.timeout = timeout
        self.maxtasksperchild = maxtasksperchild
        self.funcion = funcion
        self._pool = None

    def _obtener_pool(self):
        if self._pool is None:
            contexto = multiprocessing.get_context("spawn")
            self._pool = contexto.Pool(
                1, maxtasksperchild=self.maxtasksperchild, initializer=ignorar_interrupciones
            )
        return self._pool

    def __call__(self, datos):
        tarea = self._obtener_pool().apply_async(self.funcion, (datos,))
        try:
            return tarea.get(timeout=self.timeout)
        except multiprocessing.TimeoutError:
            self.terminar()
            raise TimeoutError(f"El PDF tardó más de {self.timeout:g} s en abrirse.") from None

    def cerrar(self):
        """Fin normal: espera a que el hijo termine."""
        if self._pool is not None:
            self._pool.close()
            self._pool.join()
            self._pool = None

    def terminar(self):
        """Cuelgue o cancelación: mata al hijo."""
        if self._pool is not None:
            self._pool.terminate()
            self._pool.join()
            self._pool = None

    def __enter__(self):
        return self

    def __exit__(self, tipo, valor, traza):
        if tipo is None:
            self.cerrar()
        else:
            self.terminar()
