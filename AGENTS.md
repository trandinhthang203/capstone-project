# Repository Guidelines

## Project Structure & Module Organization

The FastAPI application lives in `app/`. HTTP routes are under `app/api/`, database models under `app/models/`, validation schemas under `app/schemas/`, and business logic under `app/services/`. Agent workflow code is grouped in `app/agents/`, with shared graph, state, memory, and retrieval components in `app/agents/base/`. Alembic revisions belong in `migrations/versions/`.

Use `scripts/ingestion/` for data-loading pipelines and `scripts/eval/` for retrieval or generation evaluations. Automated tests live in `tests/`. Treat `data/`, `forms/`, `backup/`, and `notebooks/` as datasets, document assets, or experiments rather than application modules.

## Build, Test, and Development Commands

- `python -m venv .venv` creates a local environment; activate it before installing packages.
- `pip install -r requirements.txt` installs runtime dependencies. Install `pytest` and `pytest-asyncio` separately when needed for development.
- `uvicorn app.main:app --reload --port 8000` runs the API locally; interactive docs are at `/docs`.
- `pytest -q` runs the complete test suite; use `pytest tests/test_api_auth.py -q` for one module.
- `alembic upgrade head` applies all database migrations.
- `docker build -t dvc-agents .` builds the Python 3.11 production image. `docker compose up -d` runs the configured published image using `.env`.

## Coding Style & Naming Conventions

Follow PEP 8 with four-space indentation. Use `snake_case` for modules, functions, variables, and test names; use `PascalCase` for classes and Pydantic/SQLAlchemy models. Keep routers thin and move reusable logic into services or agent-base modules. Add type hints to public functions and async functions where practical. No formatter or linter is currently enforced, so keep imports grouped and changes consistent with nearby code.

## Testing Guidelines

Tests use pytest, including `pytest.mark.asyncio`, fixtures, monkeypatching, and FastAPI's `TestClient`. Name files `test_<feature>.py` and tests `test_<expected_behavior>`. Isolate external databases, LLMs, and vector stores with fakes or monkeypatches. Add regression tests for route, schema, migration-related, or workflow changes. No coverage threshold is configured; cover each changed behavior and failure path.

## Commit & Pull Request Guidelines

Recent history favors concise Conventional Commit-style subjects such as `feat(ingestion): ...`, `fix(migrations): ...`, and `refactor: ...`. Keep each commit focused and imperative. Pull requests should explain behavior changes, configuration or migration steps, tests run, and linked issues. Include request/response examples for API changes and screenshots or workflow diagrams for visible graph/UI changes.

## Security & Configuration

Never commit `.env`, credentials, tokens, or service-account JSON. Document new environment variables in the PR, use test-only secrets in tests, and review migrations before applying them to shared databases.
