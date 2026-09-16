#!/usr/bin/env python3
"""
LOCAL DEVELOPMENT SERVER ONLY. Not a production entry point.

Serves the static frontend and the real API from one origin, so the browser
can exercise the actual application with cookies and CSRF behaving exactly as
they will in production. Production uses wsgi.py behind gunicorn + nginx;
nothing in app/ is modified or bypassed here.

  python devserver.py [--port 8300] [--frontend ../]
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from werkzeug.middleware.shared_data import SharedDataMiddleware
from werkzeug.serving import run_simple

from app import create_app


def build(frontend_dir):
    application = create_app(os.environ.get("FLASK_ENV", "development"))
    # Static files sit UNDER the API app, so /api/* always wins and every
    # other path falls through to the frontend.
    application.wsgi_app = SharedDataMiddleware(
        application.wsgi_app,
        {"/": os.path.abspath(frontend_dir)},
        fallback_mimetype="text/html",
    )
    return application


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8300)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--frontend", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), ".."))
    args = ap.parse_args()
    print("frontend: %s" % os.path.abspath(args.frontend))
    print("serving http://%s:%d/" % (args.host, args.port))
    run_simple(args.host, args.port, build(args.frontend),
               threaded=True, use_reloader=False)
