# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Sodeom is a privacy-first search engine built with Flask. It aggregates results from SearXNG (a meta-search engine) and proxies requests to protect user privacy. The app can run SearXNG locally as a subprocess or connect to external instances.

## Common Development Commands

```bash
# Run development server (uses .env for configuration)
python app.py

# Run with explicit environment variables
FLASK_DEBUG=1 python app.py

# Run tests
bash test.sh                          # Full diagnostic suite
python test_proxy_working.py          # Proxy configuration test

# Install dependencies
pip install -r requirements.txt

# Production deployment (use WSGI server)
gunicorn -w 4 -b 0.0.0.0:9999 app:app
```

The server starts on `http://0.0.0.0:9999` by default.

## Architecture

### Application Factory Pattern

The app uses Flask's application factory pattern via `core/__init__.py:create_app()`:

1. Loads `.env` file before importing local modules
2. Registers blueprints from `core/routes/` (search, ai, pages)
3. Attaches privacy/security headers via `add_privacy_headers()` middleware
4. Starts SearXNG subprocess (unless `SEARXNG_URL` is set)
5. Sets up CSS cache-busting via `static_ver` template global

### Routing Structure

Routes are organized as Flask blueprints in `core/routes/`:

- `search.py` — Main search routes (`/`, `/api/search`, `/images`, `/videos`, `/news`, `/wiki`, `/placeholder`)
- `ai.py` — AI assistant endpoints
- `pages.py` — Static pages (about, contact, privacy, etc.)

Blueprints are registered in `core/routes/__init__.py:register_blueprints()`.

### Search Backend Architecture

Search is powered by SearXNG, a meta-search engine that queries multiple sources.

**Two operational modes:**

1. **Local SearXNG** (default for development): Runs as subprocess on `localhost:8888`
   - Managed by `core/services/searxng.py:start_searxng()`
   - Auto-starts in background thread; watchdog restarts if it dies
   - Skipped if `SEARXNG_URL` environment variable is set

2. **External SearXNG** (recommended for production/PythonAnywhere):
   - Set `SEARXNG_URL` to a public instance (e.g., `https://searx.be`)
   - Configure fallbacks with `SEARXNG_FALLBACKS` (comma-separated URLs)
   - No subprocess management; pure HTTP requests

**Search flow:**
- `search/results.py` queries SearXNG's JSON API (`/search?format=json`)
- Results cached in memory (5-minute TTL, max 300 entries)
- NSFW content filtered via regex in `_filter_results()`
- Falls back through instances until one returns results

### Cloudflare Worker Proxy

For PythonAnywhere deployment, the app can route external requests through a Cloudflare Worker proxy to bypass whitelist restrictions:

- Set `PROXY_WORKER_URL` in `.env` (e.g., `https://your-proxy.workers.dev`)
- Proxy code in `cloudflare-worker-proxy.js`
- Applied to all external HTTP requests (except localhost)

## Key Environment Variables

```bash
# Required
FLASK_SECRET_KEY=random-secret-string

# For external SearXNG (recommended for production)
SEARXNG_URL=https://searx.be
SEARXNG_FALLBACKS=https://search.sapti.me,https://searx.fmac.xyz

# For PythonAnywhere proxy
PROXY_WORKER_URL=https://your-proxy.workers.dev

# Optional (for AI features)
GITHUB_TOKEN=your_github_token_for_openai_api
```

## File Organization

```
core/
  __init__.py          # App factory, loads .env, starts SearXNG
  middleware.py        # Privacy/security headers, CSS version hashing
  routes/
    __init__.py        # Blueprint registration
    search.py          # Search routes (/, /images, /videos, /news, etc.)
    ai.py              # AI assistant routes
    pages.py           # Static page routes
  services/
    searxng.py         # Local SearXNG subprocess lifecycle
    image.py           # Image fetching/caching utilities
    ai_client.py       # OpenAI API client
search/
  results.py           # SearXNG API client with caching and filtering
templates/             # Jinja2 templates
static/                # CSS, JS, images
searxng_src/           # Local SearXNG source (when running locally)
```

## Privacy & Security

All responses include privacy headers (DNT, Referrer-Policy, Permissions-Policy, CSP, etc.) via `core/middleware.py:add_privacy_headers()`. The app does not log queries or use tracking cookies.

## Deployment Notes

- **Local development**: SearXNG starts automatically as subprocess
- **PythonAnywhere**: Use external SearXNG with `SEARXNG_URL` and optionally `PROXY_WORKER_URL`
- Check `PYTHONANYWHERE_DEPLOYMENT.md` and `DEPLOYMENT_CHECKLIST.md` for detailed setup

## Search API Response Format

Results are normalized to this structure:

```python
{
  "results": [{"title": "...", "link": "...", "description": "...", "engine": "..."}],
  "suggestions": ["..."],
  "corrections": ["..."],
  "infoboxes": [{"infobox": "...", "content": "..."}],
  "answers": [{"answer": "..."}],
  "query": "user query",
  "page": 1,
  "number_of_results": 10
}
```
