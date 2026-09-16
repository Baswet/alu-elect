"""
Public and voter-facing API.

Route names match the contract the existing frontend already expects
(js/election.js, js/results.js, js/verify.js), so the UI can be pointed at
this backend without renaming endpoints.
"""

from flask import Blueprint, g, jsonify, request

from app import ledger, voting
from app.auth import login_voter, logout, voter_required
from app.db import get_session
from app.governance import log_security
from app.models import Candidate, Election, ElectionState, Position, Voter
from app.security import csrf_token

api = Blueprint("api", __name__, url_prefix="/api")


def _election_or_404(db, slug=None):
    """Resolve which election a request means.

    An explicit slug always wins. Without one, prefer the election that is
    actually OPEN - defaulting to "the most recently created" would quietly
    send voters to the wrong ballot as soon as a second election exists, and
    a draft for next year would shadow the live one. If exactly one election
    is open, that is unambiguous; otherwise fall back to the newest so
    read-only summary views still work.
    """
    q = db.query(Election)
    if slug:
        return q.filter(Election.slug == slug).first()
    open_ones = q.filter(Election.state == ElectionState.OPEN).all()
    if len(open_ones) == 1:
        return open_ones[0]
    return q.order_by(Election.id.desc()).first()


def _err(msg, status=400, code=None):
    body = {"error": msg}
    if code:
        body["code"] = code
    return jsonify(body), status


# ------------------------------------------------------------------ meta

@api.get("/health")
def health():
    db = get_session()
    try:
        db.execute(__import__("sqlalchemy").text("SELECT 1"))
        return jsonify({"status": "ok", "database": "up"})
    except Exception:
        return jsonify({"status": "degraded", "database": "down"}), 503


@api.get("/csrf")
def csrf():
    return jsonify({"csrf_token": csrf_token()})


@api.get("/election")
def election_summary():
    db = get_session()
    e = _election_or_404(db)
    if not e:
        return jsonify({"election": None, "message": "No election has been created."})
    positions = db.query(Position).filter(Position.election_id == e.id).count()
    candidates = (db.query(Candidate).join(Position)
                  .filter(Position.election_id == e.id,
                          Candidate.is_active.is_(True)).count())
    eligible = db.query(Voter).filter(Voter.election_id == e.id,
                                      Voter.is_eligible.is_(True)).count()
    voted = db.query(Voter).filter(Voter.election_id == e.id,
                                   Voter.has_voted.is_(True)).count()
    return jsonify({"election": {
        "slug": e.slug, "name": e.name, "state": e.state.value,
        "voting_open": e.state == ElectionState.OPEN,
        "opens_at": e.opens_at.isoformat() if e.opens_at else None,
        "closes_at": e.closes_at.isoformat() if e.closes_at else None,
        "positions": positions, "candidates": candidates,
        "eligible_voters": eligible, "votes_cast": voted,
        "turnout_percent": round(voted * 100.0 / eligible, 1) if eligible else 0.0,
        "certified": e.state == ElectionState.CERTIFIED,
    }})


# States in which the candidate list is public information. A DRAFT
# election is still being assembled and an ARCHIVED one has been withdrawn
# from publication, so neither may leak a nomination list. Everything from
# SCHEDULED onwards has been published to voters by the returning officer.
PUBLIC_CANDIDATE_STATES = {
    ElectionState.SCHEDULED,
    ElectionState.OPEN,
    ElectionState.PAUSED,
    ElectionState.CLOSED,
    ElectionState.COUNTING,
    ElectionState.CERTIFIED,
}


@api.get("/election/candidates")
def public_candidates():
    """Nominated candidates, for the public voter-education page.

    Deliberately separate from GET /election/positions: that route is for a
    signed-in voter filling in a ballot and is authenticated. This one is
    open to anybody, so it carries no ballot state, no voter identity and no
    vote counts - only what a candidate agreed to publish. Withdrawn
    (inactive) candidates are omitted rather than shown greyed out.
    """
    db = get_session()
    e = _election_or_404(db, request.args.get("election"))
    if not e:
        return jsonify({"election": None, "positions": [], "candidates": 0,
                        "message": "No election has been created."})

    if e.state not in PUBLIC_CANDIDATE_STATES:
        return jsonify({
            "election": {"slug": e.slug, "name": e.name, "state": e.state.value,
                         "published": False},
            "positions": [], "candidates": 0,
            "message": "The candidate list for this election has not been "
                       "published yet.",
        })

    rows = (db.query(Position).filter(Position.election_id == e.id)
            .order_by(Position.display_order, Position.id).all())

    positions = []
    total = 0
    for p in rows:
        actives = sorted([c for c in p.candidates if c.is_active],
                         key=lambda c: (c.display_order, c.full_name))
        total += len(actives)
        positions.append({
            "position_id": p.id,
            "slug": p.slug,
            "title": p.title,
            "description": p.description,
            "max_selections": p.max_selections,
            "candidates": [{
                "candidate_id": c.id,
                "name": c.full_name,
                "photo": c.photo_path,
                "symbol": c.symbol,
                "school": c.school,
                "programme": c.programme,
                "year": c.year_of_study,
                "manifesto": c.manifesto,
            } for c in actives],
        })

    return jsonify({
        "election": {"slug": e.slug, "name": e.name, "state": e.state.value,
                     "voting_open": e.state == ElectionState.OPEN,
                     "published": True},
        "positions": positions,
        "candidates": total,
    })


# ------------------------------------------------------------------ auth

@api.post("/election/login")
def voter_login():
    g.rate_bucket = "login"
    db = get_session()
    body = request.get_json(silent=True) or {}
    e = _election_or_404(db, body.get("election"))
    if not e:
        return _err("No election is available.", 404)

    voter = login_voter(db, e.id, body.get("student_no", ""),
                        body.get("password", ""),
                        request.remote_addr or "")
    if voter is None:
        # One message for every failure mode: never reveal whether the
        # student number exists, is ineligible, or is locked.
        return _err("Those sign-in details were not accepted.", 401)

    return jsonify({
        "authenticated": True,
        "csrf_token": csrf_token(),
        "voter": {
            "masked_id": "•••" + str(voter.id)[-2:],
            "school": voter.school,
            "eligible": voter.is_eligible,
            "has_voted": voter.has_voted,
        },
        "election": {"slug": e.slug, "name": e.name, "state": e.state.value},
    })


@api.post("/election/logout")
def voter_logout():
    logout()
    return jsonify({"authenticated": False})


@api.get("/election/me")
@voter_required
def voter_me():
    v = g.voter
    return jsonify({"masked_id": "•••" + str(v.id)[-2:], "school": v.school,
                    "eligible": v.is_eligible, "has_voted": v.has_voted})


# ---------------------------------------------------------------- ballot

@api.get("/election/positions")
@voter_required
def positions():
    db = get_session()
    e = db.get(Election, g.voter.election_id)
    rows = (db.query(Position).filter(Position.election_id == e.id)
            .order_by(Position.display_order, Position.id).all())
    return jsonify({
        "election": {"slug": e.slug, "name": e.name, "state": e.state.value,
                     "voting_open": e.state == ElectionState.OPEN},
        "has_voted": g.voter.has_voted,
        "positions": [{
            "position_id": p.id, "slug": p.slug, "title": p.title,
            "description": p.description, "max_selections": p.max_selections,
            "candidates": [{
                "candidate_id": c.id, "name": c.full_name, "photo": c.photo_path,
                "symbol": c.symbol, "school": c.school, "programme": c.programme,
                "year": c.year_of_study, "manifesto": c.manifesto,
            } for c in sorted([c for c in p.candidates if c.is_active],
                              key=lambda c: (c.display_order, c.full_name))],
        } for p in rows],
    })


@api.post("/election/ballot")
@voter_required
def cast():
    g.rate_bucket = "ballot"
    db = get_session()
    e = db.get(Election, g.voter.election_id)
    body = request.get_json(silent=True) or {}
    try:
        out = voting.cast_ballot(db, e, g.voter, body.get("selections"))
    except voting.VotingError as exc:
        if exc.code in ("already_voted", "not_eligible"):
            log_security(db, "ballot_rejected", exc.code,
                         request.remote_addr or "", "")
        return _err(exc.message, exc.status, exc.code)

    # The receipt is returned once and never stored in the session, so a
    # later session hijack cannot recover it.
    return jsonify({"recorded": True, "reference": out["reference"],
                    "recorded_at": out["recorded_at"],
                    "reveals_choices": False}), 201


@api.get("/election/receipt")
@voter_required
def receipt_status():
    return jsonify({"has_voted": g.voter.has_voted,
                    "note": "Receipts are shown once, at the moment of voting, "
                            "and are not retrievable afterwards."})


# --------------------------------------------------------------- results

@api.get("/election/results")
def results():
    db = get_session()
    e = _election_or_404(db, request.args.get("election"))
    if not e:
        return jsonify({"election": None, "positions": [], "totals": {}})
    if not e.results_public:
        return _err("Results are not published for this election.", 403)
    if e.results_frozen:
        return _err("Results are temporarily frozen by the returning officer.", 423)
    return jsonify(voting.results(db, e))


@api.get("/election/results/stream")
def results_stream():
    """Server-Sent Events. Chosen over WebSockets because results are
    one-directional and SSE survives ordinary reverse proxies."""
    import json
    import time

    from flask import Response, stream_with_context

    from app.db import get_engine
    from sqlalchemy.orm import sessionmaker

    slug = request.args.get("election")
    Session = sessionmaker(bind=get_engine(), future=True, expire_on_commit=False)

    @stream_with_context
    def gen():
        db = Session()
        last = None
        try:
            for _ in range(720):  # ~1 hour, then the client reconnects
                e = (db.query(Election).filter(Election.slug == slug).first()
                     if slug else db.query(Election).order_by(Election.id.desc()).first())
                if e and e.results_public and not e.results_frozen:
                    payload = voting.results(db, e)
                    # Only push when something actually changed. Numbers never
                    # move on their own.
                    fingerprint = json.dumps(payload["positions"], sort_keys=True)
                    if fingerprint != last:
                        last = fingerprint
                        yield "event: results\ndata: %s\n\n" % json.dumps(payload)
                    else:
                        yield ": keep-alive\n\n"
                else:
                    yield "event: unavailable\ndata: {}\n\n"
                db.expire_all()
                time.sleep(5)
        finally:
            db.close()

    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-store",
                             "X-Accel-Buffering": "no", "Connection": "keep-alive"})


# ---------------------------------------------------------- verification

@api.post("/election/verify")
def verify():
    g.rate_bucket = "verify"
    db = get_session()
    body = request.get_json(silent=True) or {}
    return jsonify(voting.verify_receipt(db, body.get("reference", "")))


@api.get("/ledger/status")
def ledger_status():
    return jsonify(ledger.status(get_session()))
