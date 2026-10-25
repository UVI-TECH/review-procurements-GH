"""Pruebas en Chromium real con Playwright. Solo corren en CI (job "navegador").

Localmente se excluyen (pyproject: -m "not navegador"): el sandbox de Claude Code no
tiene acceso a la descarga del navegador. Para correrlas a mano en una terminal propia:
    uv run playwright install chromium
    uv run pytest -m navegador --browser-channel chromium
"""

import os

import pytest
from django.utils import timezone

from apps.contrataciones.models import Analisis, Documento, Profesor
from apps.contrataciones.servicios.estado import recalcular_estado
from apps.motor.catalogo import cargar_catalogo
from tests.fixtures.datos import completo, documento
from tests.fixtures.pdfs import crear_pdf

CLAVE = "una-clave-larga-de-prueba-9"

# Cualquier violación de CSP llega a la consola como error, aunque el navegador la reporte
# de otra forma. Los scripts de inicio de Playwright no están sujetos a la CSP de la página.
ESCUCHAR_CSP = """
document.addEventListener("securitypolicyviolation", (e) => {
  console.error("CSP: " + e.violatedDirective + " bloqueó " + (e.blockedURI || "código en línea"));
});
"""


@pytest.fixture(scope="session", autouse=True)
def permitir_orm_con_playwright():
    """La API síncrona de Playwright deja un bucle de asyncio en el hilo de la prueba, y
    Django se niega a usar el ORM ahí. Solo afecta a estas pruebas (autouse de este dir)."""
    anterior = os.environ.get("DJANGO_ALLOW_ASYNC_UNSAFE")
    os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
    yield
    if anterior is None:
        os.environ.pop("DJANGO_ALLOW_ASYNC_UNSAFE", None)
    else:
        os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = anterior


# El visor de PDF de Chrome es una extensión interna. Si la página navega mientras carga
# el PDF del iframe (p. ej. al guardar una revisión), el navegador aborta su petición: no
# es un recurso de la app. Solo se ignora ese caso exacto.
VISOR_PDF_DE_CHROME = "chrome-extension://mhjfbmdgcfjbbpaeojofohoefgiehjai/"


def _fallo_propio(peticion):
    return not (
        peticion.url.startswith(VISOR_PDF_DE_CHROME) and peticion.failure == "net::ERR_ABORTED"
    )


@pytest.fixture
def problemas(page):
    """Errores de consola, de JavaScript, de red y respuestas >= 400 durante la prueba."""
    lista = []
    page.add_init_script(script=ESCUCHAR_CSP)
    page.on("console", lambda m: m.type == "error" and lista.append(f"consola: {m.text}"))
    page.on("pageerror", lambda e: lista.append(f"JavaScript: {e}"))
    page.on(
        "requestfailed",
        lambda r: _fallo_propio(r) and lista.append(f"falló {r.url}: {r.failure}"),
    )
    page.on("response", lambda r: r.status >= 400 and lista.append(f"{r.status} {r.url}"))
    yield lista
    assert lista == [], "\n".join(lista)


@pytest.fixture
def datos_navegador(tmp_path, settings, crear_usuario, corrida):
    raiz = tmp_path / "Contrataciones"
    raiz.mkdir()
    settings.CARPETA_CONTRATACIONES = raiz
    catalogo = cargar_catalogo()
    ana = Profesor.objects.create(carpeta="DEMO ANA", nombre="Ana Ejemplo")
    completo(ana, corrida)
    beto = Profesor.objects.create(carpeta="DEMO BETO", nombre="Beto Prueba")
    completo(beto, corrida, certificado_afp=None)
    documento(beto, corrida, Analisis.TIPO_ILEGIBLE, valido=False, cedula="", nombre="roto.pdf")
    # Completo, pero con un archivo nuevo aún sin analizar: PENDIENTE_ANALISIS.
    ciro = Profesor.objects.create(carpeta="DEMO CIRO", nombre="Ciro Pendiente")
    completo(ciro, corrida)
    Documento.objects.create(
        profesor=ciro,
        ruta_relativa="DEMO CIRO/nuevo.pdf",
        nombre_archivo="nuevo.pdf",
        sha256="e" * 64,
        tamano=1,
        modificado_en=timezone.now(),
    )
    for profesor in (ana, beto, ciro):
        recalcular_estado(profesor, catalogo)
    for doc in Documento.objects.all():
        destino = raiz / doc.ruta_relativa
        destino.parent.mkdir(parents=True, exist_ok=True)
        crear_pdf(destino)
    revisor = crear_usuario("revisor", grupo="Revisor GH", first_name="Rita")
    revisor.set_password(CLAVE)
    revisor.save()
    return {"ana": ana, "beto": beto, "ciro": ciro, "revisor": revisor}


@pytest.fixture
def entrar(page, live_server, datos_navegador):
    def _entrar(usuario="revisor"):
        page.goto(f"{live_server.url}/entrar/")
        page.get_by_label("Usuario").fill(usuario)
        page.get_by_label("Contraseña").fill(CLAVE)
        page.get_by_role("button", name="Entrar").click()
        page.wait_for_url(f"{live_server.url}/tablero/")

    return _entrar
