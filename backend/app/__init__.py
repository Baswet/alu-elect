"""ALU-ELECT application factory."""

import logging
import os

from flask import Flask, jsonify

from app.config import get_config
from app.db import close_session, init_engine


def create_app(config_name=None):
    app = Flask(__name__)
    app.config.from_object(get_config(config_name))

    if not app.config.get("SECRET_KEY"):
        raise RuntimeError(
            "SECRET_KEY is not set. Sessions would be forgeable. "
            "Copy .env.example to .env and set it before starting.")
    if not app.config.get("BALLOT_PEPPER"):
        raise RuntimeError(
            "BALLOT_PEPPER is not set. Ballot commitments and student-number "
            "hashes depend on it.")
    if not app.config.get("DATABASE_URL"):
        raise RuntimeError("DATABASE_URL is not set.")

    os.environ.setdefault("BALLOT_PEPPER", app.config["BALLOT_PEPPER"])
    init_engine(app.config["DATABASE_URL"])
    app.teardown_appcontext(close_session)

    from app.security import install as install_security
    install_security(app)

    from app.api import api
    from app.admin_api import admin_api
    app.register_blueprint(api)
    app.register_blueprint(admin_api)

    _errors(app)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    return app


def _errors(app):
    @app.errorhandler(400)
    def _400(e):
        return jsonify({"error": "Malformed request."}), 400

    @app.errorhandler(401)
    def _401(e):
        return jsonify({"error": "Authentication required."}), 401

    @app.errorhandler(403)
    def _403(e):
        return jsonify({"error": "Not permitted."}), 403

    @app.errorhandler(404)
    def _404(e):
        return jsonify({"error": "Not found."}), 404

    @app.errorhandler(405)
    def _405(e):
        return jsonify({"error": "Method not allowed."}), 405

    @app.errorhandler(429)
    def _429(e):
        return jsonify({"error": "Too many requests."}), 429

    @app.errorhandler(Exception)
    def _500(e):
        # Never leak a stack trace or SQL to a client in production.
        app.logger.exception("Unhandled error")
        if app.config.get("EXPOSE_ERRORS"):
            return jsonify({"error": "Server error", "detail": repr(e)}), 500
        return jsonify({"error": "A server error occurred."}), 500
