"""Configuration. Every secret comes from the environment; none is hard-coded."""

import os
from datetime import timedelta


def _bool(name, default=False):
    return str(os.environ.get(name, str(default))).strip().lower() in (
        "1", "true", "yes", "on")


class BaseConfig:
    SECRET_KEY = os.environ.get("SECRET_KEY", "")
    DATABASE_URL = os.environ.get("DATABASE_URL", "")
    BALLOT_PEPPER = os.environ.get("BALLOT_PEPPER", "")

    # Sessions. HttpOnly always; Secure everywhere but local development.
    SESSION_COOKIE_NAME = "alu_session"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = True
    PERMANENT_SESSION_LIFETIME = timedelta(hours=4)
    # Voters get a much shorter window: long enough to vote, not to leave a
    # session open on a shared library machine all afternoon.
    VOTER_SESSION_MINUTES = int(os.environ.get("VOTER_SESSION_MINUTES", "30"))

    # Account protection
    MAX_FAILED_LOGINS = int(os.environ.get("MAX_FAILED_LOGINS", "5"))
    LOCKOUT_MINUTES = int(os.environ.get("LOCKOUT_MINUTES", "15"))

    # Rate limits (requests per window per IP).
    #
    # Overridable because one number cannot suit every deployment: a campus
    # where thousands of students vote from behind a single NAT address
    # needs a different ballot limit from a test rig, and an integration run
    # signs in as every role in quick succession. The defaults are the
    # production ones, so an unconfigured deployment gets the strict values.
    RATE_LIMITS = {
        "login": (int(os.environ.get("RATE_LIMIT_LOGIN", "10")), 300),
        "ballot": (int(os.environ.get("RATE_LIMIT_BALLOT", "5")), 300),
        "verify": (int(os.environ.get("RATE_LIMIT_VERIFY", "30")), 300),
        "default": (int(os.environ.get("RATE_LIMIT_DEFAULT", "240")), 60),
    }

    CORS_ALLOWED_ORIGINS = [
        o.strip() for o in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",")
        if o.strip()
    ]

    JSON_SORT_KEYS = False
    DEBUG = False
    # Controls whether exception detail reaches a client. Never on in prod.
    EXPOSE_ERRORS = False


class DevelopmentConfig(BaseConfig):
    DEBUG = True
    EXPOSE_ERRORS = True
    SESSION_COOKIE_SECURE = False


class TestingConfig(BaseConfig):
    TESTING = True
    EXPOSE_ERRORS = True
    SESSION_COOKIE_SECURE = False
    SECRET_KEY = os.environ.get("SECRET_KEY", "testing-key-not-for-production")
    BALLOT_PEPPER = os.environ.get("BALLOT_PEPPER", "testing-pepper")


class ProductionConfig(BaseConfig):
    pass


BY_NAME = {"development": DevelopmentConfig, "testing": TestingConfig,
           "production": ProductionConfig}


def get_config(name=None):
    return BY_NAME.get(name or os.environ.get("FLASK_ENV", "production"),
                       ProductionConfig)
