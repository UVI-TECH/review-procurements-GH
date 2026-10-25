"""Interfaz de la Fase 4a: autenticación, tablero, detalle, revisión y visor de PDF."""

import base64
import hashlib
from html.parser import HTMLParser

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.contrataciones.models import Analisis, Documento, Profesor, Revision, TipoDocumento
from apps.contrataciones.servicios.estado import recalcular_estado
from apps.contrataciones.servicios.revisiones import verificar_profesor
from apps.cuentas.models import RegistroAuditoria
from apps.motor.catalogo import cargar_catalogo
from config.entorno import BASE_DIR
from tests.fixtures.catalogo import CODIGOS
from tests.fixtures.datos import completo, documento
from tests.fixtures.pdfs import crear_pdf

pytestmark = pytest.mark.django_db

CLAVE = "una-clave-larga-de-prueba-9"


@pytest.fixture
def raiz(tmp_path, settings):
    raiz = tmp_path / "Contrataciones"
    raiz.mkdir()
    settings.CARPETA_CONTRATACIONES = raiz
    return raiz


@pytest.fixture
def revisor(crear_usuario):
    return crear_usuario("revisor", grupo="Revisor GH")


@pytest.fixture
def consulta(crear_usuario):
    return crear_usuario("consulta", grupo="Consulta")


@pytest.fixture
def datos(raiz, corrida):
    """Tres profesores: uno completo, uno incompleto con ilegible y uno sin carpeta."""
    catalogo = cargar_catalogo()
    ana = Profesor.objects.create(carpeta="DEMO ANA", nombre="Ana Ejemplo", cedula="")
    completo(ana, corrida)
    beto = Profesor.objects.create(carpeta="DEMO BETO", nombre="Beto Prueba")
    completo(beto, corrida, certificado_afp=None)
    documento(beto, corrida, Analisis.TIPO_ILEGIBLE, valido=False, cedula="", nombre="roto.pdf")
    ido = Profesor.objects.create(carpeta="DEMO IDO", nombre="Ido Ausente", carpeta_presente=False)
    for profesor in (ana, beto, ido):
        recalcular_estado(profesor, catalogo)
    # PDFs reales en la carpeta sintética, para el visor.
    for doc in Documento.objects.all():
        destino = raiz / doc.ruta_relativa
        destino.parent.mkdir(parents=True, exist_ok=True)
        crear_pdf(destino)
    return {"ana": ana, "beto": beto, "ido": ido}


def entrar(client, usuario):
    client.force_login(usuario)
    return client


def doc_de(profesor, codigo):
    return profesor.documentos.get(nombre_archivo=f"{codigo}.pdf")


# --- Autenticación y auditoría ---


def test_inicio_y_cierre_de_sesion_quedan_en_auditoria(client, crear_usuario):
    usuario = get_user_model().objects.create_user("persona", password=CLAVE)
    respuesta = client.post(reverse("login"), {"username": "persona", "password": CLAVE})
    assert respuesta.status_code == 302
    assert RegistroAuditoria.objects.filter(accion="inicio_sesion", usuario=usuario).exists()
    client.post(reverse("logout"))
    assert RegistroAuditoria.objects.filter(accion="cierre_sesion", usuario=usuario).exists()


def test_inicio_fallido_sin_usuario_y_con_el_nombre_intentado(client):
    respuesta = client.post(reverse("login"), {"username": "intruso", "password": "x"})
    assert respuesta.status_code == 200
    registro = RegistroAuditoria.objects.get(accion="inicio_sesion_fallido")
    assert registro.usuario is None
    assert registro.detalle == {"usuario": "intruso"}


def test_sin_sesion_redirige_al_login(client, datos):
    for url in (reverse("tablero"), reverse("detalle", args=[datos["ana"].pk])):
        respuesta = client.get(url)
        assert respuesta.status_code == 302
        assert respuesta.url.startswith(reverse("login"))


def test_la_sesion_expira_a_los_30_minutos_de_inactividad(settings):
    assert settings.SESSION_COOKIE_AGE == 30 * 60
    assert settings.SESSION_SAVE_EVERY_REQUEST


# --- Permisos por rol ---


def test_consulta_ve_el_tablero_pero_no_el_detalle_ni_el_pdf(client, consulta, datos):
    entrar(client, consulta)
    assert client.get(reverse("tablero")).status_code == 200
    ana = datos["ana"]
    assert client.get(reverse("detalle", args=[ana.pk])).status_code == 403
    doc = ana.documentos.first()
    assert client.get(reverse("pdf", args=[doc.pk])).status_code == 403
    respuesta = client.post(
        reverse("revisar", args=[ana.pk, doc.pk]), {"decision": "aprobado", "comentario": ""}
    )
    assert respuesta.status_code == 403


def test_consulta_no_ve_enlaces_al_detalle_ni_observaciones(client, consulta, datos):
    html = entrar(client, consulta).get(reverse("tablero")).content.decode()
    assert reverse("detalle", args=[datos["ana"].pk]) not in html


def test_revisor_no_llega_a_la_auditoria_global(client, revisor):
    entrar(client, revisor)
    url = reverse("admin:cuentas_registroauditoria_changelist")
    assert client.get(url).status_code == 403


def test_revisor_ve_el_detalle(client, revisor, datos):
    respuesta = entrar(client, revisor).get(reverse("detalle", args=[datos["ana"].pk]))
    assert respuesta.status_code == 200
    assert "Ana Ejemplo" in respuesta.content.decode()


# --- Tablero ---


def test_tablero_totales_columnas_del_catalogo_y_ocultos(client, revisor, datos):
    TipoDocumento.objects.filter(codigo="certificado_afp").update(activo=False)
    html = entrar(client, revisor).get(reverse("tablero")).content.decode()
    assert "Ana Ejemplo" in html and "Beto Prueba" in html
    assert "Ido Ausente" not in html  # carpeta no presente: oculto por defecto
    assert "Certificados EPS/AFP" not in html  # columna de un tipo inactivo
    assert "Antecedentes Disciplinarios" in html
    html = client.get(reverse("tablero"), {"ocultos": "1"}).content.decode()
    assert "Ido Ausente" in html


@pytest.mark.parametrize(
    ("filtros", "aparece", "no_aparece"),
    [
        ({"estado": "COMPLETO"}, "Ana Ejemplo", "Beto Prueba"),
        ({"falta": "certificado_afp"}, "Beto Prueba", "Ana Ejemplo"),
        ({"atencion": "1"}, "Beto Prueba", "Ana Ejemplo"),
        ({"q": "beto"}, "Beto Prueba", "Ana Ejemplo"),
        ({"q": "1000000001"}, "Ana Ejemplo", "Ido Ausente"),
        ({"verificacion": "vigente"}, "Ana Ejemplo", "Beto Prueba"),
    ],
)
def test_filtros_del_tablero(client, revisor, datos, filtros, aparece, no_aparece):
    verificar_profesor(datos["ana"], revisor)
    html = entrar(client, revisor).get(reverse("tablero"), filtros).content.decode()
    assert aparece in html
    assert no_aparece not in html


def test_filtro_por_tipo_desconocido_se_ignora(client, revisor, datos):
    respuesta = entrar(client, revisor).get(reverse("tablero"), {"falta": "__nombre__"})
    assert respuesta.status_code == 200


def test_tablero_paginado(client, revisor, corrida, raiz):
    for i in range(30):
        Profesor.objects.create(carpeta=f"DEMO {i:02d}", nombre=f"Profesor {i:02d}")
    html = entrar(client, revisor).get(reverse("tablero")).content.decode()
    assert "Profesor 00" in html and "Profesor 29" not in html
    html = client.get(reverse("tablero"), {"pagina": "2"}).content.decode()
    assert "Profesor 29" in html


def test_tablero_con_htmx_devuelve_solo_el_fragmento(client, revisor, datos):
    respuesta = entrar(client, revisor).get(reverse("tablero"), HTTP_HX_REQUEST="true")
    html = respuesta.content.decode()
    assert "<html" not in html and "Ana Ejemplo" in html
    assert "HX-Request" in respuesta["Vary"]


# --- Revisión desde el detalle ---


def test_revisar_un_documento(client, revisor, datos):
    beto = datos["beto"]
    roto = beto.documentos.get(nombre_archivo="roto.pdf")
    respuesta = entrar(client, revisor).post(
        reverse("revisar", args=[beto.pk, roto.pk]),
        {"decision": "descartado", "comentario": "Copia dañada de otro documento"},
    )
    assert respuesta.status_code == 302
    assert Revision.objects.get().decision == "descartado"
    assert RegistroAuditoria.objects.filter(accion="revision_creada").exists()


def test_revision_invalida_muestra_el_error_y_no_guarda(client, revisor, datos):
    ana = datos["ana"]
    doc = doc_de(ana, CODIGOS[0])
    respuesta = entrar(client, revisor).post(
        reverse("revisar", args=[ana.pk, doc.pk]),
        {"decision": "rechazado", "comentario": ""},
        follow=True,
    )
    assert "comentario" in respuesta.content.decode()
    assert not Revision.objects.exists()


def test_corregir_el_tipo(client, revisor, datos):
    beto = datos["beto"]
    roto = beto.documentos.get(nombre_archivo="roto.pdf")
    eps = TipoDocumento.objects.get(codigo="certificado_afp")
    entrar(client, revisor).post(
        reverse("revisar", args=[beto.pk, roto.pk]),
        {"decision": "corregido", "comentario": "Es la EPS", "tipo_corregido": eps.pk},
    )
    assert Revision.objects.get().tipo_corregido == eps


def test_documento_de_otro_profesor_da_404(client, revisor, datos):
    doc = datos["beto"].documentos.first()
    respuesta = entrar(client, revisor).post(
        reverse("revisar", args=[datos["ana"].pk, doc.pk]), {"decision": "aprobado"}
    )
    assert respuesta.status_code == 404


def test_verificar_desde_el_detalle(client, revisor, datos):
    ana = datos["ana"]
    entrar(client, revisor).post(reverse("verificar", args=[ana.pk]))
    ana.refresh_from_db()
    assert ana.verificacion == Profesor.Verificacion.VIGENTE


def test_verificar_un_incompleto_muestra_por_que_no(client, revisor, datos):
    respuesta = entrar(client, revisor).post(
        reverse("verificar", args=[datos["beto"].pk]), follow=True
    )
    assert "COMPLETO" in respuesta.content.decode()
    datos["beto"].refresh_from_db()
    assert datos["beto"].verificado_por is None


def test_confirmar_la_cedula_desde_el_detalle(client, revisor, datos):
    ana = datos["ana"]
    entrar(client, revisor).post(reverse("cedula", args=[ana.pk]), {"cedula": "1000000001"})
    ana.refresh_from_db()
    assert ana.cedula_confirmada == "1000000001"


def test_historial_del_profesor(client, revisor, datos):
    ana = datos["ana"]
    entrar(client, revisor)
    client.post(reverse("verificar", args=[ana.pk]))
    html = client.get(reverse("detalle", args=[ana.pk])).content.decode()
    assert "profesor_verificado" in html or "Verificado por" in html


# --- Visor de PDF ---


def test_pdf_inline_con_cabeceras_y_auditoria(client, revisor, datos):
    doc = datos["ana"].documentos.first()
    respuesta = entrar(client, revisor).get(reverse("pdf", args=[doc.pk]))
    assert respuesta.status_code == 200
    assert respuesta["Content-Type"] == "application/pdf"
    assert respuesta["Content-Disposition"].startswith("inline")
    assert "no-store" in respuesta["Cache-Control"]
    assert respuesta["X-Content-Type-Options"] == "nosniff"
    assert respuesta["X-Frame-Options"] == "SAMEORIGIN"
    assert (
        b"".join(respuesta.streaming_content if respuesta.streaming else [respuesta.content])[:4]
        == b"%PDF"
    )
    registro = RegistroAuditoria.objects.get(accion="pdf_visto")
    assert (registro.usuario, registro.objeto) == (revisor, doc)


def test_pdf_con_ruta_fuera_de_la_raiz_da_404(client, revisor, datos):
    doc = datos["ana"].documentos.first()
    Documento.objects.filter(pk=doc.pk).update(ruta_relativa="../secreto.pdf")
    assert entrar(client, revisor).get(reverse("pdf", args=[doc.pk])).status_code == 404


def test_pdf_de_documento_no_presente_da_404(client, revisor, datos):
    doc = datos["ana"].documentos.first()
    Documento.objects.filter(pk=doc.pk).update(presente=False)
    assert entrar(client, revisor).get(reverse("pdf", args=[doc.pk])).status_code == 404


# --- Cabeceras y CSP ---


def test_paginas_con_datos_personales_sin_cache_y_con_csp(client, revisor, datos):
    entrar(client, revisor)
    for url in (reverse("tablero"), reverse("detalle", args=[datos["ana"].pk])):
        respuesta = client.get(url)
        assert "no-store" in respuesta["Cache-Control"]
        csp = respuesta["Content-Security-Policy"]
        assert "default-src 'self'" in csp
        assert "script-src 'self'" in csp
        assert "frame-src 'self'" in csp
        assert "frame-ancestors 'self'" in csp
        assert "unsafe-inline" not in csp and "unsafe-eval" not in csp


def test_htmx_configurado_para_la_csp_y_sin_historial_local(client, revisor, datos):
    import json

    class Meta(HTMLParser):
        config = None

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == "meta" and attrs.get("name") == "htmx-config":
                Meta.config = json.loads(attrs["content"])

    html = entrar(client, revisor).get(reverse("tablero")).content.decode()
    Meta().feed(html)
    assert Meta.config == {
        "includeIndicatorStyles": False,
        "allowEval": False,
        "historyCacheSize": 0,
        "allowScriptTags": False,
        "selfRequestsOnly": True,
        "historyRestoreAsHxRequest": False,
    }
    assert "X-CSRFToken" in html  # hx-headers con el token CSRF


class _Revision(HTMLParser):
    """Recoge scripts en línea, atributos style y campos sin etiqueta."""

    def __init__(self):
        super().__init__()
        self.scripts_en_linea, self.estilos, self.etiquetas, self.campos = 0, 0, set(), []
        self.atributos_prohibidos = []
        self._en_script = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "style" in attrs:
            self.estilos += 1
        for nombre in attrs:
            if nombre.startswith("hx-on") or nombre.startswith("on"):
                self.atributos_prohibidos.append(nombre)
        if tag == "script" and "src" not in attrs:
            self._en_script = True
        if tag == "label" and attrs.get("for"):
            self.etiquetas.add(attrs["for"])
        if tag in ("input", "select", "textarea") and attrs.get("type") not in (
            "hidden",
            "submit",
            "radio",
            "checkbox",
        ):
            self.campos.append(attrs)

    def handle_data(self, data):
        if self._en_script and data.strip():
            self.scripts_en_linea += 1

    def handle_endtag(self, tag):
        if tag == "script":
            self._en_script = False


@pytest.mark.parametrize("pagina", ["login", "tablero", "detalle"])
def test_html_sin_scripts_ni_estilos_en_linea_y_campos_con_etiqueta(client, revisor, datos, pagina):
    if pagina != "login":
        entrar(client, revisor)
    url = reverse(pagina, args=[datos["ana"].pk]) if pagina == "detalle" else reverse(pagina)
    html = client.get(url).content.decode()
    revision = _Revision()
    revision.feed(html)
    assert revision.scripts_en_linea == 0
    assert revision.estilos == 0
    assert revision.atributos_prohibidos == []
    for campo in revision.campos:
        assert campo.get("id") in revision.etiquetas or campo.get("aria-label"), campo
    assert '<html lang="es"' in html
    assert "<main" in html
    assert 'class="saltar"' in html  # enlace para saltar al contenido


# --- Archivos de static/vendor fijados ---


def test_htmx_fijado_por_su_sri():
    datos = (BASE_DIR / "static" / "vendor" / "htmx-2.0.11.min.js").read_bytes()
    sri = "sha384-" + base64.b64encode(hashlib.sha384(datos).digest()).decode()
    assert sri == "sha384-2OatzQy1H+Zd/IIrjr1TcuDGqLXeHhbooAyJY1KdQMKnr4LZ22k31GBLdYKHmVjg"


@pytest.mark.parametrize(
    ("archivo", "sha256"),
    [
        (
            "AtkinsonHyperlegibleNext-Regular.woff2",
            "378aea0f5c1d179f4e0b5382c06bfc87571b98cfcc4fd1352bc979e2e2259c54",
        ),
        (
            "AtkinsonHyperlegibleNext-Bold.woff2",
            "dda449f0f556a595cffd0a9ce479bb1210beba286cb4c2f5aeca6975f9c85a3b",
        ),
    ],
)
def test_fuentes_fijadas_y_con_su_licencia(archivo, sha256):
    carpeta = BASE_DIR / "static" / "vendor" / "fonts"
    assert hashlib.sha256((carpeta / archivo).read_bytes()).hexdigest() == sha256
    assert "SIL Open Font License" in (carpeta / "OFL.txt").read_text()


@pytest.mark.parametrize(
    "ruta",
    [
        "css/app.css",
        "vendor/htmx-2.0.11.min.js",
        "vendor/fonts/AtkinsonHyperlegibleNext-Regular.woff2",
    ],
)
def test_whitenoise_sirve_los_estaticos(client, ruta):
    respuesta = client.get(f"/static/{ruta}")
    assert respuesta.status_code == 200


def test_consulta_no_ve_ni_busca_cedulas(client, consulta, revisor, datos):
    """ADR 0002: Consulta no ve análisis porque repiten la cédula; tampoco en el tablero."""
    datos["ana"].refresh_from_db()
    cedula = datos["ana"].cedula
    assert cedula
    html = entrar(client, consulta).get(reverse("tablero")).content.decode()
    assert cedula not in html
    assert "Cédula" not in html
    html = client.get(reverse("tablero"), {"q": cedula}).content.decode()
    assert "Ana Ejemplo" not in html  # buscar por cédula no revela a quién pertenece
    html = entrar(client, revisor).get(reverse("tablero"), {"q": cedula}).content.decode()
    assert "Ana Ejemplo" in html and cedula in html


# --- Páginas de error ---


def _texto_de_error(respuesta):
    html = respuesta.content.decode()
    assert '<html lang="es"' in html
    assert 'href="/static/css/app.css"' in html
    assert 'href="/tablero/"' in html  # enlace para volver
    return html


def test_403_propio_en_espanol(client, consulta, datos):
    respuesta = entrar(client, consulta).get(reverse("detalle", args=[datos["ana"].pk]))
    assert respuesta.status_code == 403
    assert "No tienes permiso" in _texto_de_error(respuesta)


def test_404_propio_en_espanol(client, revisor, datos):
    respuesta = entrar(client, revisor).get("/profesores/999999/")
    assert respuesta.status_code == 404
    html = _texto_de_error(respuesta)
    assert "No encontramos esta página" in html
    assert "999999" not in html  # no repite la ruta pedida


def test_403_de_csrf_propio(revisor, datos):
    from django.test import Client

    client = Client(enforce_csrf_checks=True)
    client.force_login(revisor)
    respuesta = client.post(reverse("verificar", args=[datos["ana"].pk]))
    assert respuesta.status_code == 403
    assert "La página caducó" in _texto_de_error(respuesta)


def test_500_propio_sin_depender_de_la_peticion(rf):
    from django.views.defaults import server_error

    respuesta = server_error(rf.get("/"))
    assert respuesta.status_code == 500
    assert "Algo falló en la aplicación" in _texto_de_error(respuesta)


def test_consulta_no_ve_enlaces_al_detalle_ni_al_pdf(client, consulta, datos):
    html = entrar(client, consulta).get(reverse("tablero"), {"ocultos": "1"}).content.decode()
    assert "Ana Ejemplo" in html
    assert "/profesores/" not in html
    assert "/pdf/" not in html


# --- Avisos ("toasts") ---


def test_la_pagina_trae_la_region_de_avisos_y_el_script_propio(client, revisor, datos):
    html = entrar(client, revisor).get(reverse("tablero")).content.decode()
    assert 'id="avisos"' in html and 'aria-live="polite"' in html
    assert 'src="/static/js/app.js"' in html
    assert client.get("/static/js/app.js").status_code == 200


def test_mensaje_en_pagina_completa_queda_en_la_lista_del_servidor(client, revisor, datos):
    entrar(client, revisor)
    beto = datos["beto"]  # incompleto: verificarlo da un error
    client.post(reverse("verificar", args=[beto.pk]))
    html = client.get(reverse("detalle", args=[beto.pk])).content.decode()
    assert 'id="avisos-servidor"' in html
    assert 'data-nivel="error"' in html
    assert "COMPLETO" in html


def test_mensaje_en_respuesta_htmx_viaja_en_hx_trigger(client, revisor, datos):
    import json

    entrar(client, revisor)
    beto = datos["beto"]
    client.post(reverse("verificar", args=[beto.pk]))
    respuesta = client.get(reverse("tablero"), headers={"HX-Request": "true"})
    disparo = json.loads(respuesta["HX-Trigger"])
    assert respuesta["HX-Trigger"].isascii()  # cabecera HTTP: sin tildes crudas
    [aviso] = disparo["avisos"]
    assert aviso["nivel"] == "error" and "COMPLETO" in aviso["texto"]
    # Consumido: no reaparece en la página siguiente.
    assert 'id="avisos-servidor"' not in client.get(reverse("tablero")).content.decode()


def test_sin_mensajes_no_hay_hx_trigger(client, revisor, datos):
    respuesta = entrar(client, revisor).get(reverse("tablero"), headers={"HX-Request": "true"})
    assert "HX-Trigger" not in respuesta


def test_encabezados_de_tipo_con_tooltip_accesible_con_teclado(client, revisor, datos):
    html = entrar(client, revisor).get(reverse("tablero")).content.decode()
    activos = TipoDocumento.objects.filter(activo=True)
    for tipo in activos:
        assert (
            f'<span class="col-tipo-texto" tabindex="0">{tipo.etiqueta}</span>'
            f'<span class="tooltip" aria-hidden="true">{tipo.etiqueta}</span>'
        ) in html
    css = (BASE_DIR / "static/css/app.css").read_text()
    assert ".col-tipo:focus-within .tooltip" in css  # no solo :hover


def test_elegir_documento_por_htmx_mueve_el_resaltado_de_la_lista(client, revisor, datos):
    import re

    ana = datos["ana"]
    primero, segundo = ana.documentos.order_by("ruta_relativa")[:2]
    respuesta = entrar(client, revisor).get(
        reverse("detalle", args=[ana.pk]),
        {"documento": segundo.pk},
        headers={"HX-Request": "true"},
    )
    html = respuesta.content.decode()
    assert html.lstrip().startswith('<div id="espacio"')  # lista y panel, no la página
    assert "<html" not in html
    actuales = re.findall(r'<a id="doc-(\d+)"[^>]*aria-current="true"', html)
    assert actuales == [str(segundo.pk)]
    assert f'id="doc-{primero.pk}"' in html
    assert f'src="{reverse("pdf", args=[segundo.pk])}"' in html


def test_el_detalle_sin_elegir_resalta_el_primer_documento(client, revisor, datos):
    import re

    ana = datos["ana"]
    primero = ana.documentos.order_by("ruta_relativa").first()
    html = entrar(client, revisor).get(reverse("detalle", args=[ana.pk])).content.decode()
    assert re.findall(r'<a id="doc-(\d+)"[^>]*aria-current="true"', html) == [str(primero.pk)]


# --- Pendientes de análisis ---


def _sin_analizar(profesor, nombre="nuevo.pdf", **extra):
    from django.utils import timezone

    return Documento.objects.create(
        profesor=profesor,
        ruta_relativa=f"{profesor.carpeta}/{nombre}",
        nombre_archivo=nombre,
        sha256=hashlib.sha256(nombre.encode()).hexdigest(),
        tamano=10,
        modificado_en=timezone.now(),
        **extra,
    )


def test_tablero_cuenta_y_filtra_pendientes_de_analisis(client, revisor, datos):
    ana, beto = datos["ana"], datos["beto"]
    _sin_analizar(ana, "nuevo1.pdf")
    _sin_analizar(ana, "nuevo2.pdf")
    _sin_analizar(beto, "viejo.pdf", presente=False)  # ya no está: no cuenta
    # Analizado, pero el archivo cambió después: su sha256 actual está pendiente.
    cambiado = beto.documentos.filter(presente=True).first()
    cambiado.sha256 = "f" * 64
    cambiado.save()
    entrar(client, revisor)
    html = client.get(reverse("tablero")).content.decode()
    assert "2 pendientes de análisis" in html
    assert "1 pendiente de análisis" in html
    html = client.get(reverse("tablero"), {"pendientes": "1"}).content.decode()
    assert "Ana Ejemplo" in html and "Beto Prueba" in html
    cambiado.sha256 = Analisis.objects.filter(documento=cambiado).first().sha256
    cambiado.save()
    html = client.get(reverse("tablero"), {"pendientes": "1"}).content.decode()
    assert "Ana Ejemplo" in html and "Beto Prueba" not in html
    assert 'id="pendientes"' in html


def test_un_error_de_analisis_no_es_pendiente(client, revisor, datos, corrida):
    nuevo = _sin_analizar(datos["ana"], "fallo.pdf")
    Analisis.objects.create(
        documento=nuevo,
        corrida=corrida,
        sha256=nuevo.sha256,
        modelo="simulado",
        tipo_detectado=Analisis.TIPO_ERROR,
        es_valido=False,
        observaciones="Red caída.",
    )
    html = entrar(client, revisor).get(reverse("tablero"), {"pendientes": "1"}).content.decode()
    assert "Ana Ejemplo" not in html


def test_detalle_muestra_pendiente_y_no_error(client, revisor, datos):
    ana = datos["ana"]
    nuevo = _sin_analizar(ana, "zz-nuevo.pdf")
    entrar(client, revisor)
    html = client.get(reverse("detalle", args=[ana.pk])).content.decode()
    assert "1 documento pendiente de análisis." in html
    html = client.get(reverse("detalle", args=[ana.pk]), {"documento": nuevo.pk}).content.decode()
    inicio = html.index(f'id="doc-{nuevo.pk}"')
    enlace = html[inicio : html.index("</a>", inicio)]
    assert "Pendiente de análisis" in enlace and "Error" not in enlace
    panel = html[html.index('id="panel"') :]
    assert "Se analizará en la próxima corrida." in panel
    assert "<dt>Error</dt>" not in panel


def test_estado_pendiente_de_analisis_en_tablero_y_filtro(client, consulta, datos):
    ana = datos["ana"]
    _sin_analizar(ana, "zz-nuevo.pdf")
    recalcular_estado(ana, cargar_catalogo())
    ana.refresh_from_db()
    assert ana.estado == "PENDIENTE_ANALISIS"
    entrar(client, consulta)
    html = client.get(reverse("tablero")).content.decode()
    assert (
        '<span class="insignia estado-pendiente_analisis"><span aria-hidden="true">⏳</span> '
        "Pendiente de análisis</span>"
    ) in html
    assert 'href="?estado=PENDIENTE_ANALISIS"' in html  # total por estado
    assert '<option value="PENDIENTE_ANALISIS"' in html  # filtro
    html = client.get(reverse("tablero"), {"estado": "PENDIENTE_ANALISIS"}).content.decode()
    assert "Ana Ejemplo" in html and "Beto Prueba" not in html


def test_verificacion_sin_verificar_no_se_confunde_con_pendiente_de_analisis(
    client, revisor, datos
):
    entrar(client, revisor)
    html = client.get(reverse("tablero")).content.decode()
    assert '<span class="insignia verificacion-pendiente">Sin verificar</span>' in html
    assert '<option value="pendiente">Sin verificar</option>' in html  # filtro, mismo valor
    assert ">Pendiente<" not in html
    html = client.get(reverse("detalle", args=[datos["beto"].pk])).content.decode()
    assert '<span class="insignia verificacion-pendiente">Sin verificar</span>' in html
