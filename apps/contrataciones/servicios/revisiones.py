"""Acciones del revisor: revisar un documento, verificar al profesor, confirmar su cédula.

Cada acción valida, guarda, queda en auditoría y recalcula el estado del profesor.
"""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.cuentas.auditoria import registrar
from apps.motor.catalogo import cargar_catalogo
from apps.motor.reglas import EstadoProfesor, solo_digitos

from ..models import Analisis, Revision
from .estado import evaluar, recalcular_estado

Decision = Revision.Decision


def cedula_que_no_coincide(evaluado, cedula_profesor):
    """La cédula del documento si es distinta de la del profesor; si no, None."""
    if evaluado.analisis is None:
        return None
    cedula = solo_digitos(evaluado.analisis.numero_documento)
    profesor = solo_digitos(cedula_profesor)
    return cedula if cedula and profesor and cedula != profesor else None


@transaction.atomic
def crear_revision(documento, usuario, decision, comentario="", tipo_corregido=None):
    catalogo = cargar_catalogo()
    profesor = documento.profesor
    if not documento.presente:
        raise ValidationError("El documento no está en la carpeta: no se puede revisar.")
    evaluacion, evaluados = evaluar(profesor, catalogo)
    evaluado = next(e for e in evaluados if e.documento.pk == documento.pk)
    if evaluado.analisis is None:
        raise ValidationError("El documento aún no tiene análisis: espera a la corrida.")

    if decision == Decision.APROBADO:
        sin_tipo = (
            evaluado.analisis.tipo_detectado
            in (
                Analisis.TIPO_ERROR,
                Analisis.TIPO_ILEGIBLE,
            )
            or catalogo.resolver(evaluado.analisis.tipo_detectado) is None
        )
        if sin_tipo:
            raise ValidationError(
                "Este documento no tiene un tipo del catálogo: corrige el tipo, recházalo o "
                "descártalo."
            )
    if decision in (Decision.APROBADO, Decision.CORREGIDO) and not comentario.strip():
        ajena = cedula_que_no_coincide(evaluado, evaluacion.cedula or "")
        if ajena:
            raise ValidationError(
                f"La cédula del documento ({ajena}) no coincide con la del profesor "
                f"({evaluacion.cedula}). Explica en el comentario por qué lo aceptas."
            )

    revision = Revision(
        analisis=evaluado.analisis,
        usuario=usuario,
        decision=decision,
        comentario=comentario,
        tipo_corregido=tipo_corregido,
    )
    revision.save()  # full_clean: comentario, tipo corregido y tipo activo
    registrar(
        usuario, "revision_creada", documento, {"decision": decision, "revision": revision.pk}
    )
    recalcular_estado(profesor, catalogo)
    return revision


@transaction.atomic
def verificar_profesor(profesor, usuario):
    recalcular_estado(profesor, cargar_catalogo())
    if profesor.estado != EstadoProfesor.COMPLETO:
        raise ValidationError(
            "Solo se verifica un profesor en estado COMPLETO "
            f"(hoy está {profesor.get_estado_display().upper()})."
        )
    profesor.verificado_por = usuario
    profesor.verificado_en = timezone.now()
    profesor.verificado_huella = profesor.huella_actual
    profesor.save(update_fields=["verificado_por", "verificado_en", "verificado_huella"])
    registrar(usuario, "profesor_verificado", profesor)


@transaction.atomic
def confirmar_cedula(profesor, usuario, cedula):
    cedula = (cedula or "").strip()
    if not solo_digitos(cedula):
        raise ValidationError("Escribe la cédula del profesor (con sus dígitos).")
    if len(cedula) > 20:
        raise ValidationError("La cédula no puede tener más de 20 caracteres.")
    anterior = profesor.cedula_confirmada
    profesor.cedula_confirmada = cedula
    profesor.cedula_confirmada_por = usuario
    profesor.cedula_confirmada_en = timezone.now()
    profesor.save(
        update_fields=["cedula_confirmada", "cedula_confirmada_por", "cedula_confirmada_en"]
    )
    registrar(usuario, "cedula_confirmada", profesor, {"anterior": anterior, "nueva": cedula})
    recalcular_estado(profesor, cargar_catalogo())
