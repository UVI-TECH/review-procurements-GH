"""Comparación del motor nuevo con el legado, para el comando comparar_con_legado.

Por profesor se calculan tres columnas:
1. IA del legado + reglas del legado.
2. IA nueva + reglas del legado (sus propias funciones, desde legado/).
3. IA nueva + reglas nuevas.
1 frente a 2 aísla las diferencias de prompt o modelo; 2 frente a 3, las de reglas,
que se clasifican según la diferencia intencional del ADR 0003 que las explica.
"""

import copy
import importlib.util
from pathlib import Path

from django.core.management import CommandError

from config.entorno import BASE_DIR

from .reglas import EstadoProfesor, evaluar_profesor, norm, revalidar_por_cedula

RUTA_LEGADO = BASE_DIR / "legado" / "revisar_contrataciones.py"


def cargar_legado():
    """Importa el script del legado desde su ruta, sin modificarlo.

    Al importarse crea su propio cliente con la clave de ejemplo; quien lo use debe
    reemplazar modulo.client antes de analizar nada.
    """
    spec = importlib.util.spec_from_file_location("legado_revisar_contrataciones", RUTA_LEGADO)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def validar_ruta_salida(ruta):
    """El informe tiene datos reales: nunca dentro del repositorio."""
    ruta = Path(ruta).expanduser().resolve()
    if ruta.is_relative_to(BASE_DIR.resolve()):
        raise CommandError(
            f"El informe contiene datos reales: escríbelo fuera del repositorio ({BASE_DIR})."
        )
    if not ruta.parent.is_dir():
        raise CommandError(f"La carpeta del informe no existe: {ruta.parent}")
    return ruta


def a_dict_legado(resultado):
    """ResultadoDocumento -> el dict que esperan las funciones del legado."""
    if resultado.es_error or resultado.es_ilegible:
        # El legado mandaba a la API también los ilegibles; fallaban y quedaban como ERROR.
        return {
            "tipo_detectado": "ERROR",
            "es_valido": False,
            "observaciones": resultado.error or resultado.observaciones,
        }
    return {
        "tipo_detectado": resultado.tipo_detectado,
        "es_valido": resultado.es_valido,
        "numero_documento": resultado.numero_documento,
        "nombre_persona": resultado.nombre_persona,
        "tiene_firma": resultado.tiene_firma,
        "observaciones": resultado.observaciones,
        **{k: v for k, v in resultado.datos_extra.items() if v is not None},
    }


def _reglas_del_legado(legado, profesor, dicts):
    """Aplica revalidar_por_cedula y construir_fila del legado sobre una copia."""
    dicts = copy.deepcopy(dicts)
    if not dicts:
        fila = legado.fila_sin_documentos(profesor)
        faltantes = [codigo for codigo, _ in legado.DOCS]
    else:
        legado.revalidar_por_cedula(dicts)
        fila = legado.construir_fila(profesor, dicts)
        por_etiqueta = {etiqueta: codigo for codigo, etiqueta in legado.DOCS}
        faltantes = [
            por_etiqueta[e] for e in fila["Docs_Faltantes"].split(", ") if e in por_etiqueta
        ]
    problemas = sorted(i for i, d in enumerate(dicts) if d.get("es_valido") is False)
    return dicts, {"estado": fila["Estado"], "faltantes": sorted(faltantes), "problemas": problemas}


def _tipo(catalogo, codigo):
    if norm(codigo) == "error":
        return "error"
    tipo = catalogo.resolver(codigo)
    return tipo.codigo if tipo else "otro"


def _motivos_intencionales(evaluacion, documentos, catalogo, estado_legado):
    motivos = []
    if evaluacion.cedula_ambigua:
        motivos.append("cedula_ambigua")
    tipos = [
        catalogo.resolver(d.tipo_detectado)
        for d in documentos
        if not d.es_error and not d.es_ilegible
    ]
    codigos = [t.codigo for t in tipos if t is not None]
    if len(codigos) != len(set(codigos)):
        motivos.append("duplicados")
    if evaluacion.no_reconocidos:
        motivos.append("otro")
    if evaluacion.errores:
        motivos.append("error_de_analisis")
    if evaluacion.ilegibles:
        motivos.append("documento_ilegible")
    # Estados nuevos donde el legado solo decía INCOMPLETO (ADR 0003, diferencia 4).
    if estado_legado == "INCOMPLETO":
        if evaluacion.estado == EstadoProfesor.SIN_DOCUMENTOS:
            motivos.append("sin_documentos")
        elif evaluacion.estado == EstadoProfesor.CON_PROBLEMAS:
            motivos.append("con_problemas")
    return motivos


def comparar_profesor(profesor, dicts_legado, resultados_nuevos, catalogo, legado):
    """Compara un profesor; dicts_legado y resultados_nuevos van en el mismo orden de PDFs."""
    viejos, col1 = _reglas_del_legado(legado, profesor, dicts_legado)
    _, col2 = _reglas_del_legado(legado, profesor, [a_dict_legado(r) for r in resultados_nuevos])
    revalidados = revalidar_por_cedula(resultados_nuevos, catalogo)
    evaluacion = evaluar_profesor(revalidados, catalogo)
    col3 = {
        "estado": str(evaluacion.estado),
        "faltantes": sorted(t.codigo for t in evaluacion.faltantes),
        "problemas": sorted(revalidados.index(r) for r in evaluacion.problemas),
        "cedula_ambigua": evaluacion.cedula_ambigua,
        "no_reconocidos": [r.nombre_archivo for r in evaluacion.no_reconocidos],
        "errores": [r.error for r in evaluacion.errores],
        "ilegibles": [r.nombre_archivo for r in evaluacion.ilegibles],
    }

    completo = EstadoProfesor.COMPLETO
    completo1, completo2 = col1["estado"] == completo, col2["estado"] == completo
    completo3 = evaluacion.estado == completo
    origen = []
    if completo1 != completo2:
        origen.append("ia")
    if completo2 != completo3:
        origen.append("reglas")

    difieren_reglas = (col2["estado"], col2["faltantes"], col2["problemas"]) != (
        col3["estado"],
        col3["faltantes"],
        col3["problemas"],
    )
    motivos = (
        _motivos_intencionales(evaluacion, revalidados, catalogo, col2["estado"])
        if difieren_reglas
        else []
    )

    documentos = []
    for viejo, nuevo in zip(viejos, revalidados, strict=True):
        tipo_viejo = _tipo(catalogo, viejo.get("tipo_detectado"))
        if nuevo.es_error:
            tipo_nuevo = "error"
        elif nuevo.es_ilegible:
            tipo_nuevo = "ilegible"
        else:
            tipo_nuevo = _tipo(catalogo, nuevo.tipo_detectado)
        documentos.append(
            {
                "archivo": nuevo.nombre_archivo,
                "legado": {"tipo": tipo_viejo, "es_valido": bool(viejo.get("es_valido"))},
                "nuevo": {"tipo": tipo_nuevo, "es_valido": nuevo.es_valido},
                # Un ilegible es el mismo archivo que en el legado falló en la API.
                "coincide_tipo": tipo_viejo == tipo_nuevo
                or (tipo_viejo == "error" and tipo_nuevo == "ilegible"),
                "coincide_es_valido": bool(viejo.get("es_valido")) == nuevo.es_valido,
            }
        )

    return {
        "profesor": profesor,
        "legado": col1,
        "ia_nueva_con_reglas_del_legado": col2,
        "motor_nuevo": col3,
        "coincide_estado": completo1 == completo3,
        # El legado solo tiene COMPLETO, INCOMPLETO y ERROR (fallo de toda la carpeta).
        "coincide_estado_detallado": col1["estado"] == col3["estado"],
        "origen_diferencia_estado": "_y_".join(origen) or None,
        "diferencias_intencionales": motivos,
        "diferencias_no_explicadas": (["reglas"] if difieren_reglas and not motivos else []),
        "documentos": documentos,
    }


def resumir(informes):
    """Conteos para la pantalla: sin nombres, cédulas ni rutas."""
    documentos = [d for i in informes for d in i["documentos"]]
    return {
        "profesores": len(informes),
        "estado_coincide": sum(i["coincide_estado"] for i in informes),
        "estado_detallado_difiere": sum(not i["coincide_estado_detallado"] for i in informes),
        "estado_difiere_por_ia": sum(
            "ia" in (i["origen_diferencia_estado"] or "") for i in informes
        ),
        "estado_difiere_por_reglas": sum(
            "reglas" in (i["origen_diferencia_estado"] or "") for i in informes
        ),
        "con_diferencias_intencionales": sum(
            bool(i["diferencias_intencionales"]) for i in informes
        ),
        "con_diferencias_no_explicadas": sum(
            bool(i["diferencias_no_explicadas"]) for i in informes
        ),
        "documentos": len(documentos),
        "documentos_tipo_coincide": sum(d["coincide_tipo"] for d in documentos),
        "documentos_es_valido_coincide": sum(d["coincide_es_valido"] for d in documentos),
    }
