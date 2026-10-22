# 0001. Protección de `main` sin GitHub Team

- **Estado:** aceptada
- **Fecha:** 2026-10-21

## Contexto

Desde la Fase 1, cada fase va en su propia rama y se fusiona a `main` por pull request cuando CI pasa. Lo ideal es que GitHub lo haga cumplir: exigir PR, exigir los checks `Pruebas (ubuntu-latest)`, `Pruebas (windows-latest)`, `Ruff` y `Secretos (gitleaks)`, y bloquear el force push y el borrado de `main`.

La organización UVI-TECH está en el plan **GitHub Free** y el repositorio es privado. En ese plan no hay protección de ramas ni rulesets para repositorios privados: la API responde `403 Upgrade to GitHub Pro or make this repository public`. Hacer público el repositorio no es opción, por la naturaleza del proyecto.

## Decisión

Mientras no se adquiera GitHub Team:

1. El hook `no-commit-to-branch --branch main` de pre-commit rechaza los commits directos a `main` en cada clon que haya corrido `uv run pre-commit install`.
2. El resto queda en manos de la disciplina del equipo: trabajar en ramas, abrir PR, esperar CI en verde y no hacer force push ni borrar `main`.

## Consecuencias

- El hook es solo del lado del cliente. Se salta con `git commit --no-verify`, no actúa en un clon sin `pre-commit install` y no impide un `git push` de commits creados por otra vía. Tampoco bloquea fusionar en GitHub un PR con CI en rojo.
- CI sigue corriendo en cada push y en cada PR, así que un fallo se ve aunque no bloquee.
- Si se adquiere GitHub Team, la protección se activa con la configuración de abajo y este ADR pasa a "reemplazada".

## Configuración preparada para GitHub Team

```bash
gh api -X PUT repos/UVI-TECH/review-procurements-GH/branches/main/protection --input proteccion.json
```

`proteccion.json`:

```json
{
  "required_status_checks": {
    "strict": true,
    "checks": [
      {"context": "Secretos (gitleaks)", "app_id": 15368},
      {"context": "Ruff", "app_id": 15368},
      {"context": "Pruebas (ubuntu-latest)", "app_id": 15368},
      {"context": "Pruebas (windows-latest)", "app_id": 15368}
    ]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "required_approving_review_count": 0,
    "dismiss_stale_reviews": false,
    "require_code_owner_reviews": false
  },
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_conversation_resolution": false
}
```

- `app_id` 15368 es GitHub Actions. Los nombres de los checks tienen que coincidir con los `name` de los jobs en `.github/workflows/ci.yml`.
- `required_approving_review_count: 0` exige PR sin exigir aprobaciones, porque el equipo es pequeño.
- `enforce_admins: true` hace que la regla aplique también a los administradores de la organización.
