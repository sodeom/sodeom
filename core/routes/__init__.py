from .ai import ai_bp
from .pages import pages_bp
from .search import search_bp


def register_blueprints(app) -> None:
    app.register_blueprint(search_bp)
    app.register_blueprint(ai_bp)
    app.register_blueprint(pages_bp)
