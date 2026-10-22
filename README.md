# Revisión de Contrataciones

App Django local para revisar los documentos de contratación de Gestión Humana (UNIAJC). El plan completo y las fases están en [`docs/plan.md`](docs/plan.md).

## Puesta en marcha (desarrollo)

Requisitos: [uv](https://docs.astral.sh/uv/). Python 3.12 se instala solo.

```bash
uv sync
cp .env.example .env        # completa DJANGO_SECRET_KEY (instrucciones dentro del archivo)
uv run pre-commit install
uv run python manage.py migrate
uv run python manage.py runserver
```

Pruebas y estilo:

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

Nunca subas el `.env` ni datos reales de Gestión Humana al repositorio.
