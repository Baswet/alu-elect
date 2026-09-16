"""
Authentication for voters and administrators.

Two separate session namespaces on purpose. A voter session can never be
escalated into an admin session by editing a cookie: they are distinct keys,
and every admin route re-loads the AdminUser row and re-checks the role on
each request rather than trusting anything stored in the cookie.
"""

import functools
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from flask import current_app, g, jsonify, request, session

from app.db import get_session
from app.governance import AuthzError, can, log_security
from app.models import AdminUser, Role, Voter
from app.voting import hash_student_no

_ph = PasswordHasher()

SESSION_ADMIN = "admin_id"
SESSION_VOTER = "voter_id"
SESSION_ISSUED = "issued_at"


def hash_password(raw: str) -> str:
    return _ph.hash(raw)


def verify_password(stored: str, raw: str) -> bool:
    if not stored or not raw:
        return False
    try:
        return _ph.verify(stored, raw)
    except (VerifyMismatchError, InvalidHashError, Exception):
        return False


def _now():
    return datetime.now(timezone.utc)


def _locked(entity) -> bool:
    return bool(entity.locked_until and entity.locked_until > _now())


def _register_failure(db, entity) -> None:
    entity.failed_logins = (entity.failed_logins or 0) + 1
    if entity.failed_logins >= current_app.config["MAX_FAILED_LOGINS"]:
        entity.locked_until = _now() + timedelta(
            minutes=current_app.config["LOCKOUT_MINUTES"])
        entity.failed_logins = 0
    db.commit()


def _clear_failures(db, entity) -> None:
    entity.failed_logins = 0
    entity.locked_until = None
    db.commit()


# ---------------------------------------------------------------- login

def login_admin(db, email: str, password: str, ip: str = ""):
    """Returns AdminUser or None. The reason is never disclosed to the client."""
    admin = db.query(AdminUser).filter(
        AdminUser.email == (email or "").strip().lower()).first()

    if admin is None:
        # Spend comparable time so a missing account is not detectable by timing.
        _ph.hash("dummy-password-for-constant-time")
        log_security(db, "admin_login_failed", "unknown account", ip, email or "")
        return None
    if not admin.is_active or _locked(admin):
        log_security(db, "admin_login_blocked",
                     "inactive or locked", ip, admin.email)
        return None
    if not verify_password(admin.password_hash, password):
        _register_failure(db, admin)
        log_security(db, "admin_login_failed", "bad password", ip, admin.email)
        return None

    _clear_failures(db, admin)
    admin.last_login_at = _now()
    db.commit()

    session.clear()
    session[SESSION_ADMIN] = admin.id
    session[SESSION_ISSUED] = _now().isoformat()
    session.permanent = True
    log_security(db, "admin_login_success", "", ip, admin.email)
    return admin


def login_voter(db, election_id: int, student_no: str, password: str, ip: str = ""):
    voter = db.query(Voter).filter(
        Voter.election_id == election_id,
        Voter.student_no_hash == hash_student_no(student_no or ""),
    ).first()

    if voter is None:
        _ph.hash("dummy-password-for-constant-time")
        log_security(db, "voter_login_failed", "unknown voter", ip, "")
        return None
    if _locked(voter):
        log_security(db, "voter_login_blocked", "locked", ip, "")
        return None
    if not voter.is_eligible:
        log_security(db, "voter_login_blocked", "not eligible", ip, "")
        return None
    if not verify_password(voter.password_hash, password):
        _register_failure(db, voter)
        log_security(db, "voter_login_failed", "bad password", ip, "")
        return None

    _clear_failures(db, voter)
    session.clear()
    session[SESSION_VOTER] = voter.id
    session[SESSION_ISSUED] = _now().isoformat()
    session.permanent = False
    log_security(db, "voter_login_success", "", ip, "")
    return voter


def logout():
    session.clear()


# ------------------------------------------------------------- current user

def current_admin():
    aid = session.get(SESSION_ADMIN)
    if not aid:
        return None
    admin = get_session().get(AdminUser, aid)
    # Deactivation takes effect on the very next request, not at next login.
    if admin is None or not admin.is_active:
        session.clear()
        return None
    return admin


def current_voter():
    vid = session.get(SESSION_VOTER)
    if not vid:
        return None
    issued = session.get(SESSION_ISSUED)
    if issued:
        try:
            age = _now() - datetime.fromisoformat(issued)
            if age > timedelta(minutes=current_app.config["VOTER_SESSION_MINUTES"]):
                session.clear()
                return None
        except ValueError:
            session.clear()
            return None
    voter = get_session().get(Voter, vid)
    if voter is None or not voter.is_eligible:
        session.clear()
        return None
    return voter


# --------------------------------------------------------------- decorators

def _deny(message, status):
    return jsonify({"error": message}), status


def admin_required(permission=None):
    def wrap(fn):
        @functools.wraps(fn)
        def inner(*a, **kw):
            admin = current_admin()
            if admin is None:
                return _deny("Authentication required.", 401)
            if permission and not can(admin, permission):
                log_security(get_session(), "authz_denied",
                             "%s lacks %s" % (admin.role.value, permission),
                             request.remote_addr or "", admin.email)
                return _deny("Your role does not permit this action.", 403)
            g.admin = admin
            return fn(*a, **kw)
        return inner
    return wrap


def voter_required(fn):
    @functools.wraps(fn)
    def inner(*a, **kw):
        voter = current_voter()
        if voter is None:
            return _deny("Sign in to continue.", 401)
        g.voter = voter
        return fn(*a, **kw)
    return inner
