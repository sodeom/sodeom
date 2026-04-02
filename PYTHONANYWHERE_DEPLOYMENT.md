# PythonAnywhere Deployment Guide

## ✅ **Recommended Configuration for PythonAnywhere**

### **Use External SearXNG (Not Local Subprocess)**

PythonAnywhere has restrictions that make running SearXNG as a subprocess difficult:
- Limited subprocess permissions
- No ability to bind to ports easily
- Resource constraints

**Solution:** Use external public SearXNG instances through your proxy!

---

## 🚀 **Quick Deployment Steps**

### **1. Upload Your .env File**

Create `/home/sodi/sodeom/.env` with:

```bash
# Required
FLASK_SECRET_KEY=your-random-secret-key-here
PROXY_WORKER_URL=https://myproxy.abdulhadijunaidahmedkhan.workers.dev

# Use external SearXNG (avoids subprocess issues)
SEARXNG_URL=https://searx.be
SEARXNG_FALLBACKS=https://search.sapti.me,https://searx.fmac.xyz
```

### **2. Update PythonAnywhere Web App Configuration**

In PythonAnywhere dashboard:
- Go to "Web" tab
- Click "Reload" button
- Check error logs

### **3. Verify It's Working**

Check your logs for:
```
[SearXNG] SEARXNG_URL is set — skipping local subprocess start
[Proxy] Cloudflare Worker proxy enabled: https://myproxy...
```

✅ This means it's using external instances through your proxy!

---

## 📋 **Why This Works Better**

| Local SearXNG | External SearXNG + Proxy |
|---------------|--------------------------|
| ❌ Subprocess issues | ✅ No subprocess needed |
| ❌ Port binding problems | ✅ No ports needed |
| ❌ Resource intensive | ✅ Minimal resources |
| ❌ Startup delays | ✅ Instant startup |
| ❌ Single point of failure | ✅ Multiple fallbacks |

---

## 🔧 **Troubleshooting**

### **Problem: Import Errors**

If you see `ModuleNotFoundError`:

```bash
# SSH into PythonAnywhere
cd /home/sodi/sodeom
source /home/sodi/.venv/bin/activate
pip install -r requirements.txt
```

### **Problem: "searx module not found"**

This is **expected** when using external SearXNG! The searx module is only needed for local instances.

Just make sure `SEARXNG_URL` is set in your `.env`.

### **Problem: Still trying to start local SearXNG**

Check your `.env` file exists at: `/home/sodi/sodeom/.env`

The app looks for `.env` in the project root.

### **Problem: Slow responses**

This is normal on first load. The proxy needs to establish connections.

Subsequent requests will be faster due to connection pooling.

---

## 🎯 **Testing Your Deployment**

### **Test 1: Check if app loads**
```bash
curl https://sodi.pythonanywhere.com/
```

Should return HTML (your homepage).

### **Test 2: Test search API**
```bash
curl "https://sodi.pythonanywhere.com/api/search?q=test"
```

Should return JSON with search results.

### **Test 3: Check logs**

In PythonAnywhere:
- Web tab → Log files → Error log
- Look for `[Proxy]` and `[SearXNG]` messages

---

## 📊 **Expected Logs (Good Deployment)**

```
[Proxy] Cloudflare Worker proxy enabled: https://myproxy.abdulhadijunaidahmedkhan.workers.dev
[SearXNG] SEARXNG_URL is set — skipping local subprocess start
WSGI app 0 (mountpoint='') ready in 3 seconds
spawned uWSGI worker 1
```

✅ No SearXNG subprocess errors!

---

## ⚠️ **Important Notes**

1. **`.env` location matters**: Must be at `/home/sodi/sodeom/.env`

2. **Virtual environment**: PythonAnywhere auto-detects `/home/sodi/.venv`

3. **Dependencies**: Make sure all packages in `requirements.txt` are installed

4. **Worker URL**: Must include `https://` and no trailing slash

5. **SearXNG instances**: The proxy will route through your worker, bypassing whitelist

---

## 🎉 **Success Checklist**

- [ ] `.env` file created with `PROXY_WORKER_URL` and `SEARXNG_URL`
- [ ] All dependencies installed (`pip install -r requirements.txt`)
- [ ] Web app reloaded in PythonAnywhere
- [ ] No subprocess errors in logs
- [ ] Search API returns results
- [ ] Proxy log message appears

---

## 🆘 **Still Having Issues?**

Check these files on your local machine and upload to PythonAnywhere:

1. **`.env`** - Main configuration
2. **`requirements.txt`** - Dependencies
3. **`app.py`** - Entry point
4. **`core/`** - All core modules
5. **`search/`** - Search modules
6. **`templates/`** - HTML templates
7. **`static/`** - CSS/JS files

**Restart checklist:**
```bash
# In PythonAnywhere console
cd /home/sodi/sodeom
source /home/sodi/.venv/bin/activate
pip install -r requirements.txt

# Then reload web app in dashboard
```

---

## 💡 **Pro Tips**

1. **Use multiple fallback instances** for reliability
2. **Monitor Cloudflare Worker usage** (free tier: 100k requests/day)
3. **Set a strong FLASK_SECRET_KEY** for sessions
4. **Don't commit `.env`** to git (already in `.gitignore`)

---

**Need more help?** Check the error log in PythonAnywhere and share the relevant lines.
