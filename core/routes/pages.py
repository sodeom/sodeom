"""Static / informational page routes."""

import re

from flask import Blueprint, abort, current_app, render_template, send_from_directory

pages_bp = Blueprint("pages", __name__)


@pages_bp.route("/aaaa")
def aaaa():
    return "HELLO, WORLD"


@pages_bp.route("/services")
def services():
    return render_template("services/services.html")


@pages_bp.route("/urls")
def list_urls():
    links = []
    for rule in current_app.url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        url = str(rule)
        methods = ", ".join((rule.methods or set()) - {"HEAD", "OPTIONS"})
        links.append((url, methods))
    return render_template("pages/urls.html", links=sorted(links))


@pages_bp.route("/faq")
def faq():
    return render_template("pages/faq.html")


@pages_bp.route("/blog/<blog>")
def blogs(blog):
    if not re.match(r"^[a-zA-Z0-9_-]+$", blog):
        abort(404)
    return render_template(f"blogs/{blog}.html")


@pages_bp.route("/about")
def about():
    return render_template("pages/about.html")


@pages_bp.route("/services/ai")
def services_ai():
    return render_template("services/ai.html")


@pages_bp.route("/services/software")
def services_software():
    return render_template("services/software.html")


@pages_bp.route("/services/sodium")
def services_sodium():
    return render_template("services/sodium.html")


@pages_bp.route("/services/webs")
def services_webs():
    return render_template("services/webs.html")


@pages_bp.route("/services/projects")
def services_projects():
    return render_template("services/projects.html")


@pages_bp.route("/services/trillioniar")
def services_trillioniar():
    return render_template("services/trillioniar.html")


@pages_bp.route("/contact")
def contact():
    return render_template("pages/contact.html")


@pages_bp.route("/terms")
def terms():
    return render_template("pages/terms.html")


@pages_bp.route("/privacy-policy")
def privacy():
    return render_template("pages/privacy.html")


@pages_bp.route("/funprojects")
def funprojects():
    return render_template("pages/funprojects.html")


@pages_bp.route("/apis")
def apis():
    return render_template("apis/apis.html")


@pages_bp.route("/apis/root")
def apis_root():
    return render_template("apis/apis_root.html")


@pages_bp.route("/apis/search")
def apis_search():
    return render_template("apis/apis_search.html")


@pages_bp.route("/apis/ai")
def apis_ai():
    return render_template("apis/apis_ai.html")


@pages_bp.route("/apis/images")
def apis_images():
    return render_template("apis/apis_images.html")


@pages_bp.route("/apis/placeholder")
def apis_placeholder():
    return render_template("apis/apis_placeholder.html")


@pages_bp.route("/apis/wiki")
def apis_wiki():
    return render_template("apis/apis_wiki.html")


@pages_bp.route("/apis/routes")
def apis_routes():
    return render_template("apis/apis_routes.html")


@pages_bp.route("/robots.txt")
def robots():
    return render_template("system/robots.txt")


@pages_bp.route("/sitemap.xml")
def site():
    return render_template("system/sitemap.xml")


@pages_bp.route("/favicon.ico")
def favicon():
    return send_from_directory(
        current_app.static_folder,
        "favicon.ico",
        mimetype="image/vnd.microsoft.icon",
    )


@pages_bp.route("/fake-sha256")
def fakesha256():
    return render_template("pages/fake-sha256.html")


@pages_bp.route("/ads.txt")
def ads_txt():
    return render_template("system/ads.txt"), 200, {"Content-Type": "text/plain"}


@pages_bp.route("/metrics")
def metrics():
    return render_template("pages/metrics.html", data=[])
