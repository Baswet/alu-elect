"""
ALU-ELECT data model.

THE CENTRAL CONSTRAINT
----------------------
There is deliberately NO column, anywhere, joining a voter to a candidate.

The schema is split into three layers that cannot be joined back together:

  1. Eligibility layer  (voters)  - who may vote, and whether they have.
  2. Ballot layer       (ballots, ballot_selections) - anonymous ballots and
     the choices on them, keyed by a random ballot uuid.
  3. Results layer      (results) - per-candidate totals.

`voters.has_voted` records THAT a voter voted. `ballots` records WHAT was
voted. Nothing links the two: a ballot carries no voter id, no foreign key
to voters, and is inserted in the same transaction that flips has_voted so
neither ordering nor timing can be used to correlate them beyond the
coarse timestamp, which is deliberately truncated (see voting.py).

A receipt lets a voter confirm their own ballot was recorded. The receipt
hash is derived from the ballot uuid and a server-side pepper, so holding a
receipt proves recording without revealing content, and the receipts table
likewise carries no voter id.

Anyone tempted to "just add voter_id to ballots for debugging" should read
SECURITY.md first: that single column would destroy the secret ballot.
"""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, CheckConstraint, Column, DateTime, Enum, ForeignKey, Index,
    Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, relationship


def utcnow():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------
# Election state machine
# ---------------------------------------------------------------------

class ElectionState(str, enum.Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    PAUSED = "PAUSED"
    CLOSED = "CLOSED"
    COUNTING = "COUNTING"
    CERTIFIED = "CERTIFIED"
    ARCHIVED = "ARCHIVED"


# The only transitions the server will ever perform. Anything not listed
# here is rejected, whatever the request says.
ALLOWED_TRANSITIONS = {
    ElectionState.DRAFT:     {ElectionState.SCHEDULED, ElectionState.ARCHIVED},
    ElectionState.SCHEDULED: {ElectionState.OPEN, ElectionState.DRAFT, ElectionState.ARCHIVED},
    ElectionState.OPEN:      {ElectionState.PAUSED, ElectionState.CLOSED},
    ElectionState.PAUSED:    {ElectionState.OPEN, ElectionState.CLOSED},
    ElectionState.CLOSED:    {ElectionState.COUNTING},
    ElectionState.COUNTING:  {ElectionState.CERTIFIED, ElectionState.CLOSED},
    ElectionState.CERTIFIED: {ElectionState.ARCHIVED},
    ElectionState.ARCHIVED:  set(),
}

# Ballots are only ever accepted in this state. Not PAUSED, not CLOSED.
VOTING_STATES = {ElectionState.OPEN}


class Role(str, enum.Enum):
    SUPER_ADMIN = "SUPER_ADMIN"
    ELECTION_ADMIN = "ELECTION_ADMIN"
    RESULTS_OFFICER = "RESULTS_OFFICER"
    AUDITOR = "AUDITOR"
    READ_ONLY_ADMIN = "READ_ONLY_ADMIN"


# ---------------------------------------------------------------------
# Election / positions / candidates
# ---------------------------------------------------------------------

class Election(Base):
    __tablename__ = "elections"

    id = Column(Integer, primary_key=True)
    slug = Column(String(64), nullable=False, unique=True)
    name = Column(String(200), nullable=False)
    description = Column(Text)
    state = Column(Enum(ElectionState, name="election_state"),
                   nullable=False, default=ElectionState.DRAFT)
    opens_at = Column(DateTime(timezone=True))
    closes_at = Column(DateTime(timezone=True))
    results_public = Column(Boolean, nullable=False, default=True)
    results_frozen = Column(Boolean, nullable=False, default=False)
    certified_at = Column(DateTime(timezone=True))
    certified_by = Column(Integer, ForeignKey("admin_users.id"))
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    positions = relationship("Position", back_populates="election",
                             cascade="all, delete-orphan")


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (
        UniqueConstraint("election_id", "slug", name="uq_position_slug"),
        CheckConstraint("max_selections >= 1", name="ck_position_max_selections"),
    )

    id = Column(Integer, primary_key=True)
    election_id = Column(Integer, ForeignKey("elections.id", ondelete="CASCADE"),
                         nullable=False)
    slug = Column(String(64), nullable=False)
    title = Column(String(120), nullable=False)
    description = Column(Text)
    display_order = Column(Integer, nullable=False, default=0)
    # Almost always 1. Kept explicit so a multi-seat position cannot be
    # smuggled in by a client sending several selections.
    max_selections = Column(Integer, nullable=False, default=1)

    election = relationship("Election", back_populates="positions")
    candidates = relationship("Candidate", back_populates="position",
                              cascade="all, delete-orphan")


class Candidate(Base):
    __tablename__ = "candidates"

    id = Column(Integer, primary_key=True)
    position_id = Column(Integer, ForeignKey("positions.id", ondelete="CASCADE"),
                         nullable=False)
    full_name = Column(String(160), nullable=False)
    photo_path = Column(String(300))
    symbol = Column(String(80))
    school = Column(String(120))
    programme = Column(String(160))
    year_of_study = Column(String(24))
    manifesto = Column(Text)
    is_active = Column(Boolean, nullable=False, default=True)
    display_order = Column(Integer, nullable=False, default=0)

    position = relationship("Position", back_populates="candidates")


# ---------------------------------------------------------------------
# Layer 1 - eligibility. Knows WHO. Never knows WHAT.
# ---------------------------------------------------------------------

class Voter(Base):
    __tablename__ = "voters"
    __table_args__ = (
        UniqueConstraint("election_id", "student_no_hash", name="uq_voter_election"),
    )

    id = Column(Integer, primary_key=True)
    election_id = Column(Integer, ForeignKey("elections.id", ondelete="CASCADE"),
                         nullable=False)
    # The student number is never stored in the clear: only a peppered hash,
    # so a database leak does not hand over the university's roll.
    student_no_hash = Column(String(64), nullable=False)
    display_name = Column(String(160))
    school = Column(String(120))
    is_eligible = Column(Boolean, nullable=False, default=True)
    suspended_reason = Column(String(200))

    # THAT they voted - never what. Flipped in the same transaction as the
    # ballot insert, so the two can never disagree.
    has_voted = Column(Boolean, nullable=False, default=False)
    voted_at = Column(DateTime(timezone=True))

    password_hash = Column(String(256))
    failed_logins = Column(Integer, nullable=False, default=0)
    locked_until = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


Index("ix_voters_election", Voter.election_id)


# ---------------------------------------------------------------------
# Layer 2 - ballots. Knows WHAT. Never knows WHO.
# ---------------------------------------------------------------------

class Ballot(Base):
    """One cast ballot. Deliberately has no voter_id and no FK to voters."""

    __tablename__ = "ballots"

    id = Column(Integer, primary_key=True)
    ballot_uuid = Column(UUID(as_uuid=True), nullable=False, unique=True,
                         default=uuid.uuid4)
    election_id = Column(Integer, ForeignKey("elections.id", ondelete="CASCADE"),
                         nullable=False)
    # Truncated to the hour on write (see voting.cast_ballot) so that the
    # ordering of ballots cannot be correlated with the ordering of
    # voters.voted_at to unmask a voter.
    cast_hour = Column(DateTime(timezone=True), nullable=False)
    # Hash over the ballot's own contents, for tamper evidence.
    content_hash = Column(String(64), nullable=False)

    selections = relationship("BallotSelection", back_populates="ballot",
                              cascade="all, delete-orphan")


Index("ix_ballots_election", Ballot.election_id)


class BallotSelection(Base):
    __tablename__ = "ballot_selections"
    __table_args__ = (
        UniqueConstraint("ballot_id", "position_id", "candidate_id",
                         name="uq_ballot_selection"),
    )

    id = Column(Integer, primary_key=True)
    ballot_id = Column(Integer, ForeignKey("ballots.id", ondelete="CASCADE"),
                       nullable=False)
    position_id = Column(Integer, ForeignKey("positions.id"), nullable=False)
    candidate_id = Column(Integer, ForeignKey("candidates.id"), nullable=False)

    ballot = relationship("Ballot", back_populates="selections")


Index("ix_selection_candidate", BallotSelection.candidate_id)


class Receipt(Base):
    """Lets a voter prove their ballot was recorded, revealing nothing else."""

    __tablename__ = "receipts"

    id = Column(Integer, primary_key=True)
    # What the voter is shown, e.g. ALU-7F8A-29D1. Unique per election.
    reference = Column(String(32), nullable=False, unique=True)
    election_id = Column(Integer, ForeignKey("elections.id", ondelete="CASCADE"),
                         nullable=False)
    # Binds the receipt to its ballot without storing the ballot uuid, so a
    # stolen receipts table still does not identify which ballot is whose.
    ballot_commitment = Column(String(64), nullable=False)
    issued_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


# ---------------------------------------------------------------------
# Layer 3 - results
# ---------------------------------------------------------------------

class ResultTally(Base):
    """Materialised counts. Always recomputed from ballots, never trusted."""

    __tablename__ = "results"
    __table_args__ = (
        UniqueConstraint("election_id", "candidate_id", name="uq_result_candidate"),
    )

    id = Column(Integer, primary_key=True)
    election_id = Column(Integer, ForeignKey("elections.id", ondelete="CASCADE"),
                         nullable=False)
    position_id = Column(Integer, ForeignKey("positions.id"), nullable=False)
    candidate_id = Column(Integer, ForeignKey("candidates.id"), nullable=False)
    votes = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


# ---------------------------------------------------------------------
# Admin, audit, security
# ---------------------------------------------------------------------

class AdminUser(Base):
    __tablename__ = "admin_users"

    id = Column(Integer, primary_key=True)
    email = Column(String(200), nullable=False, unique=True)
    full_name = Column(String(160))
    password_hash = Column(String(256), nullable=False)
    role = Column(Enum(Role, name="admin_role"), nullable=False,
                  default=Role.READ_ONLY_ADMIN)
    is_active = Column(Boolean, nullable=False, default=True)
    failed_logins = Column(Integer, nullable=False, default=0)
    locked_until = Column(DateTime(timezone=True))
    last_login_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class AuditEvent(Base):
    """Hash-chained audit log: prev_hash -> payload -> entry_hash.

    This is a tamper-EVIDENT local ledger, not a blockchain. Breaking any
    earlier row invalidates every hash after it, which verify_chain()
    detects. See ledger.py for the interface a real permissioned network
    would implement.
    """

    __tablename__ = "audit_events";

    id = Column(Integer, primary_key=True)
    election_id = Column(Integer, ForeignKey("elections.id", ondelete="SET NULL"))
    seq = Column(Integer, nullable=False)
    event_type = Column(String(64), nullable=False)
    actor = Column(String(160))
    # Never contains voter identity or ballot choices - enforced in ledger.py.
    payload = Column(JSONB, nullable=False, default=dict)
    prev_hash = Column(String(64), nullable=False)
    entry_hash = Column(String(64), nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


Index("ix_audit_seq", AuditEvent.seq)


class SecurityEvent(Base):
    __tablename__ = "security_events"

    id = Column(Integer, primary_key=True)
    kind = Column(String(64), nullable=False)
    detail = Column(String(400))
    ip = Column(String(64))
    actor = Column(String(160))
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
