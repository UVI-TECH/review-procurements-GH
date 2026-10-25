# Despliegue en el PC de Gestión Humana (Windows)

> Guía en construcción: el procedimiento completo (`instalar.ps1`, `iniciar.bat`, arranque automático) llega en la Fase 7. Aquí quedan desde ya las reglas que no pueden olvidarse al instalar.

## Base de datos y OneDrive

- **La base de datos nunca va dentro de una carpeta sincronizada por OneDrive.** SQLite corre en modo WAL (crea `revision.db-wal` y `revision.db-shm`), y la sincronización de esos archivos puede corromper la base. Usa una carpeta local, por ejemplo `C:\RevisionContrataciones\datos\revision.db`, y ponla en `RUTA_BASE_DATOS`.
- La app se niega a arrancar si `RUTA_BASE_DATOS` cae dentro de `CARPETA_CONTRATACIONES`.
- **Solo los respaldos cifrados van a OneDrive** (Fase 6).

## Carpeta de Contrataciones

- `CARPETA_CONTRATACIONES` apunta a la carpeta sincronizada, con una subcarpeta por profesor.
- En OneDrive, esa carpeta se configura como **"Mantener siempre en este dispositivo"**. Así el worker no depende de descargas bajo demanda. Un ERROR por archivo no descargado queda como respaldo, no como el caso normal.

## Worker

- Solo puede haber un worker por equipo. El bloqueo (`worker.lock`) y el PID (`worker.pid`) quedan, por defecto, junto a la base de datos.
- Si el worker se cierra a mitad de una corrida (apagón, cierre forzado), al volver a iniciarlo la corrida continúa sin repetir documentos.
- El worker recalcula el estado de todos los profesores al arrancar y cada 24 horas, porque la vigencia de los certificados cambia con los días aunque no cambien los archivos (ADR 0006). Si el worker no está corriendo, el tablero no refleja los vencimientos hasta que vuelva a arrancar. El detalle de un profesor sí evalúa siempre contra el día de hoy.

## Al cambiar el prompt o el esquema de la IA

Los análisis guardados no se modifican y el procesamiento es incremental: un archivo que no cambió no se vuelve a analizar. Por eso, cuando cambian el prompt, el esquema de la herramienta o el catálogo de tipos, los análisis viejos se quedan con lo que pedía la versión anterior. Procedimiento general:

1. Revisa el costo con `uv run python manage.py crear_corrida --alcance todos --usuario <tu_usuario> --en-seco`.
2. Si el estimado es aceptable, lanza la corrida `todos` y deja trabajar al worker.

Aplica a todo entorno con análisis previos, como el clon de validación, y se repite cada vez que cambie el prompt. Producción todavía no existe: arrancará con el prompt de los requisitos 2026-2 y sin análisis viejos.
