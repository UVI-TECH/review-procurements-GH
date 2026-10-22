#!/usr/bin/env python3
"""
Revisión automatizada de documentos de contratación — Gestión Humana UNIAJC.
Lee las carpetas de profesores desde la carpeta de OneDrive sincronizada en disco,
analiza cada PDF con la API de Claude y genera un Excel de reporte (se sobreescribe).

Requisitos:  pip install anthropic openpyxl
Ejecutar:    python revisar_contrataciones.py
"""

import base64
import json
import re
import time
import unicodedata
from collections import Counter
from pathlib import Path

import anthropic
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

# ─── CONFIGURACIÓN (editar estas 3 líneas) ──────────────────────────────────
CARPETA_CONTRATACIONES = r"C:\Users\GestionHumana\OneDrive - UNIAJC\Contrataciones"
ARCHIVO_EXCEL = r"C:\Users\GestionHumana\Desktop\Reporte_Contrataciones.xlsx"
API_KEY = "PEGA_AQUI_TU_API_KEY"
# ────────────────────────────────────────────────────────────────────────────

MODELO = "claude-haiku-4-5-20251001"
PAUSA_ENTRE_LLAMADAS = 0.5
MAX_INTENTOS = 3

# tipo canónico (lo que devuelve Claude, normalizado) -> etiqueta legible
DOCS = [
    ("certificado_antecedentes_disciplinarios", "Antecedentes Disciplinarios (Procuraduría)"),
    ("boletin_responsabilidades_fiscales", "Responsabilidades Fiscales (Contraloría)"),
    ("certificado_antecedentes_judiciales", "Antecedentes Judiciales (Policía)"),
    ("certificado_registro_nacional_medidas_correctivas", "Medidas Correctivas"),
    ("formato_autorizacion_consulta_inhabilidades", "Formato Autorización Consulta"),
    ("consulta_inhabilidades_delitos_sexuales", "Consulta Inhabilidades Delitos Sexuales"),
    ("certificado_registro_deudores_morosos", "REDAM (Deudores Morosos)"),
    ("certificados_eps_afp", "Certificados EPS/AFP"),
    ("certificado_medico_laboral", "Certificado Médico Laboral"),
]

# El examen DOTC y el certificado médico laboral son el mismo documento operativo.
TIPO_MEDICO = "certificado_medico_laboral"
TIPO_MEDICO_ALTERNO = "examen_medico_laboral_dotc"

# La autorización exige firma; no se valida solo por cédula.
TIPO_FORMATO = "formato_autorizacion_consulta_inhabilidades"

COLUMNAS = [
    "Profesor", "Estado", "Docs_Faltantes", "Docs_con_Problemas", "Observaciones",
    "Total_Docs", "Docs_Validos", "Procuraduria", "Contraloria", "Policia_Nacional",
    "Medidas_Correctivas", "Formato_Consulta", "Certificado_Delitos_Sexuales",
    "REDAM", "EPS", "AFP", "Examen_Medico",
]

ESQUEMAS = """Responde SOLO con un objeto JSON, sin texto adicional ni marcas de código. Usa el esquema según el tipo detectado:
- Boletín responsabilidades fiscales (Contraloría): {"tipo_detectado":"BOLETIN_RESPONSABILIDADES_FISCALES","es_valido":true,"numero_documento":"...","nombre_persona":"No aplica - documento sin nombre por diseño oficial","observaciones":"..."}
- Antecedentes judiciales o penales (Policía): {"tipo_detectado":"CERTIFICADO_ANTECEDENTES_JUDICIALES","es_valido":true,"numero_documento":"...","nombre_persona":"...","observaciones":"..."}
- Antecedentes disciplinarios u ordinario de procuraduría: {"tipo_detectado":"CERTIFICADO_ANTECEDENTES_DISCIPLINARIOS","es_valido":true,"numero_documento":"...","nombre_persona":"...","observaciones":"..."}
- Registro nacional de medidas correctivas: {"tipo_detectado":"CERTIFICADO_REGISTRO_NACIONAL_MEDIDAS_CORRECTIVAS","es_valido":true,"numero_documento":"...","nombre_persona":"...","observaciones":"..."}
- Concepto médico ocupacional o certificado médico laboral: {"tipo_detectado":"CERTIFICADO_MEDICO_LABORAL","es_valido":true,"numero_documento":"...","nombre_persona":"...","observaciones":"Documento presente"}
- Registro de deudores morosos (REDAM): {"tipo_detectado":"CERTIFICADO_REGISTRO_DEUDORES_MOROSOS","es_valido":true,"numero_documento":"...","nombre_persona":"No aplica - documento sin nombre por diseño oficial","observaciones":"..."}
- Certificado EPS/AFP, pensión o seguridad social: {"tipo_detectado":"CERTIFICADOS_EPS_AFP","es_valido":true,"numero_documento":"...","nombre_persona":"...","fecha_emision_eps":"...","fecha_emision_afp":"...","es_certificado_afiliacion":true,"observaciones":"..."}
- Consulta de inhabilidades por delitos sexuales contra menores: {"tipo_detectado":"CONSULTA_INHABILIDADES_DELITOS_SEXUALES","es_valido":true,"numero_documento":"...","nombre_persona":"...","observaciones":"..."}
- Formato de autorización para consulta de inhabilidades: {"tipo_detectado":"FORMATO_AUTORIZACION_CONSULTA_INHABILIDADES","es_valido":true,"numero_documento":"...","nombre_persona":"...","tiene_firma":true,"observaciones":"..."}
- Examen médico laboral DOTC (audiometría, optometría, tamizaje, voz): {"tipo_detectado":"EXAMEN_MEDICO_LABORAL_DOTC","es_valido":true,"numero_documento":"...","nombre_persona":"...","observaciones":"Documento presente"}"""

client = anthropic.Anthropic(api_key=API_KEY)


def norm(texto):
    texto = (texto or "").lower().strip()
    texto = "".join(c for c in unicodedata.normalize("NFD", texto)
                    if unicodedata.category(c) != "Mn")
    texto = re.sub(r"\.pdf$", "", texto)
    return re.sub(r"[\s\-]+", "_", texto)


def solo_digitos(valor):
    return re.sub(r"\D", "", valor or "")


def construir_prompt(nombre_archivo, profesor):
    reglas = f"""Eres un asistente de Gestión Humana de UNIAJC. Analiza este documento PDF.
Nombre del archivo: {nombre_archivo}.
Profesor al que pertenece esta carpeta: {profesor}.

REGLAS DE VALIDACIÓN:
1. Identifica el tipo de documento.
2. La identidad del titular se verifica por la CÉDULA, no por el nombre. Muchos de estos documentos NO incluyen el nombre de la persona (por diseño oficial del certificado, o porque el profesor es extranjero e identificado solo con cédula de extranjería). La AUSENCIA de nombre NO es motivo para marcar el documento como inválido.
3. Marca es_valido=true cuando el documento esté correctamente emitido por la entidad correspondiente y tenga número de documento o código de verificación. En numero_documento registra la cédula que aparezca (de ciudadanía o de extranjería).
4. Marca es_valido=false SOLO si: (a) el documento muestra claramente el nombre de una persona DISTINTA de {profesor}; o (b) es de un tipo que no corresponde; o (c) en el Formato de Autorización de Consulta, faltan campos obligatorios como la firma o la identificación.
5. Si no puedes leer el nombre, escribe en nombre_persona una nota breve (por ejemplo "No incluye nombre - identificado por cédula") y NO lo marques inválido por ello.
"""
    return reglas + "\n" + ESQUEMAS


def analizar_pdf(ruta_pdf, profesor):
    datos = base64.standard_b64encode(ruta_pdf.read_bytes()).decode()
    respuesta = client.messages.create(
        model=MODELO,
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": [
                {"type": "document",
                 "source": {"type": "base64", "media_type": "application/pdf", "data": datos}},
                {"type": "text", "text": construir_prompt(ruta_pdf.name, profesor)},
            ],
        }],
    )
    texto = next((b.text for b in respuesta.content if b.type == "text"), "")
    texto = texto.replace("```json", "").replace("```", "").strip()
    try:
        datos = json.loads(texto)
    except json.JSONDecodeError:
        return {"tipo_detectado": "ERROR", "es_valido": False, "observaciones": texto[:300]}
    if isinstance(datos, list):
        datos = next((d for d in datos if isinstance(d, dict)), None)
    if not isinstance(datos, dict):
        return {"tipo_detectado": "ERROR", "es_valido": False,
                "observaciones": "Respuesta con formato inesperado: " + texto[:200]}
    return datos


def analizar_con_reintentos(ruta_pdf, profesor):
    for intento in range(1, MAX_INTENTOS + 1):
        try:
            return analizar_pdf(ruta_pdf, profesor)
        except Exception as error:
            if intento == MAX_INTENTOS:
                return {"tipo_detectado": "ERROR", "es_valido": False,
                        "observaciones": f"Error tras {MAX_INTENTOS} intentos: {error}"}
            time.sleep(5 * intento)


def cedula_modal(resultados):
    cedulas = [solo_digitos(r.get("numero_documento")) for r in resultados
               if solo_digitos(r.get("numero_documento"))]
    return Counter(cedulas).most_common(1)[0][0] if cedulas else None


def revalidar_por_cedula(resultados):
    """Cruza cada documento contra la cédula del profesor (la más frecuente del set).
    Identidad por cédula, no por nombre: corrige falsos inválidos por falta de nombre
    y marca como inválidos los documentos cuya cédula pertenece a otra persona."""
    modal = cedula_modal(resultados)
    if not modal:
        return
    for r in resultados:
        cedula = solo_digitos(r.get("numero_documento"))
        if not cedula:
            continue
        tipo = norm(r.get("tipo_detectado"))
        if cedula != modal:
            if r.get("es_valido"):
                r["es_valido"] = False
                r["observaciones"] = (f"La cédula {cedula} no coincide con la del profesor "
                                      f"({modal}). " + (r.get("observaciones") or ""))
            continue
        if r.get("es_valido"):
            continue
        if tipo == TIPO_FORMATO:
            if r.get("tiene_firma"):
                r["es_valido"] = True
                r["observaciones"] = ("Válido (cédula coincide y documento firmado). "
                                      + (r.get("observaciones") or ""))
        else:
            r["es_valido"] = True
            r["observaciones"] = ("Válido (verificado por cédula; la falta de nombre no invalida). "
                                  + (r.get("observaciones") or ""))


def _estado(doc):
    return "✓ VÁLIDO" if doc.get("es_valido") else "✗ INVÁLIDO"


def fmt(doc):
    if not doc:
        return "FALTANTE"
    return (f"{_estado(doc)} | CC: {doc.get('numero_documento', 'N/A')} "
            f"| Nombre: {doc.get('nombre_persona', 'N/A')} | {doc.get('observaciones', '')}")


def fmt_firma(doc):
    if not doc:
        return "FALTANTE"
    firma = "Sí" if doc.get("tiene_firma") else "No"
    return (f"{_estado(doc)} | CC: {doc.get('numero_documento', 'N/A')} "
            f"| Nombre: {doc.get('nombre_persona', 'N/A')} | Firma: {firma}")


def fmt_eps_afp(doc):
    if not doc:
        return "FALTANTE"
    afiliacion = "Sí" if doc.get("es_certificado_afiliacion") else "No"
    return (f"{_estado(doc)} | CC: {doc.get('numero_documento', 'N/A')} "
            f"| Nombre: {doc.get('nombre_persona', 'N/A')} "
            f"| Fecha EPS: {doc.get('fecha_emision_eps', 'N/A')} "
            f"| Fecha AFP: {doc.get('fecha_emision_afp', 'N/A')} | Es cert. afiliación: {afiliacion}")


def construir_fila(profesor, resultados):
    por_tipo = {norm(r.get("tipo_detectado")): r for r in resultados}
    if TIPO_MEDICO_ALTERNO in por_tipo and TIPO_MEDICO not in por_tipo:
        por_tipo[TIPO_MEDICO] = por_tipo[TIPO_MEDICO_ALTERNO]
    faltantes = [label for tipo, label in DOCS if tipo not in por_tipo]
    con_problemas = [r for r in resultados if r.get("es_valido") is False]
    completo = not faltantes and not con_problemas
    return {
        "Profesor": profesor,
        "Estado": "COMPLETO" if completo else "INCOMPLETO",
        "Docs_Faltantes": ", ".join(faltantes),
        "Docs_con_Problemas": ", ".join(r.get("tipo_detectado", "") for r in con_problemas),
        "Observaciones": " | ".join(f"{r.get('tipo_detectado')}: {r.get('observaciones')}"
                                    for r in con_problemas),
        "Total_Docs": len(resultados),
        "Docs_Validos": sum(1 for r in resultados if r.get("es_valido")),
        "Procuraduria": fmt(por_tipo.get("certificado_antecedentes_disciplinarios")),
        "Contraloria": fmt(por_tipo.get("boletin_responsabilidades_fiscales")),
        "Policia_Nacional": fmt(por_tipo.get("certificado_antecedentes_judiciales")),
        "Medidas_Correctivas": fmt(por_tipo.get("certificado_registro_nacional_medidas_correctivas")),
        "Formato_Consulta": fmt_firma(por_tipo.get("formato_autorizacion_consulta_inhabilidades")),
        "Certificado_Delitos_Sexuales": fmt(por_tipo.get("consulta_inhabilidades_delitos_sexuales")),
        "REDAM": fmt(por_tipo.get("certificado_registro_deudores_morosos")),
        "EPS": fmt_eps_afp(por_tipo.get("certificados_eps_afp")),
        "AFP": fmt_eps_afp(por_tipo.get("certificados_eps_afp")),
        "Examen_Medico": fmt(por_tipo.get("certificado_medico_laboral")),
    }


def fila_sin_documentos(profesor):
    fila = {col: "FALTANTE" for col in COLUMNAS}
    fila.update({
        "Profesor": profesor,
        "Estado": "INCOMPLETO",
        "Docs_Faltantes": "No tiene documentos requeridos",
        "Docs_con_Problemas": "",
        "Observaciones": f"El profesor cargó 0 de {len(DOCS)} documentos",
        "Total_Docs": 0,
        "Docs_Validos": 0,
    })
    return fila


def fila_error(profesor, error):
    fila = fila_sin_documentos(profesor)
    fila["Estado"] = "ERROR"
    fila["Docs_Faltantes"] = ""
    fila["Observaciones"] = f"Error al procesar: {error}"
    return fila


def procesar_profesor(carpeta, indice, total):
    profesor = carpeta.name
    pdfs = sorted(carpeta.glob("*.pdf"))
    porcentaje = indice * 100 // total
    print(f"[{indice}/{total}] {porcentaje}% - {profesor}: {len(pdfs)} PDF(s)")
    if not pdfs:
        return fila_sin_documentos(profesor)
    try:
        resultados = []
        for pdf in pdfs:
            resultados.append(analizar_con_reintentos(pdf, profesor))
            time.sleep(PAUSA_ENTRE_LLAMADAS)
        revalidar_por_cedula(resultados)
        return construir_fila(profesor, resultados)
    except Exception as error:
        print(f"    ERROR en {profesor}: {error}")
        return fila_error(profesor, error)


def escribir_excel(filas, ruta):
    libro = Workbook()
    hoja = libro.active
    hoja.title = "Contrataciones"
    hoja.append(COLUMNAS)
    relleno = PatternFill("solid", fgColor="1F4E78")
    for celda in hoja[1]:
        celda.font = Font(bold=True, color="FFFFFF")
        celda.fill = relleno
        celda.alignment = Alignment(horizontal="center", vertical="center")
    for fila in filas:
        hoja.append([fila.get(col, "") for col in COLUMNAS])
    hoja.freeze_panes = "A2"
    libro.save(ruta)


def main():
    carpeta_raiz = Path(CARPETA_CONTRATACIONES)
    if not carpeta_raiz.is_dir():
        raise SystemExit(f"No existe la carpeta: {carpeta_raiz}")

    carpetas = sorted(c for c in carpeta_raiz.iterdir() if c.is_dir())
    total = len(carpetas)
    print(f"Profesores encontrados: {total}\n")

    filas = [procesar_profesor(c, i, total) for i, c in enumerate(carpetas, start=1)]

    Path(ARCHIVO_EXCEL).parent.mkdir(parents=True, exist_ok=True)
    escribir_excel(filas, ARCHIVO_EXCEL)

    completos = sum(1 for f in filas if f["Estado"] == "COMPLETO")
    print(f"\nReporte generado: {ARCHIVO_EXCEL}")
    print(f"Total: {total} | Completos: {completos} | Incompletos: {total - completos}")


if __name__ == "__main__":
    main()
