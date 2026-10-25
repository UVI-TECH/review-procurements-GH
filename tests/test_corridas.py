"""Corridas y worker, con el cliente simulado y carpetas sintéticas: nunca la API real."""

import os
import time
from dataclasses import replace

import pytest
from django.core.management import CommandError, call_command

from apps.contrataciones.models import Analisis, Corrida, Documento, EstadoProfesor, Profesor
from apps.corridas.procesamiento import WorkerDetenido, ejecutar_worker
from apps.corridas.servicios import crear_corrida, documentos_a_analizar, solicitar_cancelacion
from apps.cuentas.models import RegistroAuditoria
from apps.motor.aislamiento import InspectorAislado
from apps.motor.fuentes import FuenteCarpetaLocal
from apps.motor.resultado import ResultadoDocumento
from apps.motor.simulado import ClienteSimulado
from tests.fixtures import lentos
from tests.fixtures.carpetas import crear_profesor
from tests.fixtures.catalogo import CODIGOS
from tests.fixtures.pdfs import crear_pdf

pytestmark = pytest.mark.django_db


class Caida(BaseException):
    """Simula que el proceso muere (no la atrapa ningún except Exception)."""


class ClienteContador(ClienteSimulado):
    """El simulado, contando las llamadas que harían gasto en la API."""

    llamadas = []
    antes_de_analizar = None

    def analizar_datos(self, datos, nombre_archivo, profesor, *, modificado_en=None):
        if ClienteContador.antes_de_analizar:
            ClienteContador.antes_de_analizar(len(ClienteContador.llamadas))
        ClienteContador.llamadas.append(nombre_archivo)
        return super().analizar_datos(datos, nombre_archivo, profesor, modificado_en=modificado_en)


# PROFESOR UNO: un PDF por tipo; PROFESOR DOS: tres.
TOTAL = len(CODIGOS) + 3


@pytest.fixture(autouse=True)
def limpiar_contador():
    ClienteContador.llamadas = []
    ClienteContador.antes_de_analizar = None


@pytest.fixture
def raiz(tmp_path, settings):
    raiz = tmp_path / "Contrataciones"
    crear_profesor(raiz, "PROFESOR UNO")
    crear_profesor(raiz, "PROFESOR DOS", [f"{c}.pdf" for c in CODIGOS[:3]])
    settings.CARPETA_CONTRATACIONES = raiz
    settings.RUTA_BLOQUEO_WORKER = tmp_path / "worker.lock"
    return raiz


@pytest.fixture
def revisor(crear_usuario):
    return crear_usuario("revisor", grupo="Revisor GH")


class ClienteQueFalla(ClienteContador):
    """La API responde 500 a todo."""

    def analizar_datos(self, datos, nombre_archivo, profesor, *, modificado_en=None):
        ClienteContador.llamadas.append(nombre_archivo)
        return ResultadoDocumento.con_error(nombre_archivo, "La API respondió 500.")


class ClienteRecuperado(ClienteContador):
    """La API ya responde bien a error_api.pdf (lo analiza como un certificado EPS)."""

    def analizar_datos(self, datos, nombre_archivo, profesor, *, modificado_en=None):
        ClienteContador.llamadas.append(nombre_archivo)
        nombre = "certificado_afp.pdf" if nombre_archivo == "error_api.pdf" else nombre_archivo
        resultado = ClienteSimulado.analizar_datos(
            self, datos, nombre, profesor, modificado_en=modificado_en
        )
        return replace(resultado, nombre_archivo=nombre_archivo)


def trabajar(raiz, cliente=ClienteContador, **extra):
    ejecutar_worker(
        una_vez=True,
        fuente=FuenteCarpetaLocal(raiz),
        crear_cliente=lambda catalogo, inspector: cliente(catalogo, inspector=inspector),
        **extra,
    )


def corrida_completa(
    raiz, revisor, alcance=Corrida.Alcance.NUEVOS_Y_MODIFICADOS, cliente=ClienteContador, **kwargs
):
    corrida = crear_corrida(alcance, revisor, **kwargs)
    trabajar(raiz, cliente=cliente)
    corrida.refresh_from_db()
    return corrida


# --- Criterio de aceptación ---


def test_primera_corrida_analiza_todo_y_calcula_estados(raiz, revisor):
    corrida = corrida_completa(raiz, revisor)
    assert corrida.estado == Corrida.Estado.COMPLETADA
    assert len(ClienteContador.llamadas) == TOTAL
    assert (corrida.total_documentos, corrida.documentos_procesados) == (TOTAL, TOTAL)
    assert corrida.analisis.count() == TOTAL
    uno = Profesor.objects.get(carpeta="PROFESOR UNO")
    assert uno.estado == EstadoProfesor.COMPLETO
    assert uno.cedula == "1000000001"
    assert Profesor.objects.get(carpeta="PROFESOR DOS").estado == EstadoProfesor.INCOMPLETO


def test_segunda_corrida_sin_cambios_no_llama_a_la_api(raiz, revisor):
    corrida_completa(raiz, revisor)
    ClienteContador.llamadas = []
    segunda = corrida_completa(raiz, revisor)
    assert ClienteContador.llamadas == []
    assert segunda.estado == Corrida.Estado.COMPLETADA
    assert segunda.total_documentos == 0


def test_pdf_modificado_se_reanaliza(raiz, revisor):
    corrida_completa(raiz, revisor)
    ruta = crear_pdf(raiz / "PROFESOR DOS" / f"{CODIGOS[0]}.pdf", paginas=2, marca="otra versión")
    marca = time.time() + 10
    os.utime(ruta, (marca, marca))
    ClienteContador.llamadas = []
    corrida_completa(raiz, revisor)
    assert ClienteContador.llamadas == [f"{CODIGOS[0]}.pdf"]
    documento = Documento.objects.get(ruta_relativa=f"PROFESOR DOS/{CODIGOS[0]}.pdf")
    assert documento.analisis.count() == 2
    assert documento.analisis.latest("creado_en").sha256 == documento.sha256


def test_pdf_borrado_queda_no_presente_y_no_se_analiza(raiz, revisor):
    corrida_completa(raiz, revisor)
    borrado = f"PROFESOR UNO/{CODIGOS[1]}.pdf"
    (raiz / borrado).unlink()
    ClienteContador.llamadas = []
    corrida_completa(raiz, revisor, alcance=Corrida.Alcance.TODOS)
    documento = Documento.objects.get(ruta_relativa=borrado)
    assert not documento.presente
    assert documento.analisis.count() == 1  # su historial se conserva
    assert len(ClienteContador.llamadas) == TOTAL - 1
    assert Profesor.objects.get(carpeta="PROFESOR UNO").estado == EstadoProfesor.INCOMPLETO


def test_caida_a_mitad_y_reanudacion_sin_duplicar_trabajo(raiz, revisor):
    corrida = crear_corrida(Corrida.Alcance.TODOS, revisor)

    def morir_en_el_quinto(n):
        if n == 5:
            raise Caida

    ClienteContador.antes_de_analizar = morir_en_el_quinto
    with pytest.raises(Caida):
        trabajar(raiz)
    corrida.refresh_from_db()
    assert corrida.estado == Corrida.Estado.EN_PROCESO
    assert corrida.analisis.count() == 5
    assert corrida.latido is not None

    ClienteContador.antes_de_analizar = None
    ClienteContador.llamadas = []
    trabajar(raiz)
    corrida.refresh_from_db()
    assert corrida.estado == Corrida.Estado.COMPLETADA
    assert len(ClienteContador.llamadas) == TOTAL - 5
    assert corrida.analisis.count() == TOTAL
    for documento in Documento.objects.all():
        assert documento.analisis.filter(corrida=corrida).count() == 1
    assert corrida.documentos_procesados == TOTAL
    assert RegistroAuditoria.objects.filter(accion="corrida_reanudada").count() == 1


def test_cancelacion_entre_documentos(raiz, revisor):
    corrida = crear_corrida(Corrida.Alcance.TODOS, revisor)

    def cancelar_en_el_tercero(n):
        if n == 3:
            solicitar_cancelacion(Corrida.objects.get(pk=corrida.pk), revisor)

    ClienteContador.antes_de_analizar = cancelar_en_el_tercero
    trabajar(raiz)
    corrida.refresh_from_db()
    assert corrida.estado == Corrida.Estado.CANCELADA
    assert corrida.fin is not None
    assert corrida.analisis.count() == 4  # el que estaba en curso termina
    assert corrida.cancelacion_solicitada_por == revisor
    acciones = list(RegistroAuditoria.objects.values_list("accion", flat=True))
    assert "cancelacion_solicitada" in acciones and "corrida_cancelada" in acciones


def test_cancelar_una_corrida_pendiente_la_cancela_de_inmediato(revisor):
    corrida = crear_corrida(Corrida.Alcance.TODOS, revisor)
    solicitar_cancelacion(corrida, revisor)
    corrida.refresh_from_db()
    assert corrida.estado == Corrida.Estado.CANCELADA


def test_no_se_cancela_una_corrida_terminada(raiz, revisor):
    corrida = corrida_completa(raiz, revisor)
    with pytest.raises(ValueError, match="completada"):
        solicitar_cancelacion(corrida, revisor)


def test_tiempo_limite_por_documento(raiz, revisor, settings):
    crear_pdf(raiz / "PROFESOR DOS" / "colgado.pdf", marca="COLGAR")
    corrida = crear_corrida(Corrida.Alcance.TODOS, revisor)
    with InspectorAislado(timeout=1, funcion=lentos.colgarse_si_marcado) as inspector:
        trabajar(raiz, inspector=inspector)
    corrida.refresh_from_db()
    assert corrida.estado == Corrida.Estado.COMPLETADA
    assert corrida.documentos_procesados == TOTAL + 1
    assert corrida.documentos_con_error == 1
    colgado = Analisis.objects.get(documento__nombre_archivo="colgado.pdf")
    assert colgado.tipo_detectado == Analisis.TIPO_ERROR
    assert "tardó más de 1 s" in colgado.observaciones


def test_fallo_transitorio_repetido_deja_de_reintentarse(raiz, revisor):
    crear_pdf(raiz / "PROFESOR DOS" / "error_api.pdf")
    corrida_completa(raiz, revisor)
    documento = Documento.objects.get(nombre_archivo="error_api.pdf")
    assert not documento.reintentos_agotados

    ClienteContador.llamadas = []
    corrida_completa(raiz, revisor)
    documento.refresh_from_db()
    assert ClienteContador.llamadas == ["error_api.pdf"]
    assert documento.reintentos_agotados
    assert RegistroAuditoria.objects.filter(accion="reintentos_agotados").exists()

    ClienteContador.llamadas = []
    corrida_completa(raiz, revisor)
    corrida_completa(raiz, revisor, alcance=Corrida.Alcance.TODOS)
    assert "error_api.pdf" not in ClienteContador.llamadas


def test_reintento_manual_que_sale_bien_quita_la_marca(raiz, revisor):
    crear_pdf(raiz / "PROFESOR DOS" / "error_api.pdf")
    corrida_completa(raiz, revisor)
    corrida_completa(raiz, revisor)
    documento = Documento.objects.get(nombre_archivo="error_api.pdf")
    assert documento.reintentos_agotados

    dos = Profesor.objects.get(carpeta="PROFESOR DOS")
    ClienteContador.llamadas = []
    corrida_completa(
        raiz, revisor, alcance=Corrida.Alcance.UN_PROFESOR, profesor=dos, cliente=ClienteRecuperado
    )
    documento.refresh_from_db()
    assert "error_api.pdf" in ClienteContador.llamadas  # un_profesor sí lo reintenta
    assert not documento.reintentos_agotados


def test_un_error_no_tapa_un_resultado_util(raiz, revisor):
    """Si la API falla en una corrida 'todos' posterior, nadie retrocede a ERROR."""
    corrida_completa(raiz, revisor)
    assert Profesor.objects.get(carpeta="PROFESOR UNO").estado == EstadoProfesor.COMPLETO
    corrida = corrida_completa(
        raiz, revisor, alcance=Corrida.Alcance.TODOS, cliente=ClienteQueFalla
    )
    assert corrida.documentos_con_error == TOTAL
    assert Profesor.objects.get(carpeta="PROFESOR UNO").estado == EstadoProfesor.COMPLETO
    assert Profesor.objects.get(carpeta="PROFESOR DOS").estado == EstadoProfesor.INCOMPLETO


def test_sin_ningun_resultado_util_el_error_si_cuenta(raiz, revisor):
    corrida_completa(raiz, revisor, cliente=ClienteQueFalla)
    assert Profesor.objects.get(carpeta="PROFESOR UNO").estado == EstadoProfesor.ERROR


def test_ilegible_se_guarda_como_analisis_con_su_observacion(raiz, revisor):
    (raiz / "PROFESOR DOS" / "danado.pdf").write_bytes(b"no es un pdf")
    corrida_completa(raiz, revisor)
    analisis = Analisis.objects.get(documento__nombre_archivo="danado.pdf")
    assert analisis.tipo_detectado == Analisis.TIPO_ILEGIBLE
    assert "solicitar un nuevo archivo" in analisis.observaciones
    ClienteContador.llamadas = []
    corrida_completa(raiz, revisor)
    assert "danado.pdf" not in ClienteContador.llamadas  # ilegible cuenta como resultado


def test_progreso_y_tokens_por_documento(raiz, revisor):
    corrida = corrida_completa(raiz, revisor)
    assert corrida.documentos_procesados == corrida.analisis.count()
    assert corrida.inicio is not None and corrida.fin is not None


def test_carpeta_desaparecida_se_salta(raiz, revisor, tmp_path):
    corrida_completa(raiz, revisor)
    crear_profesor(raiz, "PROFESOR TRES", ["x.pdf"])
    crear_profesor(raiz, "PROFESOR CUATRO", ["x.pdf"])
    crear_profesor(raiz, "PROFESOR CINCO", ["x.pdf"])
    corrida_completa(raiz, revisor)
    (raiz / "PROFESOR DOS").rename(tmp_path / "fuera")
    ClienteContador.llamadas = []
    corrida_completa(raiz, revisor, alcance=Corrida.Alcance.TODOS)
    assert len(ClienteContador.llamadas) == len(CODIGOS) + 3  # sin los de PROFESOR DOS


def test_freno_del_escaneo_hace_fallar_la_corrida(raiz, revisor, tmp_path):
    corrida_completa(raiz, revisor)
    (raiz / "PROFESOR UNO").rename(tmp_path / "uno")
    corrida = corrida_completa(raiz, revisor)
    assert corrida.estado == Corrida.Estado.FALLIDA
    assert "--forzar" in corrida.mensaje
    assert RegistroAuditoria.objects.filter(accion="corrida_fallida").exists()


# --- Selección y auditoría ---


def test_nuevos_y_modificados_cuenta_errores_como_pendientes(raiz, revisor):
    crear_pdf(raiz / "PROFESOR DOS" / "error_api.pdf")
    corrida_completa(raiz, revisor)
    pendientes = documentos_a_analizar(Corrida.Alcance.NUEVOS_Y_MODIFICADOS)
    assert [d.nombre_archivo for d in pendientes] == ["error_api.pdf"]


def test_auditoria_de_creacion_y_finalizacion_con_usuario_nulo_del_sistema(raiz, revisor):
    corrida_completa(raiz, revisor)
    creada = RegistroAuditoria.objects.get(accion="corrida_creada")
    assert creada.usuario == revisor
    completada = RegistroAuditoria.objects.get(accion="corrida_completada")
    assert completada.usuario is None
    assert completada.detalle["documentos_procesados"] == TOTAL


# --- Comandos ---


def test_en_seco_no_crea_nada(raiz, revisor, capsys):
    antes = [m.objects.count() for m in (Corrida, Profesor, Documento, RegistroAuditoria)]
    call_command("crear_corrida", "--alcance", "todos", "--usuario", "revisor", "--en-seco")
    despues = [m.objects.count() for m in (Corrida, Profesor, Documento, RegistroAuditoria)]
    assert antes == despues
    salida = capsys.readouterr().out
    assert f"Documentos a analizar: {TOTAL}" in salida
    assert "US$" in salida


def test_en_seco_usa_el_historial_de_tokens(raiz, revisor, capsys):
    corrida_completa(raiz, revisor)
    crear_pdf(raiz / "PROFESOR DOS" / "nuevo.pdf")
    call_command(
        "crear_corrida", "--alcance", "nuevos_y_modificados", "--usuario", "revisor", "--en-seco"
    )
    assert "Documentos a analizar: 1" in capsys.readouterr().out


def test_crear_corrida_por_comando(raiz, revisor):
    call_command(
        "crear_corrida",
        "--alcance",
        "un_profesor",
        "--profesor",
        "PROFESOR DOS",
        "--usuario",
        "revisor",
    )
    corrida = Corrida.objects.get()
    assert (corrida.alcance, corrida.profesor.carpeta) == ("un_profesor", "PROFESOR DOS")


@pytest.mark.parametrize(
    ("argumentos", "mensaje"),
    [
        (["--alcance", "un_profesor", "--usuario", "revisor"], "--profesor"),
        (
            ["--alcance", "un_profesor", "--profesor", "NO EXISTE", "--usuario", "revisor"],
            "No hay un profesor presente",
        ),
        (["--alcance", "todos", "--profesor", "PROFESOR DOS", "--usuario", "revisor"], "solo"),
        (["--alcance", "todos", "--usuario", "consulta"], "permiso"),
        (["--alcance", "todos", "--usuario", "nadie"], "No existe el usuario"),
    ],
)
def test_crear_corrida_valida_los_argumentos(raiz, revisor, crear_usuario, argumentos, mensaje):
    crear_usuario("consulta", grupo="Consulta")
    with pytest.raises(CommandError, match=mensaje):
        call_command("crear_corrida", *argumentos)


def test_cancelar_corrida_exige_el_permiso(raiz, revisor, crear_usuario):
    corrida = crear_corrida(Corrida.Alcance.TODOS, revisor)
    crear_usuario("consulta", grupo="Consulta")
    with pytest.raises(CommandError, match="permiso"):
        call_command("cancelar_corrida", str(corrida.pk), "--usuario", "consulta")
    call_command("cancelar_corrida", str(corrida.pk), "--usuario", "revisor")
    corrida.refresh_from_db()
    assert corrida.estado == Corrida.Estado.CANCELADA


# --- Consola del worker y detención limpia ---


def test_consola_muestra_corrida_progreso_y_resumen_sin_nombres(raiz, revisor):
    corrida = crear_corrida(Corrida.Alcance.NUEVOS_Y_MODIFICADOS, revisor)
    mensajes = []
    trabajar(raiz, informar=mensajes.append)
    assert mensajes[0] == "Estados recalculados por vigencia: 0 profesores."
    assert mensajes[1] == f"Corrida {corrida.pk} (nuevos_y_modificados): escaneando la carpeta…"
    assert mensajes[2] == f"Corrida {corrida.pk}: {TOTAL} documentos por analizar."
    progreso = [m for m in mensajes if " · " in m]
    assert len(progreso) == TOTAL
    assert progreso[0].startswith(f"Corrida {corrida.pk} · 1/{TOTAL} · errores: 0 · tokens:")
    assert progreso[-1].startswith(f"Corrida {corrida.pk} · {TOTAL}/{TOTAL} · errores: 0")
    assert mensajes[-2].startswith(
        f"Corrida {corrida.pk} completada: {TOTAL}/{TOTAL} documentos, 0 con error"
    )
    assert mensajes[-1] == "Sin corridas pendientes."
    texto = "\n".join(mensajes)
    assert "PROFESOR" not in texto and ".pdf" not in texto  # sin nombres ni archivos


def test_consola_avisa_la_reanudacion(raiz, revisor):
    corrida = crear_corrida(Corrida.Alcance.TODOS, revisor)

    def morir(n):
        if n == 5:
            raise Caida

    ClienteContador.antes_de_analizar = morir
    with pytest.raises(Caida):
        trabajar(raiz)
    ClienteContador.antes_de_analizar = None
    mensajes = []
    trabajar(raiz, informar=mensajes.append)
    assert mensajes[0] == "Estados recalculados por vigencia: 2 profesores."
    assert mensajes[1] == f"Corrida {corrida.pk} (todos) reanudada: escaneando la carpeta…"
    assert mensajes[2] == (
        f"Corrida {corrida.pk} reanudada: {TOTAL - 5} de {TOTAL} documentos por analizar."
    )
    assert any(m.startswith(f"Corrida {corrida.pk} · {TOTAL}/{TOTAL}") for m in mensajes)


def test_mensaje_de_espera_una_sola_vez(raiz):
    mensajes = []

    def informar(mensaje):
        mensajes.append(mensaje)
        if mensaje == "Sin corridas pendientes; esperando…":
            raise KeyboardInterrupt  # Ctrl+C mientras espera

    with pytest.raises(WorkerDetenido) as detenido:
        ejecutar_worker(fuente=FuenteCarpetaLocal(raiz), intervalo=0, informar=informar)
    assert detenido.value.corrida_id is None
    assert mensajes == [
        "Estados recalculados por vigencia: 0 profesores.",
        "Sin corridas pendientes; esperando…",
    ]


def test_ctrl_c_a_mitad_deja_la_corrida_reanudable_y_cierra_el_pool(raiz, revisor):
    import multiprocessing

    corrida = crear_corrida(Corrida.Alcance.TODOS, revisor)

    def ctrl_c(n):
        if n == 3:
            raise KeyboardInterrupt

    ClienteContador.antes_de_analizar = ctrl_c
    with pytest.raises(WorkerDetenido) as detenido:
        trabajar(raiz)
    assert detenido.value.corrida_id == corrida.pk
    assert multiprocessing.active_children() == []
    corrida.refresh_from_db()
    assert corrida.estado == Corrida.Estado.EN_PROCESO
    assert corrida.analisis.count() == 3

    ClienteContador.antes_de_analizar = None
    trabajar(raiz)
    corrida.refresh_from_db()
    assert corrida.estado == Corrida.Estado.COMPLETADA
    assert corrida.analisis.count() == TOTAL


@pytest.mark.parametrize(
    ("corrida_id", "esperado"),
    [
        (7, "Worker detenido. La corrida 7 se reanudará al volver a iniciar el worker."),
        (None, "Worker detenido."),
    ],
)
def test_comando_worker_sale_limpio_al_detenerse(monkeypatch, capsys, corrida_id, esperado):
    import apps.corridas.management.commands.worker as comando

    def detener(**kwargs):
        raise WorkerDetenido(corrida_id)

    monkeypatch.setattr(comando, "ejecutar_worker", detener)
    call_command("worker")
    assert capsys.readouterr().out.strip() == esperado


def test_archivo_nuevo_queda_pendiente_desde_el_escaneo(raiz, revisor):
    """ADR 0005: el escaneo recalcula el estado; no hay que esperar al worker."""
    from apps.corridas.escaneo import escanear

    crear_corrida(Corrida.Alcance.TODOS, revisor)
    trabajar(raiz)
    uno = Profesor.objects.get(carpeta="PROFESOR UNO")
    assert uno.estado == EstadoProfesor.COMPLETO

    crear_pdf(raiz / "PROFESOR UNO" / "carta nueva.pdf")
    escanear(FuenteCarpetaLocal(raiz))
    uno.refresh_from_db()
    assert uno.estado == EstadoProfesor.PENDIENTE_ANALISIS

    crear_corrida(Corrida.Alcance.NUEVOS_Y_MODIFICADOS, revisor)
    trabajar(raiz)
    uno.refresh_from_db()
    assert uno.estado == EstadoProfesor.COMPLETO  # el simulado lo da por "otro"


def test_el_analisis_guarda_fecha_cobertura_y_logo(raiz, revisor):
    from datetime import timedelta

    from django.utils import timezone

    crear_corrida(Corrida.Alcance.TODOS, revisor)
    trabajar(raiz)
    afp = Analisis.objects.get(documento__ruta_relativa="PROFESOR UNO/certificado_afp.pdf")
    assert afp.fecha_expedicion == timezone.localdate() - timedelta(days=3)
    assert afp.cubre == "afp"
    assert afp.tiene_logo_oficial is True
    assert afp.es_plantilla_institucional is None
    formato = Analisis.objects.get(
        documento__ruta_relativa="PROFESOR UNO/formato_autorizacion_consulta_inhabilidades.pdf"
    )
    assert formato.es_plantilla_institucional is True


def _reloj(*valores):
    iterador = iter(valores)
    return lambda: next(iterador)


@pytest.mark.parametrize(("segundos", "recalculos"), [(24 * 3600, 2), (24 * 3600 - 1, 1)])
def test_el_worker_recalcula_al_arrancar_y_cada_24_horas(raiz, revisor, segundos, recalculos):
    mensajes = []
    crear_corrida(Corrida.Alcance.TODOS, revisor)
    # Llamadas al reloj: marca tras el primer recálculo, chequeo en la 2.ª vuelta, marca.
    trabajar(raiz, informar=mensajes.append, reloj=_reloj(0, segundos, segundos))
    assert [m for m in mensajes if m.startswith("Estados recalculados")] == [
        "Estados recalculados por vigencia: 0 profesores.",
        "Estados recalculados por vigencia: 2 profesores.",
    ][:recalculos]
