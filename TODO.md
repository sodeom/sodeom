# SearXNG Integration - Task Tracker

## Plan

Integrate SearXNG as the search backend to replace direct scraping of DuckDuckGo/Bing/Brave.

## Steps

- [x] 1. Rewrite `results.py` - SearXNG API client with fallback instances
- [x] 2. Update `app.py` - Update routes to use SearXNG data, add `/videos` + `/news` routes, remove old scrapers
- [x] 3. Update `templates/base.html` - Add Videos and News links to navigation
- [x] 4. Update `templates/index.html` - Add corrections, suggestions, infobox/knowledge panel, answers
- [x] 5. Update `templates/images.html` - Use SearXNG image data with thumbnails and source
- [x] 6. Create `templates/videos.html` - New video search page
- [x] 7. Create `templates/news.html` - New news search page
- [x] 8. Update `templates/wiki.html` - Real wiki content from SearXNG infoboxes
- [x] 9. Update `static/style.css` - Add styles for corrections, suggestions, infoboxes, answers, image-grid
- [x] 10. Test the integration - Flask server running on port 9999, syntax checks pass, routes respond
