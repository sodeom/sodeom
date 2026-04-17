#!/usr/bin/env python3
"""Test search functionality. Run and copy-paste output."""

import sys
import os

# Use environment or default to production URL
BASE_URL = os.getenv("TEST_URL", "http://localhost:9999").rstrip("/")


def test_endpoint(path, params=None):
    """Test an endpoint and return (status, data, error)."""
    import requests

    url = f"{BASE_URL}{path}"
    try:
        r = requests.get(url, params=params or {}, timeout=30)
        data = r.json()
        return r.status_code, data, None
    except Exception as e:
        return 0, None, str(e)


def main():
    print("=" * 50)
    print(f"Testing: {BASE_URL}")
    print("=" * 50)

    # Test 1: Home page
    print("\n[1] Home page...")
    import requests

    try:
        r = requests.get(f"{BASE_URL}/", timeout=30)
        print(f"    STATUS: {r.status_code}")
    except Exception as e:
        print(f"    ERROR: {e}")

    # Test 2: API search
    print("\n[2] API search (q=test)...")
    status, data, err = test_endpoint("/api/search", {"q": "test"})
    if err:
        print(f"    ERROR: {err}")
    elif status == 200:
        results = data.get("results", [])
        print(f"    STATUS: {status}")
        print(f"    RESULTS: {len(results)}")
        if results:
            print(f"    SAMPLE: {results[0].get('title', 'N/A')[:60]}")
        else:
            print(f"    WARNING: No results!")
        # Show engines used
        engines = set(r.get("engine", "") for r in results)
        print(f"    ENGINES: {engines}")
    else:
        print(f"    STATUS: {status}")
        print(f"    DATA: {data}")

    # Test 3: Different query
    print("\n[3] API search (q=python)...")
    status, data, err = test_endpoint("/api/search", {"q": "python"})
    if err:
        print(f"    ERROR: {err}")
    elif status == 200:
        results = data.get("results", [])
        print(f"    STATUS: {status}")
        print(f"    RESULTS: {len(results)}")
    else:
        print(f"    STATUS: {status}")

    # Test 4: Check SearXNG directly
    print("\n[4] Local SearXNG (localhost:8888)...")
    import requests

    try:
        r = requests.get("http://localhost:8888/healthz", timeout=30)
        print(f"    STATUS: {r.status_code}")
    except Exception as e:
        print(f"    ERROR: {e}")

    # Test 5: Check if image service works
    print("\n[5] Image placeholder...")
    import requests

    try:
        r = requests.get(f"{BASE_URL}/images", params={"q": "test"}, timeout=30)
        print(f"    STATUS: {r.status_code}")
        # Check for image URLs in response
        if r.status_code == 200:
            text = r.text
            if "http" in text and ("jpg" in text or "png" in text or "image" in text):
                print(f"    Has images: YES")
            else:
                print(f"    Has images: NO")
    except Exception as e:
        print(f"    ERROR: {e}")

    print("\n" + "=" * 50)
    print("DONE - Copy output above")
    print("=" * 50)


if __name__ == "__main__":
    main()
