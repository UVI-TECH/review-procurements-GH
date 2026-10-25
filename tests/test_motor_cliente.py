"""Cliente real (con un SDK falso: ninguna prueba llama a la API), simulado y lectura del PDF."""

from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from django.core.exceptions import ImproperlyConfigured

from apps.motor.cliente_claude import ClienteClaude
from apps.motor.esquema import NOMBRE_HERRAMIENTA
from apps.motor.servicio import crear_cliente
from apps.motor.simulado import ClienteSimulado
from tests.fixtures.catalogo import FORMATO, catalogo_inicial
from tests.fixtures.pdfs import crear_pdf, crear_pdf_cifrado

CLAVE_FALSA = "sk-ant-api03-clave-falsa-de-prueba-que-no-debe-aparecer"


class SdkFalso:
    """Imita client.messages.create y guarda cada llamada."""

    def __init__(self, respuesta=None, error=None):
        self.respuesta = respuesta
        self.error = error
        self.llamadas = []
        self.messages = self

    def create(self, **kwargs):
        self.llamadas.append(kwargs)
        if self.error:
            raise self.error
        return self.respuesta


def respuesta(entrada=None, stop_reason="tool_use", uso=None, bloques=None):
    if bloques is None:
        bloques = [SimpleNamespace(type="tool_use", name=NOMBRE_HERRAMIENTA, input=entrada)]
    return SimpleNamespace(
        content=bloques,
        stop_reason=stop_reason,
        model="claude-haiku-4-5-20251001",
        usage=uso
        or SimpleNamespace(
            input_tokens=1500,
            output_tokens=120,
            cache_read_input_tokens=None,
            cache_creation_input_tokens=0,
        ),
    )


def entrada(**cambios):
    return {
        "tipo_detectado": "certificado_antecedentes_judiciales",
        "es_valido": True,
        "numero_documento": "1000000001",
        "nombre_persona": "Profesor Ficticio",
        "tiene_firma": None,
        "fecha_emision_eps": None,
        "fecha_emision_afp": None,
        "es_certificado_afiliacion": None,
        "observaciones": "",
        **cambios,
    }


def error_api(clase, codigo):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return clase(
        f"Fallo con la clave {CLAVE_FALSA}",
        response=httpx2.Response(codigo, request=request),
        body={"error": CLAVE_FALSA},
    )


@pytest.fixture
def pdf(tmp_path):
    return crear_pdf(tmp_path / "judicial.pdf")


def cliente(sdk):
    return ClienteClaude(catalogo_inicial(), sdk=sdk)


# --- El cliente real no se crea en pruebas ---


def test_instanciar_el_cliente_real_falla_en_pruebas():
    with pytest.raises(ImproperlyConfigured, match="MOTOR_SIMULADO"):
        ClienteClaude(catalogo_inicial())


def test_crear_cliente_en_pruebas_da_el_simulado():
    assert isinstance(crear_cliente(catalogo_inicial()), ClienteSimulado)


def test_sin_clave_da_un_error_claro(settings, monkeypatch):
    settings.MOTOR_SIMULADO = False
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ImproperlyConfigured, match="Define ANTHROPIC_API_KEY en el .env"):
        ClienteClaude(catalogo_inicial())


# --- Petición ---


def test_peticion_fuerza_la_herramienta_estricta_y_cachea_el_system(pdf, settings):
    sdk = SdkFalso(respuesta(entrada()))
    cliente(sdk).analizar(pdf, "PROFESOR FICTICIO")
    (llamada,) = sdk.llamadas
    assert llamada["model"] == settings.MODELO_CLAUDE == "claude-haiku-4-5-20251001"
    assert llamada["max_tokens"] == settings.MOTOR_MAX_TOKENS
    assert llamada["tool_choice"] == {"type": "tool", "name": NOMBRE_HERRAMIENTA}
    assert [h["name"] for h in llamada["tools"]] == [NOMBRE_HERRAMIENTA]
    assert llamada["tools"][0]["strict"] is True
    assert llamada["system"][-1]["cache_control"] == {"type": "ephemeral"}
    contenido = llamada["messages"][0]["content"]
    assert contenido[0]["type"] == "document"
    assert "<profesor>PROFESOR FICTICIO</profesor>" in contenido[1]["text"]


def test_resultado_y_tokens(pdf):
    uso = SimpleNamespace(
        input_tokens=1500,
        output_tokens=120,
        cache_read_input_tokens=3000,
        cache_creation_input_tokens=40,
    )
    resultado = cliente(SdkFalso(respuesta(entrada(), uso=uso))).analizar(pdf, "P")
    assert not resultado.es_error
    assert resultado.nombre_archivo == "judicial.pdf"
    assert resultado.modelo == "claude-haiku-4-5-20251001"
    assert resultado.modificado_en is not None
    assert (resultado.uso.entrada, resultado.uso.salida) == (1500, 120)
    assert (resultado.uso.cache_lectura, resultado.uso.cache_creacion) == (3000, 40)


def test_tokens_de_cache_nulos_cuentan_cero(pdf):
    resultado = cliente(SdkFalso(respuesta(entrada()))).analizar(pdf, "P")
    assert resultado.uso.cache_lectura == 0


# --- Respuestas que terminan en ERROR, nunca en excepción ---


@pytest.mark.parametrize(
    ("resp", "mensaje"),
    [
        (respuesta(entrada(es_valido="sí")), "Respuesta fuera del esquema"),
        (respuesta({"tipo_detectado": "otro"}), "Respuesta fuera del esquema"),
        (respuesta(bloques=[SimpleNamespace(type="text", text="{}")]), "no usó la herramienta"),
        (respuesta(entrada(), stop_reason="max_tokens"), "se cortó"),
        (respuesta(bloques=[], stop_reason="refusal"), "se negó"),
    ],
    ids=["tipo-incorrecto", "campos-faltantes", "sin-herramienta", "max-tokens", "rechazo"],
)
def test_respuesta_invalida_es_error(pdf, resp, mensaje):
    resultado = cliente(SdkFalso(resp)).analizar(pdf, "P")
    assert resultado.es_error
    assert mensaje in resultado.error
    assert resultado.uso.entrada == 1500  # los tokens se cobran aunque la respuesta no sirva


@pytest.mark.parametrize(
    ("error", "mensaje"),
    [
        (error_api(anthropic.AuthenticationError, 401), "401"),
        (error_api(anthropic.RateLimitError, 429), "429"),
        (error_api(anthropic.InternalServerError, 500), "500"),
        (anthropic.APITimeoutError(request=httpx2.Request("POST", "https://x")), "Tiempo"),
        (anthropic.APIConnectionError(request=httpx2.Request("POST", "https://x")), "conexión"),
    ],
    ids=["401", "429", "500", "timeout", "conexion"],
)
def test_error_de_la_api_es_error_sin_filtrar_la_clave(pdf, error, mensaje):
    resultado = cliente(SdkFalso(error=error)).analizar(pdf, "P")
    assert resultado.es_error
    assert mensaje in resultado.error
    assert CLAVE_FALSA not in repr(resultado)


def test_errores_de_la_api_no_se_registran_con_la_clave(pdf, caplog):
    cliente(SdkFalso(error=error_api(anthropic.AuthenticationError, 401))).analizar(pdf, "P")
    assert CLAVE_FALSA not in caplog.text


# --- Límites del PDF, sin llamar a la API ---


def test_pdf_por_encima_del_tamano_es_ilegible_sin_llamar_a_la_api(pdf, settings):
    settings.MOTOR_MAX_BYTES_PDF = 100
    sdk = SdkFalso(respuesta(entrada()))
    resultado = cliente(sdk).analizar(pdf, "P")
    assert resultado.es_ilegible and not resultado.es_error
    assert "MB" in resultado.observaciones
    assert "solicitar" in resultado.observaciones
    assert sdk.llamadas == []


def test_pdf_con_demasiadas_paginas_es_ilegible_sin_llamar_a_la_api(tmp_path, settings):
    settings.MOTOR_MAX_PAGINAS_PDF = 2
    sdk = SdkFalso(respuesta(entrada()))
    resultado = cliente(sdk).analizar(crear_pdf(tmp_path / "largo.pdf", paginas=3), "P")
    assert resultado.es_ilegible and not resultado.es_error
    assert "3 páginas" in resultado.observaciones
    assert sdk.llamadas == []


def test_archivo_que_no_es_pdf_es_ilegible_sin_llamar_a_la_api(tmp_path):
    falso = tmp_path / "falso.pdf"
    falso.write_bytes(b"esto no es un PDF")
    sdk = SdkFalso(respuesta(entrada()))
    resultado = cliente(sdk).analizar(falso, "P")
    assert resultado.es_ilegible and not resultado.es_error
    assert "no es un PDF válido" in resultado.observaciones
    assert sdk.llamadas == []


def test_pdf_con_clave_de_propietario_se_envia(tmp_path):
    cifrado = crear_pdf_cifrado(tmp_path / "certificado.pdf", clave_usuario="")
    sdk = SdkFalso(respuesta(entrada()))
    resultado = cliente(sdk).analizar(cifrado, "P")
    assert not resultado.es_error
    assert len(sdk.llamadas) == 1


def test_pdf_que_pide_clave_para_abrirse_es_ilegible(tmp_path):
    cifrado = crear_pdf_cifrado(tmp_path / "protegido.pdf", clave_usuario="secreta")
    sdk = SdkFalso(respuesta(entrada()))
    resultado = cliente(sdk).analizar(cifrado, "P")
    assert resultado.es_ilegible and not resultado.es_error
    assert resultado.tipo_detectado == "ilegible"
    assert resultado.es_valido is False
    assert resultado.observaciones == (
        "PDF protegido con contraseña: solicitar un nuevo archivo sin contraseña."
    )
    assert resultado.modificado_en is not None
    assert sdk.llamadas == []


def test_archivo_que_no_se_puede_leer_es_error_transitorio(tmp_path):
    """P. ej. un archivo de OneDrive aún no descargado: se resuelve reanalizando."""
    sdk = SdkFalso(respuesta(entrada()))
    resultado = cliente(sdk).analizar(tmp_path / "no-sincronizado.pdf", "P")
    assert resultado.es_error and not resultado.es_ilegible
    assert "No se pudo leer el archivo" in resultado.error
    assert sdk.llamadas == []


def test_simulado_es_determinista(tmp_path):
    ruta = crear_pdf(tmp_path / f"{FORMATO}.pdf")
    simulado = ClienteSimulado(catalogo_inicial())
    assert simulado.analizar(ruta, "P") == simulado.analizar(ruta, "P")


@pytest.mark.parametrize(
    ("archivo", "mensaje"),
    [("error_api.pdf", "simulado"), ("respuesta_malformada.pdf", "Respuesta fuera del esquema")],
)
def test_simulado_reproduce_errores(tmp_path, archivo, mensaje):
    resultado = ClienteSimulado(catalogo_inicial()).analizar(crear_pdf(tmp_path / archivo), "P")
    assert resultado.es_error
    assert mensaje in resultado.error


def test_simulado_tambien_valida_el_pdf(tmp_path, settings):
    settings.MOTOR_MAX_PAGINAS_PDF = 1
    ruta = crear_pdf(tmp_path / "largo.pdf", paginas=2)
    assert ClienteSimulado(catalogo_inicial()).analizar(ruta, "P").es_ilegible


def test_pausa_simulada_solo_afecta_al_cliente_simulado(tmp_path, settings, monkeypatch):
    """Se comprueba la llamada, no el tiempo: el reloj de Windows tiene ~15 ms de resolución."""
    import time

    pausas = []
    monkeypatch.setattr(time, "sleep", pausas.append)
    settings.MOTOR_SIMULADO_PAUSA_SEGUNDOS = 0.3
    ruta = crear_pdf(tmp_path / "certificado_afp.pdf")
    ClienteSimulado(catalogo_inicial()).analizar(ruta, "P")
    assert pausas == [0.3]
    pausas.clear()
    cliente(SdkFalso(respuesta(entrada()))).analizar(ruta, "P")
    assert pausas == []
