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

## Arquitectura

- `config/entorno.py` (`cargar_env()`) carga el `.env` **antes** de elegir `DJANGO_SETTINGS_MODULE`. Lo llaman `manage.py`, `config/wsgi.py` y `base.py`, y no pisa variables que ya estén en el entorno.
- Settings en `config/settings/`:
  - `base.py`: exige `DJANGO_SECRET_KEY`.
  - `desarrollo.py`: valor por defecto de `manage.py`; motor simulado.
  - `produccion.py`: valor por defecto de `wsgi.py`; `DEBUG=False`.
  - `validacion.py`: solo lectura sobre un respaldo importado.
  - `pruebas.py`: usado por pytest; `MOTOR_SIMULADO=True` fijo, SQLite en memoria y hasher MD5.
- Apps en `apps/`: `cuentas` (usuarios, roles, auditoría), `contrataciones` (dominio y tablero), `motor` (prompts, cliente Claude, reglas puras, fuentes de documentos), `corridas` (cola en la BD + worker como comando de Django), `reportes` (Excel) y `respaldos`. El motor no depende de la interfaz. Django y el worker se comunican solo a través de la base de datos.
- `AUTH_USER_MODEL = "cuentas.Usuario"` (subclase de `AbstractUser`) existe desde la migración `0001`. Nunca uses `django.contrib.auth.models.User`; usa `get_user_model()` o `settings.AUTH_USER_MODEL`.
- `legado/` es solo referencia: no se modifica y está excluido de ruff.

## Convenciones

- El código y los nombres de dominio van en español (`Profesor`, `Corrida`, `es_valido`, `cargar_env`). Los mensajes de commit pueden ir en inglés.
- **Nunca** pongas datos reales de Gestión Humana en el repositorio: ni PDFs, ni cédulas, ni nombres, ni Excel históricos. Para pruebas usa datos sintéticos en `tests/fixtures/`.
- La validación con respaldos reales (`importar_respaldo`, settings `validacion`) se hace en un **clon aparte, fuera de este repositorio** (p. ej. `~/validacion-contrataciones/`), donde **nunca se abre Claude Code**. En este repositorio no se importan respaldos reales.
- En desarrollo y en pruebas se usa el motor simulado (`MOTOR_SIMULADO=True`). Ninguna prueba debe llamar a la API de Anthropic.
- **Nunca leas ni imprimas el `.env`** ni sus variantes. Tampoco leas bases de datos (`*.db`, `*.sqlite3`) ni respaldos (`*.zip`, `respaldos/`): un respaldo importado contiene datos reales. Para saber qué variables existen, consulta `.env.example`. Si una variable nueva hace falta, agrégala a `.env.example` sin valor y pide al usuario que la complete.
- `.claude/settings.json` niega leer esos archivos con `Read` y con comandos de Bash comunes (`cat`, `head`, `grep`, `python -c open(...)`, `sqlite3`, `unzip`…). Es una **barrera de apoyo, no una garantía**: los patrones no cubren todas las formas de leer un archivo (por ejemplo, un `grep -r` sin nombrarlo). La regla de arriba aplica igual.
- Variantes del `.env` permitidas: `.env.local`, `.env.desarrollo`, `.env.produccion` y `.env.validacion`. Una variante con otro nombre no queda cubierta por la negación hasta que se agregue a `.claude/settings.json`.
- Los secretos (`DJANGO_SECRET_KEY`, `ANTHROPIC_API_KEY`, `CLAVE_RESPALDO`) salen solo del `.env`, sin valores por defecto en el código.

## CI

`.github/workflows/ci.yml` tiene tres jobs:

- **gitleaks:** revisa el historial completo en todas las ramas. Su versión se lee de `.pre-commit-config.yaml`; si la cambias, cámbiala solo allí.
- **ruff:** solo en Ubuntu.
- **pruebas:** en Ubuntu siempre; en Windows solo en pull requests hacia `main` y en push a `main`.

CI genera un `DJANGO_SECRET_KEY` efímero y enmascarado en cada ejecución.

`main` no tiene protección en GitHub, porque la organización está en GitHub Free (ver `docs/decisiones/0001-proteccion-de-main-sin-github-team.md`). El hook `no-commit-to-branch` de pre-commit rechaza los commits directos a `main`: trabaja siempre en una rama y fusiona por PR con CI en verde.

Al agregar un hook o cambiar un `rev` en `.pre-commit-config.yaml`, el usuario ejecuta `uv run pre-commit install-hooks` **en su terminal**. Dentro del sandbox de Claude Code la descarga falla con `Proxy CONNECT aborted`: pre-commit borra `GIT_CONFIG_PARAMETERS`, que es la variable con la que el sandbox le pasa a git la autenticación de su proxy. Con los hooks ya en caché, `git commit` funciona en el sandbox.
