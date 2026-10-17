# AGENTS.md

Privacy-first Flask search engine. See `CLAUDE.md` for architecture; this file covers what an agent would otherwise get wrong.

## Commands

```bash
python app.py                  # dev server on 0.0.0.0:9999 (reads .env)
gunicorn -w 4 -b 0.0.0.0:9999 app:app   # production
bash start.sh                  # creates .venv, installs requirements.txt, runs app.py
python -m unittest test_everything       # offline smoke suite (mocks SearXNG/network)
bash test.sh [BASE_URL]        # production diagnostic against a deployed instance
python test_search.py          # requires a live server on localhost:9999
python test_proxy_working.py   # requires live server; probes proxy config
```

- No lint, typecheck, formatter, CI workflow, or pre-commit config exists. Only the unittest smoke suite (`test_everything.py`) runs offline; the other `test_*.py` scripts need a running server and network.
- `requirements.txt` recursively includes `searxng_src/requirements.txt` (vendored SearXNG has heavy deps). `pip install -r requirements.txt` installs everything.

## Architecture gotchas

- `app.py` is just `from core import create_app`. Real entrypoint: `core/__init__.py:create_app()`.
- `core/__init__.py` calls `dotenv.load_dotenv()` **before** importing local modules — `core/services/ai_client.py` builds the OpenAI client and picks `DEFAULT_MODEL` **at import time** from env vars. Never reorder those imports.
- SearXNG runs as a subprocess (`core/services/searxng.py:start_searxng()`) on `localhost:8888` from `searxng_src/`; a proxy subprocess (`proxy_simple.py`) starts on port 8080 first. Auto-restart via watchdog. Logs to `/tmp/searxng.log`.
- Search backend: `search/results.py` (`search_web`, `search_images`, etc.), queried by `core/routes/search.py`. In-memory result cache with TTL.
- Blueprints live in `core/routes/` (`search.py`, `ai.py`, `pages.py`), registered in `core/routes/__init__.py:register_blueprints()`.
- `userdb.py` at root is a backward-compat shim; real code is `db/userdb.py` (SQLite, path via `USER_DB_PATH`).

## Environment variables

Set in `.env` (loaded automatically). `SEARXNG_URL` is a single external fallback used only when localhost:8888 is down; ignore `SEARXNG_FALLBACKS` mentioned in old docs — it is not read by any Python code.

```bash
FLASK_SECRET_KEY=...            # falls back to random per-process key if unset
SEARXNG_URL=https://searx.be    # external instance (production/PythonAnywhere)
SEARXNG_DISABLE_LOCAL_START=1   # skip subprocess spawn
SEARXNG_PYTHON=/path/to/python  # interpreter for SearXNG subprocess
PROXY_WORKER_URL=https://...    # Cloudflare Worker for restricted hosts
GITHUB_TOKEN / MISTRAL_API_KEY / OPENCODE_API_KEY   # AI routes; Mistral wins over GitHub for DEFAULT_MODEL
```

- `PROXY_WORKER_URL` has a **hardcoded default** worker URL in `search/results.py`, `core/services/image.py`, and `proxy_simple.py` — unset/blank does not disable the proxy; patch the code if you need direct requests.
- AI routes return an error until a token is configured; `client` is `None` otherwise.

## Deployment notes

- Designed for PythonAnywhere: set `SEARXNG_URL` to a public instance and `PROXY_WORKER_URL`; local subprocess is often disabled there. See `PYTHONANYWHERE_DEPLOYMENT.md`.
- Privacy/security headers attached via `after_request` in `core/middleware.py:add_privacy_headers()`. Don't remove CSP/DNT/referrer headers casually.
- CSS cache-busting: templates use `static_ver` Jinja global (hashed from static folder).
