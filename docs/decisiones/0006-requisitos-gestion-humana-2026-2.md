# 0006. Requisitos de Gestión Humana 2026-2: EPS y AFP, vigencia y logo

- **Estado:** aceptada
- **Fecha:** 2026-10-25

## Contexto

Gestión Humana respondió las preguntas pendientes sobre los requisitos de contratación. El instructivo oficial está en `docs/instructivo-2026-02.md`, sin los enlaces de SharePoint, que llevan un token de acceso. Los cambios tocan el prompt y las reglas del motor, así que van juntos: se validan contra la muestra real una sola vez.

## Decisión

### EPS y pensión por separado

- **Dos tipos obligatorios.** `certificados_eps_afp` se divide en `certificado_eps` (orden 8) y `certificado_afp` (orden 9). El certificado médico pasa al orden 10.
  - El tipo viejo queda **inactivo** con su historial: análisis y revisiones. No se borra.
  - Hay 10 tipos activos y obligatorios. Migración `0008`.
- **Un solo PDF puede cubrir los dos.** La IA reporta en `cubre` qué afiliaciones certifica cada documento: `eps`, `afp` o `ambos`.
  - Un documento de EPS o de AFP con `ambos` es vigente para los dos tipos.
  - Si está vencido o es inválido, es un problema en los dos.
- **Alternativas de pensión.** Son **alias** de `certificado_afp` con datos propios, editables en el admin:
  - `resolucion_pension_vejez`: certificado o resolución de pensión por vejez, para pensionados;
  - `carta_bono_pensional`: carta de bono pensional del profesor. Gestión Humana la acepta y cuenta como válida. El detalle muestra la observación "Carta de bono pensional: declaración del profesor, no certificado de una entidad".
- **Se conserva con qué documento se cumplió.** `Analisis.tipo_detectado` guarda el código del alias, no el del tipo. Cada alias tiene su etiqueta legible. El detalle, y más adelante el informe de la Fase 5, dicen con qué documento se cumplió el requisito de pensión, no solo "AFP".
- **Campos nuevos de los alias:** `etiqueta` (vacía: la del tipo), `hereda_vigencia`, `vigencia_dias` y `observacion`. El catálogo del motor los expone con `etiqueta_de`, `vigencia_de` y `observacion_de`.

### Vigencia

- **La IA solo extrae la fecha.** Reporta `fecha_expedicion` en formato AAAA-MM-DD, o nulo, y se guarda en `Analisis.fecha_expedicion`.
  - Un texto que no es una fecha AAAA-MM-DD válida cuenta como fecha no leída.
  - El prompt le pide no marcar inválido un documento por su fecha.
- **La regla la aplica el motor.** `reglas.aplicar_vigencia(resultados, catalogo, hoy)` recibe la fecha de referencia como parámetro, así que el motor sigue siendo puro.
  - Se aplica **después** de la revalidación por cédula: si no, la cédula que coincide rescataría a un vencido.
- **`TipoDocumento.vigencia_dias`**, editable en el admin:
  - 30 días: Procuraduría, Contraloría, Policía, medidas correctivas, REDAM, inhabilidades, EPS y AFP;
  - sin vigencia: el formato de autorización, el examen médico y las dos alternativas de pensión, cuyos alias no heredan la vigencia del tipo. **Pendiente de confirmar con Gestión Humana.**
- **Fecha de referencia:** hoy en America/Bogota (`TIME_ZONE`), con `estado.hoy()`.
  - **Vencido**, con más días que los permitidos: queda inválido, con la observación "Certificado expedido el dd/mm/aaaa (N días; máximo 30): solicitar uno nuevo." El profesor queda CON_PROBLEMAS. Por la regla del ADR 0005, si estaba verificado, su verificación queda desactualizada.
  - **Por vencer**, con 7 días o menos: sigue válido. El detalle avisa "vence el dd/mm" en la lista, en el panel y en la ficha del profesor.
  - **Fecha que no se lee**, o posterior a hoy: no invalida. El documento queda señalado como "Fecha sin leer" y el profesor, como "requiere atención", para revisión humana.
- **Recálculo diario.** El estado cambia con el paso del tiempo aunque no cambien los archivos. Por eso el worker recalcula el estado de todos los profesores presentes al arrancar y cada 24 horas (`recalcular_todos`). Una carpeta que desapareció conserva su último estado (ADR 0004).
- **Decisión humana.** Un revisor puede aprobar o corregir un vencido, con comentario obligatorio, igual que con la cédula ajena. Esa decisión prevalece: `aplicar_vigencia` no toca lo que validó un revisor.

### Logo oficial: solo se observa

- El instructivo pide descargar los certificados con Control + P, para que salga el logo de la entidad. También pide que el formato de autorización sea la plantilla de la UNICAMACHO, con título, logo y firma.
- La IA reporta `tiene_logo_oficial` y, en el formato, `es_plantilla_institucional`. Se guardan en columnas propias de `Analisis`.
- **No cambian `es_valido` todavía.** El prompt lo dice explícitamente, y el detalle los muestra como observación.
- Se agrega `TipoDocumento.requiere_logo`, falso por defecto y sin regla. Se activará por tipo desde el admin cuando el logo esté calibrado contra documentos reales.

### Comparación con el legado

- **`--fecha-referencia AAAA-MM-DD`** evalúa la vigencia contra esa fecha en lugar de hoy. La muestra real es de junio y julio de 2026. El resumen dice qué fecha usó.
- **Logo por tipo:** el resumen cuenta cuántos documentos dieron `tiene_logo_oficial` verdadero, falso o nulo en cada tipo, para calibrar la regla.
- **Para las reglas del legado**, EPS, AFP y las alternativas de pensión se traducen a su tipo único, `certificados_eps_afp`.
- **Diferencias intencionales nuevas:**
  - `separacion_eps_afp`: falta exactamente uno de los dos, cuando al legado le bastaba un documento;
  - `vigencia`: un vencido o una fecha sin leer;
  - `alternativa_pension`: el vigente de AFP es un alias de pensión.
- Las diferencias intencionales se clasifican también cuando vienen de la IA, no solo de las reglas. El prompt nuevo reconoce documentos que el legado no conocía.

### Datos de demostración

- `ClienteSimulado` reconoce nuevas marcas en el nombre del archivo:
  - `combinado`, para un PDF que cubre EPS y pensión;
  - `vencido` (45 días), `por_vencer` (25 días) y `fecha_ilegible`;
  - `sin_logo`.
  - Las fechas simuladas se cuentan desde hoy.
- `sembrar_demo` agrega siete profesores: uno con EPS y pensión en un solo PDF, un pensionado, uno con carta de bono pensional, uno con solo EPS (INCOMPLETO), uno con un certificado vencido, uno con un certificado por vencer y uno con una fecha ilegible. Los demás casos ya tenían EPS y AFP por separado.

## Consecuencias

- **Reanálisis al cambiar el prompt o el esquema.** Los análisis guardados no traen fecha, cobertura ni logo, y los que dicen `certificados_eps_afp` ya no cuentan, porque el tipo está inactivo. En un entorno con análisis previos, como el clon de validación, casi todos los profesores quedan INCOMPLETOS hasta una corrida `todos`. Procedimiento general, en `docs/despliegue-windows.md`: al cambiar el prompt o el esquema, revisar el estimado con `--en-seco` y lanzar una corrida `todos`. Producción todavía no existe y arrancará con este prompt, sin análisis viejos.
- **El tablero depende de que el worker corra.** Si el worker no está corriendo, el tablero no refleja los vencimientos. El detalle sí evalúa siempre contra hoy.
- **Pendientes de confirmar con Gestión Humana:** que el formato de autorización, el examen médico y las alternativas de pensión no tienen vigencia; y si la regla del logo debe invalidar o solo señalar, cuando esté calibrada.
