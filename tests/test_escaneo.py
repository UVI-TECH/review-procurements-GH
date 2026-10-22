"""Escaneo: sincroniza Profesor y Documento con el disco, sin borrar nunca nada."""

import hashlib
import os
import time

import pytest
from django.core.management import CommandError, call_command

from apps.contrataciones.models import Documento, EstadoProfesor, Profesor
from apps.corridas.escaneo import ErrorEscaneo, escanear
from apps.cuentas.models import RegistroAuditoria
from apps.motor.fuentes import FuenteCarpetaLocal
from tests.fixtures.carpetas import crear_profesor
from tests.fixtures.pdfs import crear_pdf

pytestmark = pytest.mark.django_db


class FuenteEspia(FuenteCarpetaLocal):
    """Cuenta las lecturas, para comprobar que no se recalcula el hash sin necesidad."""

    def __init__(self, raiz):
        super().__init__(raiz)
        self.lecturas = []

    def leer(self, ruta_relativa):
        self.lecturas.append(ruta_relativa)
        return super().leer(ruta_relativa)


@pytest.fixture
def raiz(tmp_path):
    raiz = tmp_path / "Contrataciones"
    crear_profesor(raiz, "PROFESOR UNO", ["a.pdf", "b.pdf"])
    crear_profesor(raiz, "PROFESOR DOS", ["c.pdf"])
    return raiz


def tocar(ruta, segundos=10):
    """Cambia la fecha de modificación de forma visible en cualquier sistema de archivos."""
    marca = time.time() + segundos
    os.utime(ruta, (marca, marca))


def test_carpetas_y_pdfs_nuevos(raiz):
    resumen = escanear(FuenteCarpetaLocal(raiz))
    assert (resumen.profesores_nuevos, resumen.documentos_nuevos) == (2, 3)
    uno = Profesor.objects.get(carpeta="PROFESOR UNO")
    assert uno.nombre == "PROFESOR UNO"
    assert uno.carpeta_presente and uno.estado == EstadoProfesor.SIN_ANALIZAR
    a = Documento.objects.get(ruta_relativa="PROFESOR UNO/a.pdf")
    datos = (raiz / "PROFESOR UNO" / "a.pdf").read_bytes()
    assert a.sha256 == hashlib.sha256(datos).hexdigest()
    assert (a.nombre_archivo, a.tamano, a.presente) == ("a.pdf", len(datos), True)


def test_segundo_escaneo_sin_cambios_no_relee_los_archivos(raiz):
    escanear(FuenteCarpetaLocal(raiz))
    fuente = FuenteEspia(raiz)
    resumen = escanear(fuente)
    assert fuente.lecturas == []
    assert resumen.documentos_sin_cambios == 3
    assert resumen.documentos_nuevos == resumen.documentos_modificados == 0


def test_pdf_modificado_actualiza_hash_tamano_y_fecha(raiz):
    escanear(FuenteCarpetaLocal(raiz))
    documento = Documento.objects.get(ruta_relativa="PROFESOR UNO/a.pdf")
    documento.reintentos_agotados = True
    documento.save()
    ruta = crear_pdf(raiz / "PROFESOR UNO" / "a.pdf", paginas=2, marca="versión nueva")
    tocar(ruta)
    fuente = FuenteEspia(raiz)
    resumen = escanear(fuente)
    documento.refresh_from_db()
    assert fuente.lecturas == ["PROFESOR UNO/a.pdf"]
    assert resumen.documentos_modificados == 1
    assert documento.sha256 == hashlib.sha256(ruta.read_bytes()).hexdigest()
    assert documento.tamano == ruta.stat().st_size
    assert not documento.reintentos_agotados


def test_misma_fecha_y_tamano_no_se_rehashea(raiz):
    """Solo se lee el archivo si cambió el tamaño o la fecha de modificación."""
    escanear(FuenteCarpetaLocal(raiz))
    fuente = FuenteEspia(raiz)
    escanear(fuente)
    assert "PROFESOR UNO/a.pdf" not in fuente.lecturas


def test_pdf_borrado_queda_no_presente_y_si_reaparece_vuelve(raiz):
    escanear(FuenteCarpetaLocal(raiz))
    ruta = raiz / "PROFESOR UNO" / "a.pdf"
    respaldo = ruta.read_bytes()
    ruta.unlink()
    resumen = escanear(FuenteCarpetaLocal(raiz))
    documento = Documento.objects.get(ruta_relativa="PROFESOR UNO/a.pdf")
    assert resumen.documentos_desaparecidos == 1
    assert not documento.presente
    ruta.write_bytes(respaldo)
    resumen = escanear(FuenteCarpetaLocal(raiz))
    documento.refresh_from_db()
    assert resumen.documentos_reaparecidos == 1
    assert documento.presente
    assert Documento.objects.filter(ruta_relativa="PROFESOR UNO/a.pdf").count() == 1


def test_archivos_temporales_no_se_registran(raiz):
    for nombre in ["~$a.pdf", ".oculto.pdf", "a.pdf.tmp", "foto.jpg"]:
        (raiz / "PROFESOR UNO" / nombre).write_bytes(b"x")
    escanear(FuenteCarpetaLocal(raiz))
    assert Documento.objects.count() == 3


def test_carpeta_que_desaparece_conserva_su_estado_y_su_historial(raiz, tmp_path):
    for nombre in ["TRES", "CUATRO", "CINCO"]:
        crear_profesor(raiz, f"PROFESOR {nombre}", ["x.pdf"])
    escanear(FuenteCarpetaLocal(raiz))
    Profesor.objects.filter(carpeta="PROFESOR DOS").update(estado=EstadoProfesor.COMPLETO)
    (raiz / "PROFESOR DOS").rename(tmp_path / "fuera")

    resumen = escanear(FuenteCarpetaLocal(raiz))
    dos = Profesor.objects.get(carpeta="PROFESOR DOS")
    assert resumen.profesores_desaparecidos == 1
    assert not dos.carpeta_presente
    assert dos.estado == EstadoProfesor.COMPLETO
    assert not dos.documentos.filter(presente=True).exists()
    registro = RegistroAuditoria.objects.get(accion="carpeta_desaparecida")
    assert registro.usuario is None
    assert registro.detalle == {"carpeta": "PROFESOR DOS"}

    (tmp_path / "fuera").rename(raiz / "PROFESOR DOS")
    resumen = escanear(FuenteCarpetaLocal(raiz))
    dos.refresh_from_db()
    assert resumen.profesores_reaparecidos == 1
    assert dos.carpeta_presente
    assert dos.documentos.filter(presente=True).count() == 1


def test_carpeta_renombrada_es_un_profesor_nuevo(raiz):
    """Limitación conocida (ADR 0004): no se fusiona con el anterior."""
    for nombre in ["TRES", "CUATRO", "CINCO"]:
        crear_profesor(raiz, f"PROFESOR {nombre}", ["x.pdf"])
    escanear(FuenteCarpetaLocal(raiz))
    (raiz / "PROFESOR DOS").rename(raiz / "PROFESOR DOS (CORREGIDO)")
    escanear(FuenteCarpetaLocal(raiz))
    assert not Profesor.objects.get(carpeta="PROFESOR DOS").carpeta_presente
    assert Profesor.objects.get(carpeta="PROFESOR DOS (CORREGIDO)").carpeta_presente


# --- Freno de seguridad ---


def test_raiz_inexistente_aborta(tmp_path):
    with pytest.raises(ErrorEscaneo, match="no existe"):
        escanear(FuenteCarpetaLocal(tmp_path / "no-existe"))


def test_raiz_vacia_aborta_sin_marcar_desaparecidos(raiz, tmp_path):
    escanear(FuenteCarpetaLocal(raiz))
    vacia = tmp_path / "vacia"
    vacia.mkdir()
    with pytest.raises(ErrorEscaneo, match="vacía"):
        escanear(FuenteCarpetaLocal(vacia))
    assert Profesor.objects.filter(carpeta_presente=True).count() == 2


def _cinco_profesores(raiz):
    for nombre in ["TRES", "CUATRO", "CINCO"]:
        crear_profesor(raiz, f"PROFESOR {nombre}", ["x.pdf"])
    escanear(FuenteCarpetaLocal(raiz))


def test_si_desaparece_mas_del_umbral_aborta_sin_cambiar_nada(raiz, tmp_path):
    _cinco_profesores(raiz)
    (raiz / "PROFESOR UNO").rename(tmp_path / "uno")
    (raiz / "PROFESOR DOS").rename(tmp_path / "dos")  # 2 de 5 = 40 % > 20 %
    crear_profesor(raiz, "PROFESOR NUEVO", ["n.pdf"])
    with pytest.raises(ErrorEscaneo, match="40 %") as error:
        escanear(FuenteCarpetaLocal(raiz))
    assert "--forzar" in str(error.value)
    assert Profesor.objects.filter(carpeta_presente=True).count() == 5
    assert not Profesor.objects.filter(carpeta="PROFESOR NUEVO").exists()


def test_en_el_umbral_continua(raiz, tmp_path):
    _cinco_profesores(raiz)
    (raiz / "PROFESOR UNO").rename(tmp_path / "uno")  # 1 de 5 = 20 %
    assert escanear(FuenteCarpetaLocal(raiz)).profesores_desaparecidos == 1


def test_forzar_continua_y_queda_en_auditoria(raiz, tmp_path, crear_usuario):
    _cinco_profesores(raiz)
    (raiz / "PROFESOR UNO").rename(tmp_path / "uno")
    (raiz / "PROFESOR DOS").rename(tmp_path / "dos")
    admin = crear_usuario("admin")
    resumen = escanear(FuenteCarpetaLocal(raiz), forzar=True, usuario=admin)
    assert resumen.profesores_desaparecidos == 2
    registro = RegistroAuditoria.objects.get(accion="escaneo_forzado")
    assert registro.usuario == admin
    assert registro.detalle["desaparecidas"] == 2
    assert registro.detalle["conocidas"] == 5


def test_umbral_configurable(raiz, tmp_path, settings):
    settings.ESCANEO_MAX_DESAPARECIDAS = 0.5
    _cinco_profesores(raiz)
    (raiz / "PROFESOR UNO").rename(tmp_path / "uno")
    (raiz / "PROFESOR DOS").rename(tmp_path / "dos")
    assert escanear(FuenteCarpetaLocal(raiz)).profesores_desaparecidos == 2


def test_escaneo_de_un_profesor_solo_toca_esa_carpeta(raiz):
    escanear(FuenteCarpetaLocal(raiz))
    (raiz / "PROFESOR DOS" / "c.pdf").unlink()
    crear_pdf(raiz / "PROFESOR UNO" / "nuevo.pdf")
    resumen = escanear(FuenteCarpetaLocal(raiz), carpeta="PROFESOR UNO")
    assert resumen.documentos_nuevos == 1
    assert Documento.objects.get(ruta_relativa="PROFESOR DOS/c.pdf").presente


# --- Comando ---


def test_comando_escanear(raiz, settings, capsys):
    settings.CARPETA_CONTRATACIONES = raiz
    call_command("escanear")
    salida = capsys.readouterr().out
    assert "profesores nuevos: 2" in salida
    assert "documentos nuevos: 3" in salida


def test_comando_sin_carpeta_configurada(settings):
    settings.CARPETA_CONTRATACIONES = None
    with pytest.raises(CommandError, match="CARPETA_CONTRATACIONES"):
        call_command("escanear")


def test_comando_explica_el_freno(raiz, tmp_path, settings):
    settings.CARPETA_CONTRATACIONES = raiz
    _cinco_profesores(raiz)
    (raiz / "PROFESOR UNO").rename(tmp_path / "uno")
    (raiz / "PROFESOR DOS").rename(tmp_path / "dos")
    with pytest.raises(CommandError, match="--forzar"):
        call_command("escanear")
