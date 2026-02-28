# TODO: Add proxy support to search engine

## Plan

- [x] Update results.py to use the proxy for all HTTP requests
- [x] Update searxng_src/settings_local.yml to use the proxy for local SearXNG
- [x] Update app.py install_image function to use the proxy

## Details

- Proxy URL: https://allow-cors.abdulhadijunaidahmedkhan.workers.dev/?url=
- Need to prepend proxy URL to all outgoing HTTP requests
- Use requests library's proxies parameter
