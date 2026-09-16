# ALU-ELECT API

All responses are JSON. All state-changing requests require `X-CSRF-Token`
(or `csrf_token` in the body), except `/login` and `/election/verify`, which
change no state and are rate-limited instead.

Obtain a token from `GET /api/csrf`, or from any successful login response.

## Public

| Method | Path | Notes |
|---|---|---|
| GET | `/api/health` | `200` ok / `503` database down |
| GET | `/api/csrf` | issues a CSRF token |
| GET | `/api/election` | current election summary + turnout |
| GET | `/api/election/results` | full results; `403` unpublished, `423` frozen |
| GET | `/api/election/results/stream` | Server-Sent Events, `event: results` |
| POST | `/api/election/verify` | `{reference}` → recorded status only |
| GET | `/api/ledger/status` | ledger mode and chain validity |

## Voter

| Method | Path | Notes |
|---|---|---|
| POST | `/api/election/login` | `{student_no, password, election}` |
| POST | `/api/election/logout` | |
| GET | `/api/election/me` | masked id, school, eligibility, has_voted |
| GET | `/api/election/positions` | ballot: positions + active candidates |
| POST | `/api/election/ballot` | `{selections:[{position_id,candidate_id}]}` → `201 {reference}` |

Ballot error codes: `election_not_open` (409), `already_voted` (409),
`not_eligible` (403), `bad_position`, `bad_candidate`,
`candidate_position_mismatch`, `too_many_selections`, `duplicate`,
`malformed` (400).

## Admin — `/api/admin/*`

| Method | Path | Permission |
|---|---|---|
| POST | `/login`, `/logout` | — |
| GET | `/me` | authenticated |
| GET | `/elections` | `results.view` |
| POST | `/elections` | `election.create` |
| POST | `/elections/action` | `election.transition` (+`election.certify` for CERTIFIED) |
| GET | `/elections/<id>/readiness` | `results.view` |
| POST | `/elections/<id>/results-visibility` | `results.publish` |
| POST | `/elections/<id>/positions` | `candidate.manage` |
| POST | `/positions/<id>/candidates` | `candidate.manage` |
| PATCH | `/candidates/<id>` | `candidate.manage` (deactivate, never delete) |
| POST | `/elections/<id>/voters/import` | `voter.manage` |
| GET | `/elections/<id>/voters` | `voter.manage` (never shows choices) |
| PATCH | `/voters/<id>` | `voter.manage` |
| GET | `/elections/<id>/results` | `results.view` |
| GET | `/audit` | `audit.view` |
| GET | `/ledger` | `audit.view` |
| GET | `/security` | `security.view` |

## Rate limits (per IP)

`login` 10/5min · `ballot` 5/5min · `verify` 30/5min · default 240/min.
Exceeding any returns `429`.
