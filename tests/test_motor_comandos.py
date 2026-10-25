"""Comandos para la validación real (los ejecuta John) y la comparación con el legado."""

from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command

from apps.motor.comparacion import (
    CODIGOS_SEGURIDAD_SOCIAL,
    a_dict_legado,
    cargar_legado,
    comparar_profesor,
    resumir,
    validar_ruta_salida,
)
from apps.motor.resultado import ResultadoDocumento
from config.entorno import BASE_DIR
from tests.fixtures.catalogo import CODIGOS, FORMATO, catalogo_inicial

CEDULA = "1000000001"


# --- Los comandos se niegan a correr en pruebas o con el motor simulado ---


@pytest.mark.parametrize(
    "argumentos",
    [
        ["probar_motor", "x.pdf"],
        ["comparar_con_legado", "carpeta", "--limite", "1", "--salida", "/tmp/informe.json"],
    ],
    ids=["probar_motor", "comparar_con_legado"],
)
def test_comandos_se_niegan_en_settings_de_pruebas(argumentos):
    with pytest.raises(CommandError, match="pruebas"):
        call_command(*argumentos)


@pytest.mark.parametrize("comando", ["probar_motor", "comparar_con_legado"])
def test_comandos_se_niegan_con_motor_simulado(settings, comando):
    settings.ES_ENTORNO_DE_PRUEBAS = False
    settings.MOTOR_SIMULADO = True
    argumentos = (
        ["x.pdf"]
        if comando == "probar_motor"
        else ["c", "--limite", "1", "--salida", "/tmp/i.json"]
    )
    with pytest.raises(CommandError, match="MOTOR_SIMULADO"):
        call_command(comando, *argumentos)


# --- Ruta del informe ---


@pytest.mark.parametrize(
    "ruta",
    [
        BASE_DIR / "informe.json",
        BASE_DIR / "docs" / "informe.json",
        BASE_DIR / ".." / BASE_DIR.name / "x.json",
    ],
    ids=["raiz", "subcarpeta", "ruta-con-puntos"],
)
def test_informe_dentro_del_repositorio_se_rechaza(ruta):
    with pytest.raises(CommandError, match="fuera del repositorio"):
        validar_ruta_salida(ruta)


def test_informe_fuera_del_repositorio_se_acepta(tmp_path):
    assert validar_ruta_salida(tmp_path / "informe.json") == (tmp_path / "informe.json").resolve()


def test_informe_en_carpeta_inexistente_se_rechaza(tmp_path):
    with pytest.raises(CommandError, match="no existe"):
        validar_ruta_salida(tmp_path / "no-existe" / "informe.json")


# --- Comparación con el legado (con sus propias funciones, sin API) ---


@pytest.fixture(scope="module")
def legado():
    modulo = cargar_legado()
    modulo.client = None  # nunca se llama a la API en pruebas
    return modulo


def test_el_legado_se_carga_sin_modificar_el_archivo(legado):
    assert (
        Path(legado.__file__).resolve()
        == (BASE_DIR / "legado" / "revisar_contrataciones.py").resolve()
    )
    # El legado tiene un solo tipo de seguridad social; el motor, EPS y AFP (ADR 0006).
    nuevos = [c for c in CODIGOS if c not in CODIGOS_SEGURIDAD_SOCIAL]
    assert [codigo for codigo, _ in legado.DOCS] == [*nuevos[:7], "certificados_eps_afp", nuevos[7]]


def resultado(tipo, valido=True, cedula=CEDULA, archivo=None, minutos=0, firma=None, error=""):
    from datetime import UTC, datetime, timedelta

    return ResultadoDocumento(
        nombre_archivo=archivo or f"{tipo}.pdf",
        tipo_detectado=tipo,
        es_valido=valido,
        numero_documento=cedula,
        tiene_firma=firma,
        error=error,
        modificado_en=datetime(2026, 10, 1, tzinfo=UTC) + timedelta(minutes=minutos),
    )


def completos(**reemplazos):
    docs = []
    for codigo in CODIGOS:
        docs.append(
            reemplazos.get(codigo, resultado(codigo, firma=True if codigo == FORMATO else None))
        )
    return docs


def test_a_dict_legado_conserva_lo_que_usa_el_legado():
    r = resultado(FORMATO, valido=False, firma=True)
    assert a_dict_legado(r) == {
        "tipo_detectado": FORMATO,
        "es_valido": False,
        "numero_documento": CEDULA,
        "nombre_persona": "",
        "tiene_firma": True,
        "observaciones": "",
    }
    assert (
        a_dict_legado(resultado("", valido=False, cedula="", error="x"))["tipo_detectado"]
        == "ERROR"
    )


def test_sin_diferencias(legado):
    nuevos = completos()
    informe = comparar_profesor(
        "P", [a_dict_legado(r) for r in nuevos], nuevos, catalogo_inicial(), legado
    )
    assert informe["coincide_estado"]
    assert informe["diferencias_intencionales"] == []
    assert informe["diferencias_no_explicadas"] == []
    assert all(d["coincide_tipo"] and d["coincide_es_valido"] for d in informe["documentos"])


def test_duplicado_es_diferencia_intencional(legado):
    """El legado se queda con el último del tipo; el motor nuevo, con el vigente."""
    valido = resultado("certificado_afp", archivo="eps_a.pdf", minutos=1)
    invalido = resultado("certificado_afp", valido=False, cedula="", archivo="eps_b.pdf", minutos=2)
    nuevos = completos(certificado_afp=valido) + [invalido]
    informe = comparar_profesor(
        "P", [a_dict_legado(r) for r in nuevos], nuevos, catalogo_inicial(), legado
    )
    assert informe["legado"]["estado"] == "INCOMPLETO"
    assert informe["motor_nuevo"]["estado"] == "COMPLETO"
    assert not informe["coincide_estado"]
    assert informe["diferencias_intencionales"] == ["duplicados"]
    assert informe["diferencias_no_explicadas"] == []


def test_cedula_ambigua_es_diferencia_intencional(legado):
    nuevos = [
        resultado(
            codigo,
            cedula=(CEDULA if i < 2 else "1000000099" if i < 4 else ""),
            firma=True if codigo == FORMATO else None,
        )
        for i, codigo in enumerate(CODIGOS)
    ]
    informe = comparar_profesor(
        "P", [a_dict_legado(r) for r in nuevos], nuevos, catalogo_inicial(), legado
    )
    assert informe["motor_nuevo"]["estado"] == "CON_PROBLEMAS"
    assert "cedula_ambigua" in informe["diferencias_intencionales"]


def test_diferencia_de_la_ia_se_reporta_por_documento(legado):
    nuevos = completos()
    viejos = [a_dict_legado(r) for r in nuevos]
    viejos[0] = {**viejos[0], "tipo_detectado": "OTRO", "es_valido": False}
    informe = comparar_profesor("P", viejos, nuevos, catalogo_inicial(), legado)
    primero = informe["documentos"][0]
    assert not primero["coincide_tipo"]
    assert primero["legado"]["tipo"] == "otro"
    assert not informe["coincide_estado"]
    assert informe["origen_diferencia_estado"] == "ia"


def test_sin_pdfs(legado):
    informe = comparar_profesor("P", [], [], catalogo_inicial(), legado)
    assert informe["legado"]["estado"] == "INCOMPLETO"
    assert informe["motor_nuevo"]["estado"] == "SIN_DOCUMENTOS"
    assert informe["coincide_estado"]
    assert informe["diferencias_intencionales"] == ["sin_documentos"]
    assert informe["diferencias_no_explicadas"] == []


def test_con_problemas_frente_a_incompleto_es_intencional(legado):
    """Un vigente inválido: el legado dice INCOMPLETO y el motor nuevo, CON_PROBLEMAS."""
    nuevos = completos(certificado_afp=resultado("certificado_afp", valido=False, cedula=""))
    informe = comparar_profesor(
        "P", [a_dict_legado(r) for r in nuevos], nuevos, catalogo_inicial(), legado
    )
    assert (informe["legado"]["estado"], informe["motor_nuevo"]["estado"]) == (
        "INCOMPLETO",
        "CON_PROBLEMAS",
    )
    assert informe["diferencias_intencionales"] == ["con_problemas"]
    assert informe["diferencias_no_explicadas"] == []


def test_probar_motor_falla_claro_si_el_pdf_no_existe(settings, tmp_path):
    settings.ES_ENTORNO_DE_PRUEBAS = False
    settings.MOTOR_SIMULADO = False
    with pytest.raises(CommandError, match="No existe"):
        call_command("probar_motor", str(tmp_path / "no-existe.pdf"))


def test_comparar_falla_claro_si_la_carpeta_no_existe(settings, tmp_path):
    settings.ES_ENTORNO_DE_PRUEBAS = False
    settings.MOTOR_SIMULADO = False
    with pytest.raises(CommandError, match="No existe"):
        call_command(
            "comparar_con_legado",
            str(tmp_path / "no-existe"),
            "--limite",
            "1",
            "--salida",
            str(tmp_path / "i.json"),
        )


# --- Ajustes tras la comparación real ---


def test_estado_detallado_distinto_se_reporta_aunque_coincida_completo(legado):
    """INCOMPLETO del legado frente a SIN_DOCUMENTOS: no COMPLETO en los dos, pero distintos."""
    informe = comparar_profesor("P", [], [], catalogo_inicial(), legado)
    assert informe["coincide_estado"]
    assert not informe["coincide_estado_detallado"]


def test_estado_detallado_igual(legado):
    nuevos = completos()
    informe = comparar_profesor(
        "P", [a_dict_legado(r) for r in nuevos], nuevos, catalogo_inicial(), legado
    )
    assert informe["coincide_estado_detallado"]


def test_resumen_cuenta_el_estado_detallado_distinto(legado):
    nuevos = completos()
    informes = [
        comparar_profesor("A", [], [], catalogo_inicial(), legado),
        comparar_profesor(
            "B", [a_dict_legado(r) for r in nuevos], nuevos, catalogo_inicial(), legado
        ),
    ]
    resumen = resumir(informes)
    assert resumen["profesores"] == 2
    assert resumen["estado_coincide"] == 2
    assert resumen["estado_detallado_difiere"] == 1
    assert resumen["documentos"] == len(CODIGOS)


@pytest.mark.parametrize("comando", ["probar_motor", "comparar_con_legado"])
def test_sin_migraciones_da_un_mensaje_claro(settings, monkeypatch, tmp_path, comando):
    import apps.motor.servicio as servicio

    settings.ES_ENTORNO_DE_PRUEBAS = False
    settings.MOTOR_SIMULADO = False
    monkeypatch.setattr(servicio, "hay_migraciones_pendientes", lambda: True)
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF")
    argumentos = (
        [str(pdf)]
        if comando == "probar_motor"
        else [str(tmp_path), "--limite", "1", "--salida", str(tmp_path / "i.json")]
    )
    with pytest.raises(CommandError, match="Ejecuta manage.py migrate primero"):
        call_command(comando, *argumentos)


@pytest.mark.django_db
def test_base_migrada_no_tiene_migraciones_pendientes():
    from apps.motor.servicio import hay_migraciones_pendientes

    assert not hay_migraciones_pendientes()


def test_ilegible_es_diferencia_intencional(legado):
    """El legado lo mandaba a la API y quedaba como ERROR; el motor nuevo lo señala."""
    protegido = ResultadoDocumento.ilegible(
        "eps.pdf", "PDF protegido con contraseña: solicitar un nuevo archivo sin contraseña."
    )
    nuevos = [r for r in completos() if r.tipo_detectado != "certificado_afp"] + [protegido]
    viejos = [a_dict_legado(r) for r in nuevos]
    assert viejos[-1]["tipo_detectado"] == "ERROR"
    informe = comparar_profesor("P", viejos, nuevos, catalogo_inicial(), legado)
    assert informe["motor_nuevo"]["estado"] == "INCOMPLETO"
    assert informe["motor_nuevo"]["ilegibles"] == ["eps.pdf"]
    assert "documento_ilegible" in informe["diferencias_intencionales"]
    assert informe["documentos"][-1]["coincide_tipo"]


def test_pendiente_de_analisis_es_diferencia_intencional(legado):
    """El legado no tiene ese estado: analizaba todo en la misma corrida (ADR 0005)."""
    pendiente = ResultadoDocumento.pendiente_de_analisis("nuevo.pdf")
    nuevos = [*completos(), pendiente]
    # El legado sí lo analizó: un documento que no es requisito.
    viejos = [*[a_dict_legado(r) for r in completos()], {"tipo_detectado": "otro"}]
    assert a_dict_legado(pendiente)["tipo_detectado"] == "ERROR"
    informe = comparar_profesor("P", viejos, nuevos, catalogo_inicial(), legado)
    assert informe["legado"]["estado"] == "COMPLETO"
    assert informe["motor_nuevo"]["estado"] == "PENDIENTE_ANALISIS"
    assert informe["motor_nuevo"]["pendientes"] == ["nuevo.pdf"]
    assert informe["motor_nuevo"]["errores"] == []
    assert "pendiente_de_analisis" in informe["diferencias_intencionales"]
    assert informe["diferencias_no_explicadas"] == []
    assert informe["documentos"][-1]["nuevo"]["tipo"] == "pendiente"


# --- Requisitos 2026-2 (ADR 0006) ---

REFERENCIA = date(2026, 7, 15)


def con_fecha(r, dias=3, logo=None):
    return replace(r, fecha_expedicion=REFERENCIA - timedelta(days=dias), tiene_logo_oficial=logo)


def comparar_nuevos(nuevos, legado, viejos=None):
    viejos = [a_dict_legado(r) for r in nuevos] if viejos is None else viejos
    return comparar_profesor("P", viejos, nuevos, catalogo_inicial(), legado, hoy=REFERENCIA)


def test_eps_y_afp_van_al_tipo_unico_del_legado(legado):
    for codigo in CODIGOS_SEGURIDAD_SOCIAL:
        assert a_dict_legado(resultado(codigo))["tipo_detectado"] == "certificados_eps_afp"
    informe = comparar_nuevos([con_fecha(r) for r in completos()], legado)
    assert informe["legado"]["estado"] == "COMPLETO"
    assert informe["motor_nuevo"]["estado"] == "COMPLETO"
    assert all(d["coincide_tipo"] for d in informe["documentos"])


def test_solo_eps_es_la_separacion_eps_afp(legado):
    nuevos = [con_fecha(r) for r in completos() if r.tipo_detectado != "certificado_afp"]
    informe = comparar_nuevos(nuevos, legado)
    assert informe["legado"]["estado"] == "COMPLETO"  # al legado le basta un documento
    assert informe["motor_nuevo"]["estado"] == "INCOMPLETO"
    assert informe["diferencias_intencionales"] == ["separacion_eps_afp"]


def test_vencido_contra_la_fecha_de_referencia_es_vigencia(legado):
    nuevos = [
        con_fecha(r, dias=45 if r.tipo_detectado == "certificado_eps" else 3) for r in completos()
    ]
    informe = comparar_nuevos(nuevos, legado)
    assert informe["motor_nuevo"]["estado"] == "CON_PROBLEMAS"
    assert informe["motor_nuevo"]["vencidos"] == ["certificado_eps.pdf"]
    assert informe["diferencias_intencionales"] == ["vigencia"]
    # Sin fecha de referencia no se evalúa la vigencia.
    sin_vigencia = comparar_profesor(
        "P", [a_dict_legado(r) for r in nuevos], nuevos, catalogo_inicial(), legado
    )
    assert sin_vigencia["motor_nuevo"]["estado"] == "COMPLETO"


def test_alternativa_de_pension_es_intencional(legado):
    bono = con_fecha(resultado("carta_bono_pensional", archivo="bono.pdf"), dias=200)
    nuevos = [con_fecha(r) for r in completos() if r.tipo_detectado != "certificado_afp"]
    # La IA del legado no conocía la carta: la tomó como un documento que no es requisito.
    viejos = [*[a_dict_legado(r) for r in nuevos], {"tipo_detectado": "otro", "es_valido": False}]
    informe = comparar_nuevos([*nuevos, bono], legado, viejos)
    assert informe["legado"]["estado"] == "INCOMPLETO"
    assert informe["motor_nuevo"]["estado"] == "COMPLETO"
    assert informe["origen_diferencia_estado"] == "ia"
    assert informe["diferencias_intencionales"] == ["alternativa_pension"]
    assert informe["diferencias_no_explicadas"] == []


def test_resumen_cuenta_el_logo_por_tipo(legado):
    nuevos = [con_fecha(r, logo=r.tipo_detectado != "certificado_eps") for r in completos()]
    nuevos[0] = replace(nuevos[0], tiene_logo_oficial=None)
    resumen = resumir([comparar_nuevos(nuevos, legado)])
    conteo = resumen["logo_por_tipo"]
    assert conteo["certificado_eps"] == {"verdadero": 0, "falso": 1, "nulo": 0}
    assert conteo["certificado_afp"] == {"verdadero": 1, "falso": 0, "nulo": 0}
    assert conteo[nuevos[0].tipo_detectado] == {"verdadero": 0, "falso": 0, "nulo": 1}
    assert set(conteo) == set(CODIGOS)


@pytest.mark.parametrize("fecha", ["2026-13-01", "15/07/2026"])
def test_fecha_de_referencia_invalida_da_un_error_claro(fecha):
    with pytest.raises(CommandError, match="no es una fecha AAAA-MM-DD"):
        call_command(
            "comparar_con_legado",
            "c",
            "--limite",
            "1",
            "--salida",
            "/tmp/i.json",
            "--fecha-referencia",
            fecha,
        )
