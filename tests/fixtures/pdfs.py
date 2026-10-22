"""PDFs sintéticos generados al vuelo: nunca documentos reales en el repositorio."""

from pathlib import Path

from pypdf import PdfWriter


def crear_pdf(ruta: Path, paginas: int = 1) -> Path:
    escritor = PdfWriter()
    for _ in range(paginas):
        escritor.add_blank_page(width=612, height=792)
    with ruta.open("wb") as archivo:
        escritor.write(archivo)
    return ruta


def crear_pdf_cifrado(ruta: Path, clave_usuario: str = "", clave_propietario: str = "x") -> Path:
    """Con clave_usuario vacía se abre sin contraseña (solo restricciones de propietario).

    AES-256, como muchos certificados oficiales.
    """
    escritor = PdfWriter()
    escritor.add_blank_page(width=612, height=792)
    escritor.encrypt(
        user_password=clave_usuario, owner_password=clave_propietario, algorithm="AES-256"
    )
    with ruta.open("wb") as archivo:
        escritor.write(archivo)
    return ruta
