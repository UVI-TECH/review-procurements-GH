"""Fuentes de documentos: de dónde salen las carpetas y los PDFs.

FuenteCarpetaLocal lee la carpeta de OneDrive sincronizada. FuenteGraph (Fase 8)
cumplirá la misma interfaz: disponible, listar_profesores, listar_pdfs y leer.

Toda ruta se resuelve y se valida dentro de la carpeta raíz: ni path traversal ni
enlaces simbólicos que salgan de ella. Las rutas relativas usan "/" en todos los
sistemas, para que Documento.ruta_relativa sea igual en Windows y en Linux.
"""

import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath


class ErrorFuente(Exception):
    """La ruta no existe, no se puede leer o sale de la carpeta raíz."""


@dataclass(frozen=True)
class ArchivoFuente:
    carpeta: str
    nombre: str
    ruta_relativa: str
    tamano: int
    modificado_en: datetime


def _ignorado(ruta, estado):
    nombre = ruta.name
    if nombre.startswith((".", "~$")) or nombre.lower().endswith(".tmp"):
        return True
    # Atributo "oculto" de Windows (en Linux st_file_attributes no existe).
    return bool(
        getattr(estado, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_HIDDEN", 0)
    )


class FuenteCarpetaLocal:
    def __init__(self, raiz):
        self.raiz = Path(raiz)

    def _raiz_resuelta(self):
        raiz = self.raiz.resolve()
        if not raiz.is_dir():
            raise ErrorFuente(f"La carpeta raíz no existe o no es una carpeta: {self.raiz}")
        return raiz

    def _resolver(self, relativa):
        raiz = self._raiz_resuelta()
        partes = PurePosixPath(str(relativa).replace("\\", "/"))
        if partes.is_absolute() or Path(str(relativa)).is_absolute() or ".." in partes.parts:
            raise ErrorFuente(f"Ruta fuera de la carpeta raíz: {relativa}")
        ruta = raiz.joinpath(*partes.parts).resolve()
        if not ruta.is_relative_to(raiz):
            raise ErrorFuente(f"Ruta fuera de la carpeta raíz: {relativa}")
        return ruta

    def disponible(self):
        return self.raiz.is_dir()

    def listar_profesores(self):
        raiz = self._raiz_resuelta()
        carpetas = []
        for entrada in raiz.iterdir():
            try:
                if (
                    entrada.is_dir()
                    and not _ignorado(entrada, entrada.stat())
                    and entrada.resolve().is_relative_to(raiz)
                ):
                    carpetas.append(entrada.name)
            except OSError:
                continue
        return sorted(carpetas)

    def listar_pdfs(self, carpeta):
        destino = self._resolver(carpeta)
        if not destino.is_dir():
            raise ErrorFuente(f"La carpeta del profesor no existe: {carpeta}")
        raiz = self._raiz_resuelta()
        archivos = []
        for entrada in destino.iterdir():
            if entrada.suffix.lower() != ".pdf":
                continue
            try:
                estado = entrada.stat()
                if (
                    not entrada.is_file()
                    or _ignorado(entrada, estado)
                    or not entrada.resolve().is_relative_to(raiz)
                ):
                    continue
            except OSError:
                continue
            archivos.append(
                ArchivoFuente(
                    carpeta=carpeta,
                    nombre=entrada.name,
                    ruta_relativa=f"{carpeta}/{entrada.name}",
                    tamano=estado.st_size,
                    modificado_en=datetime.fromtimestamp(estado.st_mtime, tz=UTC),
                )
            )
        return sorted(archivos, key=lambda a: a.nombre)

    def leer(self, ruta_relativa):
        ruta = self._resolver(ruta_relativa)
        try:
            return ruta.read_bytes()
        except OSError as error:
            raise ErrorFuente(
                f"No se pudo leer el archivo ({type(error).__name__}): {ruta_relativa}"
            ) from None
