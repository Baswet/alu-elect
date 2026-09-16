# ALU-ELECT Deployment

## Requirements
Python 3.11+, PostgreSQL 14+, a TLS-terminating reverse proxy.

## Install
```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r backend/requirements.txt
cp backend/.env.example backend/.env      # then fill it in
```

Generate secrets (never reuse across environments):
```bash
python3 -c "import secrets;print('SECRET_KEY='+secrets.token_urlsafe(48))"
python3 -c "import secrets;print('BALLOT_PEPPER='+secrets.token_urlsafe(48))"
```

**`BALLOT_PEPPER` is effectively permanent.** It peppers student-number
hashes and ballot commitments; changing it invalidates every existing
receipt and makes the voter roll unmatchable. Back it up with the database.

## Bootstrap
```bash
python manage.py init-db
python manage.py create-admin --email ro@alupe.ac.ke --role SUPER_ADMIN
python manage.py create-election --slug ge-2026 --name "Student Council 2026"
python manage.py add-position  --election ge-2026 --slug president --title President
python manage.py add-candidate --election ge-2026 --position president --name "..."
python manage.py import-voters --election ge-2026 --csv roll.csv
```
`import-voters` writes `voter-credentials.csv` (mode 600) containing one-time
passwords. Distribute securely, then delete it — only hashes are stored.

## Run
```bash
gunicorn -w 4 -b 127.0.0.1:8000 wsgi:application
```

Serve behind nginx with TLS. Required:
- forward `X-Forwarded-For` (rate limiting and security logs use the client IP)
- disable proxy buffering on `/api/election/results/stream` (SSE)
- set `CORS_ALLOWED_ORIGINS` to the exact frontend origin — never `*`

## Known limitation: rate limiting is per worker
The limiter keeps counters in process memory, so with `-w 4` a client gets
roughly four times the configured limit. Acceptable for a single-worker or
low-traffic deployment; for production, back it with Redis or enforce limits
at nginx. This is stated plainly rather than left to be discovered.

## Election-day checklist
1. `python manage.py status` — confirm state and ledger validity
2. `DRAFT → SCHEDULED → OPEN` via the admin API
3. Monitor `/api/admin/security` for failed logins and rate-limit events
4. `OPEN → CLOSED → COUNTING`
5. `GET /elections/<id>/readiness` — all four checks must pass
6. `COUNTING → CERTIFIED` (SUPER_ADMIN only)
7. `python manage.py verify-chain` and archive the output
