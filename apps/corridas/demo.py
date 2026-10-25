"""Datos de demostración: profesores ficticios que cubren todos los estados.

Los PDFs son sintéticos (páginas en blanco) y el nombre de cada archivo dirige al
cliente simulado (ver motor/simulado.py): tipo, cédula, firma, error, etc. Los nombres
empiezan por "DEMO" y las cédulas por 999, para que nadie los confunda con datos reales.
"""

from pypdf import PdfWriter

from apps.contrataciones.models import Corrida

from .escaneo import escanear
from .procesamiento import ejecutar_worker
from .servicios import crear_corrida

NOMBRES = [
    "Ana Ejemplo Ruiz",
    "Bruno Prueba Gil",
    "Carla Muestra Paz",
    "Dario Ficticio Sol",
    "Elena Demo Vega",
    "Fabio Simulado Luna",
    "Gina Ejemplo Mar",
    "Hugo Prueba Rio",
    "Irene Muestra Lago",
    "Julio Ficticio Monte",
    "Karen Demo Valle",
    "Luis Simulado Prado",
    "Marta Ejemplo Cielo",
    "Nicolas Prueba Bosque",
    "Olga Muestra Nube",
    "Pablo Ficticio Roca",
    "Rosa Demo Arena",
    "Sergio Simulado Brisa",
    "Teresa Ejemplo Lluvia",
    "Ulises Prueba Campo",
    "Valeria Muestra Flor",
    "Walter Ficticio Piedra",
    "Ximena Demo Selva",
    "Yesid Simulado Isla",
    "Zoe Ejemplo Costa",
    "Andres Prueba Duna",
    "Beatriz Muestra Ola",
    "Camilo Ficticio Sierra",
    "Diana Demo Llano",
    "Esteban Simulado Pampa",
]


def _pdf(ruta, marca, *, clave_usuario=None):
    escritor = PdfWriter()
    escritor.add_blank_page(width=612, height=792)
    escritor.add_metadata({"/Title": marca})
    if clave_usuario:
        escritor.encrypt(user_password=clave_usuario, owner_password="x", algorithm="AES-256")
    with ruta.open("wb") as archivo:
        escritor.write(archivo)


def _perfil(indice, codigos, cedula):
    """Lista de (nombre de archivo, contenido especial) del profesor según su perfil."""
    completo = [f"{codigo} cc_{cedula}.pdf" for codigo in codigos]
    if indice < 10:  # completos
        return completo
    if indice < 15:  # incompletos: faltan de 1 a 3 tipos
        return completo[: -(1 + indice % 3)]
    if indice == 15:  # con problemas: formato sin firma
        return [n.replace(f"{codigos[4]} ", f"{codigos[4]} sin_firma ") for n in completo]
    if indice < 18:  # con problemas: certificado de otra persona
        return [*completo[:-1], f"{codigos[-1]} otra_persona.pdf"]
    if indice < 20:  # cédula ambigua: 2 con una cédula, 2 con otra
        otra = f"999{9000000 + indice}"
        return [
            f"{codigos[0]} cc_{cedula}.pdf",
            f"{codigos[1]} cc_{cedula}.pdf",
            f"{codigos[2]} cc_{otra}.pdf",
            f"{codigos[3]} cc_{otra}.pdf",
            *[f"{codigo} sin_cedula.pdf" for codigo in codigos[4:]],
        ]
    if indice == 20:  # ilegible: archivo dañado
        return [*completo, ("documento escaneado.pdf", "dañado")]
    if indice == 21:  # ilegible: protegido con contraseña
        return [*completo, ("certificado protegido.pdf", "contraseña")]
    if indice < 24:  # "otro": un documento que no es requisito
        return [*completo[:-1], f"carta de recomendacion cc_{cedula}.pdf"]
    if indice < 26:  # duplicados del mismo tipo
        return [*completo, f"certificado_afp copia cc_{cedula}.pdf"]
    if indice == 26:  # reintentos agotados, y falta un tipo
        return [*completo[:-1], f"error_api cc_{cedula}.pdf"]
    if indice == 27:  # reintentos agotados en un duplicado
        return [*completo, f"error_api cc_{cedula}.pdf"]
    return []  # sin documentos


def generar_carpeta(raiz, codigos):
    for indice, nombre in enumerate(NOMBRES):
        carpeta = raiz / f"DEMO {indice + 1:02d} - {nombre}"
        carpeta.mkdir(parents=True)
        cedula = f"999{indice + 1:07d}"
        for archivo in _perfil(indice, codigos, cedula):
            especial = None
            if isinstance(archivo, tuple):
                archivo, especial = archivo
            ruta = carpeta / archivo
            if especial == "dañado":
                ruta.write_bytes(b"Esto no es un PDF valido.")
            else:
                clave = "secreta" if especial == "contraseña" else None
                _pdf(ruta, f"{carpeta.name}/{archivo}", clave_usuario=clave)
    return len(NOMBRES)


# Después de las corridas llega un archivo nuevo a estas carpetas y solo se escanea: un
# completo queda PENDIENTE_ANALISIS y un incompleto sigue INCOMPLETO, con su pendiente.
LLEGAN_DESPUES = (9, 10)


def agregar_pendientes(raiz):
    for indice in LLEGAN_DESPUES:
        carpeta = raiz / f"DEMO {indice + 1:02d} - {NOMBRES[indice]}"
        archivo = f"carta de recomendacion cc_999{indice + 1:07d}.pdf"
        _pdf(carpeta / archivo, f"{carpeta.name}/{archivo}")


def sembrar(raiz, usuario, fuente, codigos):
    cantidad = generar_carpeta(raiz, codigos)
    escanear(fuente)
    # Dos corridas: la segunda reintenta los errores y deja los reintentos agotados.
    for _ in range(2):
        crear_corrida(Corrida.Alcance.NUEVOS_Y_MODIFICADOS, usuario)
        ejecutar_worker(una_vez=True, fuente=fuente)
    agregar_pendientes(raiz)
    escanear(fuente)  # sin corrida: quedan pendientes de análisis
    return cantidad
