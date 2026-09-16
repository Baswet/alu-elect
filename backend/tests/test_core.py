"""Behavioural tests for ALU-ELECT, run against real PostgreSQL."""

import os
import sys
import threading
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("BALLOT_PEPPER", "test-pepper-not-for-production")

import pytest
from sqlalchemy import create_engine, func, inspect, text
from sqlalchemy.orm import sessionmaker

from app import governance, ledger, voting
from app.models import (AdminUser, Ballot, BallotSelection, Base, Candidate,
                        Election, ElectionState, Position, Receipt, Role, Voter)

from tests.dbguard import assert_disposable  # noqa: E402

# The fixture below drops every table in this database. Refuse anything
# that is not named as a disposable one - see tests/dbguard.py.
DB = assert_disposable(
    os.environ.get("TEST_DATABASE_URL",
                   "postgresql+psycopg://postgres@/aluelect_test"
                   "?host=/tmp&port=5433"),
    "TEST_DATABASE_URL")


@pytest.fixture()
def session():
    engine = create_engine(DB)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()
    engine.dispose()


def build(session, n_voters=5, state=ElectionState.OPEN):
    e = Election(slug="ge-2026", name="Student Council 2026", state=state)
    session.add(e)
    session.flush()
    pres = Position(election_id=e.id, slug="president", title="President",
                    display_order=1)
    sec = Position(election_id=e.id, slug="secretary", title="Secretary",
                   display_order=2)
    session.add_all([pres, sec])
    session.flush()
    cands = [
        Candidate(position_id=pres.id, full_name="Amina Otieno"),
        Candidate(position_id=pres.id, full_name="Brian Kiptoo"),
        Candidate(position_id=pres.id, full_name="Cynthia Wafula"),
        Candidate(position_id=sec.id, full_name="Daniel Mwangi"),
        Candidate(position_id=sec.id, full_name="Esther Njeri"),
    ]
    session.add_all(cands)
    voters = [Voter(election_id=e.id,
                    student_no_hash=voting.hash_student_no("ALU/%04d" % i),
                    display_name="Voter %d" % i, school="SESS")
              for i in range(n_voters)]
    session.add_all(voters)
    session.commit()
    return e, pres, sec, cands, voters


# ---------------------------------------------------------------- privacy

def test_no_column_links_a_voter_to_a_candidate(session):
    """The structural guarantee: no join exists from voters to choices."""
    insp = inspect(session.get_bind())
    ballot_cols = {c["name"] for c in insp.get_columns("ballots")}
    sel_cols = {c["name"] for c in insp.get_columns("ballot_selections")}
    receipt_cols = {c["name"] for c in insp.get_columns("receipts")}

    for cols, table in ((ballot_cols, "ballots"), (sel_cols, "ballot_selections"),
                        (receipt_cols, "receipts")):
        assert not {"voter_id", "student_no", "student_no_hash"} & cols, \
            "%s must not carry voter identity" % table

    for table in ("ballots", "ballot_selections", "receipts"):
        for fk in insp.get_foreign_keys(table):
            assert fk["referred_table"] != "voters", \
                "%s must not have a foreign key to voters" % table


def test_ballot_timestamp_is_coarsened(session):
    e, pres, sec, cands, voters = build(session)
    voting.cast_ballot(session, e, voters[0],
                       [{"position_id": pres.id, "candidate_id": cands[0].id}])
    b = session.query(Ballot).one()
    assert (b.cast_hour.minute, b.cast_hour.second, b.cast_hour.microsecond) == (0, 0, 0)


# ------------------------------------------------------------- one vote

def test_second_ballot_from_same_voter_is_refused(session):
    e, pres, sec, cands, voters = build(session)
    sel = [{"position_id": pres.id, "candidate_id": cands[0].id}]
    voting.cast_ballot(session, e, voters[0], sel)

    with pytest.raises(voting.VotingError) as ex:
        voting.cast_ballot(session, e, voters[0], sel)
    assert ex.value.code == "already_voted"
    assert session.query(func.count(Ballot.id)).scalar() == 1


def test_concurrent_double_submission_records_one_ballot(session):
    """The race a determined voter would actually try."""
    e, pres, sec, cands, voters = build(session)
    engine = session.get_bind()
    Session = sessionmaker(bind=engine)
    sel = [{"position_id": pres.id, "candidate_id": cands[0].id}]
    results = []
    barrier = threading.Barrier(2)

    def attempt():
        s = Session()
        try:
            el = s.get(Election, e.id)
            v = s.get(Voter, voters[0].id)
            barrier.wait(timeout=10)
            voting.cast_ballot(s, el, v, sel)
            results.append("ok")
        except Exception as exc:
            results.append(type(exc).__name__)
        finally:
            s.close()

    ts = [threading.Thread(target=attempt) for _ in range(2)]
    [t.start() for t in ts]
    [t.join(timeout=20) for t in ts]

    session.expire_all()
    assert results.count("ok") == 1, results
    assert session.query(func.count(Ballot.id)).scalar() == 1


def test_ballot_and_voted_flag_never_disagree(session):
    e, pres, sec, cands, voters = build(session)
    for v in voters[:3]:
        voting.cast_ballot(session, e, v,
                           [{"position_id": pres.id, "candidate_id": cands[1].id}])
    session.expire_all()
    voted = session.query(func.count(Voter.id)).filter(Voter.has_voted.is_(True)).scalar()
    ballots = session.query(func.count(Ballot.id)).scalar()
    assert voted == ballots == 3


# ------------------------------------------------------------ validation

def test_rejects_candidate_from_another_position(session):
    e, pres, sec, cands, voters = build(session)
    with pytest.raises(voting.VotingError) as ex:
        voting.cast_ballot(session, e, voters[0],
                           [{"position_id": pres.id, "candidate_id": cands[3].id}])
    assert ex.value.code == "candidate_position_mismatch"


def test_rejects_inactive_candidate(session):
    e, pres, sec, cands, voters = build(session)
    cands[0].is_active = False
    session.commit()
    with pytest.raises(voting.VotingError) as ex:
        voting.cast_ballot(session, e, voters[0],
                           [{"position_id": pres.id, "candidate_id": cands[0].id}])
    assert ex.value.code == "bad_candidate"


def test_rejects_too_many_selections_for_one_position(session):
    e, pres, sec, cands, voters = build(session)
    with pytest.raises(voting.VotingError) as ex:
        voting.cast_ballot(session, e, voters[0], [
            {"position_id": pres.id, "candidate_id": cands[0].id},
            {"position_id": pres.id, "candidate_id": cands[1].id},
        ])
    assert ex.value.code == "too_many_selections"


@pytest.mark.parametrize("payload", [
    "not-a-list", [{"position_id": "x", "candidate_id": 1}], [["a", "b"]],
    [{"position_id": 999999, "candidate_id": 1}], [{}],
])
def test_malformed_ballots_are_refused(session, payload):
    e, pres, sec, cands, voters = build(session)
    with pytest.raises(voting.VotingError):
        voting.cast_ballot(session, e, voters[0], payload)
    assert session.query(func.count(Ballot.id)).scalar() == 0


@pytest.mark.parametrize("state", [
    ElectionState.DRAFT, ElectionState.SCHEDULED, ElectionState.PAUSED,
    ElectionState.CLOSED, ElectionState.COUNTING, ElectionState.CERTIFIED,
    ElectionState.ARCHIVED,
])
def test_voting_refused_unless_election_open(session, state):
    e, pres, sec, cands, voters = build(session, state=state)
    with pytest.raises(voting.VotingError) as ex:
        voting.cast_ballot(session, e, voters[0],
                           [{"position_id": pres.id, "candidate_id": cands[0].id}])
    assert ex.value.code == "election_not_open"
    assert session.query(func.count(Ballot.id)).scalar() == 0


def test_ineligible_voter_refused(session):
    e, pres, sec, cands, voters = build(session)
    voters[0].is_eligible = False
    session.commit()
    with pytest.raises(voting.VotingError) as ex:
        voting.cast_ballot(session, e, voters[0],
                           [{"position_id": pres.id, "candidate_id": cands[0].id}])
    assert ex.value.code == "not_eligible"


# --------------------------------------------------------------- results

def test_results_include_every_contestant_even_on_zero(session):
    e, pres, sec, cands, voters = build(session)
    voting.cast_ballot(session, e, voters[0],
                       [{"position_id": pres.id, "candidate_id": cands[0].id}])
    out = voting.results(session, e)
    pres_block = next(p for p in out["positions"] if p["slug"] == "president")
    assert len(pres_block["candidates"]) == 3
    assert {c["votes"] for c in pres_block["candidates"]} == {1, 0}
    assert pres_block["leader"] == "Amina Otieno"
    assert out["totals"]["ballots"] == 1


def test_percentages_and_lead(session):
    e, pres, sec, cands, voters = build(session, n_voters=4)
    for v, c in zip(voters, [cands[0], cands[0], cands[0], cands[1]]):
        voting.cast_ballot(session, e, v,
                           [{"position_id": pres.id, "candidate_id": c.id}])
    p = next(x for x in voting.results(session, e)["positions"] if x["slug"] == "president")
    assert p["candidates"][0]["votes"] == 3
    assert p["candidates"][0]["percentage"] == 75.0
    assert p["lead"] == 2
    assert p["tied"] is False


def test_tie_is_reported_as_a_tie(session):
    e, pres, sec, cands, voters = build(session, n_voters=2)
    for v, c in zip(voters, [cands[0], cands[1]]):
        voting.cast_ballot(session, e, v,
                           [{"position_id": pres.id, "candidate_id": c.id}])
    p = next(x for x in voting.results(session, e)["positions"] if x["slug"] == "president")
    assert p["tied"] is True
    assert p["leader"] is None
    assert sorted(p["tied_between"]) == ["Amina Otieno", "Brian Kiptoo"]


def test_empty_election_reports_zeroes_not_invented_numbers(session):
    e, pres, sec, cands, voters = build(session)
    out = voting.results(session, e)
    assert out["totals"]["ballots"] == 0
    assert out["totals"]["turnout_percent"] == 0.0
    assert all(c["votes"] == 0 for p in out["positions"] for c in p["candidates"])


# ---------------------------------------------------------- verification

def test_receipt_verifies_without_revealing_choice(session):
    e, pres, sec, cands, voters = build(session)
    r = voting.cast_ballot(session, e, voters[0],
                           [{"position_id": pres.id, "candidate_id": cands[2].id}])
    out = voting.verify_receipt(session, r["reference"])
    assert out["found"] and out["recorded"] and out["integrity_verified"]

    # No candidate name, no voter name, and no structured field naming a
    # candidate, position or ballot may appear anywhere in the response.
    blob = repr(out).lower()
    for name in ("cynthia", "wafula", "amina", "brian", voters[0].display_name.lower()):
        assert name not in blob, "receipt leaked %r" % name
    assert not {"candidate_id", "candidate", "position_id", "selections",
                "choices", "voter_id", "ballot_uuid"} & set(out)
    assert out["reveals"] == {"candidate_choice": False, "voter_identity": False,
                              "ballot_contents": False}


def test_forged_receipt_is_rejected(session):
    e, pres, sec, cands, voters = build(session)
    voting.cast_ballot(session, e, voters[0],
                       [{"position_id": pres.id, "candidate_id": cands[0].id}])
    for bogus in ("ALU-0000-0000", "", "'; DROP TABLE ballots;--", "ALU-XXXX-YYYY"):
        assert voting.verify_receipt(session, bogus)["found"] is False
    assert session.query(func.count(Ballot.id)).scalar() == 1


def test_receipt_lookup_is_case_insensitive_but_not_guessable(session):
    e, pres, sec, cands, voters = build(session)
    r = voting.cast_ballot(session, e, voters[0],
                           [{"position_id": pres.id, "candidate_id": cands[0].id}])
    assert voting.verify_receipt(session, r["reference"].lower())["found"] is True


# ------------------------------------------------------------ state machine

def make_admin(session, role):
    a = AdminUser(email="%s@alupe.ac.ke" % role.value.lower(),
                  password_hash="x", role=role)
    session.add(a)
    session.commit()
    return a


def test_illegal_transitions_are_refused(session):
    e, *_ = build(session, state=ElectionState.DRAFT)
    admin = make_admin(session, Role.SUPER_ADMIN)
    for bad in (ElectionState.OPEN, ElectionState.CERTIFIED, ElectionState.CLOSED):
        with pytest.raises(governance.StateError):
            governance.transition(session, e, bad, admin)
    assert session.get(Election, e.id).state == ElectionState.DRAFT


def test_legal_path_to_certification(session):
    e, *_ = build(session, state=ElectionState.DRAFT)
    admin = make_admin(session, Role.SUPER_ADMIN)
    for step in (ElectionState.SCHEDULED, ElectionState.OPEN, ElectionState.CLOSED,
                 ElectionState.COUNTING, ElectionState.CERTIFIED):
        governance.transition(session, e, step, admin)
    assert e.state == ElectionState.CERTIFIED and e.certified_at is not None


def test_election_admin_cannot_certify(session):
    e, *_ = build(session, state=ElectionState.COUNTING)
    admin = make_admin(session, Role.ELECTION_ADMIN)
    with pytest.raises(governance.AuthzError):
        governance.transition(session, e, ElectionState.CERTIFIED, admin)
    assert e.state == ElectionState.COUNTING


@pytest.mark.parametrize("role,allowed", [
    (Role.SUPER_ADMIN, True), (Role.ELECTION_ADMIN, True),
    (Role.RESULTS_OFFICER, False), (Role.AUDITOR, False),
    (Role.READ_ONLY_ADMIN, False),
])
def test_only_election_roles_may_transition(session, role, allowed):
    e, *_ = build(session, state=ElectionState.OPEN)
    admin = make_admin(session, role)
    if allowed:
        governance.transition(session, e, ElectionState.PAUSED, admin)
        assert e.state == ElectionState.PAUSED
    else:
        with pytest.raises(governance.AuthzError):
            governance.transition(session, e, ElectionState.PAUSED, admin)


def test_read_only_admin_has_no_write_permissions(session):
    admin = make_admin(session, Role.READ_ONLY_ADMIN)
    for perm in ("election.edit", "candidate.manage", "voter.manage",
                 "results.publish", "election.certify", "admin.manage"):
        assert governance.can(admin, perm) is False


def test_inactive_admin_loses_all_permissions(session):
    admin = make_admin(session, Role.SUPER_ADMIN)
    admin.is_active = False
    session.commit()
    assert governance.can(admin, "results.view") is False


# ----------------------------------------------------------------- ledger

def test_chain_detects_tampering(session):
    e, pres, sec, cands, voters = build(session)
    for v in voters[:3]:
        voting.cast_ballot(session, e, v,
                           [{"position_id": pres.id, "candidate_id": cands[0].id}])
    assert ledger.verify_chain(session)["ok"] is True

    session.execute(text(
        "UPDATE audit_events SET payload = '{\"tampered\": true}'::jsonb WHERE seq = 2"))
    session.commit()
    out = ledger.verify_chain(session)
    assert out["ok"] is False and out["broken_at"] == 2


def test_ledger_refuses_voter_or_ballot_data(session):
    e, *_ = build(session)
    for bad in ({"voter_id": 3}, {"candidate_id": 9}, {"selections": []},
                {"student_no": "ALU/1"}, {"password": "x"}):
        with pytest.raises(ledger.LedgerBackendError):
            ledger.record_event(session, "x", actor="t", election_id=e.id, payload=bad)


def test_status_does_not_claim_blockchain(session):
    st = ledger.status(session)
    assert st["blockchain_connected"] is False
    assert st["mode"] == "AUDIT_LEDGER_DEVELOPMENT_MODE"
    assert st["tamper_proof"] is False and st["tamper_evident"] is True


def test_state_changes_are_audited(session):
    e, *_ = build(session, state=ElectionState.DRAFT)
    admin = make_admin(session, Role.SUPER_ADMIN)
    governance.transition(session, e, ElectionState.SCHEDULED, admin)
    from app.models import AuditEvent
    ev = session.query(AuditEvent).filter(
        AuditEvent.event_type == "election_state_changed").one()
    assert ev.payload["from"] == "DRAFT" and ev.payload["to"] == "SCHEDULED"
    assert ev.actor == admin.email


# ------------------------------------------------------- reconciliation

def test_certification_readiness_reconciles(session):
    e, pres, sec, cands, voters = build(session)
    admin = make_admin(session, Role.SUPER_ADMIN)
    for v in voters[:3]:
        voting.cast_ballot(session, e, v,
                           [{"position_id": pres.id, "candidate_id": cands[0].id}])
    governance.transition(session, e, ElectionState.CLOSED, admin)
    governance.transition(session, e, ElectionState.COUNTING, admin)
    out = governance.certification_readiness(session, e)
    assert out["ready"] is True, out["checks"]


def test_readiness_fails_when_chain_broken(session):
    e, pres, sec, cands, voters = build(session)
    admin = make_admin(session, Role.SUPER_ADMIN)
    voting.cast_ballot(session, e, voters[0],
                       [{"position_id": pres.id, "candidate_id": cands[0].id}])
    governance.transition(session, e, ElectionState.CLOSED, admin)
    governance.transition(session, e, ElectionState.COUNTING, admin)
    session.execute(text("UPDATE audit_events SET actor = 'forged' WHERE seq = 1"))
    session.commit()
    out = governance.certification_readiness(session, e)
    assert out["ready"] is False
