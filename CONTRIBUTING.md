# Contributing to TestAgent

Thanks for your interest! TestAgent is at an early stage (v0.1), so feedback is as valuable as code.

## Ways to help

- **Try it** with the demo or your own app and [open an issue](https://github.com/Coral-TSS/testagent/issues) with what worked and what did not.
- **Report bugs** using the bug template (steps, expected vs. actual, logs without secrets).
- **Propose features** using the feature template; explain the testing problem you want to solve.
- **Send pull requests** for bugs, docs, tests or features discussed in an issue.

## Development setup

See [docs/deployment.md](docs/deployment.md#local-development). In short:

```bash
uv sync
cp .env.example .env   # point TESTAGENT_DATABASE_URL / TESTAGENT_TEST_DATABASE_URL to PostgreSQL 17
uv run python ops/init_db.py
PLAYWRIGHT_BROWSERS_PATH=0 uv run playwright install chromium
cd web && npm ci && cd ..
```

## Before you open a pull request

All of these must pass:

```bash
uv run ruff check . && uv run ruff format --check .
uv run pytest -q
cd web && npm run lint && npx tsc -b --noEmit && npm test && npm run build
```

Guidelines:

- **Tests first.** Add or update a test that fails without your change (pytest for the backend, Vitest +
  Testing Library for the UI). Agent behaviour is tested with the deterministic `FakeChatModel`
  (`src/testagent/agent/fake.py`); tests never call a real LLM.
- **Database changes** go into a new numbered SQL migration in `src/testagent/migrations/`; never edit a
  migration that has been released.
- **API changes**: regenerate the OpenAPI types with `uv run python ops/export_openapi.py` and
  `cd web && npm run gen:api`.
- **Human gates stay human.** Actions such as confirming requirements, freezing a version, setting cases
  ready or choosing a defect cause must not be performed by the agent.
- **No secrets** in code, tests, fixtures, screenshots or logs. `tests/unit/test_no_credentials.py` guards
  against connection strings with passwords.
- Keep pull requests focused, describe the why, and link the issue.

## Licensing

By contributing you agree that your contributions are licensed under the [Apache License 2.0](LICENSE).
