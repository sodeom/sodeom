# AGENTS.md

Privacy-first Flask search engine: SearXNG aggregator with an in-app Cloudflare-Worker proxy fallback.

## Commands

```bash
python app.py                     # dev server 0.0.0.0:9999; reads .env; FLASK_DEBUG=1 enables debug
gunicorn -w 4 -b 0.0.0.0:9999 app:app
bash start.sh                     # creates .venv, pip installs requirements.txt, runs app.py
python -m unittest test_everything # full suite; slow/integration parts boot local SearXNG
python -m unittest test_everything.SodeomSmokeTest   # fast offline smoke only
python test_search.py             # needs a running server on localhost:9999
python test_proxy_working.py      # needs a running server; probes proxy config
bash test.sh [BASE_URL]           # deployed-instance diagnostic
```

- No lint, typecheck, formatter, CI, or pre-commit config. Run smoke tests as verification.
- `requirements.txt` recursively includes `searxng_src/requirements.txt`; first install is heavy.
- `python`/`python3`: repo is 3.10+ (badge); use the `.venv` from `start.sh`.

## Architecture gotchas

- `app.py` is only `from core import create_app`; real factory is `core/__init__.py:create_app()`. `main.py` is equivalent.
- Load order: `core/__init__.py` calls `dotenv.load_dotenv()` before local imports. `core/services/ai_client.py` builds the OpenAI client and selects `DEFAULT_MODEL` at import time. Do not reorder.
- SearXNG: subprocess on `localhost:8888` using `searxng_src/settings_local.yml`; starts a proxy subprocess (`proxy_simple.py --port 8080`) first. Disabled only by `SEARXNG_DISABLE_LOCAL_START=1`, not by setting `SEARXNG_URL`. `SEARXNG_PYTHON` or nearest `.venv/bin/python` (up to 5 parents) is used, else `sys.executable`. Logs: `/tmp/searxng.log`, `/tmp/proxy.log`.
- `SEARXNG_URL` is a single additional fallback appended after local; code does not read `SEARXNG_FALLBACKS` despite old docs. Local tries first, external on failure/empty, then Brave/Bing direct proxy fallbacks.
- Search backend: `search/results.py` (shim at root `results.py`), cached in memory (TTL 5 min, max 300). Queried by `core/routes/search.py`; blueprints registered in `core/routes/__init__.py`.
- `userdb.py` at root is a shim; real code is `db/userdb.py` (SQLite, path via `USER_DB_PATH`, default `userdb.sqlite3` relative to CWD).
- Root-level `results.py`/`userdb.py` are shims; edit `search/results.py`/`db/userdb.py`.
- AI: `client` and `_DEFAULT_MODEL` chosen at import from env (`OLLAMA_API_KEY`+`OPENAI_ENDPOINT`+`MODEL_NAME` > `MISTRAL_API_KEY` > `GITHUB_TOKEN` > none). `_DEFAULT_MODEL` defaults to `mistral-small-latest` when no key (routes error). `DEFAULT_MODEL` env overrides the model string only; it does not create a client. OpenCode models require `OPENCODE_API_KEY` and route to the OpenCode endpoint independently.
- `PROXY_WORKER_URL` has a hardcoded default worker, so unset it leaves the proxy enabled. Setting it to an empty string disables the Python-side proxy (`_USE_PROXY` false) but the proxy subprocess still starts and serves port 8080.
- If `OLLAMA_API_KEY` (URL) + `OPENAI_ENDPOINT` (key) + `MODEL_NAME` are set, they take precedence for the AI client, `DEFAULT_MODEL` becomes `MODEL_NAME`, and `/v1/models` exposes only that model.
- Watchdog restarts SearXNG if port 8888 dies; it does not restart the port-8080 proxy.
- CSS cache busting: `static_ver` in templates is MD5 of `static/*.css` only (non-recursive).

## Environment variables

```bash
FLASK_SECRET_KEY=...            # random per-process key if unset
FLASK_DEBUG=1                   # enables debug in app.py/main.py
SEARXNG_URL=https://searx.be    # single external fallback, production/PythonAnywhere
SEARXNG_DISABLE_LOCAL_START=1   # required for external-only deployments
SEARXNG_PYTHON=/path/to/python  # interpreter for SearXNG subprocess
PROXY_WORKER_URL=https://...    # Cloudflare Worker for restricted hosts (hardcoded default if unset)
USER_DB_PATH=/path/userdb.sqlite3
GITHUB_TOKEN / MISTRAL_API_KEY / OPENCODE_API_KEY / DEFAULT_MODEL   # AI routes
OLLAMA_API_KEY=https://ollama.com/v1/models   # Ollama-compatible base URL (optionally ending /models)
OPENAI_ENDPOINT=...                          # API key for that endpoint (legacy name)
MODEL_NAME=beam                              # becomes DEFAULT_MODEL and the only /v1 model when Ollama config is present
```

## Deployment notes

- PythonAnywhere: set `SEARXNG_URL` and `PROXY_WORKER_URL`, and set `SEARXNG_DISABLE_LOCAL_START=1`. See `PYTHONANYWHERE_DEPLOYMENT.md` for details (that doc still mentions removed `SEARXNG_FALLBACKS`).
- Privacy/security headers are attached by `core/middleware.py:add_privacy_headers()` via `after_request`. CSP includes Google Fonts. Don't remove CSP/DNT/referrer headers casually; update CSP when adding external assets.
- `RealSearchTests` in `test_everything.py` `pkill`s SearXNG and boots a live instance/network; they can disrupt a running dev server. Use `SodeomSmokeTest` for routine changes.

## Testing notes

- Smoke suite patches `core.services.searxng.start_searxng` (returns None) and sets `SEARXNG_URL=https://example.invalid`, so it stays offline/deterministic.
- No snapshots; frontend template routes are asserted 200 in `test_static_pages`.