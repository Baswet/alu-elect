"""
Who may do what, and which state changes are legal.

Both are enforced here, server-side. Hiding a button in the admin UI is a
courtesy to the operator; this module is the actual control.
"""

from datetime import datetime, timezone

from app import ledger
from app.models import (ALLOWED_TRANSITIONS, AdminUser, Election, ElectionState,
                        Role, SecurityEvent)


class AuthzError(Exception):
    def __init__(self, message, status=403):
        super().__init__(message)
        self.message = message
        self.status = status


class StateError(Exception):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.message = message
        self.status = status


# Explicit permissions per role. A role holds exactly what is listed and
# nothing more; there is no implicit inheritance to reason about.
PERMISSIONS: dict[Role, set[str]] = {
    Role.SUPER_ADMIN: {
        "election.create", "election.edit", "election.transition",
        "election.certify", "candidate.manage", "voter.manage",
        "results.view", "results.publish", "audit.view", "security.view",
        "admin.manage",
    },
    Role.ELECTION_ADMIN: {
        "election.edit", "election.transition", "candidate.manage",
        "voter.manage", "results.view", "audit.view",
    },
    Role.RESULTS_OFFICER: {
        "results.view", "results.publish", "audit.view",
    },
    Role.AUDITOR: {
        "results.view", "audit.view", "security.view",
    },
    Role.READ_ONLY_ADMIN: {
        "results.view",
    },
}

# Certification is deliberately SUPER_ADMIN only: it is the one irreversible
# act that turns provisional numbers into the official result.


def can(admin: AdminUser | None, permission: str) -> bool:
    if admin is None or not admin.is_active:
        return False
    return permission in PERMISSIONS.get(admin.role, set())


def require(admin: AdminUser | None, permission: str) -> None:
    if not can(admin, permission):
        raise AuthzError("Your role does not permit this action.")


def transition(session, election: Election, target: ElectionState,
               admin: AdminUser, reason: str | None = None) -> Election:
    """Move an election between states, or refuse."""
    require(admin, "election.transition")

    if isinstance(target, str):
        try:
            target = ElectionState(target)
        except ValueError:
            raise StateError("Unknown election state.", status=400)

    if target == ElectionState.CERTIFIED:
        require(admin, "election.certify")

    allowed = ALLOWED_TRANSITIONS.get(election.state, set())
    if target not in allowed:
        raise StateError(
            "An election cannot move from %s to %s. Allowed from here: %s."
            % (election.state.value, target.value,
               ", ".join(sorted(s.value for s in allowed)) or "nothing")
        )

    previous = election.state
    election.state = target
    if target == ElectionState.CERTIFIED:
        election.certified_at = datetime.now(timezone.utc)
        election.certified_by = admin.id

    ledger.record_event(
        session, "election_state_changed", actor=admin.email,
        election_id=election.id,
        payload={"from": previous.value, "to": target.value,
                 "reason": (reason or "")[:200]},
    )
    session.commit()
    return election


def certification_readiness(session, election: Election) -> dict:
    """Checks an officer should see before certifying. Advisory, not a gate."""
    from sqlalchemy import func
    from app.models import Ballot, Receipt, Voter

    ballots = session.query(func.count(Ballot.id)).filter(
        Ballot.election_id == election.id).scalar() or 0
    receipts = session.query(func.count(Receipt.id)).filter(
        Receipt.election_id == election.id).scalar() or 0
    voted = session.query(func.count(Voter.id)).filter(
        Voter.election_id == election.id, Voter.has_voted.is_(True)).scalar() or 0
    chain = ledger.verify_chain(session)

    checks = [
        {"check": "Election is closed and counted",
         "ok": election.state == ElectionState.COUNTING,
         "detail": "State is %s" % election.state.value},
        {"check": "Ballots reconcile with voters marked as voted",
         "ok": ballots == voted,
         "detail": "%d ballots, %d voters recorded as having voted" % (ballots, voted)},
        {"check": "Every ballot has a receipt",
         "ok": receipts == ballots,
         "detail": "%d receipts, %d ballots" % (receipts, ballots)},
        {"check": "Audit chain intact",
         "ok": chain["ok"],
         "detail": "%d entries" % chain["entries"] if chain["ok"]
                   else "chain breaks at entry %s" % chain["broken_at"]},
    ]
    return {"ready": all(c["ok"] for c in checks), "checks": checks}


def log_security(session, kind: str, detail: str = "", ip: str = "",
                 actor: str = "") -> None:
    session.add(SecurityEvent(kind=kind, detail=detail[:400], ip=ip[:64],
                              actor=actor[:160]))
    session.commit()
