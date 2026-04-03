#!/usr/bin/env python3
"""Comprehensive smoke tests for Sodeom.

This file focuses on the public Flask surface and the key helper functions
that power it. It patches out network-bound pieces so the suite stays fast and
deterministic while still covering the app end-to-end.
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("FLASK_SECRET_KEY", "test-secret-key")
os.environ.setdefault("SEARXNG_URL", "https://example.invalid")

from core import create_app
from search import results as search_results


class SodeomSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        patcher = patch("core.services.searxng.start_searxng", return_value=None)
        cls._start_searxng_patch = patcher
        patcher.start()
        cls.app = create_app()
        cls.client = cls.app.test_client()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._start_searxng_patch.stop()

    def test_app_boots(self) -> None:
        self.assertIsNotNone(self.app)
        self.assertTrue(self.app.secret_key)

    def test_index_route(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Sodeom", response.data)

    def test_search_api_validation(self) -> None:
        response = self.client.get("/api/search")
        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertEqual(payload["error"], "Missing query parameter 'q'")

    def test_search_api_general(self) -> None:
        sample = {
            "results": [
                {"title": "Python", "url": "https://python.org", "content": "Language"}
            ],
            "suggestions": ["py"],
            "corrections": ["python"],
            "infoboxes": [{"infobox": "Python"}],
            "answers": [{"answer": "Python"}],
            "number_of_results": 1,
        }
        with patch("core.routes.search.search_web", return_value=sample):
            response = self.client.get("/api/search?q=python")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["query"], "python")
        self.assertEqual(payload["results"][0]["title"], "Python")
        self.assertEqual(payload["suggestions"], ["py"])
        self.assertEqual(payload["answers"][0]["answer"], "Python")

    def test_search_api_category_routes(self) -> None:
        sample = {
            "results": [{"title": "Item", "url": "https://example.com"}],
            "suggestions": [],
            "corrections": [],
            "infoboxes": [],
            "answers": [],
            "number_of_results": 1,
        }
        cases = [
            ("images", "search_images"),
            ("videos", "search_videos"),
            ("news", "search_news"),
        ]
        for category, func_name in cases:
            with self.subTest(category=category), patch(
                f"core.routes.search.{func_name}", return_value=sample
            ):
                response = self.client.get(f"/api/search?q=test&category={category}")
                self.assertEqual(response.status_code, 200)
                payload = response.get_json()
                self.assertEqual(payload["category"], category)
                self.assertEqual(payload["results"][0]["title"], "Item")

    def test_wiki_api(self) -> None:
        wiki_payload = {
            "title": "Python",
            "extract": "A programming language.",
            "thumbnail": {"source": "https://example.com/python.png"},
            "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Python"}},
        }

        def fake_urlopen(request, timeout=5):
            url = getattr(request, "full_url", request)
            if "opensearch" in url:
                body = json.dumps(["python", ["Python"], [], []]).encode()
            elif "summary" in url:
                body = json.dumps(wiki_payload).encode()
            else:
                body = json.dumps({"query": {"search": []}}).encode()
            return io.BytesIO(body)

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            response = self.client.get("/api/wiki?q=Python")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["infoboxes"][0]["infobox"], "Python")
        self.assertEqual(payload["answers"], [])

    def test_wiki_route(self) -> None:
        with patch("core.routes.search.search_wiki", return_value={"infoboxes": [], "answers": [], "results": [], "suggestions": []}):
            response = self.client.get("/wiki/Python")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Python", response.data)

    def test_images_videos_news_routes(self) -> None:
        sample = {
            "results": [{"title": "Item", "url": "https://example.com"}],
            "suggestions": ["suggestion"],
            "corrections": ["correction"],
            "number_of_results": 1,
        }
        route_patches = {
            "/images?q=cat": patch("core.routes.search.search_images", return_value=sample),
            "/videos?q=cat": patch("core.routes.search.search_videos", return_value=sample),
            "/news?q=cat": patch("core.routes.search.search_news", return_value=sample),
        }
        for url, patcher in route_patches.items():
            with self.subTest(url=url), patcher:
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertIn(b"Item", response.data)

    def test_placeholder_routes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            static_dir = Path(tmpdir)
            fallback = static_dir / "not-found.png"
            fallback.write_bytes(b"fallback-image")

            original_static_folder = self.app.static_folder
            self.app.static_folder = str(static_dir)
            try:
                with patch("core.routes.search.search_first_image_url", return_value=["https://example.com/image.png"]), patch(
                    "core.routes.search.install_image", return_value=str(fallback)
                ):
                    response = self.client.get("/placeholder?q=cat")
                self.assertEqual(response.status_code, 200)
                response.close()

                with patch("core.routes.search.search_first_image_url", return_value=["https://example.com/image.png"]):
                    response = self.client.get("/placeholder/url?q=cat")
                self.assertEqual(response.status_code, 200)
                self.assertIn(b"example.com/image.png", response.data)
                response.close()
            finally:
                self.app.static_folder = original_static_folder

    def test_static_pages(self) -> None:
        paths = [
            "/about",
            "/services",
            "/services/ai",
            "/services/software",
            "/services/sodium",
            "/services/webs",
            "/services/projects",
            "/contact",
            "/terms",
            "/privacy-policy",
            "/funprojects",
            "/apis",
            "/apis/root",
            "/apis/search",
            "/apis/ai",
            "/apis/images",
            "/apis/placeholder",
            "/apis/wiki",
            "/apis/routes",
            "/faq",
            "/urls",
            "/robots.txt",
            "/sitemap.xml",
            "/fake-sha256",
            "/upgrade",
            "/cancel",
            "/success",
            "/metrics",
            "/aaaa",
        ]
        for path in paths:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)

    def test_blog_route_validation(self) -> None:
        response = self.client.get("/blog/how-i-built-the-sodeom-search-engine")
        self.assertEqual(response.status_code, 200)

        response = self.client.get("/blog/../../etc/passwd")
        self.assertEqual(response.status_code, 404)

    def test_headers_and_css_global(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.headers.get("Referrer-Policy"), "no-referrer")
        self.assertEqual(response.headers.get("DNT"), "1")
        with self.app.app_context():
            self.assertTrue(self.app.jinja_env.globals.get("static_ver"))

    def test_search_results_helpers(self) -> None:
        normalized = search_results._filter_results_normalised(
            [
                {"title": "Python", "link": "https://python.org", "description": "Language"},
                {"title": "NSFW", "link": "https://example.com", "description": "adult"},
            ]
        )
        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0]["title"], "Python")

        empty = search_results._empty_response("query", 1)
        self.assertEqual(empty["query"], "query")
        self.assertEqual(empty["results"], [])

    def test_search_web_normalization(self) -> None:
        data = {
            "results": [
                {
                    "title": "Python",
                    "url": "https://python.org",
                    "content": "Programming language",
                    "engine": "test",
                    "engines": ["test"],
                }
            ],
            "suggestions": ["py"],
            "corrections": ["python"],
            "infoboxes": [],
            "answers": [],
            "number_of_results": 1,
        }
        with patch("search.results._query_searxng", return_value=data):
            result = search_results.search_web("python")
        self.assertEqual(result["results"][0]["link"], "https://python.org")
        self.assertEqual(result["number_of_results"], 1)


class SearxngServiceTest(unittest.TestCase):
    def test_searxng_starts_by_default(self) -> None:
        from core.services import searxng as searxng_service

        with patch.object(searxng_service.threading, "Thread") as thread_mock, patch.dict(
            searxng_service.os.environ, {}, clear=False
        ):
            searxng_service.start_searxng()

        thread_mock.assert_called_once()

    def test_searxng_skips_when_disabled(self) -> None:
        from core.services import searxng as searxng_service

        with patch.object(searxng_service.threading, "Thread") as thread_mock, patch.dict(
            searxng_service.os.environ,
            {"SEARXNG_DISABLE_LOCAL_START": "1"},
            clear=False,
        ):
            searxng_service.start_searxng()

        thread_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)