# Cloudflare Worker Proxy Setup

This guide will help you deploy a Cloudflare Worker proxy to bypass PythonAnywhere whitelist restrictions.

## 🚀 Quick Setup

### Step 1: Deploy Cloudflare Worker

1. **Go to Cloudflare Dashboard**
   - Visit: https://dash.cloudflare.com/
   - Login or create a free account

2. **Create Worker**
   - Click "Workers & Pages" in the left sidebar
   - Click "Create application"
   - Click "Create Worker"
   - Give it a name like `sodeom-proxy`

3. **Paste Worker Code**
   - Click "Edit Code"
   - Delete the default code
   - Copy and paste the code from `cloudflare-worker-proxy.js`
   - Click "Save and Deploy"

4. **Copy Worker URL**
   - After deployment, copy your worker URL
   - It will look like: `https://sodeom-proxy.YOUR-SUBDOMAIN.workers.dev`

### Step 2: Configure Sodeom

Add the worker URL to your `.env` file:

```bash
PROXY_WORKER_URL=https://sodeom-proxy.YOUR-SUBDOMAIN.workers.dev
```

### Step 3: Update Search Code (Optional - Auto-configured)

The proxy is already integrated! If `PROXY_WORKER_URL` is set, all external requests will automatically route through the worker.

**Manual usage:**

```python
from core.utils.proxy import proxy

# Make requests through the proxy
response = proxy.get("https://search.brave.com/search?q=python")
response = proxy.post("https://api.example.com", json={"key": "value"})
```

---

## 📝 Testing

Test your worker directly:

```bash
curl "https://sodeom-proxy.YOUR-SUBDOMAIN.workers.dev?url=https://httpbin.org/get"
```

You should see a JSON response from httpbin.org.

---

## 🔒 Security Notes

- The worker allows requests to any HTTP/HTTPS URL
- CORS is enabled (`Access-Control-Allow-Origin: *`)
- No authentication is required (suitable for public proxy use)

**Optional: Add Authentication**

To restrict access, you can modify the worker to check for an API key:

```javascript
// At the top of the fetch handler:
const apiKey = request.headers.get('X-API-Key');
if (apiKey !== 'your-secret-key') {
  return new Response('Unauthorized', { status: 401 });
}
```

Then in Python:

```python
proxy.get(url, headers={'X-API-Key': 'your-secret-key'})
```

---

## 📊 Usage Limits

**Cloudflare Workers Free Tier:**
- 100,000 requests per day
- 10ms CPU time per request
- Should be more than enough for a search engine

If you need more, upgrade to the paid plan ($5/month for 10 million requests).

---

## 🎯 Integration Points

The proxy can be used in these parts of Sodeom:

1. **Search Results** (`search/results.py`)
2. **Image Fetching** (`core/services/image.py`)
3. **SearXNG Fallbacks** (when local SearXNG is down)

All these will automatically use the proxy if `PROXY_WORKER_URL` is configured.

---

## 🐛 Troubleshooting

**Worker not responding?**
- Check the worker is deployed and running
- Check the URL is correct (should end with `.workers.dev`)
- Check Cloudflare dashboard for error logs

**Still getting blocked?**
- Some sites may block Cloudflare IPs
- Try using a different proxy service (ScraperAPI, ScrapingAnt)
- Consider rotating User-Agent headers

**Slow responses?**
- Cloudflare Workers are edge-deployed (very fast)
- If slow, the target site itself may be slow
- Check Cloudflare analytics for performance metrics

---

## 📚 Alternative: ScraperAPI

If you prefer a managed solution:

1. Sign up at https://www.scraperapi.com (free tier: 1,000 requests/month)
2. Get your API key
3. Set in `.env`:
   ```bash
   SCRAPER_API_KEY=your_api_key
   ```
4. Use ScraperAPI format:
   ```python
   proxy_url = f"http://api.scraperapi.com?api_key={API_KEY}&url={target_url}"
   ```

---

## ✅ Deployment Checklist

- [ ] Cloudflare Worker deployed
- [ ] Worker URL copied
- [ ] `PROXY_WORKER_URL` added to `.env`
- [ ] Worker tested with curl
- [ ] Sodeom restarted to pick up new env var
- [ ] Search tested on PythonAnywhere

---

**Need help?** Open an issue on GitHub or contact support.
