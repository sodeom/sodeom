import hashlib
import os
import re
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup
from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
)

# from urllib.parse import urlparse, parse_qs, unquote
from results import main

app = Flask(__name__)


# ── Privacy: Add security/privacy headers to every response ──
@app.after_request
def add_privacy_headers(response):
    # Tell browsers not to track
    response.headers["DNT"] = "1"
    # No referrer info leaked to external sites
    response.headers["Referrer-Policy"] = "no-referrer"
    # Block third-party cookies, trackers, etc.
    response.headers["Permissions-Policy"] = "interest-cohort=()"  # Block FLoC
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    # Don't cache search queries on the server
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
    response.headers["Pragma"] = "no-cache"
    return response


# Setup Flask-Caching (simple backend → in memory, for prod use Redis/Memcached)
# Setup Flask-Caching
# cache = Cache(
#     app,
#     config={
#         "CACHE_TYPE": "SimpleCache",             # In-memory cache
#         "CACHE_DEFAULT_TIMEOUT": 86400           # Cache for 1 day
#     }
# )

import dotenv
from openai import OpenAI

dotenv.load_dotenv()

# AI features enabled via GitHub Models API
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_ENDPOINT = "https://models.github.ai/inference"
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "gpt-4o-mini")
client = OpenAI(base_url=GITHUB_ENDPOINT, api_key=GITHUB_TOKEN)


def install_image(url: str, base_dir="placeholders") -> str | None:
    os.makedirs(base_dir, exist_ok=True)

    # Unique filename from URL hash
    filename = hashlib.sha1(url.encode()).hexdigest() + ".jpg"
    filepath = os.path.join(base_dir, filename)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0 Safari/537.36",
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    }

    try:
        response = requests.get(url, stream=True, timeout=10, headers=headers)
        response.raise_for_status()
        if not response.headers.get("Content-Type", "").startswith("image/"):
            return None

        with open(filepath, "wb") as f:
            for chunk in response.iter_content(8192):
                f.write(chunk)
        return filepath
    except Exception as e:
        print(f"[install_image] Failed: {e}")
        return None


app.secret_key = os.getenv("FLASK_SECRET_KEY", "replace-this-in-production")


def utf8_string_to_binary(input_str: str) -> str:
    byte_data = input_str.encode("utf-8")
    binary = "".join(format(byte, "08b") for byte in byte_data)
    # Pad to multiple of 64 bits
    while len(binary) % 64 != 0:
        binary += "0"
    return binary


@app.route("/ai", methods=["GET", "POST"])
def query_ai():
    query = request.args.get("query", "").strip()
    if not query:
        return jsonify({"error": "No query provided"}), 400

    other_params = request.get_json(silent=True) or {}

    model = other_params.get("model", DEFAULT_MODEL)

    if "messages" not in other_params:
        other_params["messages"] = [
            {"role": "system", "content": ""},
            {"role": "user", "content": query},
        ]

    other_params["model"] = model

    try:
        response = client.chat.completions.create(**other_params)
        answer = response.choices[0].message.content
        return jsonify({"answer": answer})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def binary_to_utf8_string(binary_str: str) -> str:
    if len(binary_str) % 8 != 0:
        raise ValueError("Binary string length must be a multiple of 8")
    byte_list = [int(binary_str[i : i + 8], 2) for i in range(0, len(binary_str), 8)]
    # Remove trailing zero bytes (padding)
    while byte_list and byte_list[-1] == 0:
        byte_list.pop()
    return bytes(byte_list).decode("utf-8")


# Common headers to mimic a real browser
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

### ── Image Search Utilities ───────────────────────────────────────────────────


def fetch_all_duckduckgo_images(query, page=1):
    """DuckDuckGo JSON image endpoint (vqd token)."""
    try:
        txt = requests.get(
            f"https://duckduckgo.com/?q={quote_plus(query)}&iax=images&ia=images",
            headers=HEADERS,
            timeout=10,
        ).text
        vqd_match = re.search(r"vqd=([\d-]+)&", txt)
        if not vqd_match:
            return []

        vqd = vqd_match.group(1)
        images, seen = [], set()

        # Calculate offset for pagination
        start_offset = (page - 1) * 100

        for off in range(start_offset, start_offset + 100, 100):
            j = requests.get(
                "https://duckduckgo.com/i.js",
                headers=HEADERS,
                params={"l": "us-en", "o": "json", "q": query, "vqd": vqd, "s": off},
                timeout=10,
            ).json()
            for img in j.get("results", []):
                url = img.get("image")
                if url and url not in seen:
                    seen.add(url)
                    images.append(url)
        return images
    except Exception as e:
        print(f"Error fetching DuckDuckGo images: {e}")
        return []


def fetch_all_bing_images(query, page=1):
    """Scrape Bing images via the `m` attribute on <a class='iusc'>."""
    try:
        offset = (page - 1) * 35 + 1
        params = {"q": query, "first": offset}

        resp = requests.get(
            "https://www.bing.com/images/search",
            headers=HEADERS,
            params=params,
            timeout=10,
        )
        soup = BeautifulSoup(resp.text, "html.parser")
        imgs = []
        for a in soup.select("a.iusc"):
            m = a.get("m", "")
            match = re.search(r'"murl":"(https?://[^"]+)"', m)
            if match:
                imgs.append(match.group(1))
        return imgs
    except Exception as e:
        print(f"Error fetching Bing images: {e}")
        return []


def fetch_all_brave_images(query, page=1):
    """Use Brave's public image JSON endpoint (no key)."""
    try:
        offset = (page - 1) * 20
        params = {"q": query, "source": "web", "offset": offset}

        resp = requests.get(
            "https://search.brave.com/api/images",
            headers=HEADERS,
            params=params,
            timeout=10,
        )
        return [r.get("image") for r in resp.json().get("results", [])]
    except Exception as e:
        print(f"Error fetching Brave images: {e}")
        return []


def fetch_images_with_fallback(query, page=1):
    """Try DuckDuckGo → Bing → Brave for images, filtering NSFW results."""

    def is_safe(img_url):
        if not img_url:
            return False
        # Filter out images with adult keywords in the URL
        adult_keywords = ["porn", "xxx", "adult", "sex", "nude", "nsfw", "mature"]
        return not any(keyword in str(img_url).lower() for keyword in adult_keywords)

    image_functions = [
        (fetch_all_duckduckgo_images, "DuckDuckGo"),
        (fetch_all_bing_images, "Bing"),
        (fetch_all_brave_images, "Brave"),
    ]

    for fetch_func, engine_name in image_functions:
        try:
            imgs = fetch_func(query, page)
            if imgs:
                safe_imgs = [img for img in imgs if is_safe(img)]
                if safe_imgs:
                    print(f"Successfully fetched page {page} images from {engine_name}")
                    return safe_imgs
        except Exception as e:
            print(f"Failed to fetch images from {engine_name}: {e}")
            continue

    return []


### ── Flask Routes ─────────────────────────────────────────────────────────────


@app.route("/")
def index():
    q = request.args.get("q", "")
    b = request.args.get("b", "")
    page = request.args.get("page", 1, type=int)

    query_error = ""
    if isinstance(q, str):
        q = q.strip()
        if q == "" and request.args.get("q") is not None:
            query_error = "Please enter a search query."

    # Ensure page is at least 1
    if page < 1:
        page = 1

    if b == "" and q != "":
        binary = utf8_string_to_binary(q)
        return redirect(f"/?q={q}&b={binary}&page={page}")

    if b != "" and q == "":
        try:
            text = binary_to_utf8_string(b)
            return redirect(f"/?q={text}&b={b}&page={page}")
        except ValueError:
            # Invalid binary, redirect to clean search
            return redirect("/?q=&b=&page=1")

    results = []
    total_results = 0
    if q:
        try:
            results = main(q, page)
            total_results = len(results)
        except Exception:
            query_error = "Search temporarily unavailable. Please try again."
            results = []
            total_results = 0

    # Calculate pagination info
    has_next = (
        total_results >= 10
    )  # Assume there might be more results if we got 10 or more
    has_prev = page > 1

    return render_template(
        "index.html",
        results=results,
        query=q,
        query_error=query_error,
        page=page,
        b=b,
        has_next=has_next,
        has_prev=has_prev,
        total_results=total_results,
    )


@app.route("/api/search")
def indexapi():
    q = request.args.get("q", "")
    page = request.args.get("page", 1, type=int)

    if not q:
        return jsonify({"error": "Missing query parameter 'q'"}), 400

    # Ensure page is at least 1
    if page < 1:
        page = 1

    try:
        results = main(q, page)
        total_results = len(results)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    data = {
        "results": results,
        "query": q,
        "page": page,
        "has_next": len(results) >= 10,
        "has_prev": page > 1,
        "total_results": total_results,
    }

    return jsonify(data)


# ── Wiki lookup route ──────────────────────────────────────────────────────────
@app.route("/wiki/<query>", methods=["GET"])
def wiki(query):
    paragraph = "this is coming soon"
    return render_template("wiki.html", query=query, paragraph=paragraph)


@app.route("/images")
def images():
    q = request.args.get("q", "")
    page = request.args.get("page", 1, type=int)

    if page < 1:
        page = 1

    imgs = fetch_images_with_fallback(q, page) if q else []

    return render_template(
        "images.html",
        images=imgs,
        query=q,
        page=page,
        has_next=len(imgs) >= 20,  # Assume more if we got 20+ images
        has_prev=page > 1,
        total_results=len(imgs),
    )


import mimetypes


@app.route("/placeholder")
def placeholder():
    q = request.args.get("q", "")
    if not q:
        # No query → show docs page
        return render_template("placeholder.html")

    fallback = os.path.join("static", "not-found.png")

    page = request.args.get("page", 1, type=int)
    if page < 1:
        page = 1

    # Fetch a pool of candidate images
    imgs = fetch_images_with_fallback(q, page) if q else []
    if not imgs:
        return send_file(fallback, mimetype="image/png")

    # Try up to 5 candidates until one works
    for candidate in imgs[:10]:
        img_path = install_image(candidate)
        if img_path and os.path.exists(img_path):
            try:
                mime_type, _ = mimetypes.guess_type(img_path)
                return send_file(
                    os.path.abspath(img_path),
                    mimetype=mime_type or "application/octet-stream",
                )
            except Exception as e:
                print(f"[placeholder] Error serving {img_path}: {e}")
                continue

    # If all failed → serve fallback
    return send_file(fallback, mimetype="image/png")


@app.route("/placeholder/url")
def placeholder_url():
    q = request.args.get("q", "")
    if not q:
        # No query → show docs page
        return render_template("placeholder.html")

    fallback = os.path.join("static", "not-found.png")

    page = request.args.get("page", 1, type=int)
    if page < 1:
        page = 1

    # Fetch a pool of candidate images
    imgs = fetch_images_with_fallback(q, page) if q else []
    if imgs[0]:
        return imgs[0]

    # If all failed → serve fallback
    return fallback


@app.route("/aaaa")
def aaaa():
    return "HELLO, WORLD"


# — Additional routes as requested —
@app.route("/services")
def services():
    return render_template("services.html")


@app.route("/urls")
def list_urls():
    links = []
    for rule in app.url_map.iter_rules():
        # Skip static files if not needed
        if rule.endpoint == "static":
            continue
        url = str(rule)
        methods = ", ".join(rule.methods - {"HEAD", "OPTIONS"})
        links.append((url, methods))

    # Render with inline HTML (or use a Jinja template instead)
    return render_template("urls.html", links=sorted(links))


@app.route("/faq")
def faq():
    return render_template("faq.html")


@app.route("/blog/<blog>")
def blogs(blog):
    return render_template(f"blogs/{blog}.html")


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/services/ai")
def services_ai():
    return render_template("ai.html")


@app.route("/services/software")
def services_software():
    return render_template("software.html")


@app.route("/services/sodium")
def services_sodium():
    return render_template("sodium.html")


@app.route("/services/webs")
def services_webs():
    return render_template("webs.html")


@app.route("/services/projects")
def services_projects():
    return render_template("projects.html")


@app.route("/contact")
def contact():
    return render_template("contact.html")


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy-policy")
def privacy():
    return render_template("privacy.html")


@app.route("/funprojects")
def funprojects():
    return render_template("funprojects.html")


@app.route("/apis")
def apis():
    return render_template("apis.html")


@app.route("/apis/root")
def apis_root():
    return render_template("apis_root.html")


@app.route("/apis/search")
def apis_search():
    return render_template("apis_search.html")


@app.route("/apis/ai")
def apis_ai():
    return render_template("apis_ai.html")


@app.route("/apis/images")
def apis_images():
    return render_template("apis_images.html")


@app.route("/apis/placeholder")
def apis_placeholder():
    return render_template("apis_placeholder.html")


@app.route("/apis/wiki")
def apis_wiki():
    return render_template("apis_wiki.html")


@app.route("/apis/routes")
def apis_routes():
    return render_template("apis_routes.html")


@app.route("/robots.txt")
def robots():
    return render_template("robots.txt")


@app.route("/sitemap.xml")
def site():
    return render_template("sitemap.xml")


@app.route("/favicon.ico")
def favicon():
    return send_from_directory(
        ".", "static/favicon.ico", mimetype="image/vnd.microsoft.icon"
    )


@app.route("/fake-sha256")
def fakesha256():
    return render_template("fake-sha256.html")


# ads.txt

### ── App Entry Point ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=9999, debug=True)
