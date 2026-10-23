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

## Consecuencias

- La revisión humana y la verificación quedan trazables. Un "verificado" nunca afirma algo que ya no es cierto.
- **Pendiente de probar en un navegador real** (no lo detecta CI): la interacción entre la CSP, el iframe y el visor de PDF de Chrome y Edge. Está en la lista de `docs/prueba-usabilidad.md`.
- **Fase 4b:** pantallas de corridas (lanzar, progreso en vivo, cancelar), auditoría global (solo el Administrador) y el estado de los respaldos.
