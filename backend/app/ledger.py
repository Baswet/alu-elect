"""
Audit ledger.

WHAT THIS IS
------------
A tamper-evident, hash-chained append-only log held in PostgreSQL:

    entry_hash = sha256(seq || prev_hash || event_type || actor || payload || ts)

Each entry commits to the one before it, so altering or deleting any earlier
row invalidates every hash after it and verify_chain() reports the exact
sequence number where the chain breaks.

WHAT THIS IS NOT
----------------
This is NOT a blockchain, and the system must never say that it is while
running on this backend alone. There is no distributed consensus, no
independent validators, and an administrator with database superuser rights
could in principle rewrite the whole chain from seq 1. Tamper-EVIDENT is an
honest claim; tamper-PROOF is not.

`status()` reports mode "AUDIT_LEDGER_DEVELOPMENT_MODE" unless a real
permissioned network is wired in through LedgerBackend below.

CONNECTING A REAL NETWORK
-------------------------
Implement LedgerBackend against Hyperledger Fabric / Besu and register it
with set_backend(). Voting logic calls only record_event() / verify_chain()
/ status(), so nothing in the ballot path changes when a network is added.
Only the commitment hashes and election events cross to the ledger - never
ballots, voter identity, or personal data.
"""

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import func

from app.models import AuditEvent

GENESIS = "0" * 64

# Keys that must never reach the ledger. Enforced, not merely documented:
# an attempt to record one raises rather than silently leaking.
FORBIDDEN_KEYS = {
    "student_no", "student_number", "student_no_hash", "voter_id", "voter",
    "candidate_id", "candidate", "selections", "ballot_uuid", "choices",
    "password", "email", "phone", "national_id", "receipt_reference",
}


class LedgerBackendError(RuntimeError):
    pass


class LedgerBackend:
    """Interface a real permissioned ledger must satisfy."""

    name = "abstract"
    is_live = False

    def submit(self, entry: dict) -> str:
        raise NotImplementedError

    def verify(self, entry_hash: str) -> bool:
        raise NotImplementedError


_backend: LedgerBackend | None = None


def set_backend(backend: LedgerBackend | None) -> None:
    global _backend
    _backend = backend


def _canonical(payload: dict) -> str:
    """Stable JSON so the same payload always hashes identically."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _assert_clean(payload: dict) -> None:
    leaked = FORBIDDEN_KEYS.intersection({str(k).lower() for k in payload})
    if leaked:
        raise LedgerBackendError(
            "Refusing to write %s to the audit ledger: the ledger must never "
            "carry voter identity or ballot content." % sorted(leaked)
        )


def compute_hash(seq, prev_hash, event_type, actor, payload, created_at) -> str:
    blob = "|".join([
        str(seq), prev_hash, event_type, actor or "",
        _canonical(payload), created_at.isoformat(),
    ])
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def record_event(session, event_type: str, actor: str | None = None,
                 election_id: int | None = None, payload: dict | None = None) -> AuditEvent:
    """Append one entry. Caller commits."""
    payload = dict(payload or {})
    _assert_clean(payload)

    last = session.query(AuditEvent).order_by(AuditEvent.seq.desc()).first()
    seq = (last.seq + 1) if last else 1
    prev_hash = last.entry_hash if last else GENESIS
    created_at = datetime.now(timezone.utc)

    entry_hash = compute_hash(seq, prev_hash, event_type, actor, payload, created_at)

    event = AuditEvent(
        election_id=election_id, seq=seq, event_type=event_type, actor=actor,
        payload=payload, prev_hash=prev_hash, entry_hash=entry_hash,
        created_at=created_at,
    )
    session.add(event)

    if _backend is not None and _backend.is_live:
        try:
            _backend.submit({
                "seq": seq, "event_type": event_type,
                "entry_hash": entry_hash, "prev_hash": prev_hash,
            })
        except Exception as exc:  # never let the ledger break an election action
            session.add(AuditEvent(
                election_id=election_id, seq=seq + 1,
                event_type="ledger_submit_failed", actor="system",
                payload={"error": type(exc).__name__},
                prev_hash=entry_hash,
                entry_hash=compute_hash(seq + 1, entry_hash,
                                        "ledger_submit_failed", "system",
                                        {"error": type(exc).__name__}, created_at),
                created_at=created_at,
            ))
    return event


def verify_chain(session) -> dict:
    """Recompute every hash. Reports the first sequence that does not match."""
    events = session.query(AuditEvent).order_by(AuditEvent.seq.asc()).all()
    prev = GENESIS
    for e in events:
        expect = compute_hash(e.seq, e.prev_hash, e.event_type, e.actor,
                              e.payload or {}, e.created_at)
        if e.prev_hash != prev:
            return {"ok": False, "entries": len(events), "broken_at": e.seq,
                    "reason": "prev_hash does not match the previous entry"}
        if e.entry_hash != expect:
            return {"ok": False, "entries": len(events), "broken_at": e.seq,
                    "reason": "entry_hash does not match its own contents"}
        prev = e.entry_hash
    return {"ok": True, "entries": len(events), "broken_at": None,
            "head": prev if events else GENESIS}


def status(session) -> dict:
    chain = verify_chain(session)
    live = bool(_backend is not None and _backend.is_live)
    return {
        "mode": "PERMISSIONED_LEDGER" if live else "AUDIT_LEDGER_DEVELOPMENT_MODE",
        "network": _backend.name if live else None,
        "blockchain_connected": live,
        "tamper_evident": True,
        "tamper_proof": False,
        "entries": chain["entries"],
        "chain_valid": chain["ok"],
        "broken_at": chain["broken_at"],
        "head_hash": chain.get("head"),
        "note": (
            "Local hash-chained audit log. Tamper-evident, not tamper-proof, "
            "and not a blockchain: no distributed consensus is in use."
            if not live else
            "Commitments mirrored to a permissioned ledger."
        ),
    }
