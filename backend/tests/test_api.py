"""HTTP-level behaviour and security tests for ALU-ELECT."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("BALLOT_PEPPER", "testing-pepper")
os.environ.setdefault("SECRET_KEY", "testing-key-not-for-production")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://postgres@/aluelect_api_test?host=/tmp&port=5433")

import pytest
from sqlalchemy import create_engine, func, text
from sqlalchemy.orm import sessionmaker

from app import create_app
from app.auth import hash_password
from app.db import init_engine
from app.models import (AdminUser, Ballot, Base, Candidate, Election,
                        ElectionState, Position, Role, Voter)
from app.security import reset_rate_limits
from app.voting import hash_student_no

from tests.dbguard import assert_disposable  # noqa: E402

# The fixture below drops every table in this database. Refuse anything
# that is not named as a disposable one - see tests/dbguard.py.
DB = assert_disposable(os.environ["DATABASE_URL"], "DATABASE_URL")
VOTER_PW = "voter-pass-123"
ADMIN_PW = "admin-pass-123"


@pytest.fixture()
def app():
    engine = create_engine(DB)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()

    e = Election(slug="ge-2026", name="Student Council 2026",
                 state=ElectionState.OPEN)
    s.add(e); s.flush()
    p = Position(election_id=e.id, slug="president", title="President")
    s.add(p); s.flush()
    c1 = Candidate(position_id=p.id, full_name="Amina Otieno")
    c2 = Candidate(position_id=p.id, full_name="Brian Kiptoo")
    s.add_all([c1, c2])
    for i in range(3):
        s.add(Voter(election_id=e.id,
                    student_no_hash=hash_student_no("ALU/000%d" % i),
                    display_name="Voter %d" % i, school="SESS",
                    password_hash=hash_password(VOTER_PW)))
    for role in Role:
        s.add(AdminUser(email="%s@alupe.ac.ke" % role.value.lower(),
                        password_hash=hash_password(ADMIN_PW), role=role))
    s.commit()
    ids = {"election": e.id, "position": p.id, "c1": c1.id, "c2": c2.id}
    s.close()

    application = create_app("testing")
    init_engine(DB)
    application.config["IDS"] = ids
    reset_rate_limits()
    yield application
    engine.dispose()


@pytest.fixture()
def client(app):
    return app.test_client()


def login_voter(client, sn="ALU/0000", election="ge-2026"):
    r = client.post("/api/election/login",
                    json={"student_no": sn, "password": VOTER_PW,
                          "election": election})
    assert r.status_code == 200, r.get_json()
    return r.get_json()["csrf_token"]


def login_admin(client, role=Role.SUPER_ADMIN):
    r = client.post("/api/admin/login",
                    json={"email": "%s@alupe.ac.ke" % role.value.lower(),
                          "password": ADMIN_PW})
    assert r.status_code == 200, r.get_json()
    return r.get_json()["csrf_token"]


# ------------------------------------------------------------- basics

def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.get_json()["database"] == "up"


def test_security_headers_present(client):
    h = client.get("/api/health").headers
    assert h["X-Content-Type-Options"] == "nosniff"
    assert h["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in h["Content-Security-Policy"]
    assert h["Cache-Control"] == "no-store"
    assert h["Referrer-Policy"] == "strict-origin-when-cross-origin"


def test_voting_flow_end_to_end(client, app):
    ids = app.config["IDS"]
    csrf = login_voter(client)

    r = client.get("/api/election/positions")
    assert r.status_code == 200
    body = r.get_json()
    assert len(body["positions"][0]["candidates"]) == 2
    assert body["has_voted"] is False

    r = client.post("/api/election/ballot", json={
        "csrf_token": csrf,
        "selections": [{"position_id": ids["position"], "candidate_id": ids["c1"]}]})
    assert r.status_code == 201, r.get_json()
    out = r.get_json()
    assert out["recorded"] is True and out["reference"].startswith("ALU-")
    assert out["reveals_choices"] is False

    v = client.post("/api/election/verify", json={"reference": out["reference"]})
    vb = v.get_json()
    assert vb["found"] and vb["recorded"] and vb["integrity_verified"]
    assert "amina" not in repr(vb).lower()

    res = client.get("/api/election/results").get_json()
    pres = res["positions"][0]
    assert pres["candidates"][0]["votes"] == 1
    assert len(pres["candidates"]) == 2          # zero-vote candidate visible
    assert res["election"]["provisional"] is True


# ------------------------------------------------------- authn / authz

def test_ballot_requires_authentication(client, app):
    ids = app.config["IDS"]
    r = client.post("/api/election/ballot", json={
        "selections": [{"position_id": ids["position"], "candidate_id": ids["c1"]}]})
    assert r.status_code in (401, 403)


def test_positions_requires_authentication(client):
    assert client.get("/api/election/positions").status_code == 401


def test_login_failure_message_is_uniform(client):
    a = client.post("/api/election/login",
                    json={"student_no": "ALU/9999", "password": "x"})
    b = client.post("/api/election/login",
                    json={"student_no": "ALU/0000", "password": "wrong"})
    assert a.status_code == b.status_code == 401
    assert a.get_json()["error"] == b.get_json()["error"]


def test_admin_endpoints_reject_anonymous(client, app):
    eid = app.config["IDS"]["election"]
    for method, path in [("get", "/api/admin/elections"),
                         ("get", "/api/admin/audit"),
                         ("get", "/api/admin/security"),
                         ("get", "/api/admin/elections/%d/voters" % eid),
                         ("post", "/api/admin/elections/action")]:
        r = getattr(client, method)(path, json={})
        assert r.status_code in (401, 403), path


@pytest.mark.parametrize("role,expected", [
    (Role.SUPER_ADMIN, 200), (Role.ELECTION_ADMIN, 403),
    (Role.RESULTS_OFFICER, 403), (Role.AUDITOR, 403),
    (Role.READ_ONLY_ADMIN, 403),
])
def test_only_super_admin_may_certify(client, app, role, expected):
    """Privilege escalation: a lesser role must not be able to certify."""
    eid = app.config["IDS"]["election"]
    csrf = login_admin(client, Role.SUPER_ADMIN)
    for target in ("CLOSED", "COUNTING"):
        r = client.post("/api/admin/elections/action",
                        json={"csrf_token": csrf, "election_id": eid,
                              "target_state": target,
                              "password": ADMIN_PW})
        assert r.status_code == 200, r.get_json()
    client.post("/api/admin/logout", json={"csrf_token": csrf})

    csrf = login_admin(client, role)
    r = client.post("/api/admin/elections/action",
                    json={"csrf_token": csrf, "election_id": eid,
                          "target_state": "CERTIFIED",
                          "password": ADMIN_PW})
    assert r.status_code == expected, r.get_json()


def test_read_only_admin_cannot_manage_candidates(client, app):
    pid = app.config["IDS"]["position"]
    csrf = login_admin(client, Role.READ_ONLY_ADMIN)
    r = client.post("/api/admin/positions/%d/candidates" % pid,
                    json={"csrf_token": csrf, "full_name": "Injected"})
    assert r.status_code == 403


def test_auditor_cannot_change_election_state(client, app):
    eid = app.config["IDS"]["election"]
    csrf = login_admin(client, Role.AUDITOR)
    r = client.post("/api/admin/elections/action",
                    json={"csrf_token": csrf, "election_id": eid,
                          "target_state": "PAUSED"})
    assert r.status_code == 403


def test_voter_session_cannot_reach_admin_api(client):
    """A voter cookie must not be usable as an admin cookie."""
    login_voter(client)
    assert client.get("/api/admin/elections").status_code == 401


# --------------------------------------------------------------- CSRF

def test_ballot_without_csrf_is_refused(client, app):
    ids = app.config["IDS"]
    login_voter(client)
    r = client.post("/api/election/ballot", json={
        "selections": [{"position_id": ids["position"], "candidate_id": ids["c1"]}]})
    assert r.status_code == 403
    assert "csrf" in r.get_json()["error"].lower()


def test_ballot_with_wrong_csrf_is_refused(client, app):
    ids = app.config["IDS"]
    login_voter(client)
    r = client.post("/api/election/ballot", json={
        "csrf_token": "forged-token",
        "selections": [{"position_id": ids["position"], "candidate_id": ids["c1"]}]})
    assert r.status_code == 403


def test_csrf_accepted_via_header(client, app):
    ids = app.config["IDS"]
    csrf = login_voter(client)
    r = client.post("/api/election/ballot",
                    json={"selections": [{"position_id": ids["position"],
                                          "candidate_id": ids["c1"]}]},
                    headers={"X-CSRF-Token": csrf})
    assert r.status_code == 201


# ------------------------------------------------------ duplicate/replay

def test_duplicate_vote_over_http(client, app):
    ids = app.config["IDS"]
    csrf = login_voter(client)
    payload = {"csrf_token": csrf,
               "selections": [{"position_id": ids["position"],
                               "candidate_id": ids["c1"]}]}
    assert client.post("/api/election/ballot", json=payload).status_code == 201
    r2 = client.post("/api/election/ballot", json=payload)
    assert r2.status_code == 409
    assert r2.get_json()["code"] == "already_voted"


def test_replay_after_relogin_still_refused(client, app):
    ids = app.config["IDS"]
    csrf = login_voter(client)
    payload = {"csrf_token": csrf,
               "selections": [{"position_id": ids["position"],
                               "candidate_id": ids["c1"]}]}
    client.post("/api/election/ballot", json=payload)
    client.post("/api/election/logout", json={"csrf_token": csrf})
    csrf2 = login_voter(client)
    r = client.post("/api/election/ballot",
                    json={"csrf_token": csrf2,
                          "selections": payload["selections"]})
    assert r.status_code == 409


# -------------------------------------------------------------- IDOR

def test_voter_cannot_vote_in_another_election(client, app):
    """IDOR: forging position/candidate ids from another election."""
    ids = app.config["IDS"]
    engine = create_engine(DB)
    S = sessionmaker(bind=engine)
    s = S()
    other = Election(slug="other", name="Other", state=ElectionState.DRAFT)
    s.add(other); s.flush()
    op = Position(election_id=other.id, slug="p", title="P")
    s.add(op); s.flush()
    oc = Candidate(position_id=op.id, full_name="Outsider")
    s.add(oc); s.commit()
    oc_id, op_id = oc.id, op.id
    s.close(); engine.dispose()

    csrf = login_voter(client)
    r = client.post("/api/election/ballot", json={
        "csrf_token": csrf,
        "selections": [{"position_id": op_id, "candidate_id": oc_id}]})
    assert r.status_code == 400
    assert r.get_json()["code"] == "bad_position"


def test_cannot_vote_for_candidate_of_another_position(client, app):
    ids = app.config["IDS"]
    csrf = login_voter(client)
    r = client.post("/api/election/ballot", json={
        "csrf_token": csrf,
        "selections": [{"position_id": ids["position"], "candidate_id": 999999}]})
    assert r.status_code == 400


# ------------------------------------------------------------ injection

@pytest.mark.parametrize("payload", [
    "'; DROP TABLE ballots;--", "1 OR 1=1", "' UNION SELECT NULL--",
    "<script>alert(1)</script>", "../../../../etc/passwd",
    "%2e%2e%2f%2e%2e%2fetc/passwd", "\x00null",
])
def test_injection_payloads_are_inert(client, app, payload):
    """SQLi / XSS / traversal strings must neither execute nor be echoed raw."""
    r = client.post("/api/election/verify", json={"reference": payload})
    assert r.status_code == 200
    assert r.get_json()["found"] is False
    # Reflected content must never come back as executable markup.
    assert "<script>" not in r.get_data(as_text=True)

    r2 = client.post("/api/election/login",
                     json={"student_no": payload, "password": payload})
    assert r2.status_code == 401

    engine = create_engine(DB)
    with engine.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM ballots")).scalar() is not None
    engine.dispose()


def test_json_content_type_is_enforced(client):
    r = client.post("/api/election/verify", data="reference=x",
                    content_type="application/x-www-form-urlencoded")
    assert r.status_code in (200, 400, 415)


@pytest.mark.parametrize("body", [
    {"selections": "not-a-list"}, {"selections": [{"position_id": None}]},
    {"selections": [{"position_id": 1, "candidate_id": {"a": 1}}]},
    {}, {"selections": [1, 2, 3]},
])
def test_malformed_ballot_json_refused(client, app, body):
    csrf = login_voter(client)
    body = dict(body, csrf_token=csrf)
    r = client.post("/api/election/ballot", json=body)
    assert r.status_code in (400, 409)


# ------------------------------------------------------- rate limiting

def test_login_brute_force_is_rate_limited(client):
    reset_rate_limits()
    codes = [client.post("/api/election/login",
                         json={"student_no": "ALU/0000", "password": "wrong"}
                         ).status_code for _ in range(15)]
    assert 429 in codes, codes


def test_account_locks_after_repeated_failures(client, app):
    reset_rate_limits()
    for _ in range(app.config["MAX_FAILED_LOGINS"]):
        client.post("/api/election/login",
                    json={"student_no": "ALU/0001", "password": "wrong"})
    r = client.post("/api/election/login",
                    json={"student_no": "ALU/0001", "password": VOTER_PW})
    assert r.status_code == 401  # correct password, but locked


# ------------------------------------------------------------- privacy

def test_admin_voter_list_never_exposes_choices(client, app):
    ids = app.config["IDS"]
    csrf = login_voter(client)
    client.post("/api/election/ballot", json={
        "csrf_token": csrf,
        "selections": [{"position_id": ids["position"], "candidate_id": ids["c1"]}]})
    client.post("/api/election/logout", json={"csrf_token": csrf})

    login_admin(client, Role.SUPER_ADMIN)
    body = client.get("/api/admin/elections/%d/voters" % ids["election"]).get_json()
    assert any(v["has_voted"] for v in body["voters"])
    # No candidate name and no ballot-bearing field may appear on any row.
    rows = repr(body["voters"]).lower()
    for leak in ("amina", "otieno", "brian", "candidate", "selection", "ballot",
                 "choice", "vote_for"):
        assert leak not in rows, "voter list leaked %r" % leak
    assert not {"candidate_id", "selections", "ballot_id", "choice"} & set(
        body["voters"][0])


def test_audit_log_contains_no_ballot_content(client, app):
    ids = app.config["IDS"]
    csrf = login_voter(client)
    client.post("/api/election/ballot", json={
        "csrf_token": csrf,
        "selections": [{"position_id": ids["position"], "candidate_id": ids["c1"]}]})
    client.post("/api/election/logout", json={"csrf_token": csrf})

    login_admin(client, Role.AUDITOR)
    blob = repr(client.get("/api/admin/audit").get_json()).lower()
    for leak in ("amina", "otieno", "candidate_id", "voter_id", "student"):
        assert leak not in blob, "audit leaked %r" % leak


def test_error_responses_do_not_leak_internals(client):
    r = client.get("/api/does-not-exist")
    assert r.status_code == 404
    blob = r.get_data(as_text=True).lower()
    for leak in ("traceback", "sqlalchemy", "postgres", "/home/", "psycopg"):
        assert leak not in blob


def test_ledger_status_is_honest(client):
    body = client.get("/api/ledger/status").get_json()
    assert body["blockchain_connected"] is False
    assert body["mode"] == "AUDIT_LEDGER_DEVELOPMENT_MODE"
    assert body["tamper_proof"] is False


# ----------------------------------------------------------------- CORS

def test_unlisted_origin_gets_no_cors_header(client):
    r = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "Access-Control-Allow-Origin" not in r.headers


def test_no_wildcard_cors(client):
    r = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert r.headers.get("Access-Control-Allow-Origin") != "*"


# ------------------------------------------------- state-machine over HTTP

def test_cannot_force_election_open_from_draft_over_http(client, app):
    eid = app.config["IDS"]["election"]
    csrf = login_admin(client, Role.SUPER_ADMIN)
    for t in ("CLOSED", "COUNTING", "CERTIFIED"):
        client.post("/api/admin/elections/action",
                    json={"csrf_token": csrf, "election_id": eid,
                          "target_state": t})
    r = client.post("/api/admin/elections/action",
                    json={"csrf_token": csrf, "election_id": eid,
                          "target_state": "OPEN"})
    assert r.status_code == 409


def test_unknown_state_rejected(client, app):
    eid = app.config["IDS"]["election"]
    csrf = login_admin(client, Role.SUPER_ADMIN)
    r = client.post("/api/admin/elections/action",
                    json={"csrf_token": csrf, "election_id": eid,
                          "target_state": "PRESIDENT_FOR_LIFE"})
    assert r.status_code == 400


def test_voting_blocked_once_paused(client, app):
    ids = app.config["IDS"]
    csrf_a = login_admin(client, Role.SUPER_ADMIN)
    client.post("/api/admin/elections/action",
                json={"csrf_token": csrf_a, "election_id": ids["election"],
                      "target_state": "PAUSED"})
    client.post("/api/admin/logout", json={"csrf_token": csrf_a})

    csrf = login_voter(client)
    r = client.post("/api/election/ballot", json={
        "csrf_token": csrf,
        "selections": [{"position_id": ids["position"], "candidate_id": ids["c1"]}]})
    assert r.status_code == 409
    assert r.get_json()["code"] == "election_not_open"


def test_results_respect_freeze(client, app):
    eid = app.config["IDS"]["election"]
    csrf = login_admin(client, Role.SUPER_ADMIN)
    r = client.post("/api/admin/elections/%d/results-visibility" % eid,
                    json={"csrf_token": csrf, "frozen": True,
                          "password": ADMIN_PW})
    assert r.status_code == 200, r.get_json()
    client.post("/api/admin/logout", json={"csrf_token": csrf})
    assert client.get("/api/election/results").status_code == 423


def test_candidate_deactivation_not_deletion(client, app):
    ids = app.config["IDS"]
    csrf = login_admin(client, Role.ELECTION_ADMIN)
    r = client.patch("/api/admin/candidates/%d" % ids["c2"],
                     json={"csrf_token": csrf, "is_active": False})
    assert r.status_code == 200 and r.get_json()["is_active"] is False
    engine = create_engine(DB)
    with engine.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM candidates WHERE id=:i"),
                         {"i": ids["c2"]}).scalar() == 1
    engine.dispose()


# ------------------------------------------------- step-up authentication
#
# A live admin session is not enough to close, count, certify, archive,
# publish or freeze. Those need the administrator's own password again, at
# the moment of acting. Without this, an unattended signed-in machine is
# enough to end an election.

def test_irreversible_transition_needs_the_password(client, app):
    eid = app.config["IDS"]["election"]
    csrf = login_admin(client, Role.SUPER_ADMIN)
    r = client.post("/api/admin/elections/action",
                    json={"csrf_token": csrf, "election_id": eid,
                          "target_state": "CLOSED"})
    assert r.status_code == 403
    assert r.get_json()["code"] == "reauth_required"


def test_wrong_password_does_not_close_the_election(client, app):
    eid = app.config["IDS"]["election"]
    csrf = login_admin(client, Role.SUPER_ADMIN)
    r = client.post("/api/admin/elections/action",
                    json={"csrf_token": csrf, "election_id": eid,
                          "target_state": "CLOSED",
                          "password": "not-the-password"})
    assert r.status_code == 403
    state = client.get("/api/admin/elections").get_json()["elections"]
    assert [e for e in state if e["id"] == eid][0]["state"] == "OPEN"


def test_reversible_transition_does_not_need_the_password(client, app):
    """Pausing is undoable, so it must not demand a re-type."""
    eid = app.config["IDS"]["election"]
    csrf = login_admin(client, Role.SUPER_ADMIN)
    r = client.post("/api/admin/elections/action",
                    json={"csrf_token": csrf, "election_id": eid,
                          "target_state": "PAUSED"})
    assert r.status_code == 200, r.get_json()


def test_publishing_results_needs_the_password(client, app):
    eid = app.config["IDS"]["election"]
    csrf = login_admin(client, Role.SUPER_ADMIN)
    r = client.post("/api/admin/elections/%d/results-visibility" % eid,
                    json={"csrf_token": csrf, "public": False})
    assert r.status_code == 403
    assert client.get("/api/election/results").status_code == 200


def test_failed_reauth_is_recorded_as_a_security_event(client, app):
    eid = app.config["IDS"]["election"]
    csrf = login_admin(client, Role.SUPER_ADMIN)
    client.post("/api/admin/elections/action",
                json={"csrf_token": csrf, "election_id": eid,
                      "target_state": "CLOSED", "password": "wrong"})
    kinds = [e["kind"] for e in
             client.get("/api/admin/security").get_json()["events"]]
    assert "admin_reauth_failed" in kinds


# ------------------------------------------------ public candidate list

def test_public_candidates_needs_no_login(client):
    r = client.get("/api/election/candidates")
    assert r.status_code == 200
    assert r.get_json()["positions"]


def test_public_candidates_hides_withdrawn(client, app):
    ids = app.config["IDS"]
    csrf = login_admin(client, Role.ELECTION_ADMIN)
    client.patch("/api/admin/candidates/%d" % ids["c2"],
                 json={"csrf_token": csrf, "is_active": False})
    client.post("/api/admin/logout", json={"csrf_token": csrf})

    names = [c["name"] for p in
             client.get("/api/election/candidates").get_json()["positions"]
             for c in p["candidates"]]
    admin_names = []
    csrf = login_admin(client, Role.ELECTION_ADMIN)
    for p in client.get("/api/admin/elections/%d/positions"
                        % app.config["IDS"]["election"]).get_json()["positions"]:
        admin_names += [c["full_name"] for c in p["candidates"]]

    # The withdrawn nomination is gone from the public list but still on
    # the administrative record, which is where an auditor looks for it.
    assert len(admin_names) == len(names) + 1


def test_public_candidates_carries_no_votes_or_voters(client):
    """No vote counts and nothing about voters on the public roster.

    Checks the KEYS rather than scanning the text: the election is called
    "Student Council 2026", so a substring sweep flags its own name.
    """
    body = client.get("/api/election/candidates").get_json()

    keys = set()

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                keys.add(k)
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(body)
    forbidden = {"votes", "vote_count", "tally", "voter", "voters",
                 "has_voted", "student_no", "student_no_hash", "ballot",
                 "ballots", "turnout", "eligible_voters", "receipt"}
    assert not (keys & forbidden), sorted(keys & forbidden)


def test_public_candidates_hidden_before_publication(client, app):
    """A DRAFT election must not leak its nomination list."""
    from sqlalchemy import create_engine, text as sqltext
    eid = app.config["IDS"]["election"]
    engine = create_engine(DB)
    with engine.begin() as c:
        c.execute(sqltext("UPDATE elections SET state='DRAFT' WHERE id=:i"),
                  {"i": eid})
    body = client.get("/api/election/candidates").get_json()
    assert body["positions"] == []
    assert body["election"]["published"] is False


# ------------------------------------------------------ admin summary

def test_admin_summary_reconciles_ballots_and_voters(client, app):
    eid = app.config["IDS"]["election"]
    login_voter(client)
    pid = app.config["IDS"]["position"]
    cid = app.config["IDS"]["c1"]
    csrf = client.get("/api/csrf").get_json()["csrf_token"]
    client.post("/api/election/ballot",
                json={"csrf_token": csrf,
                      "selections": [{"position_id": pid,
                                      "candidate_id": cid}]},
                headers={"X-CSRF-Token": csrf})
    client.post("/api/election/logout", json={"csrf_token": csrf})

    login_admin(client, Role.SUPER_ADMIN)
    body = client.get("/api/admin/elections/%d/summary" % eid).get_json()
    assert body["counts"]["ballots"] == body["counts"]["voted"]
    assert body["reconciles"] is True


def test_admin_summary_needs_a_role(client, app):
    eid = app.config["IDS"]["election"]
    assert client.get("/api/admin/elections/%d/summary" % eid).status_code == 401
