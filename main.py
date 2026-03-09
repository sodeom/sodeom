from app import app

if __name__ == "__main__":
    import os

    debug_mode = os.getenv("FLASK_DEBUG", "false").lower() in ("true", "1", "yes")
    app.run(host="0.0.0.0", port=9999, debug=debug_mode, threaded=True)
