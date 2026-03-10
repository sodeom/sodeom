#!/usr/bin/env bash
# Sodeom Production Diagnostic Script
# Run on your PythonAnywhere server and paste the output back.

BASE_URL="${1:-https://sodeom.com}"

SEP="━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
PASS="[PASS]"
FAIL="[FAIL]"
INFO="[INFO]"

pass() { echo "$PASS $1"; }
fail() { echo "$FAIL $1"; }
info() { echo "$INFO $1"; }
section() { echo ""; echo "$SEP"; echo "  $1"; echo "$SEP"; }

echo "Sodeom Production Test"
echo "Target: $BASE_URL"
echo "Date:   $(date)"

# ── 1. Git ────────────────────────────────────────────────────────────────────
section "1. Git Status"
if command -v git &>/dev/null; then
    info "Branch:  $(git rev-parse --abbrev-ref HEAD 2>/dev/null)"
    info "Commit:  $(git log --oneline -1 2>/dev/null)"
    info "Remote:  $(git log --oneline origin/main -1 2>/dev/null)"
    BEHIND=$(git rev-list HEAD..origin/main --count 2>/dev/null)
    [ "$BEHIND" = "0" ] && pass "Up to date with origin/main" || fail "Behind origin/main by $BEHIND commit(s) — run git pull"
else
    info "git not available"
fi

# ── 2. Python environment ─────────────────────────────────────────────────────
section "2. Python Environment"
if command -v python3 &>/dev/null; then
    info "Python: $(python3 --version 2>&1)"
else
    fail "python3 not found"
fi

PYTHON=""
for p in .venv/bin/python python3 python; do
    if command -v "$p" &>/dev/null || [ -f "$p" ]; then
        PYTHON="$p"
        break
    fi
done
info "Using: $PYTHON"

# Check key packages
for pkg in flask openai requests; do
    if $PYTHON -c "import $pkg" 2>/dev/null; then
        VER=$($PYTHON -c "import $pkg; print(getattr($pkg,'__version__','?'))" 2>/dev/null)
        pass "$pkg ($VER)"
    else
        fail "$pkg NOT installed"
    fi
done

# ── 3. App files ──────────────────────────────────────────────────────────────
section "3. Key Files"
for f in app.py core/__init__.py core/routes/search.py search/results.py templates/index.html .env; do
    [ -f "$f" ] && pass "$f" || fail "$f MISSING"
done

# ── 4. Environment variables ──────────────────────────────────────────────────
section "4. Environment Variables"
$PYTHON -c "
import os, sys
sys.path.insert(0,'.')
try:
    import dotenv; dotenv.load_dotenv()
except: pass
token = os.environ.get('GITHUB_TOKEN','')
if token:
    print('[PASS] GITHUB_TOKEN set (' + str(len(token)) + ' chars)')
else:
    print('[FAIL] GITHUB_TOKEN not set — AI answers will not work')
" 2>/dev/null

# ── 5. HTTP endpoint tests ────────────────────────────────────────────────────
section "5. HTTP Endpoints"

_get() {
    local url="$1"
    local label="$2"
    local expect="$3"
    local result
    result=$(curl -s -o /tmp/_sodeom_resp -w "%{http_code}" --max-time 15 "$url" 2>/dev/null)
    local body
    body=$(cat /tmp/_sodeom_resp 2>/dev/null)
    if [ "$result" = "200" ]; then
        if [ -n "$expect" ] && ! echo "$body" | grep -qi "$expect" 2>/dev/null; then
            fail "$label — HTTP 200 but expected content '$expect' not found"
            echo "       Response snippet: $(echo "$body" | head -c 200)"
        else
            pass "$label (HTTP 200)"
        fi
    else
        fail "$label — HTTP $result"
        echo "       Response: $(echo "$body" | head -c 300)"
    fi
}

_get "$BASE_URL/" "Homepage" "Sodeom"
_get "$BASE_URL/?q=python" "Web search (python)" "result"
_get "$BASE_URL/api/wiki?q=Albert+Einstein" "Wiki panel API" "Albert Einstein"
_get "$BASE_URL/images?q=cat" "Image search" ""
_get "$BASE_URL/news?q=technology" "News search" ""

# ── 6. Wiki API JSON check ────────────────────────────────────────────────────
section "6. Wiki API Response Detail"
WIKI_RESP=$(curl -s --max-time 15 "$BASE_URL/api/wiki?q=Python+programming+language" 2>/dev/null)
if echo "$WIKI_RESP" | grep -q '"infoboxes"'; then
    COUNT=$(echo "$WIKI_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('infoboxes',[])))" 2>/dev/null)
    if [ "$COUNT" -gt 0 ] 2>/dev/null; then
        TITLE=$(echo "$WIKI_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['infoboxes'][0].get('infobox','?'))" 2>/dev/null)
        pass "Wiki infoboxes: $COUNT returned | Title: $TITLE"
    else
        fail "Wiki API returned 0 infoboxes for 'Python programming language'"
        echo "       Full response: $(echo "$WIKI_RESP" | head -c 400)"
    fi
else
    fail "Wiki API did not return JSON with 'infoboxes' key"
    echo "       Response: $(echo "$WIKI_RESP" | head -c 400)"
fi

# ── 7. AI endpoint ────────────────────────────────────────────────────────────
section "7. AI Endpoint"
AI_RESP=$(curl -s --max-time 20 "$BASE_URL/ai?query=what+is+2+plus+2" 2>/dev/null)
if echo "$AI_RESP" | grep -qi '"answer"'; then
    ANSWER=$(echo "$AI_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(str(d.get('answer',''))[:80])" 2>/dev/null)
    pass "AI response received: $ANSWER"
else
    fail "AI endpoint did not return expected JSON"
    echo "       Response: $(echo "$AI_RESP" | head -c 400)"
fi

# ── 8. SearXNG (local only) ───────────────────────────────────────────────────
section "8. SearXNG (local subprocess)"
if curl -s --max-time 3 "http://localhost:8888/search?q=test&format=json" | grep -q '"results"' 2>/dev/null; then
    pass "SearXNG running on localhost:8888"
else
    info "SearXNG not on localhost:8888 (normal on PythonAnywhere — using external engines)"
fi

echo ""
echo "$SEP"
echo "  Done. Copy all output above and paste it back."
echo "$SEP"
echo ""
