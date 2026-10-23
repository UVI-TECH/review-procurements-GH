# 0004. Escaneo, corridas y worker

- **Estado:** aceptada
- **Fecha:** 2026-10-22

## Contexto

La Fase 3 conecta el motor (ADR 0003) con la carpeta de Contrataciones y con la base de datos:

- un escaneo que sincroniza `Profesor` y `Documento` con el disco;
- corridas que analizan solo lo necesario;
- un worker que corre en segundo plano en el PC de Gestión Humana con Windows.

El criterio de aceptación tiene dos partes: una segunda corrida sin cambios no llama a la API, y al reanudar tras cerrar la app a mitad no se duplica trabajo.

## Decisión

### Fuente de documentos

`motor/fuentes.py` define `FuenteCarpetaLocal`, con la interfaz que cumplirá `FuenteGraph` en la Fase 8: `disponible`, `listar_profesores`, `listar_pdfs` y `leer`.

- **Rutas:** toda ruta se resuelve y se valida dentro de la carpeta raíz. No se aceptan path traversal ni enlaces simbólicos que salgan de ella; un enlace que apunta dentro de la raíz sí se acepta.
- **Archivos ignorados:** los ocultos (incluido el atributo oculto de Windows), los temporales de Office y OneDrive (`~$*`, `*.tmp`) y todo lo que no sea PDF.
- **Profundidad:** como en el legado, solo se leen los PDFs del primer nivel de la carpeta de cada profesor.
- **Formato de `ruta_relativa`:** siempre usa `/`, así que es igual en Windows y en Linux.
- **El motor recibe bytes:** los clientes tienen `analizar_datos(bytes, ...)`, para que la fuente pueda ser local o remota. `analizar(ruta)` sigue existiendo para los comandos de validación.

### Escaneo

- **Qué sincroniza:**
  - Una carpeta nueva crea un `Profesor`, y un PDF nuevo crea un `Documento`.
  - Un PDF cambiado recibe su nuevo sha256, tamaño y fecha. **Solo se relee y se hashea si cambió el tamaño o la fecha de modificación**, para no hashear miles de archivos en cada escaneo. La consecuencia es que un cambio que conserve el mismo tamaño y la misma fecha no se detecta; con PDFs reales eso no ocurre en la práctica.
  - Un PDF que desaparece queda con `presente=False`, y vuelve a `True` si reaparece. Nunca se borra nada.
- **Carpeta que desaparece:**
  - Queda con `Profesor.carpeta_presente=False` y sus documentos pasan a `presente=False`.
  - El profesor **conserva su último estado**: no se recalcula a SIN_DOCUMENTOS.
  - Las corridas lo saltan, y queda en la auditoría (`carpeta_desaparecida`, con usuario nulo).
- **Freno de seguridad:**
  - Si la raíz no existe o está vacía, el escaneo aborta.
  - Si en un mismo escaneo desaparece más de `ESCANEO_MAX_DESAPARECIDAS` (20 %) de las carpetas conocidas, aborta **sin cambiar nada** y lo explica. Es el síntoma típico de OneDrive desconectado o de una carpeta movida.
  - Solo `--forzar` continúa, y eso queda en la auditoría (`escaneo_forzado`).
- **Limitación conocida, una carpeta renombrada:** se trata como un profesor nuevo. El anterior queda con `carpeta_presente=False` y su historial.
- **Mejora futura** (solo si los renombres resultan frecuentes): la heurística más segura no es el sha256 sino la cédula. Una carpeta nueva cuya cédula modal coincida con la de un profesor con `carpeta_presente=False` se marcaría como "posible renombre", para que un revisor lo confirme. **Nunca se fusiona de forma automática.**

### Corridas

| Alcance | Qué analiza |
| --- | --- |
| `todos` | Todos los documentos presentes, salvo los de reintentos agotados |
| `nuevos_y_modificados` | Los presentes cuyo sha256 actual no tiene ningún `Analisis` exitoso o ilegible. Un error no cuenta, así que se reintenta |
| `un_profesor` | Todos los documentos del profesor, **incluidos** los de reintentos agotados: es la vía manual para volver a probar |

- **Escaneo al empezar:** el worker escanea el alcance de cada corrida antes de analizar, así la corrida siempre refleja el disco.
- **Guardado por documento:** cada `Analisis` se guarda en su propia transacción apenas responde la API. El progreso de la corrida (procesados, errores, tokens, latido) se actualiza por documento.
- **Estado al terminar cada profesor:** se calcula con `evaluar_profesor` y se guardan `Profesor.estado` y `Profesor.cedula` (la cédula modal). Para cada documento cuenta el último `Analisis` de su sha256 actual que **no** sea error. Un error solo cuenta si no hay ningún resultado útil para el archivo actual, para que una caída de la API durante un reanálisis no haga retroceder a ERROR a profesores que ya estaban bien. La capa de revisiones humanas se suma en la Fase 4.
- **Fallos transitorios:** se guardan como `Analisis` con `tipo_detectado="error"`, junto con sus tokens, y el historial muestra cada intento. Los ilegibles se guardan con `"ilegible"` y su observación (ADR 0003), para que en la Fase 4 un revisor pueda descartarlos.
- **Reintentos agotados:**
  - Si los dos últimos `Analisis` del sha256 actual de un documento son errores, se marca `Documento.reintentos_agotados` y queda en la auditoría. Esos dos análisis vienen siempre de dos corridas distintas, porque una corrida analiza cada documento una sola vez.
  - Las corridas automáticas lo saltan, para no gastar tokens en un bucle.
  - La marca se quita cuando cambia el sha256 o cuando un reintento manual (`un_profesor`) sale bien.
  - El nombre del campo dice el motivo exacto, porque en la Fase 4 habrá varios motivos para pedir revisión humana.
- **`crear_corrida --en-seco`:**
  - Escanea dentro de una transacción que se deshace: el conteo refleja el disco actual y no queda nada creado ni modificado.
  - El costo se estima con el promedio de tokens de los `Analisis` previos (o un valor por defecto si no hay historial) y los precios por millón de tokens de settings, que se pueden cambiar en el archivo de entorno.
- **Permisos:**
  - `crear_corrida` exige `add_corrida`.
  - `cancelar_corrida` exige el permiso nuevo `cancelar_corrida`, que tienen el Administrador y el Revisor GH (migración `cuentas/0004`).
- **Auditoría:**
  - creación, con el usuario que la crea;
  - solicitud de cancelación;
  - inicio, reanudación, cancelación, finalización y fallo, con usuario nulo porque actúa el sistema.

### Worker

- **Un solo worker por equipo:**
  - Usa un bloqueo del sistema operativo sobre `worker.lock`, solo con la biblioteca estándar: `msvcrt.locking` en Windows y `fcntl.flock` en Linux.
  - El PID va en un archivo aparte (`worker.pid`), porque en Windows el rango de bytes bloqueado no se puede leer desde otro proceso.
  - Un segundo worker se niega con "Ya hay un worker en ejecución (pid N)". Lo prueba un subproceso real, que en CI también corre en Windows.
  - El sistema operativo libera el bloqueo cuando el proceso muere, aunque sea por un cierre forzado.
  - `RUTA_BLOQUEO_WORKER` está por defecto junto a la base de datos.
- **Reanudación:**
  - Mientras el worker tiene el bloqueo, toda corrida "en proceso" es huérfana por definición, así que se reanuda primero.
  - No repite lo que ya tiene `Analisis` en esa corrida.
  - El latido (`Corrida.latido`) se actualiza por documento; sirve para mostrar en la Fase 4 si el worker está vivo.
- **Cancelación:** `Corrida.cancelacion_solicitada` se revisa entre documentos, y el documento en curso termina. Una corrida pendiente se cancela de inmediato.
- **Tiempo límite por documento**, que funciona en Windows sin `signal.alarm`:
  - `pypdf` corre en un `multiprocessing.Pool(1, maxtasksperchild=200)` con *spawn*, y la función del hijo (`motor/lector_pdf.py`) es pura y no importa Django.
  - Si se vence `MOTOR_TIMEOUT_PDF_SEGUNDOS` (30 s), el pool se termina y el documento queda como ERROR transitorio. La regla de reintentos agotados lo frena si se repite.
  - El pool se cierra de forma explícita al terminar (`close`/`join`), o con `terminate` si hubo un cuelgue o el worker sale por una excepción, para que en Windows no queden procesos `python.exe` huérfanos.
  - La llamada a la API tiene su propio timeout en el SDK.

### Consola y detención (cambio de `fase-3-ajustes`)

En la primera prueba con datos reales, el worker no mostraba nada: no se sabía si trabajaba, estaba colgado o esperaba. Y Ctrl+C dejaba tracebacks del worker y del hijo del pool. Por eso:

- **Mensajes del worker:**
  - al tomar una corrida (nueva o reanudada): su id, su alcance y el total de documentos;
  - el progreso por documento con contadores (n/total, errores, tokens acumulados);
  - un resumen al terminar, cancelar o fallar;
  - "Sin corridas pendientes; esperando…", una sola vez al entrar en espera.
- **Privacidad:** los mensajes nunca muestran nombres de profesores ni de archivos.
- **Ctrl+C:**
  - El worker lo atrapa, termina el pool y sale con código 0 y el mensaje "Worker detenido. La corrida N se reanudará al volver a iniciar el worker.".
  - La corrida queda "en proceso", así que se reanuda.
  - En Windows, Ctrl+Break (y el cierre de la consola) se trata igual.
  - El hijo del pool ignora SIGINT y SIGBREAK (`initializer` del pool), para que solo el padre maneje la interrupción.
- **Prueba:** interrumpe un worker real a mitad de una corrida, como subproceso, en Linux y en Windows. Para poder hacerlo, el cliente simulado acepta una pausa por documento (`MOTOR_SIMULADO_PAUSA_SEGUNDOS`, por defecto 0, solo para pruebas y demostraciones). Además, los settings de pruebas aceptan una base en archivo (`RUTA_BASE_DATOS_PRUEBAS`); por defecto sigue en memoria.
- **Freno en producción:** los settings de `produccion` se niegan a arrancar si `MOTOR_SIMULADO=True` o si `MOTOR_SIMULADO_PAUSA_SEGUNDOS` no es 0. Un motor simulado en el PC de Gestión Humana daría validaciones falsas sin que nadie lo note.

### SQLite y configuración

- **Escrituras concurrentes:** el web y el worker escriben a la vez, así que SQLite corre en modo WAL, con `busy timeout` de 20 s y transacciones `IMMEDIATE` (desde `OPTIONS` en settings).
- **Archivos de WAL:** `revision.db-wal` y `revision.db-shm` ya estaban cubiertos por `.gitignore` y por las reglas de lectura negada (`*.db-*`). El `-wal` contiene datos recientes.
- **La base nunca va dentro de una carpeta sincronizada por OneDrive:** la sincronización con WAL activo puede corromperla, y solo los respaldos van a OneDrive. La app se niega a arrancar si `RUTA_BASE_DATOS` cae dentro de `CARPETA_CONTRATACIONES`.
- **Rutas desde el archivo de entorno:** `CARPETA_CONTRATACIONES` y `RUTA_BASE_DATOS` salen de ahí, para poder correr la app en un clon de validación separado. Un valor vacío usa el valor por defecto.

## Validación real

La hizo John en el clon de validación, con datos reales:

- Una corrida `todos` se interrumpió a mitad y se reanudó: terminó **completada con 116 documentos**.
- Una corrida `nuevos_y_modificados` posterior analizó **0 documentos y gastó 0 tokens**. El `--en-seco` previo había estimado **US$ 0,00**.

Con eso se cumple el criterio de aceptación de la fase con datos reales.

## Consecuencias

- La primera corrida analiza todo. Las siguientes, con `nuevos_y_modificados`, solo lo nuevo o cambiado. Una corrida sin cambios no llama a la API.
- Cerrar la app a mitad no pierde trabajo ni lo duplica.
- **Pendientes para la Fase 4:**
  - La cancelación y el latido se muestran en la interfaz.
  - Las revisiones humanas se suman al cálculo del estado.
  - La cancelación se hará desde una vista propia. Mientras tanto, en el admin los campos de cancelación son de solo lectura (también para el superusuario) y la única vía es el comando `cancelar_corrida`, que audita.
- **Datos de desarrollo:** en desarrollo, `CARPETA_CONTRATACIONES` apunta siempre a una carpeta sintética. Los datos reales solo se procesan en el clon de validación y en el PC de Gestión Humana.
