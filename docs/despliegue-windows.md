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
