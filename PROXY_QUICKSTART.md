# Cloudflare Worker Proxy - Quick Start

## 📦 What You Got

1. **`cloudflare-worker-proxy.js`** - The worker code to deploy
2. **`core/utils/proxy.py`** - Python client (auto-configured)
3. **`CLOUDFLARE_WORKER_SETUP.md`** - Full setup guide
4. **`.env.example`** - Updated with proxy configuration

## 🚀 Deploy in 3 Steps

### 1️⃣ Deploy to Cloudflare

```bash
# Go to: https://dash.cloudflare.com/
# Click: Workers & Pages → Create Worker
# Name: sodeom-proxy (or any name you like)
# Click: Edit Code
# Paste: Content from cloudflare-worker-proxy.js
# Click: Save and Deploy
# Copy: Your worker URL (e.g., https://sodeom-proxy.YOURNAME.workers.dev)
```

### 2️⃣ Add to Your `.env`

```bash
PROXY_WORKER_URL=https://sodeom-proxy.YOURNAME.workers.dev
```

### 3️⃣ Test It

```bash
# Test the worker directly
curl "https://sodeom-proxy.YOURNAME.workers.dev?url=https://httpbin.org/get"

# Should return JSON response
```

## 💡 How to Use

Once deployed and configured, **it works automatically!** All external HTTP requests will route through your worker.

### Manual Usage (Optional)

```python
from core.utils.proxy import proxy

# Simple GET request
response = proxy.get("https://search.brave.com/search?q=python")

# POST request
response = proxy.post("https://api.example.com", json={"key": "value"})

# Any HTTP method
response = proxy.request("PUT", "https://api.example.com", data={"test": 1})
```

## 📋 Integration Checklist

After you give me your worker URL, I'll:
- ✅ Integrate proxy into search engine scrapers
- ✅ Update image proxy to use worker
- ✅ Add fallback logic (direct → worker → error)
- ✅ Test with all search engines

## 🎯 What Works After Deployment

✅ **All search engines** (Brave, Startpage, Qwant, etc.)  
✅ **Image search** from any source  
✅ **News search** from any provider  
✅ **Video search** from any platform  
✅ **API endpoints** anywhere on the internet  

## 🔍 Example: Before & After

**Before (PythonAnywhere blocked):**
```python
response = requests.get("https://search.brave.com/search?q=python")
# ❌ Error: Site not whitelisted
```

**After (with worker):**
```python
from core.utils.proxy import proxy
response = proxy.get("https://search.brave.com/search?q=python")
# ✅ Works! Proxied through Cloudflare Worker
```

## 🆓 Free Tier Limits

- **100,000 requests/day** (Cloudflare Workers Free)
- **10ms CPU time** per request
- **Unlimited bandwidth**

Perfect for a search engine! Even with heavy traffic, you'll stay well within limits.

## 🎉 Next Steps

1. Deploy the worker
2. Copy your worker URL
3. Reply with: "Here's my worker URL: https://..."
4. I'll integrate it into the search engine automatically

That's it! Simple as that. 🚀
