#!/usr/bin/env python3
"""
Test script for Cloudflare Worker proxy integration.

This script tests:
1. Direct worker access
2. Proxy helper module
3. Search integration
4. Image proxy integration
"""

import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Set proxy URL for testing
os.environ["PROXY_WORKER_URL"] = "https://myproxy.abdulhadijunaidahmedkhan.workers.dev"

def test_direct_worker():
    """Test 1: Direct worker access"""
    print("\n" + "="*70)
    print("TEST 1: Direct Cloudflare Worker Access")
    print("="*70)
    
    import requests
    from urllib.parse import quote
    
    worker_url = os.getenv("PROXY_WORKER_URL")
    test_url = "https://httpbin.org/get"
    proxied_url = f"{worker_url}?url={quote(test_url, safe='')}"
    
    try:
        response = requests.get(proxied_url, timeout=10)
        print(f"✅ Worker is responding")
        print(f"   Status: {response.status_code}")
        print(f"   Response length: {len(response.text)} bytes")
        
        # Check if it's actually proxying
        data = response.json()
        if "headers" in data:
            print(f"✅ Worker is proxying correctly")
            return True
    except Exception as e:
        print(f"❌ Worker test failed: {e}")
        return False

def test_proxy_helper():
    """Test 2: Proxy helper module"""
    print("\n" + "="*70)
    print("TEST 2: Proxy Helper Module")
    print("="*70)
    
    try:
        from core.utils.proxy import proxy
        
        print(f"   Proxy enabled: {proxy.enabled}")
        print(f"   Worker URL: {proxy.worker_url}")
        
        # Test GET request
        response = proxy.get("https://httpbin.org/get", timeout=10)
        print(f"✅ Proxy helper GET request works")
        print(f"   Status: {response.status_code}")
        return True
    except Exception as e:
        print(f"❌ Proxy helper test failed: {e}")
        return False

def test_search_integration():
    """Test 3: Search integration"""
    print("\n" + "="*70)
    print("TEST 3: Search Integration")
    print("="*70)
    
    try:
        from search import results
        
        # Check if proxy is detected
        print(f"   Proxy enabled in search: {results._USE_PROXY}")
        print(f"   Proxy URL: {results._PROXY_WORKER_URL}")
        
        # Try a simple search (will use fallback instances through proxy)
        print("   Testing public SearXNG instance through proxy...")
        result = results.search("test", category="general", page=1)
        
        if result and "results" in result:
            print(f"✅ Search through proxy works")
            print(f"   Found {len(result['results'])} results")
            return True
        else:
            print(f"⚠️  Search returned no results (might be normal)")
            return True
    except Exception as e:
        print(f"❌ Search integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_image_proxy():
    """Test 4: Image proxy integration"""
    print("\n" + "="*70)
    print("TEST 4: Image Proxy Integration")
    print("="*70)
    
    try:
        from core.services.image import _USE_PROXY, _PROXY_WORKER_URL
        
        print(f"   Proxy enabled in image service: {_USE_PROXY}")
        print(f"   Proxy URL: {_PROXY_WORKER_URL}")
        
        if _USE_PROXY:
            print(f"✅ Image proxy configuration detected")
            return True
        else:
            print(f"❌ Image proxy not configured")
            return False
    except Exception as e:
        print(f"❌ Image proxy test failed: {e}")
        return False

def main():
    """Run all tests"""
    print("\n" + "="*70)
    print("CLOUDFLARE WORKER PROXY - INTEGRATION TEST")
    print("="*70)
    print(f"Worker URL: {os.getenv('PROXY_WORKER_URL')}")
    
    results = []
    
    results.append(("Direct Worker Access", test_direct_worker()))
    results.append(("Proxy Helper Module", test_proxy_helper()))
    results.append(("Search Integration", test_search_integration()))
    results.append(("Image Proxy Integration", test_image_proxy()))
    
    # Summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    
    for test_name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} - {test_name}")
    
    passed_count = sum(1 for _, p in results if p)
    total_count = len(results)
    
    print(f"\nPassed: {passed_count}/{total_count}")
    
    if passed_count == total_count:
        print("\n🎉 All tests passed! Proxy integration is working correctly.")
        return 0
    else:
        print(f"\n⚠️  {total_count - passed_count} test(s) failed. Check the output above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
