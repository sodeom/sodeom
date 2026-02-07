<p align="center">
  <img src="https://sodeom.com/static/logo.png" alt="Sodeom Logo" width="200"/>
</p>

<h1 align="center">Sodeom — Private Search Engine</h1>

<p align="center">
  <strong>Private search with zero tracking and minimal filtering.</strong><br>
  <a href="https://sodeom.com/">Website</a> · <a href="https://sodeom.com/apis">API Docs</a> · <a href="https://sodeom.com/privacy-policy">Privacy Policy</a> · <a href="https://sodeom.com/contact">Contact</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/license-GPLv3-blue.svg" alt="License: GPLv3"/>
  <img src="https://img.shields.io/badge/python-3.10%2B-brightgreen.svg" alt="Python 3.10+"/>
  <img src="https://img.shields.io/badge/framework-Flask-black.svg" alt="Flask"/>
  <img src="https://img.shields.io/badge/privacy-100%25-success.svg" alt="Privacy: 100%"/>
</p>

---

## Table of Contents

- [What is Sodeom?](#what-is-sodeom)
- [Features](#features)
- [Privacy & Security](#privacy--security)
- [Architecture](#architecture)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
  - [Running](#running)
- [API Reference](#api-reference)
  - [Web Search](#web-search-api)
  - [Image Search](#image-search)
  - [Placeholder Image](#placeholder-image-api)
- [Routes Overview](#routes-overview)
- [Project Structure](#project-structure)
- [How Search Works](#how-search-works)
- [Self-Hosting](#self-hosting)
- [Contributing](#contributing)
- [License](#license)
- [Contact](#contact)

---

## What is Sodeom?

**Sodeom** is a privacy-first, open-source search engine built with Python and Flask. It aggregates results from multiple search engines (DuckDuckGo, Bing, Brave, and Google) while acting as a proxy between you and those services — meaning **they never see your IP, cookies, or identity**. Only the Sodeom server communicates with external search providers.

Founded in 2025 and built by **Abdul Hadi**, Sodeom is designed for users who want fast, relevant search results without sacrificing their privacy.

> _"Search should be private by default."_

---

## Features

| Feature                      | Description                                                                    |
| ---------------------------- | ------------------------------------------------------------------------------ |
| **Private by Design**        | Zero logging, no tracking cookies, no analytics, no user profiles              |
| **Multi-Engine Aggregation** | Pulls results from DuckDuckGo, Bing, Brave, and Google with automatic fallback |
| **Web Search**               | Full web search with pagination and binary-encoded query support               |
| **Image Search**             | Aggregated image search across four engines with NSFW filtering                |
| **Placeholder Image API**    | Fetch and serve images by keyword — great for prototyping and development      |
| **Search API**               | JSON REST API for programmatic access to search results                        |
| **Adult Content Filtering**  | Built-in keyword-based filter blocks NSFW results automatically                |
| **Self-Hostable**            | Run your own private instance on any server                                    |
| **Open Source**              | Licensed under GPLv3 — fully auditable and transparent                         |
| **Security Headers**         | DNT, no-referrer, FLoC blocking, X-Frame-Options, and more on every response   |

---

## Privacy & Security

Sodeom takes a **zero-knowledge** approach to search:

### What Sodeom Does NOT Do

- ❌ Log or store your search queries
- ❌ Use analytics or tracking cookies
- ❌ Track your IP address
- ❌ Build user profiles
- ❌ Share any data with third parties
- ❌ Use browser fingerprinting or session tracking
- ❌ Leak referrer information to external sites

### How Your Privacy is Protected

| Protection              | Implementation                                                             |
| ----------------------- | -------------------------------------------------------------------------- |
| **Proxy Model**         | Search engines see the Sodeom server IP, never yours                       |
| **No Logging**          | Zero search queries are stored on the server                               |
| **No Cookies**          | No tracking cookies are used                                               |
| **Referrer Policy**     | `Referrer-Policy: no-referrer` on all responses                            |
| **FLoC/Topics Blocked** | `Permissions-Policy: interest-cohort=()` header                            |
| **Security Headers**    | `X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`, `DNT: 1` |
| **Cache Control**       | `no-store, no-cache, must-revalidate, private` — queries are never cached  |

---

## Architecture

```
┌─────────────┐         ┌───────────────────┐         ┌──────────────────┐
│   Browser   │ ──────► │   Sodeom Server   │ ──────► │  DuckDuckGo      │
│  (You)      │ ◄────── │   (Flask/Python)  │ ◄────── │  Bing            │
└─────────────┘         │                   │         │  Google          │
                        │  - Proxy Layer    │         │  Brave           │
                        │  - NSFW Filter    │         └──────────────────┘
                        │  - Privacy Headers│
                        └───────────────────┘
```

Your browser talks **only** to the Sodeom server. The server fetches results from external search engines on your behalf, filters them, and returns clean results — all without exposing your identity.

---

## Getting Started

### Prerequisites

- **Python 3.10+**
- **pip** (Python package manager)

### Installation

1. **Clone the repository**

   ```bash
   git clone https://github.com/your-username/sodeom.git
   cd sodeom
   ```

2. **Install dependencies**

   ```bash
   pip install flask requests beautifulsoup4 httpx selectolax python-dotenv openai
   ```

3. **Set up environment variables** (optional)

   Create a `.env` file in the project root:

   ```env
   FLASK_SECRET_KEY=your-secret-key-here
   ```

### Running

```bash
python app.py
```

The server starts on **`http://0.0.0.0:9999`** by default.

Open your browser and navigate to `http://localhost:9999` to start searching privately.

---

## API Reference

### Web Search API

Search the web and get results as JSON.

**Endpoint:** `GET /api/search`

| Parameter | Type   | Required | Description                |
| --------- | ------ | -------- | -------------------------- |
| `q`       | string | Yes      | Search query               |
| `page`    | int    | No       | Page number (default: `1`) |

**Example Request:**

```bash
curl "https://sodeom.com/api/search?q=python+flask&page=1"
```

**Example Response:**

```json
{
  "results": [
    {
      "title": "Welcome to Flask",
      "link": "https://flask.palletsprojects.com/",
      "description": "Flask is a lightweight WSGI web application framework..."
    }
  ],
  "query": "python flask",
  "page": 1,
  "has_next": true,
  "has_prev": false,
  "total_results": 10
}
```

---

### Image Search

Search for images across multiple engines.

**Endpoint:** `GET /images`

| Parameter | Type   | Required | Description                |
| --------- | ------ | -------- | -------------------------- |
| `q`       | string | Yes      | Image search query         |
| `page`    | int    | No       | Page number (default: `1`) |

Returns an HTML page with image results. Images are fetched from DuckDuckGo → Bing → Google → Brave with automatic fallback.

---

### Placeholder Image API

Fetch an image by keyword — useful for prototyping, mockups, and development.

**Endpoint:** `GET /placeholder`

| Parameter | Type   | Required | Description                               |
| --------- | ------ | -------- | ----------------------------------------- |
| `q`       | string | Yes      | Image keyword (e.g., `cat`, `sunset`)     |
| `page`    | int    | No       | Page for different results (default: `1`) |

**Example — Use in HTML:**

```html
<img src="https://sodeom.com/placeholder?q=mountain" alt="Mountain" />
```

**Get image URL only:**

```
GET /placeholder/url?q=mountain
```

Returns the direct URL string of the image instead of the image itself.

---

## Routes Overview

| Route              | Method    | Description                                  |
| ------------------ | --------- | -------------------------------------------- |
| `/`                | GET       | Homepage & web search                        |
| `/api/search`      | GET       | JSON search API                              |
| `/images`          | GET       | Image search                                 |
| `/placeholder`     | GET       | Placeholder image (serves file)              |
| `/placeholder/url` | GET       | Placeholder image URL (returns URL string)   |
| `/ai`              | GET, POST | AI features (currently disabled for privacy) |
| `/wiki/<query>`    | GET       | Wiki lookup (coming soon)                    |
| `/about`           | GET       | About page                                   |
| `/contact`         | GET       | Contact page                                 |
| `/services`        | GET       | Services overview                            |
| `/privacy-policy`  | GET       | Privacy policy                               |
| `/terms`           | GET       | Terms of service                             |
| `/faq`             | GET       | Frequently asked questions                   |
| `/apis`            | GET       | API documentation                            |
| `/urls`            | GET       | All available routes                         |
| `/blog/<blog>`     | GET       | Blog posts                                   |
| `/funprojects`     | GET       | Fun projects page                            |
| `/fake-sha256`     | GET       | SHA-256 tool                                 |
| `/robots.txt`      | GET       | Robots file                                  |
| `/sitemap.xml`     | GET       | Sitemap                                      |

---

## Project Structure

```
sodeom/
├── app.py                  # Main Flask application & all routes
├── results.py              # Search engine scrapers (DuckDuckGo, Bing, Brave)
├── LICENSE                 # GNU GPLv3 License
├── PRIVACY.md              # Privacy statement
├── README.md               # This file
├── static/
│   ├── style.css           # Main stylesheet
│   ├── styleimg.css        # Image search styles
│   ├── styleabt.css        # About page styles
│   ├── styles.css          # Additional styles
│   ├── apistyle.css        # API docs styles
│   └── images/             # Static images
└── templates/
    ├── base.html           # Base layout (header, nav, footer)
    ├── index.html          # Search page
    ├── images.html         # Image search results
    ├── about.html          # About page
    ├── apis.html           # API documentation
    ├── contact.html        # Contact page
    ├── privacy.html        # Privacy policy
    ├── terms.html          # Terms of service
    ├── faq.html            # FAQ
    ├── placeholder.html    # Placeholder API docs
    ├── services.html       # Services page
    ├── wiki.html           # Wiki page (coming soon)
    └── blogs/              # Blog posts
        └── index.html
```

---

## How Search Works

Sodeom uses a **multi-engine aggregation** strategy with automatic fallback:

### Web Search Pipeline

1. **Query received** → User submits a search query
2. **Concurrent fetching** → DuckDuckGo and Bing are queried in parallel using `asyncio` and `httpx`
3. **URL cleaning** → Redirect URLs from search engines are decoded to extract the actual target URL (handles DuckDuckGo `/l/` redirects and Bing `/ck/` base64-encoded redirects)
4. **NSFW filtering** → Results containing adult keywords are removed automatically
5. **Result merging** → Results from all engines are combined and returned

### Image Search Pipeline

1. **Query received** → User searches for images
2. **Cascading fallback** → Engines are tried in order: DuckDuckGo → Bing → Google → Brave
3. **NSFW filtering** → Image URLs containing adult keywords are excluded
4. **First success wins** → The first engine to return safe results is used

### Search Engines Used

| Engine         | Web Search   | Image Search | Method                                 |
| -------------- | ------------ | ------------ | -------------------------------------- |
| **DuckDuckGo** | ✅ Primary   | ✅ Primary   | HTML scraping (web), JSON API (images) |
| **Bing**       | ✅ Primary   | ✅ Fallback  | HTML scraping                          |
| **Google**     | ❌           | ✅ Fallback  | Regex on inline JSON                   |
| **Brave**      | ✅ Available | ✅ Fallback  | HTML scraping (web), JSON API (images) |

---

## Self-Hosting

Sodeom is designed to be self-hosted. Run your own private search instance:

### Quick Start with Docker (recommended)

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir flask requests beautifulsoup4 httpx selectolax python-dotenv openai
EXPOSE 9999
CMD ["python", "app.py"]
```

```bash
docker build -t sodeom .
docker run -p 9999:9999 sodeom
```

### Production Deployment

For production, use a WSGI server like **Gunicorn**:

```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:9999 app:app
```

**Recommended production setup:**

- Use a reverse proxy (Nginx/Caddy) with HTTPS
- Set a strong `FLASK_SECRET_KEY` in your `.env`
- Run behind a firewall with rate limiting
- Consider adding API key authentication for the `/api/search` endpoint

---

## Contributing

Contributions are welcome! Sodeom is open source under the GPLv3 license.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

### Areas for Contribution

- Adding more search engine backends
- Improving result ranking and deduplication
- UI/UX improvements
- Accessibility enhancements
- Translation / i18n support
- Performance optimization

---

## License

This project is licensed under the **GNU General Public License v3.0** — see the [LICENSE](LICENSE) file for details.

You are free to use, modify, and distribute this software under the terms of the GPLv3.

---

## Contact

- **Website:** [https://sodeom.com/](https://sodeom.com/)
- **Email:** [sodeom@sodeom.com](mailto:sodeom@sodeom.com)
- **Contact Page:** [https://sodeom.com/contact](https://sodeom.com/contact)

---

<p align="center">
  Built with ❤️ by <strong>Abdul Hadi</strong><br>
  © 2025 Sodeom Search Engine
</p>
