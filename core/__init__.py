import os
import secrets

import dotenv
from flask import Flask

from .middleware import _css_version, add_privacy_headers
from .routes import register_blueprints
from .services.searxng import start_searxng

dotenv.load_dotenv()

# Absolute path to the project root (one level above this package)
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=os.path.join(_ROOT, "templates"),
        static_folder=os.path.join(_ROOT, "static"),
    )

    app.secret_key = os.getenv("FLASK_SECRET_KEY") or secrets.token_hex(32)

    # Security / privacy headers on every response
    app.after_request(add_privacy_headers)

    # Cache-busting version tag for CSS files
    app.jinja_env.globals["static_ver"] = _css_version(app.static_folder)

    # Register all route blueprints
    register_blueprints(app)

    # Launch SearXNG subprocess (skip in Flask reloader child process)
    if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        start_searxng()

    return app
