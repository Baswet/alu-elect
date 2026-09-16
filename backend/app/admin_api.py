"""Admin API. Every route re-checks the role server-side."""

import secrets

from flask import Blueprint, g, jsonify, request

from app import governance, ledger, voting
from app.auth import admin_required, current_admin, hash_password, login_admin, logout
from app.db import get_session
from app.models import (ALLOWED_TRANSITIONS, AdminUser, AuditEvent, Candidate,
                        Election, ElectionState, Position, Role, SecurityEvent,
                        Voter)
from app.security import csrf_token
from app.voting import hash_student_no

admin_api = Blueprint("admin_api", __name__, url_prefix="/api/admin")


def _err(msg, status=400):
    return jsonify({"error": msg}), status


def _election(db, eid):
    e = db.get(Election, eid)
    return e


# Actions that cannot be undone, or that change what the public is told the
# result is. A live admin session is not enough for these: the person at the
# keyboard must prove they are the account holder right now. This is what
# makes the "authorization code" field in the admin UI mean something instead
# of being decoration.
REAUTH_STATES = {ElectionState.CLOSED, ElectionState.COUNTING,
                 ElectionState.CERTIFIED, ElectionState.ARCHIVED}


def _reauth(db, password, action):
    """Return an error response, or None when re-authentication succeeded."""
    from app.auth import verify_password
    from app.governance import log_security

    admin = g.admin
    if not password or not verify_password(admin.password_hash, str(password)):
        log_security(db, "admin_reauth_failed", action[:200],
                     request.remote_addr or "", admin.email)
        return jsonify({
            "error": "Confirm this action with your own account password.",
            "code": "reauth_required",
        }), 403
    log_security(db, "admin_reauth_ok", action[:200],
                 request.remote_addr or "", admin.email)
    return None


# ------------------------------------------------------------------ auth

@admin_api.post("/login")
def admin_login():
    g.rate_bucket = "login"
    db = get_session()
    body = request.get_json(silent=True) or {}
    admin = login_admin(db, body.get("email", ""), body.get("password", ""),
                        request.remote_addr or "")
    if admin is None:
        return _err("Those sign-in details were not accepted.", 401)
    return jsonify({"authenticated": True, "csrf_token": csrf_token(),
                    "admin": {"email": admin.email, "name": admin.full_name,
                              "role": admin.role.value,
                              "permissions": sorted(
                                  governance.PERMISSIONS.get(admin.role, set()))}})


@admin_api.post("/logout")
def admin_logout():
    logout()
    return jsonify({"authenticated": False})


@admin_api.get("/me")
@admin_required()
def me():
    a = g.admin
    return jsonify({"email": a.email, "name": a.full_name, "role": a.role.value,
                    "permissions": sorted(governance.PERMISSIONS.get(a.role, set()))})


# -------------------------------------------------------------- elections

@admin_api.get("/elections")
@admin_required("results.view")
def list_elections():
    db = get_session()
    return jsonify({"elections": [{
        "id": e.id, "slug": e.slug, "name": e.name, "state": e.state.value,
        "results_public": e.results_public, "results_frozen": e.results_frozen,
        "certified_at": e.certified_at.isoformat() if e.certified_at else None,
    } for e in db.query(Election).order_by(Election.id.desc()).all()]})


@admin_api.post("/elections")
@admin_required("election.create")
def create_election():
    db = get_session()
    body = request.get_json(silent=True) or {}
    slug = (body.get("slug") or "").strip().lower()
    name = (body.get("name") or "").strip()
    if not slug or not name:
        return _err("A slug and a name are required.")
    if db.query(Election).filter(Election.slug == slug).first():
        return _err("An election with that slug already exists.", 409)
    e = Election(slug=slug, name=name, description=body.get("description"))
    db.add(e)
    db.flush()
    ledger.record_event(db, "election_created", actor=g.admin.email,
                        election_id=e.id, payload={"slug": slug, "name": name})
    db.commit()
    return jsonify({"id": e.id, "slug": e.slug, "state": e.state.value}), 201


@admin_api.post("/elections/action")
@admin_required("election.transition")
def election_action():
    """The endpoint js/admin.js already expects."""
    db = get_session()
    body = request.get_json(silent=True) or {}
    e = _election(db, body.get("election_id"))
    if not e:
        return _err("Election not found.", 404)

    target = body.get("target_state")
    try:
        as_state = ElectionState(target)
    except (ValueError, TypeError):
        return _err("Unknown election state.", 400)

    if as_state in REAUTH_STATES:
        failed = _reauth(db, body.get("password"),
                         "election %s -> %s" % (e.slug, as_state.value))
        if failed:
            return failed

    try:
        governance.transition(db, e, target, g.admin, body.get("reason"))
    except governance.AuthzError as exc:
        return _err(exc.message, exc.status)
    except governance.StateError as exc:
        return _err(exc.message, exc.status)
    return jsonify({"id": e.id, "state": e.state.value})


@admin_api.get("/elections/<int:eid>/readiness")
@admin_required("results.view")
def readiness(eid):
    db = get_session()
    e = _election(db, eid)
    if not e:
        return _err("Election not found.", 404)
    return jsonify(governance.certification_readiness(db, e))


@admin_api.post("/elections/<int:eid>/results-visibility")
@admin_required("results.publish")
def results_visibility(eid):
    db = get_session()
    e = _election(db, eid)
    if not e:
        return _err("Election not found.", 404)
    body = request.get_json(silent=True) or {}

    # Publishing or freezing changes what every student is told the result
    # is, so it takes the same step-up as an irreversible transition.
    failed = _reauth(db, body.get("password"),
                     "results visibility on %s" % e.slug)
    if failed:
        return failed

    if "public" in body:
        e.results_public = bool(body["public"])
    if "frozen" in body:
        e.results_frozen = bool(body["frozen"])
    ledger.record_event(db, "results_visibility_changed", actor=g.admin.email,
                        election_id=e.id,
                        payload={"public": e.results_public,
                                 "frozen": e.results_frozen})
    db.commit()
    return jsonify({"results_public": e.results_public,
                    "results_frozen": e.results_frozen})


# ------------------------------------------------- positions & candidates

@admin_api.get("/elections/<int:eid>/positions")
@admin_required("results.view")
def list_positions(eid):
    """The full nomination record for administration.

    Unlike the public candidate list this includes WITHDRAWN candidates.
    An administrator has to be able to see that somebody was withdrawn -
    a person who silently disappears from the register is exactly what an
    audit is meant to catch.
    """
    db = get_session()
    e = _election(db, eid)
    if not e:
        return _err("Election not found.", 404)
    rows = (db.query(Position).filter(Position.election_id == e.id)
            .order_by(Position.display_order, Position.id).all())
    return jsonify({"positions": [{
        "position_id": p.id, "slug": p.slug, "title": p.title,
        "description": p.description, "display_order": p.display_order,
        "max_selections": p.max_selections,
        "candidates": [{
            "candidate_id": c.id, "full_name": c.full_name,
            "photo_path": c.photo_path, "symbol": c.symbol, "school": c.school,
            "programme": c.programme, "year_of_study": c.year_of_study,
            "manifesto": c.manifesto, "is_active": c.is_active,
            "display_order": c.display_order,
        } for c in sorted(p.candidates,
                          key=lambda c: (c.display_order, c.full_name))],
    } for p in rows]})


@admin_api.get("/elections/<int:eid>/summary")
@admin_required("results.view")
def election_summary_admin(eid):
    """Counts for the dashboard. No per-voter and no per-ballot detail."""
    from sqlalchemy import func

    from app.models import Ballot

    db = get_session()
    e = _election(db, eid)
    if not e:
        return _err("Election not found.", 404)

    positions = db.query(func.count(Position.id)).filter(
        Position.election_id == e.id).scalar() or 0
    active = (db.query(func.count(Candidate.id)).join(Position)
              .filter(Position.election_id == e.id,
                      Candidate.is_active.is_(True)).scalar() or 0)
    withdrawn = (db.query(func.count(Candidate.id)).join(Position)
                 .filter(Position.election_id == e.id,
                         Candidate.is_active.is_(False)).scalar() or 0)
    eligible = db.query(func.count(Voter.id)).filter(
        Voter.election_id == e.id, Voter.is_eligible.is_(True)).scalar() or 0
    suspended = db.query(func.count(Voter.id)).filter(
        Voter.election_id == e.id, Voter.is_eligible.is_(False)).scalar() or 0
    voted = db.query(func.count(Voter.id)).filter(
        Voter.election_id == e.id, Voter.has_voted.is_(True)).scalar() or 0
    ballots = db.query(func.count(Ballot.id)).filter(
        Ballot.election_id == e.id).scalar() or 0

    return jsonify({
        "election": {
            "id": e.id, "slug": e.slug, "name": e.name, "state": e.state.value,
            "voting_open": e.state == ElectionState.OPEN,
            "results_public": e.results_public,
            "results_frozen": e.results_frozen,
            "opens_at": e.opens_at.isoformat() if e.opens_at else None,
            "closes_at": e.closes_at.isoformat() if e.closes_at else None,
            "certified_at": e.certified_at.isoformat() if e.certified_at
                            else None,
            "allowed_transitions": sorted(
                s.value for s in ALLOWED_TRANSITIONS.get(e.state, set())),
        },
        "counts": {
            "positions": positions,
            "candidates": active,
            "candidates_withdrawn": withdrawn,
            "eligible_voters": eligible,
            "suspended_voters": suspended,
            "voted": voted,
            "not_voted": max(eligible - voted, 0),
            "ballots": ballots,
            "turnout_percent": round(voted * 100.0 / eligible, 1)
                               if eligible else 0.0,
        },
        # Ballots and voters are counted in two separate tables that share no
        # key. They should agree; if they ever do not, an operator must see it
        # rather than the dashboard quietly showing one of the two numbers.
        "reconciles": ballots == voted,
    })


@admin_api.post("/elections/<int:eid>/positions")
@admin_required("candidate.manage")
def add_position(eid):
    db = get_session()
    e = _election(db, eid)
    if not e:
        return _err("Election not found.", 404)
    body = request.get_json(silent=True) or {}
    slug = (body.get("slug") or "").strip().lower()
    title = (body.get("title") or "").strip()
    if not slug or not title:
        return _err("A slug and a title are required.")
    p = Position(election_id=e.id, slug=slug, title=title,
                 description=body.get("description"),
                 display_order=int(body.get("display_order") or 0),
                 max_selections=max(1, int(body.get("max_selections") or 1)))
    db.add(p)
    db.flush()
    ledger.record_event(db, "position_created", actor=g.admin.email,
                        election_id=e.id, payload={"position": slug})
    db.commit()
    return jsonify({"position_id": p.id, "slug": p.slug}), 201


@admin_api.post("/positions/<int:pid>/candidates")
@admin_required("candidate.manage")
def add_candidate(pid):
    db = get_session()
    p = db.get(Position, pid)
    if not p:
        return _err("Position not found.", 404)
    body = request.get_json(silent=True) or {}
    name = (body.get("full_name") or "").strip()
    if not name:
        return _err("A candidate name is required.")
    c = Candidate(position_id=p.id, full_name=name,
                  photo_path=body.get("photo_path"), symbol=body.get("symbol"),
                  school=body.get("school"), programme=body.get("programme"),
                  year_of_study=body.get("year_of_study"),
                  manifesto=body.get("manifesto"),
                  display_order=int(body.get("display_order") or 0))
    db.add(c)
    db.flush()
    ledger.record_event(db, "candidate_created", actor=g.admin.email,
                        election_id=p.election_id,
                        payload={"position": p.slug, "name_len": len(name)})
    db.commit()
    return jsonify({"candidate_id": c.id}), 201


@admin_api.patch("/candidates/<int:cid>")
@admin_required("candidate.manage")
def edit_candidate(cid):
    db = get_session()
    c = db.get(Candidate, cid)
    if not c:
        return _err("Candidate not found.", 404)
    body = request.get_json(silent=True) or {}
    changed = []
    for field in ("full_name", "photo_path", "symbol", "school", "programme",
                  "year_of_study", "manifesto", "display_order"):
        if field in body:
            setattr(c, field, body[field])
            changed.append(field)
    # Deactivate, never delete: a withdrawn candidate must stay in the record
    # so historical results remain explicable.
    if "is_active" in body:
        c.is_active = bool(body["is_active"])
        changed.append("is_active")
    ledger.record_event(db, "candidate_updated", actor=g.admin.email,
                        election_id=c.position.election_id,
                        payload={"candidate_ref": c.id, "fields": changed})
    db.commit()
    return jsonify({"candidate_id": c.id, "is_active": c.is_active,
                    "changed": changed})


# ---------------------------------------------------------------- voters

@admin_api.post("/elections/<int:eid>/voters/import")
@admin_required("voter.manage")
def import_voters(eid):
    db = get_session()
    e = _election(db, eid)
    if not e:
        return _err("Election not found.", 404)
    rows = (request.get_json(silent=True) or {}).get("voters") or []
    if not isinstance(rows, list) or len(rows) > 20000:
        return _err("Provide a list of at most 20000 voters.")

    created, skipped, issued = 0, 0, []
    for row in rows:
        sn = str((row or {}).get("student_no") or "").strip()
        if not sn:
            skipped += 1
            continue
        h = hash_student_no(sn)
        if db.query(Voter.id).filter(Voter.election_id == e.id,
                                     Voter.student_no_hash == h).first():
            skipped += 1
            continue
        # A one-time password the registry hands out; it is returned here and
        # never stored in the clear.
        otp = secrets.token_urlsafe(9)
        db.add(Voter(election_id=e.id, student_no_hash=h,
                     display_name=(row.get("display_name") or "")[:160],
                     school=(row.get("school") or "")[:120],
                     password_hash=hash_password(otp)))
        issued.append({"student_no": sn, "initial_password": otp})
        created += 1

    ledger.record_event(db, "voter_roll_imported", actor=g.admin.email,
                        election_id=e.id,
                        payload={"created": created, "skipped": skipped})
    db.commit()
    return jsonify({"created": created, "skipped": skipped,
                    "credentials": issued,
                    "note": "Initial passwords are shown once. They are stored "
                            "only as hashes."}), 201


@admin_api.get("/elections/<int:eid>/voters")
@admin_required("voter.manage")
def list_voters(eid):
    db = get_session()
    rows = db.query(Voter).filter(Voter.election_id == eid).limit(500).all()
    # Deliberately returns has_voted but never anything about the ballot.
    return jsonify({"voters": [{
        "id": v.id, "display_name": v.display_name, "school": v.school,
        "eligible": v.is_eligible, "has_voted": v.has_voted,
        "suspended_reason": v.suspended_reason,
    } for v in rows], "note": "Ballot choices are not recoverable from this view."})


@admin_api.patch("/voters/<int:vid>")
@admin_required("voter.manage")
def edit_voter(vid):
    db = get_session()
    v = db.get(Voter, vid)
    if not v:
        return _err("Voter not found.", 404)
    body = request.get_json(silent=True) or {}
    if "is_eligible" in body:
        v.is_eligible = bool(body["is_eligible"])
        v.suspended_reason = (body.get("reason") or "")[:200] or None
    ledger.record_event(db, "voter_eligibility_changed", actor=g.admin.email,
                        election_id=v.election_id,
                        payload={"eligible": v.is_eligible})
    db.commit()
    return jsonify({"id": v.id, "eligible": v.is_eligible})


# ------------------------------------------------- results, audit, ledger

@admin_api.get("/elections/<int:eid>/results")
@admin_required("results.view")
def admin_results(eid):
    db = get_session()
    e = _election(db, eid)
    if not e:
        return _err("Election not found.", 404)
    return jsonify(voting.results(db, e))


@admin_api.get("/audit")
@admin_required("audit.view")
def audit():
    db = get_session()
    rows = (db.query(AuditEvent).order_by(AuditEvent.seq.desc()).limit(200).all())
    return jsonify({"events": [{
        "seq": r.seq, "type": r.event_type, "actor": r.actor,
        "payload": r.payload, "at": r.created_at.isoformat(),
        "entry_hash": r.entry_hash[:16] + "...",
    } for r in rows], "chain": ledger.verify_chain(db)})


@admin_api.get("/ledger")
@admin_required("audit.view")
def ledger_view():
    return jsonify(ledger.status(get_session()))


@admin_api.get("/security")
@admin_required("security.view")
def security_events():
    db = get_session()
    rows = (db.query(SecurityEvent).order_by(SecurityEvent.id.desc())
            .limit(200).all())
    return jsonify({"events": [{
        "kind": r.kind, "detail": r.detail, "ip": r.ip, "actor": r.actor,
        "at": r.created_at.isoformat(),
    } for r in rows]})
