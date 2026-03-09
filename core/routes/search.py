"""Search-related routes: web, images, videos, news, wiki, and placeholder."""

import mimetypes
import os

from flask import (
    Blueprint,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
)

from core.services.image import install_image
from core.utils.encoding import binary_to_utf8_string, utf8_string_to_binary
from search.results import (
    search_first_image_url,
    search_images,
    search_news,
    search_videos,
    search_web,
    search_wiki,
)

search_bp = Blueprint("search", __name__)


@search_bp.route("/")
def index():
    q = request.args.get("q", "")
    b = request.args.get("b", "")
    page = request.args.get("page", 1, type=int)

    query_error = ""
    if isinstance(q, str):
        q = q.strip()
        if q == "" and request.args.get("q") is not None:
            query_error = "Please enter a search query."

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
            return redirect("/?q=&b=&page=1")

    results = []
    suggestions = []
    corrections = []
    infoboxes = []
    answers = []
    total_results = 0

    if q:
        try:
            data = search_web(q, page)
            results = data.get("results", [])
            suggestions = data.get("suggestions", [])
            corrections = data.get("corrections", [])
            infoboxes = data.get("infoboxes", [])
            answers = data.get("answers", [])
            total_results = data.get("number_of_results", len(results))
        except Exception:
            query_error = "Search temporarily unavailable. Please try again."
            results = []
            total_results = 0

    has_next = total_results >= 10 or len(results) >= 10
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
        suggestions=suggestions,
        corrections=corrections,
        infoboxes=infoboxes,
        answers=answers,
    )


@search_bp.route("/api/search")
def indexapi():
    q = request.args.get("q", "")
    page = request.args.get("page", 1, type=int)
    category = request.args.get("category", "general")

    if not q:
        return jsonify({"error": "Missing query parameter 'q'"}), 400

    if page < 1:
        page = 1

    try:
        if category == "images":
            data = search_images(q, page)
        elif category == "videos":
            data = search_videos(q, page)
        elif category == "news":
            data = search_news(q, page)
        else:
            data = search_web(q, page)

        results = data.get("results", [])
        total_results = data.get("number_of_results", len(results))
    except Exception:
        return jsonify({"error": "Search temporarily unavailable"}), 500

    return jsonify(
        {
            "results": results,
            "query": q,
            "page": page,
            "category": category,
            "has_next": len(results) >= 10,
            "has_prev": page > 1,
            "total_results": total_results,
            "suggestions": data.get("suggestions", []),
            "corrections": data.get("corrections", []),
            "infoboxes": data.get("infoboxes", []),
            "answers": data.get("answers", []),
        }
    )


@search_bp.route("/wiki/<query>", methods=["GET"])
def wiki(query):
    try:
        data = search_wiki(query)
        infoboxes = data.get("infoboxes", [])
        answers = data.get("answers", [])
        results = data.get("results", [])
        suggestions = data.get("suggestions", [])
    except Exception:
        infoboxes = []
        answers = []
        results = []
        suggestions = []

    return render_template(
        "wiki.html",
        query=query,
        infoboxes=infoboxes,
        answers=answers,
        results=results,
        suggestions=suggestions,
    )


@search_bp.route("/api/wiki")
def wiki_json():
    q = request.args.get("q", "")
    if not q:
        return jsonify({"infoboxes": [], "answers": []})
    try:
        data = search_wiki(q)
        infoboxes = data.get("infoboxes", [])
        answers = data.get("answers", [])
    except Exception:
        infoboxes = []
        answers = []
    return jsonify({"infoboxes": infoboxes, "answers": answers})


@search_bp.route("/images")
def images():
    q = request.args.get("q", "")
    page = request.args.get("page", 1, type=int)

    if page < 1:
        page = 1

    imgs = []
    suggestions = []
    corrections = []
    total_results = 0

    if q:
        try:
            data = search_images(q, page)
            imgs = data.get("results", [])
            suggestions = data.get("suggestions", [])
            corrections = data.get("corrections", [])
            total_results = data.get("number_of_results", len(imgs))
        except Exception:
            imgs = []

    return render_template(
        "images.html",
        images=imgs,
        query=q,
        page=page,
        has_next=len(imgs) >= 20,
        has_prev=page > 1,
        total_results=total_results,
        suggestions=suggestions,
        corrections=corrections,
    )


@search_bp.route("/videos")
def videos():
    q = request.args.get("q", "")
    page = request.args.get("page", 1, type=int)

    if page < 1:
        page = 1

    vids = []
    suggestions = []
    corrections = []
    total_results = 0

    if q:
        try:
            data = search_videos(q, page)
            vids = data.get("results", [])
            suggestions = data.get("suggestions", [])
            corrections = data.get("corrections", [])
            total_results = data.get("number_of_results", len(vids))
        except Exception:
            vids = []

    return render_template(
        "videos.html",
        videos=vids,
        query=q,
        page=page,
        has_next=len(vids) >= 10,
        has_prev=page > 1,
        total_results=total_results,
        suggestions=suggestions,
        corrections=corrections,
    )


@search_bp.route("/news")
def news():
    q = request.args.get("q", "")
    page = request.args.get("page", 1, type=int)

    if page < 1:
        page = 1

    articles = []
    suggestions = []
    corrections = []
    total_results = 0

    if q:
        try:
            data = search_news(q, page)
            articles = data.get("results", [])
            suggestions = data.get("suggestions", [])
            corrections = data.get("corrections", [])
            total_results = data.get("number_of_results", len(articles))
        except Exception:
            articles = []

    return render_template(
        "news.html",
        articles=articles,
        query=q,
        page=page,
        has_next=len(articles) >= 10,
        has_prev=page > 1,
        total_results=total_results,
        suggestions=suggestions,
        corrections=corrections,
    )


@search_bp.route("/placeholder")
def placeholder():
    q = request.args.get("q", "")
    if not q:
        return render_template("placeholder.html")

    fallback = os.path.join(current_app.static_folder, "not-found.png")

    try:
        candidates = search_first_image_url(q, count=3)
    except Exception:
        candidates = []

    for url in candidates:
        img_path = install_image(url)
        if img_path and os.path.exists(img_path):
            mime_type, _ = mimetypes.guess_type(img_path)
            return send_file(
                os.path.abspath(img_path),
                mimetype=mime_type or "application/octet-stream",
            )

    return send_file(fallback, mimetype="image/png")


@search_bp.route("/placeholder/url")
def placeholder_url():
    q = request.args.get("q", "")
    if not q:
        return render_template("placeholder.html")

    try:
        urls = search_first_image_url(q, count=1)
        if urls:
            return urls[0]
    except Exception:
        pass

    return os.path.join(current_app.static_folder, "not-found.png")
