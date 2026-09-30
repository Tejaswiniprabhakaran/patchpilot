# Decisions

Every deviation from the prescribed stack, and every ambiguous choice, with its reason.

## D1 — pip + venv instead of uv (2026-09-30)

**Decision:** manage the environment with `python -m venv` and `pip install -e ".[dev]"`.

**Why:** `uv` is not installed on the development machine and the project brief lists pip + venv
as the accepted fallback. Using the same plain-pip install locally and in CI means a fresh clone
needs nothing beyond Python 3.11.

**Rejected:** installing uv only locally (CI and the README would then diverge from what is
actually used day to day).

## D2 — hatchling as the build backend (2026-09-30)

**Decision:** `hatchling` with the `src/` layout.

**Why:** minimal configuration, supports editable installs, no `setup.py`.

## D3 — No licence file yet (2026-09-30)

**Decision:** the repository is public but has no `LICENSE` for now, at the owner's request.
To be revisited before v1.0.0.

## D4 — Docker integration tests are excluded from CI (2026-09-30)

**Decision:** tests marked `integration` run locally only; CI runs `pytest -m "not integration"`.

**Why:** they need benchmark images and a Docker daemon with real resource limits; the unit tests
mock Docker so CI stays fast and deterministic.
