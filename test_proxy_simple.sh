#!/bin/bash
echo "=========================================="
echo "Testing Cloudflare Worker Proxy"
echo "=========================================="
echo ""
echo "Worker URL: https://myproxy.abdulhadijunaidahmedkhan.workers.dev"
echo ""

echo "Test 1: Direct worker test..."
curl -s "https://myproxy.abdulhadijunaidahmedkhan.workers.dev?url=https://httpbin.org/get" | head -5
echo ""
echo "✅ If you see JSON above, the worker is working!"
echo ""

echo "Test 2: Testing with a search engine..."
curl -s "https://myproxy.abdulhadijunaidahmedkhan.workers.dev?url=https://www.bing.com" | head -3
echo ""
echo "✅ If you see HTML above, proxy can access search engines!"
echo ""

echo "=========================================="
echo "✅ Proxy is ready to use!"
echo "=========================================="
