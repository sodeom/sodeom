import asyncio
import httpx
from selectolax.parser import HTMLParser
from urllib.parse import unquote, parse_qs, urlparse
import base64
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}

# ----------------- Helper to clean URLs -----------------
def extract_target_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    qs = parse_qs(parsed.query)

    # DuckDuckGo redirect
    if "duckduckgo.com" in domain and parsed.path.startswith("/l/"):
        return unquote(qs.get("uddg", [url])[0])

    # Bing ck/a base64 redirect
    if "bing.com" in domain and parsed.path.startswith("/ck/"):
        encoded = qs.get("u", [None])[0]
        if encoded:
            try:
                if encoded.startswith("a1"):
                    encoded = encoded[2:]  # remove the 'a1' prefix
                decoded = base64.b64decode(encoded + '==').decode("utf-8")
                return decoded
            except Exception:
                return url

    return url

# ----------------- DuckDuckGo -----------------
async def search_duckduckgo(query, max_results=10):
    url = "https://html.duckduckgo.com/html/"
    data = {"q": query, "b": ""}
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, data=data, headers=HEADERS)
        resp.raise_for_status()
        tree = HTMLParser(resp.text)

    results = []
    for node in tree.css("div.result")[:max_results]:
        try:
            a = node.css_first("a[href]")
            title = a.text(strip=True)
            link = extract_target_url(a.attributes.get("href", ""))
            desc_node = node.css_first("a.result__snippet")
            description = desc_node.text(strip=True) if desc_node else ""
            results.append({"title": title, "link": link, "description": description})
        except:
            continue
    return results

# ----------------- Bing -----------------
async def search_bing(query, max_results=10):
    url = "https://www.bing.com/search"
    params = {"q": query, "count": max_results}
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, params=params, headers=HEADERS)
        resp.raise_for_status()
        tree = HTMLParser(resp.text)

    results = []
    for li in tree.css("li.b_algo")[:max_results]:
        try:
            a = li.css_first("h2 a")
            title = a.text(strip=True)
            link = extract_target_url(a.attributes.get("href", ""))
            desc_node = li.css_first("div.b_caption p")
            description = desc_node.text(strip=True) if desc_node else ""
            results.append({"title": title, "link": link, "description": description})
        except:
            continue
    return results

# ----------------- Adult content filter -----------------
def filter_adult_content(results):
    adult_keywords = ['porn', 'xxx', 'adult', 'sex', 'nude', 'nsfw', 'mature']
    filtered = []

    for result in results:
        title = result.get('title', '')
        link = result.get('link', '')
        description = result.get('description', '')

        if not any(keyword in str(title).lower() or
                   keyword in str(link).lower() or
                   keyword in str(description).lower() for keyword in adult_keywords):
            filtered.append(result)

    return filtered

# ----------------- Fetch with fallback -----------------
async def fetch_web_with_fallback(query, max_results=10):
    """Fetch from DuckDuckGo → Bing concurrently and filter adult content."""
    tasks = {
        "duckduckgo": asyncio.create_task(search_duckduckgo(query, max_results)),
        "bing": asyncio.create_task(search_bing(query, max_results))
    }

    results = []
    for engine, task in tasks.items():
        try:
            engine_results = await task
            filtered = filter_adult_content(engine_results)
            if filtered:
                print(f"Fetched {len(filtered)} results from {engine}")
                results.extend(filtered)
        except Exception as e:
            print(f"Error fetching {engine}: {e}")

    return results

def fetch_all_brave_web(query, page=1):
    """Scrape Brave Search organic results with descriptions (no API key)."""
    all_results = []
    # Brave uses offset for pagination (0-based)
    offset = (page - 1) * 10
    params = {"q": query, "source": "web", "offset": offset}

    try:
        resp = requests.get("https://search.brave.com/search", headers=HEADERS, params=params, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        hits = soup.select(".snippet")

        for r in hits:
            # Title and link
            title_elem = r.select_one(".snippet-title")
            link_elem = r.select_one(".result-header")

            if title_elem and link_elem:
                title = title_elem.get_text(strip=True)
                link = link_elem.get("href")

                # Description from snippet content
                desc_elem = (r.select_one(".snippet-description") or
                           r.select_one(".snippet-content") or
                           r.select_one("p"))
                description = desc_elem.get_text(strip=True) if desc_elem else ""

                all_results.append({
                    "title": title,
                    "link": link,
                    "description": description
                })

    except Exception as e:
        print(f"Error fetching Brave results for page {page}: {e}")

    return all_results


# ----------------- Example usage -----------------
def main(query, page=1):
    all_results = asyncio.run(fetch_web_with_fallback(query, max_results=5))
    return all_results