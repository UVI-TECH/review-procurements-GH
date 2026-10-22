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
- **Errores que terminan en ERROR, no en excepción:** errores de la API (traducidos a "tipo + código HTTP"), rechazo (`refusal`), corte por `max_tokens` y respuesta sin la herramienta.
- **Reintentos y timeout:** los hace el SDK (`max_retries=3`: 408, 409, 429, 5xx y conexión). El timeout es de 120 s.
- **Límites del PDF** (se revisan antes de enviar; si se exceden, ERROR sin llamar a la API):
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
  - cualquier excepción de `pypdf` se convierte en ERROR;
  - la versión queda fijada en `uv.lock`.
- **PDFs cifrados:** si `is_encrypted`, se intenta `decrypt("")`. Muchos certificados oficiales solo traen contraseña de propietario y se abren así; en ese caso se cuentan las páginas y se envían normalmente. Solo es ERROR si el PDF de verdad pide contraseña para abrirse. Para descifrar AES, que es frecuente en certificados oficiales, se instala `pypdf[crypto]` (`cryptography`).

### Estado del profesor

`evaluar_profesor` aplica este orden, del primero que se comprueba al último:

1. **SIN_DOCUMENTOS:** no hay ningún PDF.
2. **COMPLETO:** solo si se cumplen las tres condiciones:
   - cada tipo obligatorio tiene un documento vigente válido;
   - ningún documento vigente de un tipo activo es inválido (incluidos los no obligatorios);
   - la cédula no es ambigua.

   Un documento con ERROR que no es el vigente y los documentos "otro" no impiden COMPLETO; quedan señalados.
3. **ERROR:** algún documento falló y el profesor no está COMPLETO.
4. **INCOMPLETO:** falta algún tipo obligatorio.
5. **CON_PROBLEMAS:** no falta nada, pero hay un vigente inválido o la cédula es ambigua.

Precisiones:
- Un documento con ERROR nunca es el vigente de ningún tipo, porque no se sabe qué tipo es.
- Solo los tipos obligatorios cuentan como faltantes. Cualquier tipo activo cuenta para problemas.

## Diferencias intencionales frente al legado

1. **Duplicados del mismo tipo.** El legado se queda con el último documento de cada tipo. El nuevo motor se queda con el **vigente**: un válido gana sobre un inválido y, entre iguales, cuenta el más reciente (por fecha de modificación del archivo; si empatan, por nombre). Un duplicado inválido no deja al profesor CON_PROBLEMAS si hay uno válido del mismo tipo. La capa de revisiones humanas se suma en la Fase 4.
2. **Empate en la cédula modal** (por ejemplo, 2 documentos con una cédula y 2 con otra). El legado toma la primera e invalida los demás. El nuevo motor no cambia la validez de nada: ni invalida ni rescata. Agrega la observación "Cédula ambigua: requiere revisión humana." a los documentos que tienen cédula, y el profesor queda CON_PROBLEMAS (nunca COMPLETO).
3. **Tipo "otro" o desconocido.** Incluye los códigos de tipos inactivos. No cuenta para ningún requisito ni como problema, y queda señalado en `no_reconocidos`. Además, la revalidación por cédula puede invalidar un documento "otro" cuya cédula no coincide, pero **no lo rescata**: el legado lo habría marcado "Válido (verificado por cédula)", lo que confundiría al revisor.
4. **Estados detallados.** El legado solo distingue COMPLETO e INCOMPLETO. Los estados ERROR, CON_PROBLEMAS y SIN_DOCUMENTOS son nuevos. En la comparación, el estado coincide cuando los dos motores dicen COMPLETO, o los dos dicen que no.
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
  - La diferencia entre 2 y 3 viene de las reglas, y se clasifica con la diferencia intencional que la explica: `duplicados`, `cedula_ambigua`, `otro` o `error_de_analisis`. Si ninguna la explica, queda en `diferencias_no_explicadas`.
  - El informe detallado lleva datos reales: se escribe en JSON en `--salida`, y el comando rechaza una ruta dentro del repositorio. En pantalla solo salen conteos.
  - Gasta tokens de los dos motores.
- **Ambos comandos se niegan a correr** con los settings de pruebas (`ES_ENTORNO_DE_PRUEBAS`) o con `MOTOR_SIMULADO=True`.

## Consecuencias y notas para fases siguientes

- **Fase 3:**
  - El worker procesa cada documento con un tiempo límite, para que un PDF que cuelgue a `pypdf` no bloquee toda la corrida.
  - Decide si `Analisis` guarda los tokens de caché.
  - Guarda en `Analisis` el `tipo_detectado` normalizado y la `respuesta_cruda`.
- **Si se cambia de modelo:** en Claude Opus 5.5 y Sonnet 5.5, el `tool_choice` forzado responde 400. Ahí hay que usar `tool_choice: auto` con `strict: true` y una instrucción en el prompt, o salidas estructuradas (`output_config.format`). También cambian el mínimo de caché y los límites de páginas.
- **Fuera de alcance:** el cliente simulado sigue convenciones de nombre de archivo (documentadas en `simulado.py`) que solo sirven para desarrollo y pruebas.
