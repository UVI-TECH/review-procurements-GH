# 0005. Revisión humana, verificación e interfaz (Fase 4a)

- **Estado:** aceptada
- **Fecha:** 2026-10-23

## Contexto

La Fase 4a agrega la interfaz web y la capa de revisión humana sobre el motor (ADR 0003) y las corridas (ADR 0004). La persona de Gestión Humana debe poder:

- encontrar profesores incompletos o con problemas;
- ver cada PDF;
- decidir sobre cada documento;
- verificar al profesor cuando todo está en orden.

Todo debe quedar en la auditoría, y nada debe salir del equipo.

## Decisión

### Resultado efectivo de un documento

- **Revisión vigente:** la última `Revision` cuyo `analisis.sha256` coincide con el sha256 actual del documento (ADR 0002). Si el archivo cambió, la revisión deja de aplicar.
- **La revisión prevalece sobre la IA y sobre la regla de la cédula:**

| Decisión | Efecto |
| --- | --- |
| Aprobado | Válido, con el tipo de la IA |
| Corregido | Válido, con `tipo_corregido` |
| Rechazado | Inválido |
| Descartado (nueva) | No cuenta para nada: ni como requisito ni como problema. Sirve para duplicados ilegibles, documentos "otro" irrelevantes, etc. |

- **Reglas sobre las decisiones:**
  - El comentario es obligatorio salvo al aprobar.
  - No se puede **aprobar** un documento sin tipo del catálogo ("otro", "ilegible" o "error"): se corrige el tipo, se rechaza o se descarta.
  - Aprobar o corregir un documento cuya cédula no coincide con la del profesor **exige comentario**. La interfaz muestra las dos cédulas.
- **Documento vigente por tipo:** primero el aprobado o corregido por un revisor, luego el válido según la IA, y por último el más reciente.
- **Cédula del profesor:**
  - La modal y la ambigüedad se calculan **sin los documentos rechazados ni descartados**, porque no son evidencia confiable de la identidad.
  - Un revisor puede **confirmar la cédula del profesor** (queda quién y cuándo). Si existe, la revalidación compara contra ella en lugar de la modal, y la ambigüedad queda resuelta. Es la salida para el caso 2 contra 2.

### Verificación

- Solo se verifica un profesor en estado COMPLETO.
- Al verificar se guarda una **huella**: el hash de (ruta, sha256, id de la revisión vigente o "sin revisión") de cada documento presente, más la cédula confirmada.
- **Regla:** la verificación está **vigente** si la huella guardada coincide con la actual **y** el estado es COMPLETO. En cualquier otro caso está **desactualizada**. No se borra: quién y cuándo verificó queda en el profesor y en la auditoría.
- **No vuelve a quedar vigente sola:** cualquier revisión nueva, cambio de archivo o confirmación de cédula cambia la huella. Por ejemplo, si un documento se rechaza y luego se aprueba de nuevo, la verificación sigue desactualizada aunque el estado vuelva a COMPLETO.
- **Cuándo se recalcula la huella:** al crear una revisión, al terminar cada profesor en el worker, al confirmar la cédula y en el escaneo, cuando cambian los archivos.
- **Para el tablero,** `Profesor` guarda la huella actual, un resumen por tipo y la marca "requiere atención" (ilegibles, cédula ambigua o reintentos agotados). Así se filtra en la base de datos sin recalcular a cada profesor.

### Interfaz

- **Pantallas:**
  - **Tablero** (requiere `view_profesor`): Revisor y Consulta.
  - **Detalle** (requiere `view_analisis`): Revisor y Administrador. Consulta nunca llega al detalle ni al PDF.
- **En el tablero, Consulta no ve las cédulas** ni puede buscar por ellas: la búsqueda por dígitos revelaría a quién pertenece una cédula. Lo encontró la revisión de seguridad de la rama.
- **Permisos de las acciones:**
  - revisar: `add_revision`;
  - verificar y confirmar la cédula: `verificar_profesor`;
  - ver el PDF: `ver_pdf`.
- **Visor de PDF:**
  - Exige sesión y `ver_pdf`, y resuelve la ruta con la fuente (sin path traversal).
  - Responde en línea, con `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN` y la CSP `frame-ancestors 'self'`.
  - Registra `pdf_visto` en la auditoría.
  - Se muestra con el visor nativo del navegador, en un iframe del mismo origen.
- **HTMX:**
  - Viene de `static/vendor/`, y una prueba fija su hash SRI.
  - Se configura con `includeIndicatorStyles: false`, `allowEval: false` (sin `hx-on`, filtros de eventos ni `js:`), `historyCacheSize: 0` (no guarda páginas con datos de Gestión Humana en el `localStorage`), `allowScriptTags: false`, `selfRequestsOnly: true` y `historyRestoreAsHxRequest: false`.
  - Las vistas que responden un fragmento o la página completa según `HX-Request` llevan `Vary: HX-Request`.
  - El token CSRF va en `hx-headers` del `<body>`, así que la cookie CSRF puede ser `HttpOnly`.
- **Cabeceras de toda página** (middleware `CabecerasDeSeguridad`):
  - `Cache-Control: no-store`;
  - una CSP estricta: `default-src 'self'`, sin scripts ni estilos en línea, `frame-src 'self'` para el visor y `frame-ancestors 'self'`.
  - El admin de Django queda fuera de la CSP, porque usa atributos `style`.
- **Estáticos en producción:** los sirve WhiteNoise, con `CompressedManifestStaticFilesStorage`, porque Waitress no sirve estáticos.
- **Inicio de sesión:** login y logout propios. Se auditan el inicio, el cierre y el fallo; en el fallo, sin usuario y con el nombre intentado en el detalle (ADR 0002). La sesión expira tras 30 minutos de inactividad.
- **Diseño:** un expediente sobrio.
  - Fuente Atkinson Hyperlegible Next, desde `static/vendor/fonts/` con su `OFL.txt`, con `font-display: swap` y Segoe UI como respaldo.
  - Los colores son variables CSS: pasar a los colores institucionales solo cambia `:root`.
  - Contraste AA en todo par de color (el mínimo medido es 6,04:1).
  - El semáforo siempre lleva ícono y texto, no solo color.
  - Foco visible, enlace para saltar al contenido, etiquetas en todos los campos.
- **Datos de demostración:** `sembrar_demo` genera unos 30 profesores ficticios ("DEMO …", cédulas que empiezan por 999) en una carpeta vacía y los procesa con el motor simulado. Se niega a correr con el motor real, en producción o sobre una carpeta con contenido.

### No se impide analizar a profesores incompletos

El legado tenía una regla que no analizaba a un profesor hasta que su carpeta estuviera completa. **No se migra:** no hay filtro que impida analizar a un profesor incompleto. Razones:

- Con el procesamiento incremental (ADR 0004), cada archivo se analiza una sola vez por sha256. Analizar temprano no gasta créditos de más: lo ya analizado no se repite cuando llegan los documentos que faltaban.
- Sin análisis no se sabe qué falta. La carpeta puede tener los nueve archivos y aun así estar incompleta (un documento ilegible, de otro tipo o de otra persona), o tener menos archivos y ya cumplir los obligatorios.

Lo que sí se distingue es el documento **pendiente de análisis**: un documento presente cuyo sha256 actual aún no tiene `Analisis`. Se muestra como tal en el detalle, no como error ni como faltante. El tablero indica cuántos tiene cada profesor y permite filtrar por ellos. Se calcula al consultar, no se guarda, porque el escaneo agrega documentos sin recalcular el resumen. Un documento cuyo único análisis es un error no está pendiente: se muestra como error y se reanaliza.

### Ajustes tras la prueba técnica y el ensayo de usabilidad

- **Páginas de error** 403, 404, 500 y de CSRF propias, en español, con el enlace al tablero. La 500 no hereda de `base.html` ni usa la petición, para mostrarse aunque falle lo demás. La 404 no repite la ruta pedida.
- **Avisos flotantes ("toasts")** en lugar de los mensajes en la cabecera, con JavaScript propio en `static/js/app.js`:
  - sin librerías, sin `eval` ni `innerHTML`: el texto entra con `textContent`;
  - se cierran solos (6 s; 12 s los de error), se pausan mientras el puntero o el foco están encima, y se cierran a mano o con Escape;
  - una región `aria-live="polite"` presente desde la carga los anuncia;
  - sin JavaScript, los mensajes quedan visibles en la página.
  - En una respuesta a HTMX, el middleware `AvisosHtmx` pasa los mensajes pendientes al encabezado `HX-Trigger` como el evento `avisos`, para que un fragmento no los pierda.
- **Tooltip de los encabezados verticales:** el nombre completo del tipo aparece al pasar el mouse y al recibir el foco del teclado (`:focus-within`), y Escape lo oculta (WCAG 1.4.13). Lleva `aria-hidden`, porque el lector de pantalla ya lee el encabezado completo.
- **Documento elegido:** la lista y el panel se reemplazan juntos (`_espacio.html`), así que el resaltado (`aria-current` y color) sigue al documento elegido. El `id` del enlace le permite a HTMX conservar el foco.
- **Pruebas de navegador** con Playwright y Chromium real, solo en CI (job `navegador`):
  - cubren el login, el tablero, el detalle con el PDF en el iframe y una revisión;
  - fallan ante cualquier violación de CSP, error de JavaScript, petición fallida o respuesta >= 400.
  - Localmente se excluyen: el sandbox de Claude Code no tiene acceso a la descarga del navegador, y no se amplía.

## Consecuencias

- La revisión humana y la verificación quedan trazables. Un "verificado" nunca afirma algo que ya no es cierto.
- **Probado en un navegador real:** la interacción entre la CSP, el iframe y el visor de PDF pasó la prueba técnica manual, y desde los ajustes la revisa en cada PR el job `navegador` de CI (Chromium). Edge queda para la prueba manual de `docs/prueba-usabilidad.md`.
- **Fase 4b:** pantallas de corridas (lanzar, progreso en vivo, cancelar), auditoría global (solo el Administrador) y el estado de los respaldos.
