"""Escaneo: sincroniza Profesor y Documento con la fuente. Nunca borra nada.

- Carpeta nueva → Profesor; PDF nuevo → Documento.
- PDF cambiado → nuevo sha256, tamaño y fecha. El archivo solo se lee (y se hashea) si
  cambió el tamaño o la fecha de modificación.
- PDF que desaparece → presente=False; si reaparece → presente=True.
- Carpeta que desaparece → carpeta_presente=False, sin recalcular su estado.

Freno de seguridad: si la raíz no existe o está vacía, o si desaparece más de
ESCANEO_MAX_DESAPARECIDAS de las carpetas conocidas (OneDrive desconectado, carpeta
movida), aborta sin cambiar nada; solo forzar=True continúa, y queda en auditoría.
"""

import hashlib
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction

from apps.contrataciones.models import Documento, Profesor
from apps.cuentas.auditoria import registrar
from apps.motor.fuentes import ErrorFuente


class ErrorEscaneo(Exception):
    """El escaneo no se hizo; el mensaje dice por qué y qué hacer."""


@dataclass
class ResumenEscaneo:
    profesores_nuevos: int = 0
    profesores_desaparecidos: int = 0
    profesores_reaparecidos: int = 0
    documentos_nuevos: int = 0
    documentos_modificados: int = 0
    documentos_desaparecidos: int = 0
    documentos_reaparecidos: int = 0
    documentos_sin_cambios: int = 0


def _sha256(datos):
    return hashlib.sha256(datos).hexdigest()


def escanear(fuente, *, carpeta=None, forzar=False, usuario=None):
    """Escanea toda la raíz, o solo una carpeta si se indica."""
    try:
        presentes = fuente.listar_profesores()
    except ErrorFuente as error:
        raise ErrorEscaneo(f"{error}. ¿Está conectado OneDrive?") from None
    if not presentes:
        raise ErrorEscaneo(
            "La carpeta raíz está vacía: no se marca a nadie como desaparecido. "
            "¿Está sincronizado OneDrive?"
        )

    resumen = ResumenEscaneo()
    if carpeta is not None:
        _escanear_profesor(fuente, carpeta, carpeta in presentes, resumen)
        return resumen

    conocidas = set(
        Profesor.objects.filter(carpeta_presente=True).values_list("carpeta", flat=True)
    )
    desaparecidas = sorted(conocidas - set(presentes))
    if conocidas and desaparecidas:
        fraccion = len(desaparecidas) / len(conocidas)
        if fraccion > settings.ESCANEO_MAX_DESAPARECIDAS:
            if not forzar:
                raise ErrorEscaneo(
                    f"Desaparecerían {len(desaparecidas)} de {len(conocidas)} carpetas "
                    f"({round(fraccion * 100)} %), más del "
                    f"{round(settings.ESCANEO_MAX_DESAPARECIDAS * 100)} % permitido. No se "
                    "cambió nada. Revisa que OneDrive esté conectado; si la desaparición es "
                    "real, vuelve a escanear con --forzar."
                )
            registrar(
                usuario,
                "escaneo_forzado",
                detalle={"desaparecidas": len(desaparecidas), "conocidas": len(conocidas)},
            )

    for nombre in presentes:
        _escanear_profesor(fuente, nombre, True, resumen)
    for nombre in desaparecidas:
        _escanear_profesor(fuente, nombre, False, resumen)
    return resumen


@transaction.atomic
def _escanear_profesor(fuente, carpeta, presente, resumen):
    profesor = Profesor.objects.filter(carpeta=carpeta).first()
    if not presente:
        if profesor and profesor.carpeta_presente:
            profesor.carpeta_presente = False
            profesor.save(update_fields=["carpeta_presente", "actualizado_en"])
            resumen.documentos_desaparecidos += profesor.documentos.filter(presente=True).update(
                presente=False
            )
            resumen.profesores_desaparecidos += 1
            registrar(None, "carpeta_desaparecida", profesor, {"carpeta": carpeta})
        return

    if profesor is None:
        profesor = Profesor.objects.create(carpeta=carpeta, nombre=carpeta)
        resumen.profesores_nuevos += 1
    elif not profesor.carpeta_presente:
        profesor.carpeta_presente = True
        profesor.save(update_fields=["carpeta_presente", "actualizado_en"])
        resumen.profesores_reaparecidos += 1
        registrar(None, "carpeta_reaparecida", profesor, {"carpeta": carpeta})

    existentes = {d.ruta_relativa: d for d in profesor.documentos.all()}
    vistos = set()
    for archivo in fuente.listar_pdfs(carpeta):
        vistos.add(archivo.ruta_relativa)
        documento = existentes.get(archivo.ruta_relativa)
        if documento is None:
            Documento.objects.create(
                profesor=profesor,
                ruta_relativa=archivo.ruta_relativa,
                nombre_archivo=archivo.nombre,
                sha256=_sha256(fuente.leer(archivo.ruta_relativa)),
                tamano=archivo.tamano,
                modificado_en=archivo.modificado_en,
            )
            resumen.documentos_nuevos += 1
            continue

        cambios = []
        if not documento.presente:
            documento.presente = True
            cambios.append("presente")
            resumen.documentos_reaparecidos += 1
        if (documento.tamano, documento.modificado_en) != (archivo.tamano, archivo.modificado_en):
            sha256 = _sha256(fuente.leer(archivo.ruta_relativa))
            if sha256 != documento.sha256:
                documento.sha256 = sha256
                documento.reintentos_agotados = False
                cambios += ["sha256", "reintentos_agotados"]
                resumen.documentos_modificados += 1
            documento.tamano = archivo.tamano
            documento.modificado_en = archivo.modificado_en
            cambios += ["tamano", "modificado_en"]
        if cambios:
            documento.save(update_fields=[*cambios, "actualizado_en"])
        elif documento.presente:
            resumen.documentos_sin_cambios += 1

    for ruta, documento in existentes.items():
        if ruta not in vistos and documento.presente:
            documento.presente = False
            documento.save(update_fields=["presente", "actualizado_en"])
            resumen.documentos_desaparecidos += 1
