# ALU-ELECT — Security & Privacy Model

Status of this document: describes what is **implemented and tested** in the
backend as of 13 Sep 2026. Anything not yet built is listed under
[Not yet implemented](#not-yet-implemented) rather than being described as if
it existed.

We do not claim this system is "unhackable", "100% secure" or "fraud-proof".
It is designed to be **multi-layered, tamper-evident, cryptographically
verifiable, auditable and privacy-preserving**, and to fail closed.

---

## 1. The secret ballot

This is the property everything else is arranged around: **the system must be
unable to answer the question "who did student X vote for?"** — not merely
decline to answer it.

The schema is split into three layers with no join between them:

| Layer | Table(s) | Knows | Never knows |
|---|---|---|---|
| Eligibility | `voters` | who may vote; **that** they voted | what they chose |
| Ballot | `ballots`, `ballot_selections` | what was chosen | who chose it |
| Results | `results` | totals per candidate | anything per voter |

`ballots` has **no `voter_id` and no foreign key to `voters`**. Nor do
`ballot_selections` or `receipts`. This is asserted by a test that reads the
live schema through SQLAlchemy's inspector, so the guarantee cannot be quietly
removed by a later migration:

```
test_no_column_links_a_voter_to_a_candidate
```

### Correlation attacks we defend against

Removing the foreign key is not sufficient on its own.

- **Timing correlation.** If `ballots.created_at` were precise and
  `voters.voted_at` were precise, ordering one against the other would unmask
  voters in a low-turnout election. Ballots therefore store `cast_hour`,
  truncated to the hour. Tested by `test_ballot_timestamp_is_coarsened`.
- **Insertion-order correlation.** Ballot ids are sequential, so a very
  low-turnout election still leaks ordering. This is a **known residual risk** —
  see below.
- **Receipt correlation.** `receipts` stores a peppered commitment over the
  ballot uuid, not the uuid itself, so possession of the receipts table does
  not identify which ballot belongs to which receipt.

### Known residual risks (not solved)

- **Very small electorates.** With 3 voters and 3 ballots in one hour, ballot
  ordering plus the audit log narrows things considerably. No software fix;
  mitigate operationally by not certifying tiny contests separately.
- **Database superuser.** Anyone with `postgres` rights can read every table
  and rewrite the audit chain from entry 1. The ledger is tamper-*evident*
  against application-level tampering, not against a hostile DBA. A real
  permissioned ledger with external validators is what closes this, and it is
  not connected — see §5.

---

## 2. One vote per voter

Enforced by the database, not by the application's own bookkeeping:

```sql
UPDATE voters SET has_voted = true WHERE id = :id AND has_voted = false
```

Only the transaction whose UPDATE actually affects a row proceeds to insert a
ballot. A replay, a double-click, or two genuinely simultaneous requests all
lose the race and receive `already_voted`.

Verified under real concurrency by
`test_concurrent_double_submission_records_one_ballot`, which starts two
threads on separate connections, synchronises them on a barrier, and asserts
exactly one ballot exists afterwards.

`test_ballot_and_voted_flag_never_disagree` asserts the two counts stay equal.

---

## 3. Server-side validation

The browser is authoritative for nothing. Every ballot is re-validated:

| Rejected | Code | Test |
|---|---|---|
| Election not `OPEN` (incl. `PAUSED`, `CLOSED`, `CERTIFIED`) | `election_not_open` | ✅ 7 states |
| Ineligible or suspended voter | `not_eligible` | ✅ |
| Voter belongs to another election | `wrong_election` | ✅ |
| Unknown position | `bad_position` | ✅ |
| Unknown / withdrawn candidate | `bad_candidate` | ✅ |
| Candidate standing for a different position | `candidate_position_mismatch` | ✅ |
| More selections than the position allows | `too_many_selections` | ✅ |
| Duplicate candidate on one ballot | `duplicate` | ✅ |
| Malformed JSON, wrong types, oversized payload | `malformed` | ✅ |

Vote **totals are never accepted from a client**. `results()` recomputes every
figure from `ballot_selections` on each call.

---

## 4. Authorization

Five roles with explicit permission sets, enforced server-side in
`governance.require()`. Hiding a button is not a control.

| Permission | SUPER | ELECTION | RESULTS | AUDITOR | READ-ONLY |
|---|---|---|---|---|---|
| `election.transition` | ✅ | ✅ | — | — | — |
| `election.certify` | ✅ | — | — | — | — |
| `candidate.manage` | ✅ | ✅ | — | — | — |
| `voter.manage` | ✅ | ✅ | — | — | — |
| `results.publish` | ✅ | — | ✅ | — | — |
| `audit.view` | ✅ | ✅ | ✅ | ✅ | — |
| `results.view` | ✅ | ✅ | ✅ | ✅ | ✅ |

Certification is deliberately SUPER_ADMIN-only: it is the single irreversible
act that converts provisional numbers into the official result. An
ELECTION_ADMIN attempting it is refused
(`test_election_admin_cannot_certify`). A deactivated admin loses every
permission immediately, including read.

---

## 5. Audit ledger — honest status

**Mode: `AUDIT_LEDGER_DEVELOPMENT_MODE`. No blockchain is connected.**

What exists is a hash-chained append-only table:

```
entry_hash = sha256(seq ‖ prev_hash ‖ event_type ‖ actor ‖ payload ‖ ts)
```

Altering any earlier row invalidates every subsequent hash;
`verify_chain()` reports the exact `seq` where the chain breaks
(`test_chain_detects_tampering`).

This is **tamper-evident, not tamper-proof, and not a blockchain** — there is
no distributed consensus and no independent validator. `ledger.status()`
reports `blockchain_connected: false` and `tamper_proof: false`, and the UI
must not claim otherwise.

`LedgerBackend` is the interface a real Hyperledger Fabric / Besu deployment
would implement. Voting logic calls only `record_event()`, `verify_chain()`
and `status()`, so connecting a network requires no change to the ballot path.

**The ledger refuses sensitive data structurally.** `FORBIDDEN_KEYS` raises
rather than writing any payload containing voter identity, candidate choice,
selections, ballot uuid, password, email or student number
(`test_ledger_refuses_voter_or_ballot_data`). Only commitments and election
events cross to it.

---

## 6. Certification reconciliation

Before certifying, `certification_readiness()` checks:

1. election is in `COUNTING`
2. ballot count equals the number of voters marked as having voted
3. every ballot has a receipt
4. the audit chain verifies

A broken chain fails readiness (`test_readiness_fails_when_chain_broken`).

---

## 7. Receipts

A receipt (`ALU-7F8A-29D1`, 32-char unambiguous alphabet, `secrets`-generated)
proves a ballot was recorded. Verification returns recorded status, election,
timestamp and integrity — and **never** the choice, the voter, or the
contents. The response is asserted to contain no candidate name and no
identifying field (`test_receipt_verifies_without_revealing_choice`).

Forged, empty and SQL-injection-shaped references all return "not found"
without side effects (`test_forged_receipt_is_rejected`).

---

## 8. Results integrity

- Recomputed from ballots every time; the `results` table is a cache.
- **Every contestant is returned, including those on zero votes.**
- Ties are reported as ties, with `leader: null` and `tied_between` listing
  everyone level — never resolved by sort order
  (`test_tie_is_reported_as_a_tie`).
- An election with no ballots reports zeroes, not invented figures
  (`test_empty_election_reports_zeroes_not_invented_numbers`).
- While voting is open, `provisional: true` is set on every response.

---

## Not yet implemented

Listed honestly; these are **not** in place:

- HTTP layer: Flask routes, sessions/tokens, CSRF, rate limiting, security
  headers, CORS policy. The service layer above is complete and tested; the
  API surface that exposes it is not yet written.
- Voter and admin authentication (password hashing, lockout, MFA/WebAuthn).
  Columns exist; the flows do not.
- Live updates (SSE/WebSocket).
- Alembic migrations (schema is currently created via `create_all`).
- Penetration testing of the HTTP surface: XSS, CSRF, IDOR at route level,
  rate-limit bypass, brute force, session manipulation, CORS. These cannot be
  meaningfully tested until the routes exist.
- Frontend integration: the existing UI is demo-data only.
