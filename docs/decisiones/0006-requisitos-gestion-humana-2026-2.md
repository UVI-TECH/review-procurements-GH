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

## Ajustes tras la validación con la muestra real

John validó el PR #11 en el clon con la muestra real: 17 profesores, 116 documentos y fecha de referencia 2026-07-04. La vigencia atrapó certificados vencidos reales que el legado aceptaba. Al revisar a mano los documentos donde el motor difería, aparecieron dos casos que el prompt no conocía.

### Régimen especial del magisterio (FOMAG)

- Los certificados del Fondo Nacional de Prestaciones Sociales del Magisterio (FOMAG, administrado por Fiduprevisora) corresponden a un régimen especial que cubre salud y pensión. Hubo dos casos reales clasificados solo como AFP, y esos profesores aparecían sin EPS.
- **El prompt da criterios explícitos:**
  - entidades de salud: EPS como Sanitas, Nueva EPS, SURA, Coomeva, Compensar, Famisanar o Salud Total, y los certificados de ADRES/BDUA;
  - fondos de pensión: Colpensiones, Porvenir, Protección, Colfondos y Skandia;
  - regímenes especiales que cubren los dos: FOMAG/Fiduprevisora, con `cubre="ambos"`.
- **En `reglas.py`, lo que cumple un documento de EPS, AFP o sus alias sale de `cubre`, no del tipo detectado:**
  - `eps` cumple EPS;
  - `afp` cumple AFP;
  - `ambos` cumple los dos;
  - sin `cubre`, cuenta el tipo detectado.
- **Pendiente de confirmar con Gestión Humana:** que aceptan el certificado FOMAG para los dos requisitos.

### Formato de autorización con datos de otra persona

- **El caso real:** el texto ("El suscrito … identificado con C.C. …") tenía el nombre y la cédula de otra persona, mientras que la firma y el bloque final eran del profesor. La IA lo clasificó como la consulta de inhabilidades.
- **El prompt distingue los dos documentos:**
  - el formato es la autorización firmada por el profesor, dirigida a la UNIAJC (Ley 1918 de 2018, Decreto 753 de 2019);
  - la consulta es el resultado del sistema de la Policía.
- **La IA extrae por separado** el nombre y la cédula del cuerpo del texto y los del bloque de firma. Van en `Analisis.datos_extra` (`nombre_texto`, `cedula_texto`, `nombre_firma` y `cedula_firma`), que se puede consultar por clave en SQLite. En el formato, `numero_documento` es la cédula de la firma.
- **La comparación la hace `reglas.py`,** solo por cédula y normalizada con `solo_digitos`. Los nombres se muestran, pero no se comparan.
  - **Formato inválido:** si la cédula del texto no es la de la firma o la del profesor. La observación es "El texto del formato autoriza a nombre de otra persona (C.C. distinta): debe diligenciarse con sus propios datos".
  - **Formato sin diligenciar:** si falta alguna de las dos cédulas, no se invalida. Queda la observación "No se pudo leer la cédula del texto o de la firma del formato: revisar" y el profesor, como "requiere atención".
  - **Orden:** la revisión va después de la revalidación por cédula, para que la cédula de la firma no rescate un formato ajeno.

### Lo que dijo la IA frente al resultado final

- Cada regla que cambia la validez que dio la IA deja su causa en el resultado (`causas`): cédula ajena, cédula que coincide, vigencia o formato a nombre de otra persona.
- El detalle muestra por separado lo que dijo la IA (tipo y validez) y el resultado final con su causa, incluida la revisión humana.
- Es la base del control de calidad: medir los aciertos de la IA sin mezclarlos con las reglas.

### Versión del prompt y corrida "desactualizados"

- **`VERSION_PROMPT`**, en `motor/prompts.py`, cubre el prompt y el esquema:
  - 1: el motor migrado;
  - 2: el PR #11;
  - 3: FOMAG y los datos del formato.
- **Cada `Analisis` la guarda en `version_prompt`.** Los análisis anteriores quedan en nulo, que cuenta como versión anterior.
- **Una prueba fija la huella de cada versión.** Si alguien cambia el prompt o el esquema sin subir la versión, la prueba falla y muestra la huella nueva.
- **Un análisis desactualizado** es un documento cuyo análisis vigente es de una versión anterior. No cuentan los errores, ni los ilegibles, porque esos los decide el lector de PDF y no el prompt.
  - El detalle dice "Analizado con un prompt anterior: requiere reanálisis", en lugar de "Fecha sin leer".
  - **No marca "requiere atención":** después de cada cambio de prompt inundaría ese filtro y escondería los casos reales.
  - El tablero muestra a los usuarios Administrador y Revisor cuántos documentos están desactualizados, con el comando para reanalizarlos. El botón llegará con la pantalla de corridas de la Fase 4b.
  - Hay un filtro "con análisis desactualizados".
- **El alcance de corrida `desactualizados`** reanaliza solo esos documentos.

### Comparación con el legado, ajustes

- **Si faltan EPS y AFP** y al legado le faltaba `certificados_eps_afp`, la diferencia es `separacion_eps_afp`, no una diferencia no explicada.
- **Discrepancias de tipo:** cada profesor lista los documentos donde la IA nueva y el legado discrepan en el tipo. El resumen los cuenta, también aparte para los profesores cuyo estado coincide (`documentos_tipo_distinto_con_estado_igual`). Antes quedaban escondidos detrás de otras etiquetas.

### El logo sigue sin regla

`requiere_logo` sigue en falso en todos los tipos. En la muestra, la IA respondió "tiene logo" en el 100 % de los certificados, sin un solo negativo para calibrar, y fue errática en el formato. No hay evidencia de que distinga.

### Estáticos

- **Lo que pasó en el clon:** con `config.settings.validacion`, WhiteNoise servía lo que había dejado `collectstatic`. Un `app.css` viejo, sin las reglas del tooltip, quedó en uso después de `git pull`, y el nombre de cada tipo se veía siempre en el tablero.
- **Validación:** ahora sirve directo desde `static/`.
- **Producción:** corre `collectstatic` después de cada actualización (`docs/despliegue-windows.md`).

## Consecuencias

- **Reanálisis al cambiar el prompt o el esquema.**
  - **Ya hecho en el clon con el PR #11:** los análisis guardados no traían fecha, cobertura ni logo, y los de `certificados_eps_afp` dejaron de contar porque el tipo quedó inactivo, así que hizo falta una corrida `todos`.
  - **Desde ahora:** al cambiar el prompt o el esquema, sube `VERSION_PROMPT`, revisa el estimado de la corrida `desactualizados` con `--en-seco` y lánzala. Solo reanaliza lo necesario.
  - **Excepción:** un cambio del catálogo hecho desde el admin cambia el prompt sin cambiar la versión; ahí corresponde `todos`.
  - El procedimiento está en `docs/despliegue-windows.md`. Producción todavía no existe y arrancará con el prompt vigente, sin análisis viejos.
- **El tablero depende de que el worker corra.** Si el worker no está corriendo, el tablero no refleja los vencimientos. El detalle sí evalúa siempre contra hoy.
- **Pendientes de confirmar con Gestión Humana:**
  - que el formato de autorización, el examen médico y las alternativas de pensión no tienen vigencia;
  - que aceptan el certificado FOMAG para EPS y AFP;
  - qué hará la regla del logo cuando haya evidencia para calibrarla.
