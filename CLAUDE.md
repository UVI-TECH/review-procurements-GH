# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Propósito

App Django local para revisar los documentos de contratación de profesores de Gestión Humana (UNIAJC). Reemplaza el `.exe` de `legado/`: lee una carpeta por profesor desde OneDrive, analiza cada PDF con Claude, cruza la identidad por cédula y permite la revisión humana con trazabilidad. Corre en un PC con Windows (Waitress en `127.0.0.1:8000`) y se desarrolla en Fedora.

El plan aprobado está en `docs/plan.md` (modelo de datos, pantallas, seguridad, respaldos y fases). **Se trabaja fase por fase:** no adelantes trabajo de una fase posterior y cumple el criterio de aceptación de cada fase antes de pasar a la siguiente. Desde la Fase 1, cada fase va en su propia rama con pull request hacia `main`.

## Stack

Python 3.12 (`.python-version`), Django 5.2 LTS, SQLite, Waitress y django-environ. Las dependencias se manejan con uv (`pyproject.toml` + `uv.lock`). Más adelante: HTMX, SDK de Anthropic, openpyxl y pyzipper, según la fase.

## Comandos

```bash
uv sync                                   # instalar dependencias (incluye el grupo dev)
uv run pre-commit install                 # una vez por clon: gitleaks + ruff en cada commit
uv run python manage.py check
uv run python manage.py migrate
uv run python manage.py runserver
uv run pytest                             # todas las pruebas
uv run pytest tests/test_arranque.py::test_check_sin_errores   # una sola prueba
uv run ruff check . && uv run ruff format --check .
uv run pre-commit run --all-files
uv add <paquete> / uv add --dev <paquete> # nunca pip
```

Desde Claude Code, el sandbox oculta el `.env`, así que Django no encuentra `DJANGO_SECRET_KEY`. Usa una clave efímera en la misma llamada, igual que CI:

```bash
export DJANGO_SECRET_KEY=$(uv run python -c "import secrets; print(secrets.token_urlsafe(50))") && uv run pytest
```

## Arquitectura

- `config/entorno.py` (`cargar_env()`) carga el `.env` **antes** de elegir `DJANGO_SETTINGS_MODULE`. Lo llaman `manage.py`, `config/wsgi.py` y `base.py`, y no pisa variables que ya estén en el entorno.
- Settings en `config/settings/`:
  - `base.py`: exige `DJANGO_SECRET_KEY`.
  - `desarrollo.py`: valor por defecto de `manage.py`; motor simulado.
  - `produccion.py`: valor por defecto de `wsgi.py`; `DEBUG=False`.
  - `validacion.py`: solo lectura sobre un respaldo importado.
  - `pruebas.py`: usado por pytest; `MOTOR_SIMULADO=True` fijo, SQLite en memoria y hasher MD5.
- Apps en `apps/`: `cuentas` (usuarios, roles, auditoría), `contrataciones` (dominio y tablero), `motor` (prompts, cliente Claude, reglas puras, fuentes de documentos), `corridas` (cola en la BD + worker como comando de Django), `reportes` (Excel) y `respaldos`. El motor no depende de la interfaz. Django y el worker se comunican solo a través de la base de datos.
- Modelos (ver `docs/decisiones/0002-modelo-de-datos-y-roles.md`):
  - `contrataciones`: catálogo (`TipoDocumento`, `AliasTipoDocumento`), `Profesor`, `Documento`, `Analisis`, `Revision` y `Corrida`.
  - `cuentas`: `Usuario` y `RegistroAuditoria`. Escribe en la auditoría solo con `apps.cuentas.auditoria.registrar(usuario, accion, objeto, detalle)`.
  - `respaldos`: `Respaldo`.
  - `motor` y `corridas` no tienen modelos.
- `Analisis`, `Revision` y `RegistroAuditoria` son de solo agregar (`apps/comun/inmutables.py`): `save()` sobre una fila existente, `delete()` y `update()`/`delete()` en bloque lanzan `ErrorInmutable`. No agregues vías para saltarse esto. Todo el historial usa `on_delete=PROTECT`.
- Los roles (Administrador, Revisor GH, Consulta) los crea la migración `cuentas/0003_roles`. Un modelo o permiso nuevo se asigna a los grupos con su propia migración de datos, y se actualiza `tests/test_roles.py`.
- El motor (`apps/motor/`, ver `docs/decisiones/0003-motor-migrado.md`) no depende del ORM: trabaja con dataclasses (`ResultadoDocumento`, `Catalogo`), y solo `catalogo.cargar_catalogo()` lee la base de datos. Usa `servicio.crear_cliente()`, que devuelve el cliente simulado mientras `MOTOR_SIMULADO=True`. El cliente real se niega a crearse en ese caso. En pruebas, el cliente real solo se usa con un SDK falso inyectado (`ClienteClaude(catalogo, sdk=...)`).
- Los PDFs no son de confianza. Cualquier fallo al leerlos o analizarlos se devuelve como un `ResultadoDocumento`, nunca como una excepción: con `error` si es transitorio (API, red; se reanaliza) o como ilegible si es un problema permanente del archivo (contraseña, dañado, límites), con una observación que dice qué pedir.
- `AUTH_USER_MODEL = "cuentas.Usuario"` (subclase de `AbstractUser`) existe desde la migración `0001`. Nunca uses `django.contrib.auth.models.User`; usa `get_user_model()` o `settings.AUTH_USER_MODEL`.
- `legado/` es solo referencia: no se modifica y está excluido de ruff.

## Convenciones

- El código y los nombres de dominio van en español (`Profesor`, `Corrida`, `es_valido`, `cargar_env`). Los mensajes de commit pueden ir en inglés.
- **Nunca** pongas datos reales de Gestión Humana en el repositorio: ni PDFs, ni cédulas, ni nombres, ni Excel históricos. Para pruebas usa datos sintéticos en `tests/fixtures/`.
- La validación con respaldos reales (`importar_respaldo`, settings `validacion`) se hace en un **clon aparte, fuera de este repositorio** (p. ej. `~/validacion-contrataciones/`), donde **nunca se abre Claude Code**. En este repositorio no se importan respaldos reales.
- En desarrollo y en pruebas se usa el motor simulado (`MOTOR_SIMULADO=True`). Ninguna prueba debe llamar a la API de Anthropic.
- **Nunca ejecutes `probar_motor` ni `comparar_con_legado`:** llaman a la API real con PDFs reales y los ejecuta el usuario en su terminal. `.claude/settings.json` también los niega (`manage.py <comando>` y `call_command(...)`). Los PDFs sintéticos de las pruebas se generan con `tests/fixtures/pdfs.py`; no se suben PDFs al repositorio.
- **Nunca leas ni imprimas el `.env`** ni sus variantes. Tampoco leas bases de datos (`*.db`, `*.sqlite3`) ni respaldos (`*.zip`, `respaldos/`): un respaldo importado contiene datos reales. Para saber qué variables existen, consulta `.env.example`. Si una variable nueva hace falta, agrégala a `.env.example` sin valor y pide al usuario que la complete.
- Esas reglas se hacen cumplir en dos capas (ver "Sandbox de Claude Code"). Son una **barrera de apoyo, no una garantía**, y la regla de arriba aplica igual.
- Variantes del `.env` permitidas: `.env.local`, `.env.desarrollo`, `.env.produccion` y `.env.validacion`. Una variante con otro nombre no queda cubierta por la negación hasta que se agregue a `.claude/settings.json`.
- Los secretos (`DJANGO_SECRET_KEY`, `ANTHROPIC_API_KEY`, `CLAVE_RESPALDO`) salen solo del `.env`, sin valores por defecto en el código.
- En desarrollo se usa una API key de Anthropic **exclusiva de desarrollo**, nunca la de producción de Gestión Humana.

## Sandbox de Claude Code

`.claude/settings.json` combina dos capas:

1. **Reglas `deny` de permisos.** Revisan el texto de la llamada antes de ejecutarla y cubren la herramienta Read (también bloquea Write y Edit sobre esos archivos) y comandos de Bash que nombran `.env*`, `*.db`, `*.sqlite3`, `*.zip` o `respaldos/` (`cat`, `head`, `grep`, `python -c open(...)`, `sqlite3`, `unzip`…). Coinciden por texto: un comentario que mencione `.env ` también bloquea la llamada.
2. **Sandbox del sistema operativo** (bubblewrap en Linux). Las mismas rutas `Read(...)` quedan ilegibles para todo comando de Bash y sus procesos hijos, aunque no las nombren (p. ej. `glob('.en*')` + `open()` da `PermissionError`). Tampoco se pueden borrar desde dentro (`Device or resource busy`). `allowUnsandboxedCommands: false` impide que Claude reintente un comando fuera del sandbox.

Lo que quedó permitido y por qué:

| Ajuste | Valor | Motivo |
| --- | --- | --- |
| `network.allowedDomains` | `pypi.org`, `files.pythonhosted.org` | `uv sync` / `uv add` |
| | `github.com` | pre-commit descarga sus hooks desde GitHub |
| `filesystem.allowWrite` | `~/.cache/uv` | caché de uv, fuera del proyecto |
| | `~/.cache/pre-commit` | entornos de los hooks y parches temporales de `git commit` |
| `excludedCommands` | `gh *`, `git push*`, `git fetch*`, `git pull*`, `git ls-remote*` | Su token está en el keyring de GNOME, al que se llega por D-Bus. Abrir el socket D-Bus al sandbox expondría todo el keyring, así que es más estrecho sacar solo estos comandos. Corren sin sandbox, pero las reglas `deny` siguen aplicando a su texto |

Límites conocidos:

- Las negaciones de `respaldos/` van ancladas a la raíz (`./respaldos/**`). Con `**/respaldos/**` el sandbox oculta también el código de `apps/respaldos/`.
- Dentro del sandbox, `git status` muestra como `??` puntos de montaje que crea el propio sandbox (`.bashrc`, `.gitconfig`, `.idea`, `.claude/agents`…). Haz `git add` con rutas explícitas; nunca `git add -A` ni `git add .`.
- Dentro del sandbox, cambiar a una rama cuyo `.claude/settings.json` es distinto falla: git no puede reemplazar ese archivo y el repositorio queda a medias. Trabaja cada rama en un worktree (`git worktree add -b <rama> <ruta> main`) y deja el directorio principal en `main`. Al terminar, el usuario ejecuta `git worktree prune` en su terminal si el sandbox no pudo borrar los metadatos.
- Una llamada sale del sandbox solo si **todos** sus comandos coinciden con `excludedCommands`. Por eso `gh ... | tail` falla con 401: ejecuta `gh` y `git push` solos, sin pipes, `cd` ni `$(...)`.
- El sandbox no existe en Windows nativo: allí solo quedan las reglas `deny`. Tampoco aplica a lo que el usuario ejecuta en su propia terminal.
- Si un comando necesita otra red u otra ruta, avisa qué restricción encontró; ampliar el sandbox lo decide el usuario.

## CI

`.github/workflows/ci.yml` tiene tres jobs:

- **gitleaks:** revisa el historial completo en todas las ramas. Su versión se lee de `.pre-commit-config.yaml`; si la cambias, cámbiala solo allí.
- **ruff:** solo en Ubuntu.
- **pruebas:** en Ubuntu siempre; en Windows solo en pull requests hacia `main` y en push a `main`.

CI genera un `DJANGO_SECRET_KEY` efímero y enmascarado en cada ejecución.

`main` no tiene protección en GitHub, porque la organización está en GitHub Free (ver `docs/decisiones/0001-proteccion-de-main-sin-github-team.md`). El hook `no-commit-to-branch` de pre-commit rechaza los commits directos a `main`: trabaja siempre en una rama y fusiona por PR con CI en verde.

Al agregar un hook o cambiar un `rev` en `.pre-commit-config.yaml`, el usuario ejecuta `uv run pre-commit install-hooks` **en su terminal**. Dentro del sandbox de Claude Code la descarga falla con `Proxy CONNECT aborted`: pre-commit borra `GIT_CONFIG_PARAMETERS`, que es la variable con la que el sandbox le pasa a git la autenticación de su proxy. Con los hooks ya en caché, `git commit` funciona en el sandbox.
