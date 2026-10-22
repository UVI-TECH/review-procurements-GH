from django.db import models


class Respaldo(models.Model):
    """Historial de copias cifradas de la base de datos (la lógica llega en la Fase 6)."""

    class Origen(models.TextChoices):
        MANUAL = "manual", "Manual"
        CORRIDA = "corrida", "Al terminar una corrida"
        INICIO = "inicio", "Al abrir la app"
        PROGRAMADO = "programado", "Tarea programada"

    class Estado(models.TextChoices):
        EN_PROCESO = "en_proceso", "En proceso"
        VERIFICADO = "verificado", "Verificado"
        FALLIDO = "fallido", "Fallido"

    fecha = models.DateTimeField(auto_now_add=True, db_index=True)
    ruta = models.CharField(max_length=500)
    tamano = models.PositiveBigIntegerField("tamaño (bytes)", null=True, blank=True)
    sha256 = models.CharField(max_length=64, blank=True)
    origen = models.CharField(max_length=20, choices=Origen.choices)
    estado = models.CharField(max_length=20, choices=Estado.choices, default=Estado.EN_PROCESO)
    mensaje = models.TextField(blank=True)

    class Meta:
        ordering = ["-fecha", "-id"]

    def __str__(self):
        return f"Respaldo {self.fecha:%Y-%m-%d %H:%M} ({self.get_estado_display()})"
