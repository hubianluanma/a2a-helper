# Contributing to a2a-helper

Thanks for helping out! This project is intentionally small — keep changes
focused, keep the diff small, keep the test count small.

## Setup

```bash
git clone https://github.com/hubianluanma/a2a-helper
cd a2a-helper
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Before opening a PR

```bash
ruff check .          # lint
ruff format .         # autoformat (run if your editor doesn't)
pytest                # all 3 smoke tests must pass
```

CI runs the same three commands on Linux + Python 3.10/3.11/3.12.

## Commit messages

Conventional Commits, scoped:

```
feat(server): add /v1/agents/<id> delete endpoint
fix(client): handle WS disconnect during claim()
docs: clarify hub port in README
test: cover failed-claim retry path
refactor(echo_agent): drop redundant skill echo/upper
```

`<scope>` is the module name when applicable. Keep the subject under 72 chars.

## Pull requests

- One logical change per PR. If you're fixing a typo and adding an endpoint,
  that's two PRs.
- Update `CHANGELOG.md` under "Unreleased" if the change is user-visible.
- PR title follows the commit convention above. The squash-merge message uses
  the PR title.
- If your change adds a public API (HTTP route, WS event, client method),
  update `docs/` and the README's protocol table.

## Code style

- Python ≥ 3.10. Use modern syntax: `list[str]`, `dict[str, Any] | None`,
  match statements are fine.
- Line length 100 (ruff config). Don't manually wrap lines for length alone.
- Prefer stdlib + the existing dependency set. New runtime dependency? Open
  an issue first.
- Keep functions short. If a function does setup + dispatch + IO, split it.

## Tests

- New behavior = at least one test. Bug fix = regression test that fails on
  `main` before the fix.
- Tests live in `tests/`, named `test_*.py`, async ones use `@pytest.mark.asyncio`.
- Don't mock what you can exercise against the real `app` (see
  `tests/test_smoke.py` for the spawn-a-uvicorn-on-a-free-port pattern).

## Out of scope (yet)

These need an issue + discussion first:

- Authentication / multi-tenant support
- TLS termination inside the package
- Postgres / MySQL backends
- Horizontal scale-out

## Reporting bugs

Open a GitHub issue with:

1. What you ran (command, OS, Python version)
2. What you expected
3. What happened (full traceback, request/response if HTTP)
4. Minimal repro if possible

Security issues: see [SECURITY.md](SECURITY.md) — please don't open a public issue.
