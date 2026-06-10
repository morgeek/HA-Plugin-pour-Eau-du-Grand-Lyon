# AGENTS.md — Guide for AI agents working on this repo

This file is read by AI coding agents (Claude Code, Cursor, Copilot, etc.).
Read it **before** changing code. It encodes the invariants and the mistakes that
have actually broken this project before. Keep it up to date when you learn a new
gotcha.

## What this is

A **Home Assistant custom integration** for the *Eau du Grand Lyon* water utility
(France). It polls the provider's cloud API, exposes consumption / cost / quality /
intelligence sensors, and injects long-term statistics into HA's recorder. Domain:
`eau_grand_lyon`. Distributed via **HACS as a custom repository**.

## Layout

```
custom_components/eau_grand_lyon/
  api/            auth.py, client.py, endpoints.py   ← HTTP + OAuth/PKCE
  sensors/        consumption.py, cost.py, quality.py, intelligence.py,
                  global_sensors.py, experimental.py, contract.py, base.py
  coordinator.py  DataUpdateCoordinator: fetch, merge history, inject statistics
  config_flow.py  setup + options + reauth flows
  device.py       shared DeviceInfo helpers (single source for all platforms)
  manifest.json   version lives here (HA + HACS read it)
  strings.json + translations/{fr,en}.json
hacs.json         HACS manifest (NOT the same schema as the action inputs)
tests/            pytest suite, self-contained (no real HA needed)
.github/workflows/tests.yaml   tests + lint + hassfest + HACS validation
```

## Golden rules — do NOT break these

1. **API endpoints live under `/application/...`.** Verified against production:
   - Auth: `/application/auth/...` (login/authorize/token). The `/auth/...` variants **404**.
   - Data: `/application/rest/produits`, `/application/rest/interfaces/ael`. The bare
     `/rest/...` paths **404**. Unauthenticated calls return `401`/`403` (normal), not 404.
   - When in doubt, `curl` the path: `404` = wrong path; `401/403` = right path, needs auth.

2. **`api/client.py` request helpers.** `_get(path, params=None)` and `_post(path, body)`
   prepend `BASE_URL` and delegate to `_do_get`/`_do_post` → `_request`. If you add a call
   site that needs query params, the helper **must forward `params`** — a missing `params`
   kwarg already caused a `TypeError` that broke every refresh. There are regression tests
   for this in `tests/test_api_error_paths.py`.

3. **`hacs.json` is strictly validated.** Allowed keys only (e.g. `name`,
   `content_in_root`, `render_readme`, `homeassistant`, `country`, `zip_release`,
   `filename`). **Never add `category`** — that is an input to the HACS *action*
   (`category: integration` in `tests.yaml`), and putting it in `hacs.json` fails
   validation with "extra keys not allowed". This blocked the HACS check for many commits.

4. **Tests run WITHOUT a real Home Assistant install.** `tests/conftest.py` stubs
   `homeassistant.*`, `aiohttp`, and `voluptuous` in `sys.modules`. The `tests.yaml` CI
   job installs **only** `pytest pytest-asyncio voluptuous` (plus flake8/black). Therefore:
   **any new third-party import in `custom_components/` must be stubbed in `conftest.py`**,
   or collection fails across the whole Python matrix. (`async-lru` once wasn't stubbed and
   broke all of CI.)

5. **No third-party runtime dependencies.** `manifest.json` → `requirements` is empty
   (`async-lru` was removed in 3.1.0 — its class-level cache leaked memory across update
   cycles; the per-cycle cache now lives in `_CycleCachedApi._tasks`). If you add a runtime
   dependency, it must go into `requirements`, be stubbed in `conftest.py`, and survive a
   manual file-copy deploy (HA installs `requirements` automatically, plain copies don't).

6. **Config/options flow + translations.** Any `async_show_form` whose translation strings
   contain `{placeholders}` (see `data_description` in `strings.json`/`translations/*.json`)
   **must pass matching `description_placeholders`**, or the frontend throws
   `formatjs MISSING_VALUE`. Keep `strings.json`, `translations/fr.json`, and
   `translations/en.json` in sync (same keys, same placeholders).

7. **Statistics / units.** Cost statistics must **not** set `unit_class: "monetary"`
   (the recorder rejects it). Use `unit_of_measurement: "EUR"` with no `unit_class`.

## Dev workflow

Run from the repo root.

```bash
# Tests (mirror CI)
pytest tests/ -v                      # 200+ tests; must stay green

# Lint (CI scope = custom_components only; ENFORCED in CI — must be clean)
flake8 custom_components/eau_grand_lyon/ --max-line-length=120 --extend-ignore=E203,W503

# Format (CI black-checks custom_components/ only; tests/ is not black-enforced)
black custom_components/eau_grand_lyon/ --line-length=120
```

- Never commit `.venv/`, `__pycache__/`, `*.pyc`, coverage artifacts (see `.gitignore`).
- When fixing a bug, add a regression test that fails before the fix.
- **Real-HA smoke tests** live in `smoke_tests/` (NOT collected by CI — CI runs `pytest tests/`
  only). They run the integration against a genuine Home Assistant install
  (`pip install pytest-homeassistant-custom-component`) with only the HTTP layer mocked:
  full entry setup, entities, real recorder statistics, options flow, unload. Run them
  before releases that touch coordinator/setup/statistics code — the stub suite cannot
  catch HA-API misuse (see `smoke_tests/test_real_ha.py` header for how to run).

## CI checks that must stay green (run on push/PR to `main`)

- **Tests Python** (3.12 & 3.13, single workflow `tests.yaml`) — flake8 + black + pytest,
  all enforced (no `continue-on-error`)
- **Validation HA (hassfest)** — manifest/translation correctness
- **Validation HACS** — repo structure + `hacs.json`
- **CodeQL** (Analyze actions/python)

## Release process (HACS installs by release tag, not by branch)

1. Bump `version` in `custom_components/eau_grand_lyon/manifest.json` (semver) **and keep
   `pyproject.toml` `version` in sync** (they drifted once: 2.9.5 vs 3.0.4).
2. Add a dated entry at the top of `CHANGELOG.md` (French, Keep-a-Changelog style).
3. Commit, push `main`, **wait for all CI checks to go green**.
4. Tag the green commit: `git tag -a vX.Y.Z -m "..."` then `git push origin vX.Y.Z`.
   (Tag the commit only after CI is green — don't tag prematurely.)
5. Publish a **GitHub Release** from that tag (HACS surfaces it as an update).

## Things that have broken before (learn from these)

- Tagging a release before CI was green → had to abandon the tag.
- `hacs.json` `category` key → persistent HACS validation failure.
- Unstubbed new import (`async_lru`) → entire test matrix red at collection.
- `_get()` missing a `params` kwarg → every data refresh crashed (looked like broken auth).
- Missing `description_placeholders` → options screen translation errors.
- Wrong API base path (`/rest/` vs `/application/rest/`) → 404 on all data fetches.

## Out of scope without explicit human sign-off

- Changing API base URLs or the auth flow (verify against production first).
- Rewriting the statistics injection logic (touches users' recorder history).
- Bumping the minimum `homeassistant` version in `hacs.json`/`manifest.json`.
