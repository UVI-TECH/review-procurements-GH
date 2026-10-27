"""Recorrido de la Fase 4a en Chromium: login, tablero, detalle con el PDF y una revisión.

Cada prueba falla si la consola registra una violación de CSP, un error de JavaScript,
o falla la carga de cualquier recurso (fuentes, scripts, estilos, el PDF): ver la
fixture problemas en conftest.py.
"""

import re

import pytest
from playwright.sync_api import expect

from apps.contrataciones.models import Revision

pytestmark = [
    pytest.mark.navegador,
    # serialized_rollback: el flush de la base transaccional no borra los roles ni el
    # catálogo que crean las migraciones de datos.
    pytest.mark.django_db(transaction=True, serialized_rollback=True),
]


def fuentes_cargadas(page):
    """Estado de cada cara de Atkinson Hyperlegible Next, cuando ya terminó de cargar."""
    return page.evaluate(
        """async () => {
            await document.fonts.ready;
            return [...document.fonts]
                .filter((f) => f.family.includes("Atkinson Hyperlegible Next"))
                .map((f) => f.weight + ":" + f.status);
        }"""
    )


def test_login_y_tablero(page, entrar, problemas):
    entrar()
    expect(page.get_by_role("heading", name="Tablero de profesores")).to_be_visible()
    expect(page.get_by_role("link", name="Ana Ejemplo")).to_be_visible()
    assert sorted(fuentes_cargadas(page)) == ["400:loaded", "700:loaded"]
    assert page.evaluate("typeof window.htmx") == "object"


def test_filtros_del_tablero_con_htmx(page, entrar, problemas):
    entrar()
    with page.expect_response(re.compile(r"/tablero/\?.*q=Beto")) as respuesta:
        page.get_by_label("Buscar por nombre o cédula").fill("Beto")
    assert respuesta.value.request.headers.get("hx-request") == "true"
    expect(page.get_by_role("link", name="Ana Ejemplo")).to_have_count(0)
    expect(page.get_by_role("link", name="Beto Prueba")).to_be_visible()
    expect(page).to_have_url(re.compile(r"q=Beto"))  # hx-push-url
    page.go_back()
    expect(page.get_by_role("link", name="Ana Ejemplo")).to_be_visible()


def test_tooltip_del_encabezado_con_teclado(page, entrar, problemas):
    entrar()
    encabezado = page.locator("th.col-tipo").first
    tooltip = encabezado.locator(".tooltip")
    expect(tooltip).to_be_hidden()
    encabezado.locator(".col-tipo-texto").focus()
    expect(tooltip).to_be_visible()
    page.keyboard.press("Escape")
    expect(tooltip).to_be_hidden()
    page.keyboard.press("Tab")  # sale del encabezado: la próxima vez vuelve a mostrarse
    encabezado.locator(".col-tipo-texto").focus()
    expect(tooltip).to_be_visible()


def test_detalle_con_el_pdf_en_el_iframe(page, live_server, entrar, problemas, datos_navegador):
    entrar()
    page.get_by_role("link", name="Ana Ejemplo").click()
    expect(page.get_by_role("heading", name="Ana Ejemplo", level=1)).to_be_visible()

    documentos = page.locator(".lista-documentos a")
    segundo = documentos.nth(1)
    pk = segundo.get_attribute("id").removeprefix("doc-")
    # El del primer documento puede seguir cargando: se espera el del elegido.
    with page.expect_response(re.compile(rf"/documentos/{pk}/pdf/$")) as pdf:
        segundo.click()
    assert pdf.value.status == 200
    assert pdf.value.headers["content-type"] == "application/pdf"
    # El resaltado sigue al elegido, y el foco se queda en él.
    expect(segundo).to_have_attribute("aria-current", "true")
    expect(documentos.nth(0)).not_to_have_attribute("aria-current", "true")
    expect(segundo).to_be_focused()
    iframe = page.locator("iframe.visor")
    expect(iframe).to_be_visible()
    assert iframe.get_attribute("src") == pdf.value.url.removeprefix(live_server.url)


def test_revisar_un_documento_y_ver_el_aviso(page, entrar, problemas, datos_navegador):
    entrar()
    page.get_by_role("link", name="Beto Prueba").click()
    page.locator(".lista-documentos a", has_text="roto.pdf").click()
    expect(page.locator("#panel h2")).to_have_text("roto.pdf")

    page.get_by_label("Descartar").check()
    page.get_by_label("Comentario").fill("Copia ilegible duplicada.")
    page.get_by_role("button", name="Guardar decisión").click()

    aviso = page.locator("#avisos .aviso-flotante")
    expect(aviso).to_have_count(1)
    expect(aviso).to_contain_text("Revisión guardada: descartado.")
    expect(page.locator("#avisos-servidor")).to_have_count(0)  # pasó a la región aria-live
    revision = Revision.objects.get()
    assert revision.decision == Revision.Decision.DESCARTADO
    assert revision.usuario == datos_navegador["revisor"]

    aviso.get_by_role("button", name="Cerrar aviso").click()
    expect(aviso).to_have_count(0)


def test_el_aviso_se_cierra_solo(page, entrar, problemas, datos_navegador):
    entrar()
    page.get_by_role("link", name="Beto Prueba").click()
    page.get_by_role("button", name="Confirmar cédula").click()
    aviso = page.locator("#avisos .aviso-flotante")
    expect(aviso).to_contain_text("Cédula confirmada.")
    expect(aviso).to_have_count(0, timeout=10_000)


def color(page, selector):
    return page.evaluate("(s) => getComputedStyle(document.querySelector(s)).color", selector)


def color_de_variable(page, variable):
    """El color calculado de una variable de :root (CSSOM: no lo restringe la CSP)."""
    return page.evaluate(
        """(v) => {
            const muestra = document.createElement("span");
            muestra.style.color = `var(${v})`;
            document.body.append(muestra);
            const calculado = getComputedStyle(muestra).color;
            muestra.remove();
            return calculado;
        }""",
        variable,
    )


def test_estado_pendiente_de_analisis_en_el_tablero(page, entrar, problemas):
    entrar()
    fila = page.locator("tr", has=page.get_by_role("link", name="Ciro Pendiente"))
    expect(fila.locator(".insignia.estado-pendiente_analisis")).to_have_text(
        "⏳ Pendiente de análisis"
    )
    expect(fila.locator(".etiqueta-pendiente")).to_have_text("1 pendiente de análisis")
    # Los colores no los pisa la base de .insignia ni de .etiqueta.
    pendiente = color_de_variable(page, "--pendiente")
    assert color(page, ".insignia.estado-pendiente_analisis") == pendiente
    assert color(page, ".etiqueta-pendiente") == pendiente
    assert color(page, ".total.estado-pendiente_analisis") == pendiente

    page.get_by_label("Estado", exact=True).select_option("PENDIENTE_ANALISIS")
    expect(page.get_by_role("link", name="Ana Ejemplo")).to_have_count(0)
    expect(page.get_by_role("link", name="Ciro Pendiente")).to_be_visible()


def test_colores_de_las_insignias_del_detalle(page, entrar, problemas):
    entrar()
    page.get_by_role("link", name="Ciro Pendiente").click()
    expect(page.locator(".ficha .insignia").first).to_have_text("⏳ Pendiente de análisis")
    expect(page.get_by_role("button", name="Marcar como verificado")).to_be_disabled()
    assert color(page, ".insignia.semaforo-valido") == color_de_variable(page, "--valido")
    assert color(page, ".lista-documentos .insignia.semaforo-pendiente") == color_de_variable(
        page, "--pendiente"
    )


def test_ningun_tooltip_se_ve_al_cargar_el_tablero(page, entrar, problemas):
    entrar()
    tooltips = page.locator("th.col-tipo .tooltip")
    expect(tooltips.first).to_be_attached()
    for indice in range(tooltips.count()):
        expect(tooltips.nth(indice)).to_be_hidden()
    encabezado = page.locator("th.col-tipo").nth(2)
    encabezado.hover()
    expect(encabezado.locator(".tooltip")).to_be_visible()
    page.mouse.move(0, 0)
    expect(encabezado.locator(".tooltip")).to_be_hidden()
