"""
Casting and counting. The only place a ballot is ever written.

Every rule below is enforced here, server-side. Nothing the browser sends is
trusted: not eligibility, not the election state, not the candidate list, and
certainly not any vote total.
"""

import hashlib
import os
import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app import ledger
from app.models import (
    Ballot, BallotSelection, Candidate, Election, ElectionState, Position,
    Receipt, ResultTally, VOTING_STATES, Voter, utcnow,
)


class VotingError(Exception):
    """Refusal with a reason safe to show a voter."""

    def __init__(self, message, code="rejected", status=400):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


def _pepper() -> bytes:
    p = os.environ.get("BALLOT_PEPPER")
    if not p:
        raise VotingError("Server is not configured for voting.",
                          code="misconfigured", status=500)
    return p.encode("utf-8")


def hash_student_no(student_no: str) -> str:
    """Peppered hash. The roll is never stored in the clear."""
    return hashlib.sha256(_pepper() + b"|sn|" + student_no.strip().upper().encode()).hexdigest()


def _commitment(ballot_uuid: uuid.UUID) -> str:
    return hashlib.sha256(_pepper() + b"|c|" + str(ballot_uuid).encode()).hexdigest()


def _reference() -> str:
    """Voter-facing receipt, e.g. ALU-7F8A-29D1. Unguessable."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no I/O/0/1
    part = lambda n: "".join(secrets.choice(alphabet) for _ in range(n))
    return "ALU-%s-%s" % (part(4), part(4))


def _content_hash(selections) -> str:
    blob = ";".join("%d:%d" % (p, c) for p, c in sorted(selections))
    return hashlib.sha256(blob.encode()).hexdigest()


# ---------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------

def validate_ballot(session, election: Election, raw_selections) -> list[tuple[int, int]]:
    """Return clean (position_id, candidate_id) pairs, or raise.

    Rejects: unknown positions, unknown or inactive candidates, candidates
    belonging to another position or another election, more selections than a
    position allows, and duplicate positions. An abstention (no selection for
    a position) is allowed - it is not the same as a spoiled ballot.
    """
    if not isinstance(raw_selections, list):
        raise VotingError("Malformed ballot.", code="malformed")
    if len(raw_selections) > 200:
        raise VotingError("Malformed ballot.", code="malformed")

    positions = {
        p.id: p for p in session.query(Position)
        .filter(Position.election_id == election.id).all()
    }
    if not positions:
        raise VotingError("This election has no positions.", code="no_positions")

    valid_candidates = {
        c.id: c for c in session.query(Candidate)
        .join(Position, Candidate.position_id == Position.id)
        .filter(Position.election_id == election.id,
                Candidate.is_active.is_(True)).all()
    }

    seen_positions = {}
    clean = []
    for item in raw_selections:
        if not isinstance(item, dict):
            raise VotingError("Malformed ballot.", code="malformed")
        try:
            pid = int(item.get("position_id"))
            cid = int(item.get("candidate_id"))
        except (TypeError, ValueError):
            raise VotingError("Malformed ballot.", code="malformed")

        pos = positions.get(pid)
        if pos is None:
            raise VotingError("Unknown position on the ballot.", code="bad_position")
        cand = valid_candidates.get(cid)
        if cand is None:
            raise VotingError("Unknown or withdrawn candidate on the ballot.",
                              code="bad_candidate")
        if cand.position_id != pid:
            raise VotingError("That candidate is not standing for that position.",
                              code="candidate_position_mismatch")

        seen_positions[pid] = seen_positions.get(pid, 0) + 1
        if seen_positions[pid] > pos.max_selections:
            raise VotingError("Too many selections for %s." % pos.title,
                              code="too_many_selections")
        if (pid, cid) in clean:
            raise VotingError("The same candidate appears twice.", code="duplicate")
        clean.append((pid, cid))

    return clean


# ---------------------------------------------------------------------
# Casting
# ---------------------------------------------------------------------

def cast_ballot(session, election: Election, voter: Voter, raw_selections) -> dict:
    """Record one ballot. Atomic, and refuses a second ballot from one voter.

    The database, not this function, is the final arbiter of one-vote-only:
    has_voted is flipped with a conditional UPDATE, and only the transaction
    that actually changes the row is allowed to continue. Two simultaneous
    submissions therefore cannot both succeed, however they interleave.
    """
    if election.state not in VOTING_STATES:
        raise VotingError("Voting is not open for this election.",
                          code="election_not_open", status=409)
    if not voter.is_eligible:
        raise VotingError("This voter is not eligible in this election.",
                          code="not_eligible", status=403)
    if voter.election_id != election.id:
        raise VotingError("This voter is not registered for this election.",
                          code="wrong_election", status=403)

    selections = validate_ballot(session, election, raw_selections)
    if not selections:
        raise VotingError("A ballot must contain at least one selection.",
                          code="empty_ballot")

    # Claim the right to vote. UPDATE ... WHERE has_voted = false returns 0
    # rows for a replay, so a duplicate can never reach the ballot insert.
    claimed = session.query(Voter).filter(
        Voter.id == voter.id, Voter.has_voted.is_(False)
    ).update({"has_voted": True, "voted_at": utcnow()},
             synchronize_session=False)
    if not claimed:
        raise VotingError("A ballot has already been recorded for this voter.",
                          code="already_voted", status=409)

    # Coarsen the timestamp so ballot order cannot be lined up against
    # voters.voted_at to work out who cast which ballot.
    now = datetime.now(timezone.utc)
    cast_hour = now.replace(minute=0, second=0, microsecond=0)

    ballot_uuid = uuid.uuid4()
    ballot = Ballot(
        ballot_uuid=ballot_uuid, election_id=election.id,
        cast_hour=cast_hour, content_hash=_content_hash(selections),
    )
    session.add(ballot)
    session.flush()

    for pid, cid in selections:
        session.add(BallotSelection(ballot_id=ballot.id, position_id=pid,
                                    candidate_id=cid))

    for _ in range(5):
        reference = _reference()
        if not session.query(Receipt.id).filter(Receipt.reference == reference).first():
            break
    else:
        raise VotingError("Could not issue a receipt. Nothing was recorded.",
                          code="receipt_failed", status=500)

    session.add(Receipt(reference=reference, election_id=election.id,
                        ballot_commitment=_commitment(ballot_uuid)))

    # The ledger records THAT a ballot was recorded, never its content.
    ledger.record_event(
        session, "ballot_recorded", actor="voter", election_id=election.id,
        payload={"content_commitment": ballot.content_hash[:16],
                 "cast_hour": cast_hour.isoformat()},
    )

    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise VotingError("The ballot could not be recorded. Please try again.",
                          code="conflict", status=409)

    return {"reference": reference, "recorded_at": cast_hour.isoformat()}


# ---------------------------------------------------------------------
# Counting - always recomputed from ballots
# ---------------------------------------------------------------------

def recount(session, election: Election) -> None:
    """Rebuild the results table from the ballots. The only way totals change."""
    counts = dict(
        session.query(BallotSelection.candidate_id, func.count(BallotSelection.id))
        .join(Ballot, BallotSelection.ballot_id == Ballot.id)
        .filter(Ballot.election_id == election.id)
        .group_by(BallotSelection.candidate_id).all()
    )
    candidates = (
        session.query(Candidate).join(Position, Candidate.position_id == Position.id)
        .filter(Position.election_id == election.id).all()
    )
    existing = {
        r.candidate_id: r for r in session.query(ResultTally)
        .filter(ResultTally.election_id == election.id).all()
    }
    for c in candidates:
        votes = int(counts.get(c.id, 0))
        row = existing.get(c.id)
        if row is None:
            session.add(ResultTally(election_id=election.id, position_id=c.position_id,
                                    candidate_id=c.id, votes=votes, updated_at=utcnow()))
        else:
            row.votes = votes
            row.updated_at = utcnow()
    session.commit()


def results(session, election: Election) -> dict:
    """Every position, every contestant - including those on zero votes."""
    recount(session, election)

    positions = (session.query(Position)
                 .filter(Position.election_id == election.id)
                 .order_by(Position.display_order, Position.id).all())
    tallies = {
        r.candidate_id: r.votes for r in session.query(ResultTally)
        .filter(ResultTally.election_id == election.id).all()
    }

    total_ballots = session.query(func.count(Ballot.id)).filter(
        Ballot.election_id == election.id).scalar() or 0
    eligible = session.query(func.count(Voter.id)).filter(
        Voter.election_id == election.id, Voter.is_eligible.is_(True)).scalar() or 0
    voted = session.query(func.count(Voter.id)).filter(
        Voter.election_id == election.id, Voter.has_voted.is_(True)).scalar() or 0

    out_positions = []
    for pos in positions:
        cands = [c for c in pos.candidates if c.is_active]
        rows = [{
            "candidate_id": c.id, "name": c.full_name, "photo": c.photo_path,
            "symbol": c.symbol, "school": c.school, "programme": c.programme,
            "year": c.year_of_study, "votes": int(tallies.get(c.id, 0)),
        } for c in cands]
        cast_here = sum(r["votes"] for r in rows)
        rows.sort(key=lambda r: (-r["votes"], r["name"].lower()))

        for i, r in enumerate(rows):
            r["percentage"] = round(r["votes"] * 100.0 / cast_here, 1) if cast_here else 0.0
            r["rank"] = i + 1
        # A tie at the top is a tie, and is reported as one rather than
        # picking whichever name sorted first.
        top = rows[0]["votes"] if rows else 0
        leaders = [r for r in rows if r["votes"] == top and top > 0]
        runner_up = next((r["votes"] for r in rows if r["votes"] < top), 0)

        out_positions.append({
            "position_id": pos.id, "slug": pos.slug, "title": pos.title,
            "max_selections": pos.max_selections,
            "votes_cast": cast_here,
            "candidates": rows,
            "leader": (leaders[0]["name"] if len(leaders) == 1 else None),
            "tied": len(leaders) > 1,
            "tied_between": [r["name"] for r in leaders] if len(leaders) > 1 else [],
            "lead": (top - runner_up) if len(leaders) == 1 else 0,
        })

    return {
        "election": {"slug": election.slug, "name": election.name,
                     "state": election.state.value,
                     "provisional": election.state != ElectionState.CERTIFIED,
                     "certified_at": election.certified_at.isoformat()
                                     if election.certified_at else None},
        "totals": {
            "ballots": total_ballots, "eligible_voters": eligible, "voted": voted,
            "turnout_percent": round(voted * 100.0 / eligible, 1) if eligible else 0.0,
            "positions": len(positions),
            "candidates": sum(len(p["candidates"]) for p in out_positions),
        },
        "positions": out_positions,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------

# A reference is only ever letters, digits and hyphens. Anything else is not
# a near-miss, it is someone probing - so the input is normalised to that
# alphabet before it is allowed near the database. A NUL byte in particular
# makes PostgreSQL raise DataError, which turned an unauthenticated request
# into a 500; found by test_injection_payloads_are_inert[\x00null].
_REF_ALLOWED = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-")
_REF_MAX = 32


def _clean_reference(raw) -> str:
    if not isinstance(raw, str):
        return ""
    return "".join(ch for ch in raw.strip().upper()
                   if ch in _REF_ALLOWED)[:_REF_MAX]


def verify_receipt(session, reference: str) -> dict:
    """Confirm a ballot was recorded. Never reveals what was on it."""
    ref = _clean_reference(reference)
    if not ref:
        return {"found": False,
                "message": "No ballot has been recorded against that reference."}
    receipt = session.query(Receipt).filter(Receipt.reference == ref).first()
    if not receipt:
        return {"found": False,
                "message": "No ballot has been recorded against that reference."}

    election = session.get(Election, receipt.election_id)
    chain = ledger.verify_chain(session)
    return {
        "found": True,
        "recorded": True,
        "reference": receipt.reference,
        "election": election.name if election else None,
        "recorded_at": receipt.issued_at.isoformat(),
        "integrity_verified": chain["ok"],
        "commitment": receipt.ballot_commitment[:16] + "...",
        "reveals": {
            "candidate_choice": False,
            "voter_identity": False,
            "ballot_contents": False,
        },
        "message": "This ballot was recorded and is included in the election record.",
    }
