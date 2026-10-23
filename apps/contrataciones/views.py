"""Tablero, detalle del profesor, acciones de revisión y visor de PDF (Fase 4a, ADR 0005).

Cada vista exige sesión y su permiso. Las vistas que HTMX actualiza en parte responden
el fragmento con la cabecera HX-Request y la página completa sin ella (Vary: HX-Request).
"""

from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.management import CommandError
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.cache import patch_vary_headers
from django.utils.http import content_disposition_header
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_POST

from apps.corridas.servicios import crear_fuente
from apps.cuentas.auditoria import registrar
from apps.cuentas.models import RegistroAuditoria
from apps.motor.catalogo import cargar_catalogo
from apps.motor.fuentes import ErrorFuente
from apps.motor.reglas import solo_digitos

from .models import Analisis, Documento, EstadoProfesor, Profesor, Revision, TipoDocumento
from .servicios.estado import evaluar, filtrar_por_verificacion
from .servicios.revisiones import (
    cedula_que_no_coincide,
    confirmar_cedula,
    crear_revision,
    verificar_profesor,
)

POR_PAGINA = 25

SEMAFORO = {
    "valido": ("✓", "Válido"),
    "invalido": ("✗", "Con problema"),
    "faltante": ("!", "Falta"),
    "ausente": ("–", "No presentado (opcional)"),
    "sin_dato": ("·", "Sin analizar"),
}

NOMBRE_DE_TIPO = {
    "otro": "Otro documento (no es requisito)",
    Analisis.TIPO_ILEGIBLE: "Ilegible",
    Analisis.TIPO_ERROR: "Error de análisis",
    "": "Sin tipo",
}


def _responder(request, completa, fragmento, contexto):
    plantilla = fragmento if request.headers.get("HX-Request") else completa
    respuesta = render(request, plantilla, contexto)
    patch_vary_headers(respuesta, ["HX-Request"])
    return respuesta


def _mensajes_de(error):
    return " ".join(error.messages) if isinstance(error, ValidationError) else str(error)


# --- Tablero ---


@login_required
@permission_required("contrataciones.view_profesor", raise_exception=True)
def tablero(request):
    tipos = list(TipoDocumento.objects.filter(activo=True).order_by("orden", "codigo"))
    codigos = {t.codigo for t in tipos}
    filtros = {
        "q": request.GET.get("q", "").strip(),
        "estado": request.GET.get("estado", ""),
        "falta": request.GET.get("falta", ""),
        "verificacion": request.GET.get("verificacion", ""),
        "atencion": request.GET.get("atencion") == "1",
        "ocultos": request.GET.get("ocultos") == "1",
    }

    profesores = Profesor.objects.all()
    if not filtros["ocultos"]:
        profesores = profesores.filter(carpeta_presente=True)
    conteos = dict(profesores.values_list("estado").annotate(n=Count("id")))
    totales = [(e.value, e.label, conteos.get(e.value, 0)) for e in EstadoProfesor]

    if filtros["estado"] in EstadoProfesor.values:
        profesores = profesores.filter(estado=filtros["estado"])
    if filtros["falta"] in codigos:  # solo códigos del catálogo: nada arbitrario en el lookup
        profesores = profesores.filter(**{f"resumen__tipos__{filtros['falta']}": "faltante"})
    if filtros["verificacion"] in Profesor.Verificacion.values:
        profesores = filtrar_por_verificacion(profesores, filtros["verificacion"])
    if filtros["atencion"]:
        profesores = profesores.filter(requiere_atencion=True)
    if filtros["q"]:
        busqueda = Q(nombre__icontains=filtros["q"]) | Q(carpeta__icontains=filtros["q"])
        if solo_digitos(filtros["q"]):
            digitos = solo_digitos(filtros["q"])
            busqueda |= Q(cedula__contains=digitos) | Q(cedula_confirmada__contains=digitos)
        profesores = profesores.filter(busqueda)

    pagina = Paginator(profesores.order_by("nombre", "pk"), POR_PAGINA).get_page(
        request.GET.get("pagina")
    )
    filas = []
    for profesor in pagina:
        celdas = []
        for tipo in tipos:
            estado = profesor.resumen.get("tipos", {}).get(tipo.codigo, "sin_dato")
            icono, texto = SEMAFORO[estado]
            celdas.append({"tipo": tipo, "estado": estado, "icono": icono, "texto": texto})
        filas.append({"profesor": profesor, "celdas": celdas})
    sin_pagina = urlencode(
        {k: v for k, v in request.GET.items() if k != "pagina" and v}, doseq=False
    )
    contexto = {
        "tipos": tipos,
        "filas": filas,
        "pagina": pagina,
        "totales": totales,
        "filtros": filtros,
        "estados": EstadoProfesor.choices,
        "verificaciones": Profesor.Verificacion.choices,
        "sin_pagina": sin_pagina,
        "puede_ver_detalle": request.user.has_perm("contrataciones.view_analisis"),
    }
    return _responder(
        request, "contrataciones/tablero.html", "contrataciones/_resultados.html", contexto
    )


# --- Detalle ---


def _nombre_de_tipo(catalogo, codigo):
    tipo = catalogo.resolver(codigo)
    return tipo.etiqueta if tipo else NOMBRE_DE_TIPO.get(codigo, codigo)


def _historial(profesor, documentos):
    tipo_profesor = ContentType.objects.get_for_model(Profesor)
    tipo_documento = ContentType.objects.get_for_model(Documento)
    eventos = RegistroAuditoria.objects.filter(
        Q(content_type=tipo_profesor, objeto_id=str(profesor.pk))
        | Q(content_type=tipo_documento, objeto_id__in=[str(d.pk) for d in documentos])
    ).select_related("usuario")[:100]
    analisis = (
        Analisis.objects.filter(documento__in=documentos)
        .select_related("documento", "corrida")
        .order_by("-creado_en", "-id")[:100]
    )
    revisiones = (
        Revision.objects.filter(analisis__documento__in=documentos)
        .select_related("analisis__documento", "usuario", "tipo_corregido")
        .order_by("-fecha", "-id")[:100]
    )
    return {"eventos": eventos, "analisis": analisis, "revisiones": revisiones}


@login_required
@permission_required("contrataciones.view_analisis", raise_exception=True)
def detalle(request, pk):
    profesor = get_object_or_404(Profesor, pk=pk)
    catalogo = cargar_catalogo()
    evaluacion, evaluados = evaluar(profesor, catalogo)
    documentos = []
    for e in evaluados:
        tipo_ia = e.analisis.tipo_detectado if e.analisis else ""
        documentos.append(
            {
                "evaluado": e,
                "tipo_ia": _nombre_de_tipo(catalogo, tipo_ia),
                "tipo_efectivo": _nombre_de_tipo(catalogo, e.resultado.tipo_detectado)
                if e.resultado
                else "Descartado",
                "valido": e.resultado.es_valido if e.resultado else None,
                "puede_aprobar": bool(e.analisis)
                and tipo_ia not in (Analisis.TIPO_ERROR, Analisis.TIPO_ILEGIBLE)
                and catalogo.resolver(tipo_ia) is not None,
                "cedula_ajena": cedula_que_no_coincide(e, evaluacion.cedula or ""),
            }
        )

    try:
        elegido_id = int(request.GET.get("documento", ""))
    except ValueError:
        elegido_id = None
    elegido = next(
        (d for d in documentos if d["evaluado"].documento.pk == elegido_id),
        documentos[0] if documentos else None,
    )
    contexto = {
        "profesor": profesor,
        "evaluacion": evaluacion,
        "documentos": documentos,
        "elegido": elegido,
        "tipos_activos": TipoDocumento.objects.filter(activo=True).order_by("orden"),
        "decisiones": Revision.Decision.choices,
        "historial": _historial(profesor, [d["evaluado"].documento for d in documentos]),
        "puede_revisar": request.user.has_perm("contrataciones.add_revision"),
        "puede_verificar": request.user.has_perm("contrataciones.verificar_profesor"),
        "puede_ver_pdf": request.user.has_perm("contrataciones.ver_pdf"),
    }
    if request.headers.get("HX-Request") and "documento" in request.GET:
        respuesta = render(request, "contrataciones/_panel.html", contexto)
        patch_vary_headers(respuesta, ["HX-Request"])
        return respuesta
    return _responder(
        request, "contrataciones/detalle.html", "contrataciones/detalle.html", contexto
    )


def _al_detalle(profesor, documento=None):
    url = reverse("detalle", args=[profesor.pk])
    return redirect(f"{url}?documento={documento.pk}#panel" if documento else url)


@login_required
@permission_required("contrataciones.add_revision", raise_exception=True)
@require_POST
def revisar(request, pk, documento):
    profesor = get_object_or_404(Profesor, pk=pk)
    doc = get_object_or_404(Documento, pk=documento, profesor=profesor)
    decision = request.POST.get("decision", "")
    tipo = None
    if decision == Revision.Decision.CORREGIDO:
        tipo = TipoDocumento.objects.filter(
            activo=True, pk=request.POST.get("tipo_corregido") or None
        ).first()
    if decision not in Revision.Decision.values:
        messages.error(request, "Elige una decisión.")
        return _al_detalle(profesor, doc)
    try:
        crear_revision(
            doc, request.user, decision, request.POST.get("comentario", "").strip(), tipo
        )
    except ValidationError as error:
        messages.error(request, _mensajes_de(error))
    else:
        messages.success(
            request, f"Revisión guardada: {Revision.Decision(decision).label.lower()}."
        )
    return _al_detalle(profesor, doc)


@login_required
@permission_required("contrataciones.verificar_profesor", raise_exception=True)
@require_POST
def verificar(request, pk):
    profesor = get_object_or_404(Profesor, pk=pk)
    try:
        verificar_profesor(profesor, request.user)
    except ValidationError as error:
        messages.error(request, _mensajes_de(error))
    else:
        messages.success(request, "Profesor verificado.")
    return _al_detalle(profesor)


@login_required
@permission_required("contrataciones.verificar_profesor", raise_exception=True)
@require_POST
def cedula(request, pk):
    profesor = get_object_or_404(Profesor, pk=pk)
    try:
        confirmar_cedula(profesor, request.user, request.POST.get("cedula", ""))
    except ValidationError as error:
        messages.error(request, _mensajes_de(error))
    else:
        messages.success(request, "Cédula confirmada.")
    return _al_detalle(profesor)


# --- Visor de PDF ---


@login_required
@permission_required("contrataciones.ver_pdf", raise_exception=True)
@xframe_options_sameorigin
def pdf(request, pk):
    documento = get_object_or_404(Documento, pk=pk, presente=True)
    try:
        datos = crear_fuente().leer(documento.ruta_relativa)
    except (ErrorFuente, CommandError):
        raise Http404("El PDF no está disponible.") from None
    registrar(request.user, "pdf_visto", documento)
    respuesta = HttpResponse(datos, content_type="application/pdf")
    respuesta["Content-Disposition"] = content_disposition_header(
        as_attachment=False, filename=documento.nombre_archivo
    )
    respuesta["X-Content-Type-Options"] = "nosniff"
    # El visor del navegador no admite más restricciones; solo se puede incrustar aquí.
    respuesta["Content-Security-Policy"] = "frame-ancestors 'self'"
    return respuesta
