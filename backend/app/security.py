"""Security middleware: headers, CSRF, rate limiting, CORS."""

import secrets
import time
from collections import defaultdict, deque

from flask import current_app, g, jsonify, request, session

CSRF_SESSION_KEY = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

# Per-IP sliding windows. Adequate for a single-process deployment; a
# multi-worker production deployment should back this with Redis (noted in
# DEPLOYMENT.md) so limits are shared across workers.
_hits: dict[tuple, deque] = defaultdict(deque)


def csrf_token() -> str:
    tok = session.get(CSRF_SESSION_KEY)
    if not tok:
        tok = secrets.token_urlsafe(32)
        session[CSRF_SESSION_KEY] = tok
    return tok


def validate_csrf() -> bool:
    expected = session.get(CSRF_SESSION_KEY)
    if not expected:
        return False
    supplied = request.headers.get(CSRF_HEADER) or ""
    if not supplied:
        body = request.get_json(silent=True) or {}
        supplied = body.get("csrf_token") or ""
    return bool(supplied) and secrets.compare_digest(expected, supplied)


# Buckets are resolved from the path in before_request. Setting g.rate_bucket
# inside a view is too late - before_request has already run - which silently
# left every endpoint on the default limit until this was fixed.
def bucket_for(path: str, method: str) -> str:
    if path.endswith("/login"):
        return "login"
    if path.endswith("/election/ballot") and method == "POST":
        return "ballot"
    if path.endswith("/election/verify"):
        return "verify"
    return "default"


# POST endpoints that change no state and hold no session. They are exempt
# from CSRF (there is nothing to forge on the user's behalf) and are guarded
# by rate limiting instead.
CSRF_EXEMPT_SUFFIXES = ("/login", "/election/verify")


def rate_limit(bucket: str) -> bool:
    """True if the request is allowed."""
    limit, window = current_app.config["RATE_LIMITS"].get(
        bucket, current_app.config["RATE_LIMITS"]["default"])
    key = (bucket, request.remote_addr or "unknown")
    now = time.time()
    q = _hits[key]
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        return False
    q.append(now)
    return True


def reset_rate_limits():
    _hits.clear()


def install(app):
    @app.before_request
    def _guard():
        if not rate_limit(bucket_for(request.path, request.method)):
            return jsonify({"error": "Too many requests. Please slow down."}), 429

        # CSRF on every state-changing request. Cookie sessions mean a
        # cross-site form post would otherwise carry the user's credentials.
        if request.method not in SAFE_METHODS and request.path.startswith("/api/"):
            if any(request.path.endswith(s) for s in CSRF_EXEMPT_SUFFIXES):
                return None
            if not validate_csrf():
                return jsonify({"error": "Invalid or missing CSRF token."}), 403

    @app.after_request
    def _headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        resp.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        if not current_app.config.get("TESTING"):
            resp.headers["Strict-Transport-Security"] = \
                "max-age=31536000; includeSubDomains"

        origin = request.headers.get("Origin")
        allowed = current_app.config.get("CORS_ALLOWED_ORIGINS") or []
        # Explicit allow-list only. No wildcard, because these endpoints are
        # cookie-authenticated and credentials are allowed.
        if origin and origin in allowed:
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
            resp.headers["Access-Control-Allow-Credentials"] = "true"
            resp.headers["Access-Control-Allow-Headers"] = \
                "Content-Type, " + CSRF_HEADER
            resp.headers["Access-Control-Allow-Methods"] = \
                "GET, POST, PATCH, DELETE, OPTIONS"
        return resp
