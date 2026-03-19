# AGENTS.md
Agent guidance for `opencode-bot`.

## Scope and architecture
- Language: Python (`>=3.8`)
- Package root: `src/opencode_bot`
- Entrypoints: `run.py`, `opencode_bot.main:run`
- Tests: `pytest` in `tests/` (`pyproject.toml`)
- Type config: `pyrightconfig.json` (`typeCheckingMode = basic`)

Key paths:
- `src/opencode_bot/` runtime logic
- `tests/` unit tests
- `scripts/opencode-botctl.sh` process helper
- `.env.example`, `config/bot.env.example` config templates

## Cursor/Copilot rules check
No repo-level rule files were found during analysis:
- `.cursor/rules/` missing
- `.cursorrules` missing
- `.github/copilot-instructions.md` missing
If these files are added later, follow them as higher-priority instructions.

## Setup commands
Install dependencies:
```bash
python -m pip install -e .
python -m pip install -r requirements.txt
```
Conda-style equivalent (if your environment uses it):
```bash
conda run -n y6_test python -m pip install -e .
conda run -n y6_test python -m pip install -r requirements.txt
```
Run service locally:
```bash
python run.py
```
Operational script:
```bash
scripts/opencode-botctl.sh start
scripts/opencode-botctl.sh status
scripts/opencode-botctl.sh stop
```
Health check:
```bash
curl -s http://127.0.0.1:8080/healthz
```

## Build/lint/test commands
This repo currently has no Ruff/Black/isort/flake8 config.

Build/package:
```bash
python -m pip install -e .
python -m build
```
Notes:
- `python -m build` needs package `build` installed.
- Editable install + tests is usually enough for normal code changes.

Type/lint check:
```bash
python -m pyright
```

Run all tests:
```bash
python -m pytest
python -m pytest -q
```

Run a single test file:
```bash
python -m pytest tests/test_service.py
```

Run a single test (preferred during iteration):
```bash
python -m pytest tests/test_service.py::test_bind_and_relay_flow
```

Run by keyword:
```bash
python -m pytest -k "bind and relay"
```

Stop on first failure:
```bash
python -m pytest -x
```

## Code style guidelines

### Imports
- Order: stdlib, third-party, local package imports.
- Prefer explicit imports; no wildcard imports.
- Keep per-file style consistent with surrounding code.

### Formatting and structure
- Use 4-space indentation.
- Prefer early returns over deeply nested branches.
- Keep functions focused and readable.
- Avoid formatting-only diffs in unrelated lines.
- Preserve quote/docstring style in touched files.

### Types and interfaces
- Add type hints for new/changed public functions.
- Keep return types explicit, especially for async methods.
- Use dataclasses for simple structured records (existing pattern).
- Avoid `Any` except at unavoidable integration boundaries.
- Keep optional typing style consistent within a file.

### Naming conventions
- `snake_case` for functions, variables, modules.
- `PascalCase` for classes.
- Prefix private/internal helpers with `_`.
- Reuse established domain names (`session_id`, `peer_key`, `receive_id`).
- Do not silently rename command strings or env var names.

### Error handling
- Fail safely at service/API boundaries with user-readable messages.
- Catch specific exceptions when practical (`JSONDecodeError`, `IntegrityError`, etc.).
- Keep transient-retry behavior for SQLite lock/busy cases.
- Avoid broad `except Exception` unless explicitly justified.

### Logging
- Use structured log messages with `%s` placeholders.
- Include context keys (session, peer, message ID) where useful.
- Never log secrets/tokens/credentials.

### Async/concurrency
- Keep async work inside async methods.
- Use `asyncio.run(...)` only at sync boundaries.
- Preserve fast-ack + background persistence behavior in relay flow.
- Do not introduce blocking calls in async paths unless isolated.

### API and persistence compatibility
- Preserve message dedup/idempotency behavior.
- Keep SQLite WAL and lock-handling safeguards intact.
- Keep endpoint response shapes backward-compatible unless intentionally changed.
- Prefer additive command aliases over removing existing commands.

### Tests
- Add/update pytest tests for each behavior change.
- Prefer deterministic tests with local fakes/mocks.
- Use `tmp_path` for filesystem/DB isolation.
- Assert both outputs and side effects when relevant.

## Agent checklist before finishing
1. Run targeted tests for touched modules.
2. Run full `python -m pytest` when feasible.
3. Run `python -m pyright` when available.
4. Verify no secrets or local env files are staged.
5. Update docs/examples when behavior or commands changed.

Last updated: 2026-03-19
