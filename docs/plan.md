# Revisión de Contrataciones — Plan y estructura del proyecto

Oct 21, 2026 · @John Doe

## Contexto y objetivo

La herramienta pasa de un programa de escritorio para un usuario a una app web en Django que corre en un PC de Gestión Humana (localhost), preparada desde ya para varios usuarios y para moverse a un servidor.

**Hoy.** El motor `revisar_contrataciones.py` y la interfaz tkinter `revisar_contrataciones_gui.py` se compilan a un `.exe` con PyInstaller. El programa lee una carpeta por profesor desde OneDrive sincronizado y analiza cada PDF con Claude (Haiku 4.5) contra 9 tipos de documento. Luego cruza la identidad por cédula y genera un Excel que se sobrescribe en cada corrida.

**Limitaciones actuales:**

- La API key está escrita en el código y queda dentro del `.exe`.
- Cada corrida reprocesa todos los PDFs, aunque no hayan cambiado.
- No hay historial, revisión humana ni registro de quién hizo qué.
- Solo lo usa una persona en un equipo.

**Meta del MVP:** tablero de profesores, detalle con visor de PDF, revisión humana con trazabilidad, procesamiento incremental, informes en Excel y respaldos cifrados en OneDrive. n8n deja de participar en este flujo.

## Decisiones tomadas

El stack es Django 5.2 LTS + HTMX + SQLite, en un solo PC, sin servidores ni servicios pagos adicionales.

| Decisión | Elección | Motivo |
| --- | --- | --- |
| Framework | Django 5.2 LTS + HTMX | Reutiliza el motor en Python; trae usuarios, permisos, admin y protección CSRF |
| Base de datos | SQLite; PostgreSQL al pasar a servidor | Un solo archivo, sin instalación; el cambio futuro es de configuración |
| Dónde corre | PC de Gestión Humana con Windows, administrado por soporteDITC | No hay servidor institucional disponible; AWS descartado por costos |
| Servidor web | Waitress, escuchando solo en 127.0.0.1:8000 | Funciona en Windows; nadie en la red alcanza el puerto |
| Segundo plano | Worker propio (comando de Django) que toma trabajos de la BD | Sin Redis ni Celery, que no funciona bien en Windows |
| Fuente de PDFs | Carpeta de OneDrive sincronizada en el PC | Igual que hoy; se deja una capa para leer por Microsoft Graph en el futuro |
| Respaldo | Copia cifrada de la BD a una carpeta de OneDrive/SharePoint | Sin costo; John valida con el mismo proyecto en su equipo |
| Usuarios | Usuarios y roles desde el inicio (1 usuario de GH + administrador) | Listo para multiusuario sin rediseño |
| Dependencias | uv (`pyproject.toml` + `uv.lock`) | Entornos idénticos en Fedora y Windows |
| Repositorio | GitHub privado de la oficina, sin secretos ni datos reales | Control de versiones y trabajo con Claude Code |
| Desarrollo | Fedora + Claude Code en terminal | Entorno actual de John |
| n8n | Fuera de este flujo | Menos sistemas tocando datos de Gestión Humana |

## Arquitectura local

Todo corre en el PC de Gestión Humana: el navegador habla con Django en localhost y el worker procesa en segundo plano. Solo salen los PDFs hacia la API de Claude y los respaldos cifrados hacia OneDrive.

&#91;embedded content: arquitectura local · 8 componentes\]

Django y el worker no se llaman entre sí: Django deja los trabajos en la base de datos y el worker los toma de ahí, así que cerrar el navegador no detiene una corrida.

## Usuarios y roles

Tres roles desde el inicio, implementados con grupos y permisos de Django y creados por una migración de datos para que existan igual en todos los entornos.

| Rol | Quién (hoy) | Puede |
| --- | --- | --- |
| Administrador | John (TI) | Todo: usuarios, configuración, catálogo de documentos, corridas, respaldos y auditoría |
| Revisor GH | La persona de Gestión Humana | Lanzar corridas, ver tablero y PDFs, aprobar, rechazar o corregir documentos, verificar profesores, exportar informes |
| Consulta | Nadie aún (futuro: directivos, auditoría) | Ver tablero e informes resumidos, sin modificar nada. No ve PDFs, análisis ni revisiones, porque repiten datos personales |

La matriz completa de permisos está en `docs/decisiones/0002-modelo-de-datos-y-roles.md`.

- Login con usuario y contraseña locales, con los validadores de contraseña de Django.
- La sesión expira tras 30 minutos de inactividad.
- Al pasar a servidor se agrega login con Entra ID (cuentas institucionales); exige HTTPS, por eso queda para esa etapa.

## Modelo de datos

Nueve entidades (detalle y motivos en `docs/decisiones/0002-modelo-de-datos-y-roles.md`). Cada análisis de la IA se guarda y nunca se sobrescribe, y la revisión humana prevalece sobre la IA.

**Ubicación:** `contrataciones` tiene el catálogo, `Profesor`, `Documento`, `Analisis`, `Revision` y `Corrida`; `cuentas` tiene `Usuario` y `RegistroAuditoria`; `respaldos` tiene `Respaldo`. `motor` y `corridas` no tienen modelos.

| Entidad | Campos clave | Para qué |
| --- | --- | --- |
| TipoDocumento | codigo, etiqueta, obligatorio, activo, orden, requiere\_firma | Catálogo de los 9 requisitos, editable desde el admin por el Administrador. `activo=False` retira un tipo sin perder su historial |
| AliasTipoDocumento | tipo, codigo (único) | Códigos alternos, como `examen_medico_laboral_dotc` → certificado médico; se editan dentro del tipo |
| Profesor | carpeta (única), nombre, cedula (texto, detectada), estado, verificado\_por, verificado\_en, carpeta\_presente | Uno por carpeta. Si la carpeta desaparece, `carpeta_presente=False` y conserva su último estado |
| Documento | profesor, ruta\_relativa (única por profesor), nombre\_archivo, sha256, tamano, modificado\_en, presente, reintentos\_agotados | Un PDF; el hash evita reanalizar lo que no cambió. Si desaparece se marca `presente=False`; nunca se borra |
| Analisis | documento, corrida, sha256, modelo, tipo\_detectado, es\_valido, numero\_documento, nombre\_persona, tiene\_firma, datos\_extra (JSON), observaciones, respuesta\_cruda (JSON), tokens\_entrada, tokens\_salida, tokens de caché | Resultado de la IA para un documento. Inmutable. Un fallo transitorio se guarda con `tipo_detectado="error"` y un archivo ilegible con `"ilegible"` |
| Revision | analisis, usuario, decision (aprobado / rechazado / corregido), tipo\_corregido, comentario, fecha | Decisión humana sobre un análisis. Inmutable: cambiar de opinión crea otra y prevalece la más reciente |
| Corrida | iniciada\_por, alcance (todos / nuevos y modificados / un profesor) y profesor, estado (pendiente / en proceso / completada / fallida / cancelada), inicio, fin, totales, errores, tokens, latido, cancelación solicitada | Un procesamiento y su progreso |
| RegistroAuditoria | usuario (nulo si es el sistema), accion, objeto (ContentType + id), detalle (JSON), fecha | Quién vio, aprobó o cambió qué. Solo se agregan filas |
| Respaldo | fecha, ruta, tamano, sha256, origen, estado | Historial de copias de seguridad |

**Documento vigente por tipo.** Si un profesor tiene varios PDFs del mismo tipo, cuenta en este orden: el aprobado por un revisor, luego el válido según la IA y, por último, el más reciente.

**Historial protegido:** `on_delete=PROTECT` en todo el historial; nada borra en cascada lo de un profesor. Una revisión sigue vigente mientras el sha256 de su análisis coincida con el del documento.

**Estado del profesor (calculado):** SIN ANALIZAR (inicial), COMPLETO, INCOMPLETO (faltan tipos obligatorios), CON PROBLEMAS (hay documentos inválidos), SIN DOCUMENTOS o ERROR. Se calcula desde la Fase 4. La verificación humana va aparte: pendiente, o verificado por quién y cuándo.

## Migración del motor actual

La lógica de validación se conserva; cambia cómo se llama a la API, dónde se guardan los resultados y quién decide al final.

| Hoy | Módulo nuevo | Cambio |
| --- | --- | --- |
| `construir_prompt`, `ESQUEMAS` | `motor/prompts.py`, `motor/esquema.py` | Se arma desde el catálogo; las instrucciones fijas van en el system prompt con `cache_control` (con Haiku 4.5 no alcanza el mínimo cacheable; ver ADR 0003) |
| `analizar_pdf` | `motor/cliente_claude.py`, `motor/pdf.py` | Respuesta por una herramienta estricta y forzada, validada contra el esquema; desaparece la limpieza de marcas de código. El tamaño y las páginas del PDF se revisan antes de enviar |
| `analizar_con_reintentos` | `motor/cliente_claude.py` | Reintentos del SDK con espera creciente; respeta límites de velocidad (HTTP 429) |
| `revalidar_por_cedula`, `cedula_modal`, `norm` | `motor/reglas.py` | Funciones puras con pruebas; la lógica solo cambia en las diferencias intencionales del ADR 0003 |
| `construir_fila`, `fmt*` | `motor/reglas.py` (`evaluar_profesor`) y `contrataciones/servicios/estado.py` | Estado calculado con la regla del documento vigente; en la Fase 4 se suman las revisiones humanas desde la BD |
| `fila_sin_documentos`, `fila_error` | Estados SIN DOCUMENTOS y ERROR | Dejan de ser filas de Excel |
| `escribir_excel` | `reportes/excel.py` | Se genera bajo demanda y con filtros; conserva las 17 columnas actuales |
| `ejecutar` y la GUI tkinter | `corridas/` (worker) y vistas web | Se reemplazan |

**Correcciones incluidas:**

1. API key fuera del código, en `.env`. La clave actual se rota porque viaja dentro del `.exe`.
2. Procesamiento incremental por hash SHA-256: solo se analizan PDFs nuevos o modificados, con opción de reanalizar todo.
3. Regla de documento vigente para los duplicados del mismo tipo (ver Modelo de datos), en vez de quedarse con el último.
4. Modo simulado (`MOTOR_SIMULADO=True`): respuestas de prueba sin llamar a la API, para desarrollar y probar sin costo.
5. Inyección de prompt: el contenido del PDF se trata como dato no confiable. Se declara así en el system prompt, la salida va por esquema, y la regla de cédula y la revisión humana sirven de control.
6. Registro de tokens por análisis para conocer el costo de cada corrida.
7. Modelo configurable en settings (hoy `claude-haiku-4-5`).

## Pantallas del MVP

Ocho pantallas. El progreso de las corridas se actualiza en vivo con HTMX, consultando cada 2 segundos.

| Pantalla | Rol | Qué hace |
| --- | --- | --- |
| Inicio de sesión | Todos | Usuario y contraseña |
| Tablero | Revisor, Consulta | Totales por estado; tabla de profesores con semáforo en los 9 tipos; filtros por estado, tipo faltante y verificación; búsqueda por nombre o cédula |
| Detalle del profesor | Revisor | Documentos con el resultado de la IA y el PDF al lado; aprobar, rechazar o corregir el tipo con comentario; marcar al profesor como verificado; historial |
| Corridas | Revisor, Administrador | Lanzar (todos, solo nuevos o modificados, un profesor); progreso en vivo; cancelar; historial con totales, errores y tokens |
| Informes | Revisor, Consulta | Excel consolidado con el formato actual y Excel de faltantes por profesor; más adelante, informe individual en PDF |
| Respaldos | Administrador (el revisor ve el estado) | Último respaldo y su estado, respaldar ahora, historial |
| Configuración | Administrador | Carpeta raíz, carpeta de respaldos, modelo, pausa entre llamadas; catálogo de tipos desde el admin de Django |
| Auditoría | Administrador | Consulta y filtro del registro de acciones |

## Respaldos y validación de la información

Cada copia es consistente, va cifrada y llega sola a OneDrive. John la abre con el mismo proyecto en su equipo, en modo solo lectura.

**Cómo se genera cada respaldo:**

1. Copia con la función de backup de SQLite, no copiando el archivo, para que no quede corrupta si la app está escribiendo.
2. Compresión ZIP cifrada con AES-256 (`pyzipper`). La clave va en `.env` (`CLAVE_RESPALDO`) y se guarda aparte.
3. Se deja en una carpeta sincronizada configurable, idealmente en un sitio de SharePoint de Gestión Humana compartido con John.

**La base de datos nunca va dentro de una carpeta sincronizada por OneDrive.** La sincronización con el modo WAL activo (archivos `-wal` y `-shm`) puede corromperla. Solo los respaldos van a OneDrive. La app se niega a arrancar si `RUTA_BASE_DATOS` cae dentro de `CARPETA_CONTRATACIONES`.
4. Se comprueba: se abre la copia, se ejecuta `PRAGMA integrity_check` y se registra su hash.

**Cuándo:** al terminar cada corrida; al abrir la app si el último respaldo tiene más de 24 horas; con una tarea programada de Windows en la noche; y con el botón manual.

**Retención:** los últimos 14 diarios y 12 mensuales; los demás se borran.

**Validación en el equipo de John (Fedora):**

- El comando `importar_respaldo <archivo.zip>` descifra la copia y la deja como base de datos local.
- Con `MODO_SOLO_LECTURA=True` (settings `validacion.py`) se bloquean las escrituras y las llamadas a la API, y se ocultan los botones de acción.
- Los PDFs no viajan en el respaldo. El visor muestra "no disponible" salvo que John tenga acceso de lectura a la carpeta de Contrataciones y la configure.

**Restauración en el PC de Gestión Humana:** el comando `restaurar_respaldo` guarda primero una copia de la base actual y luego restaura.

## Seguridad

La app no se expone a la red. Los secretos y los datos reales nunca entran al repositorio, y cada acceso a un PDF pasa por sesión y permisos.

- **Secretos:** `ANTHROPIC_API_KEY`, `DJANGO_SECRET_KEY` y `CLAVE_RESPALDO` en `.env`. El repositorio solo lleva `.env.example`. `.gitignore` excluye `.env`, `*.db`, respaldos y archivos subidos. Pre-commit con gitleaks bloquea cualquier commit con secretos.
- **Datos de prueba:** PDFs sintéticos y cédulas ficticias; nunca documentos reales de Gestión Humana en el repositorio.
- **Red:** Waitress solo en `127.0.0.1:8000`, `DEBUG=False` en producción y `ALLOWED_HOSTS` limitado a localhost.
- **PDFs:** se sirven únicamente por una vista que exige sesión y permiso, nunca como archivos estáticos. La ruta se valida para que no pueda salirse de la carpeta raíz.
- **Equipo:** BitLocker activo, cuenta de Windows dedicada, bloqueo de pantalla y actualizaciones, coordinado con soporteDITC.
- **Aplicación:** protección CSRF, expiración de sesión, validadores de contraseña y registro de auditoría.
- **Dependencias:** revisión periódica con `pip-audit` y parches de seguridad de Django 5.2 LTS.
- **Datos personales (Ley 1581 de 2012):** acceso solo para personal autorizado. La política de retención se define con Gestión Humana. El envío de los PDFs a la API de Anthropic ya ocurre hoy y debe quedar documentado.

## Estructura del repositorio

Seis apps de Django con responsabilidades separadas. El motor no depende de la interfaz, así que se prueba solo y se reutiliza en el futuro servidor.

```text
revision-contrataciones/
├── CLAUDE.md                  # contexto y reglas para Claude Code
├── README.md
├── pyproject.toml
├── uv.lock
├── .python-version            # 3.12
├── .env.example
├── .gitignore
├── .pre-commit-config.yaml    # gitleaks + ruff
├── .claude/settings.json      # niega leer .env, bases de datos y respaldos
├── .github/workflows/ci.yml   # gitleaks, ruff y pruebas (Ubuntu; Windows en PR/main)
├── manage.py
├── config/
│   ├── entorno.py             # carga el .env antes de elegir los settings
│   ├── settings/
│   │   ├── base.py
│   │   ├── desarrollo.py      # Fedora, motor simulado
│   │   ├── produccion.py      # PC de Gestión Humana
│   │   ├── validacion.py      # equipo de John, solo lectura
│   │   └── pruebas.py         # pytest: motor simulado fijo, SQLite en memoria
│   ├── urls.py
│   └── wsgi.py
├── apps/
│   ├── comun/                 # utilidades compartidas, sin modelos (modelos inmutables)
│   ├── cuentas/               # usuarios, roles, auditoría
│   ├── contrataciones/        # profesores, documentos, catálogo, revisiones, tablero
│   ├── motor/                 # prompts, cliente Claude, reglas, fuentes de documentos
│   ├── corridas/              # cola de trabajos y worker
│   ├── reportes/              # Excel e informes
│   └── respaldos/             # copia, cifrado, retención, restauración
├── templates/
├── static/
├── tests/
│   └── fixtures/              # PDFs y respuestas sintéticas
├── scripts/
│   └── windows/
│       ├── instalar.ps1
│       ├── iniciar.bat        # arranca web + worker y abre el navegador
│       └── tarea_respaldo.xml # tarea programada nocturna
├── legado/                    # scripts actuales como referencia, sin API key
└── docs/
    ├── arquitectura.md
    ├── despliegue-windows.md
    ├── operacion.md           # respaldos, restauración, actualizaciones
    └── decisiones/            # registros de decisiones (ADR)
```

**Comandos de gestión:** `escanear` (detecta nuevos y modificados), `crear_corrida` (con `--en-seco`), `cancelar_corrida`, `worker`, `respaldar`, `restaurar_respaldo`, `importar_respaldo`. Para validar el motor con la API real (solo John, en su terminal): `probar_motor` y `comparar_con_legado`.

**Fuentes de documentos (`motor/fuentes.py`):** `FuenteCarpetaLocal` ahora; `FuenteGraph` cuando haya servidor, con la misma interfaz.

## Plan por fases

Siete fases hasta reemplazar el `.exe`, cada una con un criterio de aceptación verificable antes de pasar a la siguiente. La fase 8 queda para cuando exista servidor.

0. **Base del repositorio.** uv, Django 5.2, settings por entorno, `.env`, pre-commit con gitleaks, `CLAUDE.md`, GitHub Actions con pruebas y ruff.
   - Criterio: `manage.py check` y las pruebas pasan en CI; gitleaks no encuentra secretos.
1. **Modelo de datos, roles y admin.** Modelos y migraciones, catálogo de 9 tipos sembrado, grupos y permisos, auditoría.
   - Criterio: desde el admin se gestionan catálogo y usuarios; hay pruebas de permisos por rol.
2. **Motor migrado.** Prompts desde el catálogo, cliente con tool use y caching, reglas puras, modo simulado.
   - Criterio: pruebas que reproducen los casos actuales (extranjero sin nombre, cédula de otra persona, formato sin firma, DOTC → certificado médico, duplicados). Un mismo PDF real da el mismo resultado que la versión actual.
3. **Escaneo y corridas.** Escaneo por hash, worker, alcance de corrida, progreso, cancelación y reanudación (decisiones en `docs/decisiones/0004-escaneo-y-corridas.md`).
   - Criterio: una segunda corrida sin cambios no llama a la API; si se cierra la app a mitad, al reanudar no se duplica trabajo.
4. **Interfaz.** Tablero, detalle con visor de PDF, revisión humana, verificación y auditoría.
   - Criterio: la persona de Gestión Humana completa una revisión sin ayuda, y cada acción queda registrada.
5. **Informes.** Excel consolidado y Excel de faltantes.
   - Criterio: para la misma carpeta, el consolidado coincide columna a columna con el Excel actual.
6. **Respaldos y validación.** Copia cifrada, retención, verificación, importar, restaurar y modo solo lectura.
   - Criterio: el respaldo restaurado en el equipo de John muestra los mismos datos; un respaldo dañado se detecta.
7. **Despliegue en el PC de Gestión Humana.** `instalar.ps1`, `iniciar.bat`, arranque automático, manual de operación y piloto en paralelo con el `.exe`.
   - Criterio: durante el piloto, los mismos resultados que el `.exe` sobre la misma carpeta. Luego se retira el `.exe` y se rota la API key (antes, si el `.exe` circuló fuera de Gestión Humana).
   - Base de datos: en una carpeta local, nunca en OneDrive (ver `docs/despliegue-windows.md`).
   - OneDrive: en el PC de Gestión Humana, la carpeta Contrataciones se configura como **"Mantener siempre en este dispositivo"**, para que el worker no dependa de descargas bajo demanda. El ERROR por un archivo que no se pudo leer del disco queda como respaldo, no como el caso normal.
8. **Futuro, con servidor.** PostgreSQL, Docker, login con Entra ID, lectura por Graph desde SharePoint, Message Batches API para cargas masivas y notificaciones.

## Skills de Claude Code por fase

De la lista disponible, estas son las que aportan en cada fase. Los prompts para Claude Code se construyen después, partiendo de este documento y de `CLAUDE.md`.

| Fase | Skills | Para qué |
| --- | --- | --- |
| Antes de la fase 0 | grill-me, spec-driven-workflow, senior-architect | Cuestionar este plan y convertirlo en especificación |
| 0 Base | init, env-secrets-manager, ci-cd-pipeline-builder | `CLAUDE.md`, manejo de `.env` y gitleaks, GitHub Actions |
| 1 Datos y roles | database-schema-designer, senior-backend | Modelos, índices, migraciones y permisos |
| 2 Motor | claude-api, senior-prompt-engineer, tdd-guide, llm-cost-optimizer | Uso correcto del SDK (tool use, caching), pruebas primero, costo por corrida |
| 3 Corridas | senior-backend, focused-fix | Worker, concurrencia con SQLite y reanudación |
| 4 Interfaz | frontend-design, senior-frontend, a11y-audit, ux/ui | Tablero y detalle con HTMX; accesibilidad |
| 5 Informes | xlsx | Formato del Excel |
| 6 Respaldos | senior-devops, runbook-generator | Respaldo, restauración y su procedimiento |
| 7 Despliegue | runbook-generator, docx | Manual de instalación y operación para soporteDITC y Gestión Humana |
| Transversal | security-review, ai-security, dependency-auditor, code-review, clean-code, karpathy-check | Seguridad (incluida la inyección de prompt en los PDFs), dependencias y calidad del código |
| 8 Futuro | docker-development, migration-architect, ms365-tenant-manager | Contenedores, paso de SQLite a PostgreSQL, registro de la app en Entra ID |

## Pendientes y preguntas abiertas

- [ ] Confirmar el PC de Gestión Humana: versión de Windows, RAM, OneDrive sincronizado con la carpeta Contrataciones y permisos de soporteDITC para instalar Python y uv.
- [ ] Crear o elegir la carpeta de respaldos en un sitio de SharePoint de Gestión Humana compartido con John. Respuesta: lo hace jhon en su debido momento
- [ ] Definir quién custodia la clave de los respaldos, además de John.
- [ ] Confirmar quién administra y paga la API key de Anthropic, y programar su rotación. Respuesta: lo gestiona GH yo tengo el acceso de admin tambien
- [ ] Definir con Gestión Humana la política de retención de documentos y análisis.
- [ ] Decidir si se importan los Excel históricos a la base de datos.
- [ ] Crear el repositorio privado en la organización de GitHub de la oficina y definir accesos (Felipe, profesor Héctor).Respuesta: repositorio creado, los accesos ya estan definidos en la organizacions: git remote add origin <https://github.com/UVI-TECH/review-procurements-GH.git>

  git branch -M main

  git push -u origin main
