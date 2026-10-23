# Prueba de usabilidad: revisión de documentos (Fase 4a)

Es el criterio de aceptación de la Fase 4: **la persona de Gestión Humana completa estas tareas sin ayuda, y cada acción queda en la auditoría.**

## Preparación (la hace John, antes de la sesión)

1. Usa un equipo con Windows y Edge o Chrome: es como trabajará la persona de Gestión Humana. Usa **datos de demostración**, nunca datos reales:
   ```bash
   # .env de desarrollo: CARPETA_CONTRATACIONES apunta a una carpeta vacía y sintética.
   uv run python manage.py migrate
   uv run python manage.py createsuperuser            # tu usuario administrador
   ```
2. En el admin (`/admin/`), crea el usuario de la persona de Gestión Humana con el rol **Revisor GH**.
3. Siembra los datos de demostración:
   ```bash
   uv run python manage.py sembrar_demo --usuario <tu_usuario>
   uv run python manage.py runserver
   ```
4. Ten a mano una hoja para anotar, por cada tarea: si la completó, el tiempo, dónde dudó y lo que dijo.
5. Ten abierta la pantalla de auditoría del admin (`/admin/cuentas/registroauditoria/`) para revisarla al final.

## Cómo conducir la sesión

- Explica: "Estamos probando la aplicación, no a ti. Si algo no se entiende, es un problema de la aplicación."
- Pídele que **piense en voz alta**: qué busca, qué espera que pase.
- **No ayudes** durante las tareas. Si se queda bloqueada más de 2 minutos, anótalo como "no completada" y pasa a la siguiente.
- Lee cada tarea tal como está escrita, sin señalar botones ni pantallas.

## Tareas

### 1. Entrar y orientarse (calentamiento)
**Escenario:** "Empiezas tu jornada y quieres ver cómo van las contrataciones."
**Meta:** entrar con su usuario y decir cuántos profesores están completos y cuántos incompletos.
**Éxito:** dice las dos cifras que muestra el tablero.
**Observar:**
- ¿Encuentra los totales sin buscar?
- ¿Entiende los nombres de los estados?

### 2. Encontrar a un profesor incompleto y saber qué le falta
**Escenario:** "Necesitas avisarle a un profesor qué documentos le faltan."
**Meta:** encontrar a un profesor en estado INCOMPLETO y decir qué documentos le faltan.
**Éxito:** nombra los tipos faltantes, tomándolos del semáforo del tablero o del aviso "Faltan:" del detalle.
**Observar:**
- ¿Usa el filtro de estado, el de "Le falta" o la tabla?
- ¿Entiende el semáforo (✓, ✗, !) sin explicación?
- ¿Las columnas verticales se leen bien?

### 3. Revisar un documento y decidir
**Escenario:** "A un profesor con problemas, la IA le marcó un documento como inválido. Revísalo y decide."
**Meta:** abrir el detalle de un profesor CON PROBLEMAS, ver el PDF del documento inválido y aprobarlo o rechazarlo con un comentario.
**Éxito:** queda guardada una revisión, y el mensaje de confirmación aparece.
**Observar:**
- ¿Encuentra el documento con problema en la lista?
- ¿El PDF se ve al lado y es legible?
- ¿Entiende qué significa cada decisión?
- Si la cédula del documento no coincide, ¿lee el aviso y explica en el comentario?

### 4. Corregir el tipo de un documento
**Escenario:** "La IA no reconoció un documento ('Otro documento'), pero al verlo sabes qué certificado es."
**Meta:** en un profesor con un documento "Otro", corregir su tipo al correcto, con un comentario.
**Éxito:** el documento queda "Corregido" con el tipo nuevo, y el estado del profesor cambia si corresponde.
**Observar:**
- ¿Relaciona "Corregir el tipo" con elegir el tipo en la lista desplegable?
- ¿Nota el cambio de estado?

### 5. Descartar un duplicado
**Escenario:** "Un profesor subió dos veces el mismo certificado, y una de las copias es ilegible."
**Meta:** en un profesor con un documento ilegible duplicado, descartarlo con un comentario.
**Éxito:** el documento queda "Descartado" y deja de contar (el profesor puede pasar a COMPLETO).
**Observar:**
- ¿Distingue "Descartar" de "Rechazar"?
- ¿Entiende por qué el ilegible bloqueaba el estado?

### 6. Verificar a un profesor
**Escenario:** "Revisaste todo y el profesor está completo. Déjalo verificado."
**Meta:** marcar como verificado a un profesor COMPLETO. Luego, en otro profesor que no está completo, intentar verificarlo.
**Éxito:**
- El primero queda "Verificado" con su nombre y la fecha.
- En el segundo, entiende por qué no se puede: el botón está desactivado y explica que solo se verifica un profesor COMPLETO.

**Observar:**
- ¿Encuentra la acción?
- ¿Entiende el mensaje de por qué no se puede?

## Al terminar

1. **Preguntas abiertas:** "¿Qué fue lo más difícil?" "¿Qué cambiarías?" "Del 1 al 5, ¿qué tan seguro te sentirías usándola sola?"
2. **Auditoría:** en `/admin/cuentas/registroauditoria/`, comprueba que cada acción quedó registrada con su usuario y su hora:
   - inicio de sesión;
   - cada PDF visto (`pdf_visto`);
   - cada revisión (`revision_creada`);
   - la verificación (`profesor_verificado`);
   - el cierre de sesión.

## Criterios

| Métrica | Meta |
| --- | --- |
| Tareas completadas sin ayuda | 6 de 6 (aceptación de la fase) |
| Acciones en la auditoría | 100 % |
| Seguridad para usarla sola (1 a 5) | 4 o más |

Clasifica cada problema observado con esta severidad:

| Severidad | Qué significa |
| --- | --- |
| 4, crítico | Impide completar la tarea |
| 3, mayor | Dificultad seria |
| 2, menor | Duda pasajera |
| 1, cosmético | Detalle visual |

Los críticos y los mayores se corrigen antes de cerrar la fase.

## Prueba técnica en el navegador (antes de la sesión)

Estas comprobaciones no las cubre CI. Se hacen en Edge y en Chrome de Windows:

- **El visor de PDF en el iframe** del detalle se ve con la CSP de la app (`frame-src 'self'`) y con la del PDF (`frame-ancestors 'self'`).
- **"Abrir el PDF en otra pestaña"** funciona.
- **La consola del navegador (F12)** no muestra violaciones de la CSP en el tablero, el detalle ni el inicio de sesión.
- **Los filtros del tablero** actualizan los resultados sin recargar la página, y los botones Atrás y Adelante del navegador funcionan.
- **La fuente Atkinson Hyperlegible Next** se carga. Si falla, se usa Segoe UI sin romper el diseño.
