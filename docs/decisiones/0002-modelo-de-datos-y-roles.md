# 0002. Modelo de datos, inmutabilidad del historial y roles

- **Estado:** aceptada
- **Fecha:** 2026-10-22

## Contexto

La Fase 1 crea los modelos, el catálogo inicial y los roles. Hay tres riesgos que el diseño debe cerrar desde el principio:

1. **Dependencias circulares entre apps.** Varias apps necesitan referirse a las mismas entidades.
2. **Pérdida del historial.** La revisión humana debe quedar trazable y la IA nunca debe sobrescribir un resultado anterior.
3. **Exposición de datos personales.** Los PDFs y sus análisis contienen datos personales (Ley 1581 de 2012).

## Decisión

### Ubicación de los modelos

| App | Modelos |
| --- | --- |
| `contrataciones` | `TipoDocumento`, `AliasTipoDocumento`, `Profesor`, `Documento`, `Analisis`, `Revision`, `Corrida` |
| `cuentas` | `Usuario` (desde la Fase 0), `RegistroAuditoria` y el helper `auditoria.registrar(usuario, accion, objeto, detalle)` |
| `respaldos` | `Respaldo` |
| `motor`, `corridas`, `reportes` | Sin modelos; solo lógica, en fases siguientes |

`apps/comun/` no es una app de Django: solo contiene `inmutables.py` (`ModeloInmutable`, `ErrorInmutable`), que comparten `contrataciones` y `cuentas`.

`Corrida` vive en `contrataciones` y no en `corridas`, porque `Analisis` la referencia. Así `corridas` (el worker) depende del dominio y no al revés.

### Catálogo

- `AliasTipoDocumento(tipo, codigo único)` se edita en línea dentro del tipo. Se eligió frente a un `JSONField` de alias por dos razones:
  - SQLite no admite `__contains` sobre `JSONField`.
  - La unicidad entre alias la garantiza la base de datos. `clean()` solo corre en formularios y en `full_clean()`, y un `.save()` directo o una migración se lo saltan.
- La unicidad entre alias y códigos de tipo cruza tablas, así que se valida en `clean()` de los dos modelos.
- `obligatorio` y `activo` son campos distintos:
  - `obligatorio=False`: el tipo se reconoce, pero su ausencia no deja al profesor INCOMPLETO.
  - `activo=False`: el tipo está retirado. No aparece en el desplegable de nuevas revisiones (`limit_choices_to`, validado también en `Revision.clean()`) ni cuenta para el estado, pero las revisiones históricas lo conservan.
- La migración `contrataciones/0002_catalogo_inicial` siembra los 9 tipos de `DOCS` del legado (código, etiqueta y orden), todos obligatorios y activos. Solo `formato_autorizacion_consulta_inhabilidades` lleva `requiere_firma=True`. También crea el alias `examen_medico_laboral_dotc` → `certificado_medico_laboral`.

### Análisis y revisiones

- `Analisis.tipo_detectado` es un `CharField` con el código normalizado que devolvió la IA. Puede no estar en el catálogo (p. ej. "otro"), y el valor crudo queda en `respuesta_cruda`. La resolución código/alias → tipo ocurre al calcular el estado, no al guardar.
- `Revision.tipo_corregido` es una FK a `TipoDocumento` con `PROTECT`: la corrección humana siempre sale del catálogo.
- `Analisis` guarda el `sha256` del archivo que analizó.
- Validaciones de `Revision`:
  - El comentario es obligatorio al rechazar o corregir.
  - `tipo_corregido` es obligatorio al corregir y debe ir vacío en los demás casos.
  - Se validan en `clean()`, y `save()` llama a `full_clean()` al crear, así que también aplican fuera de los formularios.
  - Además, dos `CheckConstraint` las repiten en la base de datos.

### Historial inmutable

`Analisis`, `Revision` y `RegistroAuditoria` son de solo agregar:

- **En el modelo.** `ModeloInmutable` lanza `ErrorInmutable` en `save()` sobre una fila existente, en `delete()`, y en `.update()`/`.delete()` del `QuerySet`, incluidos los managers relacionados y `bulk_update`.
- **En los permisos.** `default_permissions` no incluye `change` ni `delete`, así que esos permisos no existen ni se pueden asignar por error.
- **En el admin.** `has_change_permission` y `has_delete_permission` devuelven `False`, también para el superusuario.
- **En las FK.** Las borradas en cascada las impide `on_delete=PROTECT` en toda FK del historial: `Documento→Profesor`, `Analisis→Documento/Corrida`, `Revision→Analisis/Usuario/TipoDocumento`, `Corrida→Usuario/Profesor`, `Profesor.verificado_por` y `RegistroAuditoria→Usuario/ContentType`. Un usuario con historial no se borra: se desactiva.

Cambiar de opinión sobre un análisis es crear otra `Revision`. Prevalece la más reciente (por `fecha` y luego por `id`).

**No se usan triggers de SQLite.** Habría que reescribirlos para PostgreSQL, rompen el `flush` de `TransactionTestCase` y no agregan una barrera real: quien puede abrir el `.db` puede alterarlo todo.

`RegistroAuditoria.usuario` es nulo en las acciones del sistema (worker, respaldo programado) y en los inicios de sesión fallidos. En esos casos, el nombre de usuario intentado va en `detalle`. El registro guarda `objeto_repr` para que siga siendo legible aunque el objeto cambie.

### Roles

Los grupos los crea la migración `cuentas/0003_roles`. Como en una base nueva los permisos se crean después de las migraciones, la migración los crea antes con `create_permissions`. Si falta algún permiso, la migración falla.

| Permiso | Administrador | Revisor GH | Consulta |
| --- | --- | --- | --- |
| Catálogo (`tipodocumento`, `aliastipodocumento`): add/change/delete | ✅ | — | — |
| Catálogo: view | ✅ | ✅ | — |
| `Profesor`: view | ✅ | ✅ | ✅ |
| `Profesor`: add/change/delete | ✅ | — | — |
| `verificar_profesor` | ✅ | ✅ | — |
| `exportar_informes` | ✅ | ✅ | ✅ |
| `Documento`: view | ✅ | ✅ | ✅ |
| `Documento`: add/change/delete | ✅ | — | — |
| `ver_pdf` | ✅ | ✅ | — |
| `Analisis`: view | ✅ | ✅ | — |
| `Revision`: view | ✅ | ✅ | — |
| `Revision`: add | ✅ | ✅ | — |
| `Corrida`: view y add | ✅ | ✅ | — |
| `Corrida`: change/delete | ✅ | — | — |
| `Respaldo`: view | ✅ | ✅ | — |
| `Respaldo`: add/change/delete | ✅ | — | — |
| `RegistroAuditoria`: view | ✅ | — | — |
| `Usuario`: add/change/delete/view | ✅ | — | — |
| `auth.Group`: view | ✅ | — | — |

- Los permisos personalizados viven en `contrataciones`:
  - `ver_pdf` en `Documento`.
  - `verificar_profesor` y `exportar_informes` en `Profesor`.
- El Administrador ve los grupos, pero no los edita, para que los roles no se desvíen de la migración.
- Sin escalamiento. Un usuario que no es superusuario no otorga `is_superuser` ni permisos sueltos: en el admin esos campos son de solo lectura, así que un POST manual se ignora. Tampoco edita, borra ni cambia la contraseña de una cuenta superusuario. Solo un superusuario gestiona superusuarios.
- Asignar Administrador o Revisor GH marca `is_staff` automáticamente (señal `m2m_changed` en `cuentas/signals.py`). Quitar el rol no lo desmarca.
- El Revisor GH no ve la auditoría (incluye inicios fallidos con nombres de usuario intentados) ni los usuarios. El historial de un profesor se mostrará en la Fase 4 desde una vista propia filtrada por objeto.
- Consulta no tiene `ver_pdf`, `view_analisis` ni `view_revision`. El análisis repite la cédula, el nombre y las observaciones de cada certificado: con `view_analisis` vería casi lo mismo que en el PDF.

## Consecuencias y reglas para fases siguientes

- **Fase 2 (motor).** Resuelve código o alias → tipo con un diccionario construido una vez por corrida desde `TipoDocumento` y `AliasTipoDocumento` (solo tipos activos).
- **Fase 3 (corridas).** Define la cancelación de corridas, con su propio permiso si hace falta. Hoy el Revisor no tiene `change_corrida`.
- **Fase 4 (estado y revisión).** Una revisión humana sigue vigente mientras el `sha256` de su análisis coincida con el `sha256` actual del documento:
  - Con "reanalizar todo" sobre un PDF sin cambios, se crea un `Analisis` nuevo, pero la aprobación anterior se conserva, porque el archivo es el mismo.
  - Si el PDF cambió, la revisión anterior deja de aplicar y el documento vuelve a necesitar revisión.
  - No hace falta ningún campo nuevo.
- **Fase 5 (informes).** El informe que exporta Consulta es una versión resumida: profesor, estado, documentos faltantes y verificación, sin cédulas por documento ni observaciones. El consolidado completo exige `view_analisis`.
- **Retención (Ley 1581, pendiente con Gestión Humana).** Llegará el momento de eliminar análisis, revisiones y registros antiguos. Se hará así:
  - Con un comando de gestión dedicado, con una excepción explícita y acotada a ese comando.
  - La purga quedará registrada en la auditoría: cuántos registros, de qué rango de fechas y quién la ejecutó.
  - No se relajarán `save()` ni `delete()` de los modelos.
  - Hasta entonces, no existe ninguna vía para saltarse la inmutabilidad.
- **Modelos y permisos nuevos.** Un modelo o permiso nuevo no se suma solo a ningún grupo. Cada fase que agregue uno lo asigna con su propia migración de datos.
