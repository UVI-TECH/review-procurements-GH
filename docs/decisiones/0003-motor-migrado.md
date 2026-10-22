# 0003. Motor migrado: diferencias intencionales frente al legado

- **Estado:** aceptada
- **Fecha:** 2026-10-22

## Contexto

La Fase 2 reemplaza `analizar_pdf`, `construir_prompt`, `revalidar_por_cedula` y `construir_fila` de `legado/revisar_contrataciones.py` por el paquete `apps/motor/`. La meta es que, para un mismo PDF, el motor nuevo dé el mismo resultado que el legado, salvo en las diferencias que este ADR declara a propósito. El comando `comparar_con_legado` mide justo eso.

## Decisión

### Estructura

El núcleo del motor no depende del ORM: recibe el catálogo y los resultados como dataclasses. Solo `catalogo.cargar_catalogo()` lee la base de datos.

| Módulo | Qué hace |
| --- | --- |
| `resultado.py` | `ResultadoDocumento` y `Uso` (tokens de entrada, salida, lectura y creación de caché) |
| `catalogo.py` | `TipoCatalogo`, `Catalogo` y su resolvedor código/alias → tipo (solo tipos activos), construido una vez por corrida |
| `reglas.py` | Port de `norm`, `solo_digitos`, `cedula_modal` y `revalidar_por_cedula`, más `evaluar_profesor` |
| `prompts.py` | System prompt fijo, con las reglas del legado y la regla de contenido no confiable |
| `esquema.py` | Herramienta `registrar_resultado` y validación de su entrada |
| `pdf.py` | Lectura del PDF: tamaño, contraseña y número de páginas |
| `cliente_claude.py` | Cliente real con el SDK oficial |
| `simulado.py` | Cliente simulado y determinista, según el nombre del archivo |
| `servicio.py` | Elige el cliente y analiza la carpeta de un profesor |
| `comparacion.py` | Lógica del comando `comparar_con_legado` |

### Llamada a la API

- **Modelo:** por defecto `claude-haiku-4-5-20251001`, el mismo id del legado, para que la comparación sea con el mismo modelo. Se cambia con `MODELO_CLAUDE`.
- **Salida estructurada:** la herramienta `registrar_resultado` lleva `strict: true` y se fuerza con `tool_choice: {"type": "tool"}`. Haiku 4.5 admite las dos cosas. El esquema es uno solo para todos los tipos: `tiene_firma` y los datos de EPS/AFP son campos que pueden ir nulos (con `anyOf`).
  - `tipo_detectado` es un enum generado desde el catálogo activo (códigos y alias) más `"otro"`.
  - Aunque la API ya hace cumplir el esquema, la entrada se valida otra vez. Si no cumple, el resultado es ERROR, nunca una excepción.
- **Dos clases de fallo, nunca una excepción** (cambio de `fase-2-ajustes`, tras la comparación real):
  - **ERROR (transitorio):** se resuelve reanalizando. Incluye errores de la API (traducidos a "tipo + código HTTP"), timeout, conexión, rechazo (`refusal`), corte por `max_tokens`, respuesta sin la herramienta o fuera del esquema, y un archivo que no se pudo leer del disco (p. ej. OneDrive aún no lo descarga).
  - **Ilegible (permanente):** es un problema del propio documento y reanalizar no lo arregla. No es ERROR: el resultado lleva `tipo_detectado="ilegible"`, `es_valido=False` y una observación que dice qué pedir. Los casos son:
    - PDF que pide contraseña para abrirse → "PDF protegido con contraseña: solicitar un nuevo archivo sin contraseña."
    - PDF dañado o que no es un PDF → "solicitar un nuevo archivo."
    - PDF por encima del tamaño → "solicitar un archivo más liviano."
    - PDF por encima de las páginas → "solicitar un archivo solo con el certificado."
    - PDF sin páginas → "solicitar un nuevo archivo."
  - En la comparación real, un certificado de EPS con contraseña de usuario dejó al profesor en ERROR en vez de INCOMPLETO. Ese caso originó esta separación.
- **Reintentos y timeout:** los hace el SDK (`max_retries=3`: 408, 409, 429, 5xx y conexión). El timeout es de 120 s.
- **Límites del PDF** (se revisan antes de enviar; si se exceden, el documento es ilegible y no se llama a la API):
  - La API acepta 32 MB por petición y 100 páginas en modelos de 200K de contexto.
  - Como el base64 suma un tercio al tamaño, el tope del PDF es de 22 MB.
  - Las páginas se cuentan con `pypdf`.
- **La clave:** sale solo de `ANTHROPIC_API_KEY` en el entorno. No aparece en logs, mensajes de error ni resultados guardados: de los errores del SDK solo se guardan su clase y el código HTTP.
- **Cliente real bloqueado en desarrollo y pruebas:** con `MOTOR_SIMULADO=True` (fijo en los settings de pruebas) no se puede instanciar.
- **Tokens:** se registran los de entrada, salida, lectura de caché y creación de caché. `Analisis` (Fase 1) solo tiene campos para entrada y salida; la Fase 3 decide si agrega los de caché.

### Caché del prompt

El system prompt es fijo para un catálogo dado y lleva `cache_control`. Los datos del documento (archivo y profesor) van en el mensaje del usuario, así que no rompen el prefijo.

**Hoy no se cachea.** El prefijo (herramienta + system) mide unos 1.400 a 1.600 tokens, según una estimación por caracteres, y Haiku 4.5 solo cachea prefijos de 4096 tokens o más. No se infló el prompt para alcanzar el mínimo. `cache_control` se deja puesto porque empieza a funcionar sin cambios si se pasa a un modelo con un mínimo menor. `usage.cache_creation_input_tokens` lo confirmará en la validación real.

### Seguridad del contenido

Los PDFs **no son de confianza**: los suben los profesores y los generan portales de terceros.

- El system prompt declara como datos no confiables el contenido del PDF, el nombre del archivo y el de la carpeta. También ordena ignorar cualquier instrucción que aparezca en ellos.
- El nombre del archivo y el del profesor van dentro de etiquetas en el mensaje, sin los caracteres `<`, `>`, `/` ni `\`. Así no se puede cerrar la etiqueta y simular instrucciones.
- La salida va por un esquema estricto con un enum de tipos. La regla de la cédula y la revisión humana (Fase 4) siguen funcionando como controles posteriores.
- `pypdf` ha tenido CVEs de denegación de servicio con PDFs malformados. Por eso:
  - el tamaño se revisa **antes** de abrir el archivo;
  - se abre con `strict=False`;
  - cualquier excepción de `pypdf` deja el documento como ilegible;
  - los avisos con los que `pypdf` informa cada arreglo que hace a un PDF no conforme (p. ej. "Ignoring wrong pointing object") van al logger `apps.motor.pdf` en nivel DEBUG, no a la pantalla;
  - la versión queda fijada en `uv.lock`.
- **PDFs cifrados:** si `is_encrypted`, se intenta `decrypt("")`. Muchos certificados oficiales solo traen contraseña de propietario y se abren así; en ese caso se cuentan las páginas y se envían normalmente. Solo es ilegible si el PDF de verdad pide contraseña para abrirse. Para descifrar AES, que es frecuente en certificados oficiales, se instala `pypdf[crypto]` (`cryptography`).

### Estado del profesor

`evaluar_profesor` aplica este orden, del primero que se comprueba al último:

1. **SIN_DOCUMENTOS:** no hay ningún PDF.
2. **COMPLETO:** solo si se cumplen las cuatro condiciones:
   - cada tipo obligatorio tiene un documento vigente válido;
   - ningún documento vigente de un tipo activo es inválido (incluidos los no obligatorios);
   - la cédula no es ambigua;
   - no hay documentos ilegibles. COMPLETO significa que a Gestión Humana no le queda nada pendiente, y un archivo ilegible es algo pendiente: pedir uno nuevo.

   Un documento con ERROR que no es el vigente y los documentos "otro" no impiden COMPLETO; quedan señalados.
3. **ERROR:** algún documento falló y el profesor no está COMPLETO.
4. **INCOMPLETO:** falta algún tipo obligatorio.
5. **CON_PROBLEMAS:** no falta nada, pero hay un vigente inválido, la cédula es ambigua o hay un documento ilegible.

Precisiones:
- Un documento con ERROR o ilegible nunca es el vigente de ningún tipo, porque no se sabe qué tipo es. Tampoco cuenta para la cédula ni se revalida.
- Los ilegibles van en su propia lista (`ilegibles`), separados de `errores` y de `no_reconocidos`. Un profesor con solo PDFs ilegibles queda INCOMPLETO, no SIN_DOCUMENTOS: sí cargó archivos.
- Solo los tipos obligatorios cuentan como faltantes. Cualquier tipo activo cuenta para problemas.

## Diferencias intencionales frente al legado

1. **Duplicados del mismo tipo.** El legado se queda con el último documento de cada tipo. El nuevo motor se queda con el **vigente**: un válido gana sobre un inválido y, entre iguales, cuenta el más reciente (por fecha de modificación del archivo; si empatan, por nombre). Un duplicado inválido no deja al profesor CON_PROBLEMAS si hay uno válido del mismo tipo. La capa de revisiones humanas se suma en la Fase 4.
2. **Empate en la cédula modal** (por ejemplo, 2 documentos con una cédula y 2 con otra). El legado toma la primera e invalida los demás. El nuevo motor no cambia la validez de nada: ni invalida ni rescata. Agrega la observación "Cédula ambigua: requiere revisión humana." a los documentos que tienen cédula, y el profesor queda CON_PROBLEMAS (nunca COMPLETO).
3. **Tipo "otro" o desconocido.** Incluye los códigos de tipos inactivos. No cuenta para ningún requisito ni como problema, y queda señalado en `no_reconocidos`. Además, la revalidación por cédula puede invalidar un documento "otro" cuya cédula no coincide, pero **no lo rescata**: el legado lo habría marcado "Válido (verificado por cédula)", lo que confundiría al revisor.
4. **Estados detallados.** El legado solo distingue COMPLETO e INCOMPLETO (y ERROR cuando falla toda la carpeta). Los estados ERROR por documento, CON_PROBLEMAS y SIN_DOCUMENTOS son nuevos. En la comparación, el estado coincide cuando los dos motores dicen COMPLETO o los dos dicen que no, y el informe reporta aparte cuándo difiere el estado detallado (`coincide_estado_detallado`). Las diferencias de estado que la comparación real clasificó son:
   - **SIN_DOCUMENTOS frente a INCOMPLETO:** un profesor sin PDFs. El legado lo reporta como INCOMPLETO ("El profesor cargó 0 de 9 documentos"). Ninguno de los dos es COMPLETO, así que coincide en la comparación binaria, pero difiere el estado detallado.
   - **ERROR frente a INCOMPLETO** (`error_de_analisis`): un documento cuyo análisis falló de forma transitoria. El legado lo cuenta como problema y deja al profesor INCOMPLETO. El motor nuevo dice ERROR (hay que reanalizar), salvo que el profesor esté COMPLETO sin ese documento.
6. **Documentos ilegibles** (`documento_ilegible`). El legado mandaba a la API también un PDF con contraseña o dañado; la llamada fallaba y quedaba como un documento ERROR. El motor nuevo no lo envía, lo marca ilegible con una observación accionable y lo cuenta como algo pendiente, no como ERROR. En la comparación por documento, un ilegible coincide con el ERROR del legado.
5. **La firma se generaliza.** En vez de la constante `TIPO_FORMATO`, la regla se aplica a todo tipo con `requiere_firma=True`, incluidos sus alias. Con el catálogo inicial, el resultado es el mismo.

## Validación real (la hace John, nunca Claude Code)

- **`probar_motor <ruta.pdf> [--profesor NOMBRE]`:** analiza un solo PDF con la API real y muestra el resultado y los tokens.
- **`comparar_con_legado <carpeta> --limite N --salida RUTA`:** corre los dos motores sobre los primeros N profesores.
  - Carga `legado/revisar_contrataciones.py` desde su ruta y reemplaza su `client` en memoria, con la clave del entorno y un contador de tokens. El archivo no se modifica.
  - Calcula tres columnas por profesor:

    | Columna | Análisis | Reglas |
    | --- | --- | --- |
    | 1 | IA del legado | reglas del legado |
    | 2 | IA nueva | reglas del legado |
    | 3 | IA nueva | reglas nuevas |

  - La diferencia entre 1 y 2 viene del prompt o del modelo, y se reporta por documento (tipo y `es_valido`).
  - La diferencia entre 2 y 3 viene de las reglas, y se clasifica con la diferencia intencional que la explica: `duplicados`, `cedula_ambigua`, `otro`, `error_de_analisis` o `documento_ilegible`. Si ninguna la explica, queda en `diferencias_no_explicadas`.
  - En pantalla también sale `estado_detallado_difiere`: los profesores cuyo estado detallado es distinto aunque coincida COMPLETO / no COMPLETO (p. ej. INCOMPLETO frente a ERROR).
  - El informe detallado lleva datos reales: se escribe en JSON en `--salida`, y el comando rechaza una ruta dentro del repositorio. En pantalla solo salen conteos.
  - Gasta tokens de los dos motores.
- **Ambos comandos se niegan a correr** con los settings de pruebas (`ES_ENTORNO_DE_PRUEBAS`) o con `MOTOR_SIMULADO=True`. Si faltan migraciones, se detienen con "Ejecuta manage.py migrate primero" en lugar de un traceback.
- **Resultado de la primera comparación real** (5 profesores, 38 documentos): el tipo y `es_valido` coincidieron en 38 de 38 documentos, el estado fue coherente en 5 de 5 y hubo 0 diferencias no explicadas. Los ajustes que salieron de ahí están en esta revisión del ADR.

## Consecuencias y notas para fases siguientes

- **Fase 3:**
  - El worker procesa cada documento con un tiempo límite, para que un PDF que cuelgue a `pypdf` no bloquee toda la corrida.
  - Decide si `Analisis` guarda los tokens de caché.
  - Guarda en `Analisis` el `tipo_detectado` normalizado y la `respuesta_cruda`.
  - **Un documento ilegible también se guarda como `Analisis`**, con `tipo_detectado="ilegible"` y su observación. Así, en la Fase 4 un revisor puede crearle una `Revision` y descartarlo cuando sea un duplicado de algo que ya está bien. Sin `Analisis` no hay a qué colgar la revisión, y el profesor quedaría CON_PROBLEMAS para siempre.
  - **Fallos transitorios que se repiten:** el rechazo del modelo y la respuesta fuera del esquema son transitorios en principio, pero pueden repetirse con el mismo archivo. Si el mismo `sha256` falla de forma transitoria en 2 corridas seguidas, deja de reintentarse automáticamente y pasa a revisión humana con su observación, para no gastar tokens en un bucle.
- **Si se cambia de modelo:** en Claude Opus 5.5 y Sonnet 5.5, el `tool_choice` forzado responde 400. Ahí hay que usar `tool_choice: auto` con `strict: true` y una instrucción en el prompt, o salidas estructuradas (`output_config.format`). También cambian el mínimo de caché y los límites de páginas.
- **Códigos reservados:** `otro`, `ilegible` (motor) y `error` (legado) no se pueden usar como código ni alias del catálogo, sin distinguir mayúsculas. Lo impiden `clean()` de `TipoDocumento` y `AliasTipoDocumento` y un `CheckConstraint` en la base de datos (migración `contrataciones/0003_codigos_reservados`). Si ya existiera un tipo o alias con alguno de esos códigos, la migración se detiene con un mensaje claro y no lo renombra, porque el código puede estar en revisiones históricas.
- **Archivo que no se pudo leer del disco:** es ERROR transitorio, no ilegible (p. ej. un archivo de OneDrive aún no descargado). En producción, la carpeta se mantiene siempre en el dispositivo (plan, Fase 7), así que este ERROR queda como respaldo.
- **Fuera de alcance:** el cliente simulado sigue convenciones de nombre de archivo (documentadas en `simulado.py`) que solo sirven para desarrollo y pruebas.
