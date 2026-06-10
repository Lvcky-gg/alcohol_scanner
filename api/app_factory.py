import os

from flask import Flask
from flask_cors import CORS

from api.config import Settings
from api.routes import create_api_blueprint


def create_app(settings: Settings | None = None) -> Flask:
    app = Flask(__name__)
    effective_settings = settings or Settings.from_env()
    cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    CORS(
        app,
        resources={r"/*": {"origins": [origin.strip() for origin in cors_origins.split(',') if origin.strip()]}},
    )
    app.register_blueprint(create_api_blueprint(effective_settings))
    return app
