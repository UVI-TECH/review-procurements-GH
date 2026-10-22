"""Dominio de contratación. La ubicación de los modelos está en docs/decisiones/0002."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q

from apps.comun.inmutables import ModeloInmutable

validar_codigo = RegexValidator(
    r"^[a-z0-9_]+$", "Usa solo minúsculas sin tildes, dígitos y guion bajo."
)

# El motor usa "otro" e "ilegible" como tipo_detectado y el legado usa "error"
# (ADR 0003). Un tipo o alias con esos códigos se confundiría con ellos.
CODIGOS_RESERVADOS = ("otro", "ilegible", "error")


def _sin_codigo_reservado():
    """Condición para la BD, sin distinguir mayúsculas (un .create() salta el validador)."""
    condicion = Q()
    for codigo in CODIGOS_RESERVADOS:
        condicion &= ~Q(codigo__iexact=codigo)
    return condicion


def _validar_no_reservado(codigo):
    if (codigo or "").lower() in CODIGOS_RESERVADOS:
        raise ValidationError({"codigo": f"«{codigo}» es un código reservado del motor; usa otro."})


class TipoDocumento(models.Model):
    """Catálogo de requisitos. activo=False retira un tipo sin perder su historial."""

    codigo = models.CharField(max_length=80, unique=True, validators=[validar_codigo])
    etiqueta = models.CharField(max_length=150)
    obligatorio = models.BooleanField(
        default=True, help_text="Si falta, el profesor queda INCOMPLETO."
    )
    activo = models.BooleanField(
        default=True, help_text="Un tipo inactivo no cuenta para el estado ni admite revisiones."
    )
    orden = models.PositiveSmallIntegerField()
    requiere_firma = models.BooleanField(default=False)

    class Meta:
        ordering = ["orden", "codigo"]
        verbose_name = "tipo de documento"
        verbose_name_plural = "tipos de documento"
        constraints = [
            models.CheckConstraint(
                condition=_sin_codigo_reservado(),
                name="tipodocumento_codigo_no_reservado",
                violation_error_message="Ese código está reservado para el motor.",
            ),
        ]

    def __str__(self):
        return self.etiqueta

    def clean(self):
        _validar_no_reservado(self.codigo)
        if AliasTipoDocumento.objects.filter(codigo=self.codigo).exists():
            raise ValidationError({"codigo": "Ya existe un alias con este código."})


class AliasTipoDocumento(models.Model):
    """Código alterno que la IA puede devolver para un tipo (p. ej. el examen DOTC)."""

    tipo = models.ForeignKey(TipoDocumento, on_delete=models.CASCADE, related_name="alias")
    codigo = models.CharField(max_length=80, unique=True, validators=[validar_codigo])

    class Meta:
        ordering = ["codigo"]
        verbose_name = "alias de tipo de documento"
        verbose_name_plural = "alias de tipos de documento"
        constraints = [
            models.CheckConstraint(
                condition=_sin_codigo_reservado(),
                name="alias_codigo_no_reservado",
                violation_error_message="Ese código está reservado para el motor.",
            ),
        ]

    def __str__(self):
        return self.codigo

    def clean(self):
        _validar_no_reservado(self.codigo)
        # La unicidad entre alias la garantiza la BD; esta cruza tablas y va en el modelo.
        if TipoDocumento.objects.filter(codigo=self.codigo).exists():
            raise ValidationError({"codigo": "Ya existe un tipo de documento con este código."})


class EstadoProfesor(models.TextChoices):
    SIN_ANALIZAR = "SIN_ANALIZAR", "Sin analizar"
    COMPLETO = "COMPLETO", "Completo"
    INCOMPLETO = "INCOMPLETO", "Incompleto"
    CON_PROBLEMAS = "CON_PROBLEMAS", "Con problemas"
    SIN_DOCUMENTOS = "SIN_DOCUMENTOS", "Sin documentos"
    ERROR = "ERROR", "Error"


class Profesor(models.Model):
    """Uno por carpeta. El estado se calcula en fases siguientes."""

    carpeta = models.CharField(max_length=255, unique=True)
    nombre = models.CharField(max_length=200)
    # Texto, no entero: puede ser cédula de extranjería o tener ceros a la izquierda.
    cedula = models.CharField("cédula", max_length=20, blank=True, db_index=True)
    estado = models.CharField(
        max_length=20,
        choices=EstadoProfesor.choices,
        default=EstadoProfesor.SIN_ANALIZAR,
        db_index=True,
    )
    verificado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="profesores_verificados",
    )
    verificado_en = models.DateTimeField(null=True, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nombre"]
        verbose_name = "profesor"
        verbose_name_plural = "profesores"
        permissions = [
            ("verificar_profesor", "Puede marcar un profesor como verificado"),
            ("exportar_informes", "Puede exportar informes"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(verificado_por__isnull=True, verificado_en__isnull=True)
                | Q(verificado_por__isnull=False, verificado_en__isnull=False),
                name="profesor_verificacion_completa",
                violation_error_message="La verificación necesita usuario y fecha.",
            ),
        ]

    def __str__(self):
        return self.nombre


class Documento(models.Model):
    """Un PDF. Si desaparece de la carpeta se marca presente=False; nunca se borra."""

    profesor = models.ForeignKey(Profesor, on_delete=models.PROTECT, related_name="documentos")
    ruta_relativa = models.CharField(max_length=500)
    nombre_archivo = models.CharField(max_length=255)
    sha256 = models.CharField(max_length=64, db_index=True)
    tamano = models.PositiveBigIntegerField("tamaño (bytes)")
    modificado_en = models.DateTimeField()
    presente = models.BooleanField(default=True)
    detectado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["profesor", "ruta_relativa"]
        permissions = [("ver_pdf", "Puede ver el PDF de un documento")]
        constraints = [
            models.UniqueConstraint(
                fields=["profesor", "ruta_relativa"], name="documento_unico_por_profesor"
            ),
        ]

    def __str__(self):
        return self.ruta_relativa


class Corrida(models.Model):
    """Un procesamiento y su progreso."""

    class Alcance(models.TextChoices):
        TODOS = "todos", "Todos"
        NUEVOS_Y_MODIFICADOS = "nuevos_y_modificados", "Nuevos y modificados"
        UN_PROFESOR = "un_profesor", "Un profesor"

    class Estado(models.TextChoices):
        PENDIENTE = "pendiente", "Pendiente"
        EN_PROCESO = "en_proceso", "En proceso"
        COMPLETADA = "completada", "Completada"
        FALLIDA = "fallida", "Fallida"
        CANCELADA = "cancelada", "Cancelada"

    iniciada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="corridas"
    )
    alcance = models.CharField(max_length=30, choices=Alcance.choices)
    profesor = models.ForeignKey(
        Profesor, on_delete=models.PROTECT, null=True, blank=True, related_name="corridas"
    )
    estado = models.CharField(
        max_length=20, choices=Estado.choices, default=Estado.PENDIENTE, db_index=True
    )
    creada_en = models.DateTimeField(auto_now_add=True)
    inicio = models.DateTimeField(null=True, blank=True)
    fin = models.DateTimeField(null=True, blank=True)
    total_documentos = models.PositiveIntegerField(default=0)
    documentos_procesados = models.PositiveIntegerField(default=0)
    documentos_con_error = models.PositiveIntegerField(default=0)
    errores = models.JSONField(default=list, blank=True)
    tokens_entrada = models.PositiveBigIntegerField(default=0)
    tokens_salida = models.PositiveBigIntegerField(default=0)

    class Meta:
        ordering = ["-creada_en", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(alcance="un_profesor", profesor__isnull=False)
                | (~Q(alcance="un_profesor") & Q(profesor__isnull=True)),
                name="corrida_profesor_segun_alcance",
                violation_error_message="Solo el alcance «un profesor» lleva profesor, y lo exige.",
            ),
        ]

    def __str__(self):
        return f"Corrida {self.pk} ({self.get_alcance_display()}, {self.get_estado_display()})"


class Analisis(ModeloInmutable):
    """Resultado de la IA para un documento. Inmutable: reanalizar crea uno nuevo."""

    documento = models.ForeignKey(Documento, on_delete=models.PROTECT, related_name="analisis")
    corrida = models.ForeignKey(Corrida, on_delete=models.PROTECT, related_name="analisis")
    # Hash del archivo analizado: dice si una revisión humana sigue aplicando (ADR 0002).
    sha256 = models.CharField(max_length=64, db_index=True)
    modelo = models.CharField(max_length=100)
    # Código normalizado tal como lo devolvió la IA; puede no estar en el catálogo.
    tipo_detectado = models.CharField(max_length=80, blank=True, db_index=True)
    es_valido = models.BooleanField(null=True)
    numero_documento = models.CharField(max_length=30, blank=True)
    nombre_persona = models.CharField(max_length=200, blank=True)
    tiene_firma = models.BooleanField(null=True)
    datos_extra = models.JSONField(default=dict, blank=True)
    observaciones = models.TextField(blank=True)
    respuesta_cruda = models.JSONField(default=dict, blank=True)
    tokens_entrada = models.PositiveIntegerField(default=0)
    tokens_salida = models.PositiveIntegerField(default=0)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creado_en", "-id"]
        verbose_name = "análisis"
        verbose_name_plural = "análisis"
        default_permissions = ("view",)
        indexes = [
            models.Index(fields=["documento", "creado_en"], name="analisis_documento_fecha_idx")
        ]

    def __str__(self):
        return f"Análisis {self.pk} de {self.documento}"


class Revision(ModeloInmutable):
    """Decisión humana sobre un análisis. Inmutable: prevalece la más reciente (fecha, id)."""

    class Decision(models.TextChoices):
        APROBADO = "aprobado", "Aprobado"
        RECHAZADO = "rechazado", "Rechazado"
        CORREGIDO = "corregido", "Corregido"

    analisis = models.ForeignKey(Analisis, on_delete=models.PROTECT, related_name="revisiones")
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="revisiones"
    )
    decision = models.CharField("decisión", max_length=20, choices=Decision.choices)
    tipo_corregido = models.ForeignKey(
        TipoDocumento,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        limit_choices_to={"activo": True},
        related_name="revisiones",
    )
    comentario = models.TextField(blank=True)
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fecha", "-id"]
        verbose_name = "revisión"
        verbose_name_plural = "revisiones"
        default_permissions = ("add", "view")
        indexes = [models.Index(fields=["analisis", "fecha"], name="revision_analisis_fecha_idx")]
        constraints = [
            models.CheckConstraint(
                condition=Q(decision="aprobado") | ~Q(comentario=""),
                name="revision_comentario_si_no_aprobado",
                violation_error_message="El comentario es obligatorio al rechazar o corregir.",
            ),
            models.CheckConstraint(
                condition=Q(decision="corregido", tipo_corregido__isnull=False)
                | (~Q(decision="corregido") & Q(tipo_corregido__isnull=True)),
                name="revision_tipo_corregido_solo_si_corregido",
                violation_error_message="El tipo corregido va solo, y siempre, al corregir.",
            ),
        ]

    def __str__(self):
        return f"{self.get_decision_display()} por {self.usuario} ({self.analisis})"

    def clean(self):
        errores = {}
        if self.decision != self.Decision.APROBADO and not self.comentario.strip():
            errores["comentario"] = "El comentario es obligatorio al rechazar o corregir."
        if self.decision == self.Decision.CORREGIDO:
            if self.tipo_corregido_id is None:
                errores["tipo_corregido"] = "Indica el tipo correcto del documento."
            elif not self.tipo_corregido.activo:
                errores["tipo_corregido"] = "El tipo está retirado del catálogo."
        elif self.tipo_corregido_id is not None:
            errores["tipo_corregido"] = "El tipo corregido solo aplica al corregir."
        if errores:
            raise ValidationError(errores)

    def save(self, *args, **kwargs):
        # Validar aquí hace que la regla se cumpla también fuera de los formularios.
        if self._state.adding:
            self.full_clean()
        super().save(*args, **kwargs)
