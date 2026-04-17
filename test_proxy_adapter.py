#!/usr/bin/env python3
import subprocess
import time
import requests
import sys
import os

# Start proxy adapter
proc = subprocess.Popen([sys.executable, "proxy_local.py", "--host", "127.0.0.1", "--port", "8081"],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
print("Proxy adapter starting...")
time.sleep(3)

try:
    # Test proxy with httpbin
    print("Testing proxy with httpbin...")
    r = requests.get("http://127.0.0.1:8081/https://httpbin.org/get", timeout=10)
    print(f"Status: {r.status_code}")
    if r.status_code == 200:
        print("Proxy works")
    else:
        print(f"Error: {r.text[:200]}")
except Exception as e:
    print(f"Test failed: {e}")

# Test SearXNG via proxy
try:
    print("\nTesting SearXNG via proxy...")
    r = requests.get("http://127.0.0.1:8081/https://searx.be/search?q=test&format=json", timeout=15)
    print(f"SearXNG status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"Results: {len(data.get('results', []))}")
    else:
        print(f"Error: {r.text[:200]}")
except Exception as e:
    print(f"SearXNG test failed: {e}")

proc.terminate()
proc.wait()
print("Proxy adapter stopped.")
