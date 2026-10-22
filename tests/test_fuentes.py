"""FuenteCarpetaLocal: solo PDFs visibles, y nada fuera de la carpeta raíz."""

import os
import sys

import pytest

from apps.motor.fuentes import ErrorFuente, FuenteCarpetaLocal
from tests.fixtures.pdfs import crear_pdf


@pytest.fixture
def raiz(tmp_path):
    raiz = tmp_path / "Contrataciones"
    (raiz / "PROFESOR UNO").mkdir(parents=True)
    (raiz / "PROFESOR DOS").mkdir()
    crear_pdf(raiz / "PROFESOR UNO" / "procuraduria.pdf")
    crear_pdf(raiz / "PROFESOR UNO" / "EPS.PDF")
    return raiz


def symlink_o_saltar(enlace, destino, carpeta=False):
    try:
        enlace.symlink_to(destino, target_is_directory=carpeta)
    except OSError:  # Windows sin privilegio para crear enlaces simbólicos
        pytest.skip("este sistema no permite crear enlaces simbólicos")


def test_lista_profesores_ordenados(raiz):
    assert FuenteCarpetaLocal(raiz).listar_profesores() == ["PROFESOR DOS", "PROFESOR UNO"]


def test_lista_pdfs_con_ruta_relativa_tamano_y_fecha(raiz):
    archivos = FuenteCarpetaLocal(raiz).listar_pdfs("PROFESOR UNO")
    assert [a.ruta_relativa for a in archivos] == [
        "PROFESOR UNO/EPS.PDF",
        "PROFESOR UNO/procuraduria.pdf",
    ]
    assert all(a.tamano > 0 and a.modificado_en.tzinfo for a in archivos)
    assert archivos[0].nombre == "EPS.PDF"


def test_ignora_ocultos_temporales_y_no_pdf(raiz):
    carpeta = raiz / "PROFESOR UNO"
    for nombre in [".oculto.pdf", "~$borrador.pdf", "copia.pdf.tmp", "notas.TMP", "foto.jpg"]:
        (carpeta / nombre).write_bytes(b"x")
    (carpeta / "subcarpeta").mkdir()
    (raiz / ".oculta").mkdir()
    (raiz / "~$temporal").mkdir()
    (raiz / "suelto.pdf").write_bytes(b"x")
    fuente = FuenteCarpetaLocal(raiz)
    assert fuente.listar_profesores() == ["PROFESOR DOS", "PROFESOR UNO"]
    assert len(fuente.listar_pdfs("PROFESOR UNO")) == 2


def test_lee_un_archivo(raiz):
    datos = FuenteCarpetaLocal(raiz).leer("PROFESOR UNO/procuraduria.pdf")
    assert datos.startswith(b"%PDF")


@pytest.mark.parametrize(
    "ruta",
    ["../secreto.pdf", "PROFESOR UNO/../../secreto.pdf", "/etc/passwd", "C:/Windows/win.ini"],
)
def test_path_traversal_se_rechaza(raiz, ruta):
    (raiz.parent / "secreto.pdf").write_bytes(b"%PDF secreto")
    with pytest.raises(ErrorFuente):
        FuenteCarpetaLocal(raiz).leer(ruta)


@pytest.mark.parametrize("carpeta", ["..", "../Contrataciones/..", "/"])
def test_carpeta_fuera_de_la_raiz_se_rechaza(raiz, carpeta):
    with pytest.raises(ErrorFuente):
        FuenteCarpetaLocal(raiz).listar_pdfs(carpeta)


def test_symlink_a_un_archivo_fuera_de_la_raiz_se_ignora_y_no_se_lee(raiz):
    externo = crear_pdf(raiz.parent / "externo.pdf")
    symlink_o_saltar(raiz / "PROFESOR UNO" / "enlace.pdf", externo)
    fuente = FuenteCarpetaLocal(raiz)
    assert "enlace.pdf" not in [a.nombre for a in fuente.listar_pdfs("PROFESOR UNO")]
    with pytest.raises(ErrorFuente):
        fuente.leer("PROFESOR UNO/enlace.pdf")


def test_symlink_a_una_carpeta_fuera_de_la_raiz_se_ignora(raiz):
    externa = raiz.parent / "otra"
    externa.mkdir()
    crear_pdf(externa / "x.pdf")
    symlink_o_saltar(raiz / "PROFESOR FALSO", externa, carpeta=True)
    fuente = FuenteCarpetaLocal(raiz)
    assert "PROFESOR FALSO" not in fuente.listar_profesores()
    with pytest.raises(ErrorFuente):
        fuente.listar_pdfs("PROFESOR FALSO")


def test_symlink_dentro_de_la_raiz_se_acepta(raiz):
    symlink_o_saltar(
        raiz / "PROFESOR DOS" / "copia.pdf", raiz / "PROFESOR UNO" / "procuraduria.pdf"
    )
    nombres = [a.nombre for a in FuenteCarpetaLocal(raiz).listar_pdfs("PROFESOR DOS")]
    assert nombres == ["copia.pdf"]


@pytest.mark.skipif(sys.platform != "win32", reason="atributo oculto de Windows")
def test_archivo_oculto_de_windows_se_ignora(raiz):
    import subprocess

    oculto = crear_pdf(raiz / "PROFESOR UNO" / "oculto.pdf")
    subprocess.run(["attrib", "+h", str(oculto)], check=True)
    assert "oculto.pdf" not in [
        a.nombre for a in FuenteCarpetaLocal(raiz).listar_pdfs("PROFESOR UNO")
    ]


def test_disponible(tmp_path, raiz):
    assert FuenteCarpetaLocal(raiz).disponible()
    assert not FuenteCarpetaLocal(tmp_path / "no-existe").disponible()


def test_raiz_inexistente_no_lista_nada_y_falla_claro(tmp_path):
    with pytest.raises(ErrorFuente, match="no existe"):
        FuenteCarpetaLocal(tmp_path / "no-existe").listar_profesores()


def test_sin_permiso_de_escritura_tambien_funciona(raiz):
    if os.name != "nt":
        os.chmod(raiz / "PROFESOR UNO", 0o555)
    try:
        assert len(FuenteCarpetaLocal(raiz).listar_pdfs("PROFESOR UNO")) == 2
    finally:
        os.chmod(raiz / "PROFESOR UNO", 0o755)
