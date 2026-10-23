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
    completo(beto, corrida, certificados_eps_afp=None)
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
    TipoDocumento.objects.filter(codigo="certificados_eps_afp").update(activo=False)
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
        ({"falta": "certificados_eps_afp"}, "Beto Prueba", "Ana Ejemplo"),
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
    eps = TipoDocumento.objects.get(codigo="certificados_eps_afp")
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
