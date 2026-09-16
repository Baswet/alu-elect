#!/usr/bin/env python3
"""
ALU-ELECT operational CLI.

  python manage.py init-db
  python manage.py create-admin --email x@alupe.ac.ke --role SUPER_ADMIN
  python manage.py create-election --slug ge-2026 --name "Student Council 2026"
  python manage.py add-position --election ge-2026 --slug president --title President
  python manage.py add-candidate --election ge-2026 --position president --name "..."
  python manage.py import-voters --election ge-2026 --csv roll.csv
  python manage.py verify-chain
  python manage.py status

Passwords are never taken on the command line (they would land in shell
history and the process table); they are prompted for, or generated.
"""

import argparse
import csv
import getpass
import os
import secrets
import sys

from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import ledger
from app.auth import hash_password
from app.models import (AdminUser, Base, Candidate, Election, Position, Role,
                        Voter)
from app.voting import hash_student_no


def _session():
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is not set.")
    if not os.environ.get("BALLOT_PEPPER"):
        sys.exit("BALLOT_PEPPER is not set.")
    engine = create_engine(url, future=True)
    return sessionmaker(bind=engine, future=True)(), engine


def cmd_init_db(args):
    db, engine = _session()
    Base.metadata.create_all(engine)
    print("Schema created (idempotent).")


def cmd_create_admin(args):
    db, _ = _session()
    email = args.email.strip().lower()
    if db.query(AdminUser).filter(AdminUser.email == email).first():
        sys.exit("An administrator with that email already exists.")
    pw = getpass.getpass("Password for %s: " % email)
    if len(pw) < 12:
        sys.exit("Use at least 12 characters.")
    if pw != getpass.getpass("Confirm: "):
        sys.exit("Passwords did not match.")
    admin = AdminUser(email=email, full_name=args.name or email,
                      password_hash=hash_password(pw), role=Role(args.role))
    db.add(admin)
    ledger.record_event(db, "admin_created", actor="cli",
                        payload={"role": args.role})
    db.commit()
    print("Created %s with role %s" % (email, args.role))


def cmd_create_election(args):
    db, _ = _session()
    if db.query(Election).filter(Election.slug == args.slug).first():
        sys.exit("That slug is already in use.")
    e = Election(slug=args.slug, name=args.name)
    db.add(e)
    db.flush()
    ledger.record_event(db, "election_created", actor="cli", election_id=e.id,
                        payload={"slug": args.slug})
    db.commit()
    print("Created election %s (state=%s)" % (e.slug, e.state.value))


def _election(db, slug):
    e = db.query(Election).filter(Election.slug == slug).first()
    if not e:
        sys.exit("No election with slug %r." % slug)
    return e


def cmd_add_position(args):
    db, _ = _session()
    e = _election(db, args.election)
    p = Position(election_id=e.id, slug=args.slug, title=args.title,
                 display_order=args.order, max_selections=args.max_selections)
    db.add(p)
    ledger.record_event(db, "position_created", actor="cli", election_id=e.id,
                        payload={"position": args.slug})
    db.commit()
    print("Added position %s" % args.slug)


def cmd_add_candidate(args):
    db, _ = _session()
    e = _election(db, args.election)
    p = db.query(Position).filter(Position.election_id == e.id,
                                  Position.slug == args.position).first()
    if not p:
        sys.exit("No position %r in %s." % (args.position, args.election))
    c = Candidate(position_id=p.id, full_name=args.name, school=args.school,
                  programme=args.programme, symbol=args.symbol)
    db.add(c)
    ledger.record_event(db, "candidate_created", actor="cli", election_id=e.id,
                        payload={"position": p.slug})
    db.commit()
    print("Added candidate to %s" % p.slug)


def cmd_import_voters(args):
    """CSV columns: student_no, display_name, school"""
    db, _ = _session()
    e = _election(db, args.election)
    created = skipped = 0
    out = []
    with open(args.csv, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            sn = (row.get("student_no") or "").strip()
            if not sn:
                skipped += 1
                continue
            h = hash_student_no(sn)
            if db.query(Voter.id).filter(Voter.election_id == e.id,
                                         Voter.student_no_hash == h).first():
                skipped += 1
                continue
            otp = secrets.token_urlsafe(9)
            db.add(Voter(election_id=e.id, student_no_hash=h,
                         display_name=(row.get("display_name") or "")[:160],
                         school=(row.get("school") or "")[:120],
                         password_hash=hash_password(otp)))
            out.append((sn, otp))
            created += 1
    ledger.record_event(db, "voter_roll_imported", actor="cli", election_id=e.id,
                        payload={"created": created, "skipped": skipped})
    db.commit()

    path = args.credentials_out or "voter-credentials.csv"
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["student_no", "initial_password"])
        w.writerows(out)
    os.chmod(path, 0o600)
    print("Imported %d, skipped %d." % (created, skipped))
    print("Initial passwords written to %s (mode 600). Distribute securely, "
          "then delete this file - they are stored only as hashes." % path)


def cmd_verify_chain(args):
    db, _ = _session()
    out = ledger.verify_chain(db)
    print("entries=%s valid=%s broken_at=%s" % (out["entries"], out["ok"],
                                                out["broken_at"]))
    sys.exit(0 if out["ok"] else 1)


def cmd_status(args):
    db, _ = _session()
    for e in db.query(Election).all():
        print("%-18s %-10s public=%s frozen=%s" % (
            e.slug, e.state.value, e.results_public, e.results_frozen))
    st = ledger.status(db)
    print("\nledger: %s (blockchain_connected=%s, entries=%s, valid=%s)" % (
        st["mode"], st["blockchain_connected"], st["entries"], st["chain_valid"]))


def main():
    ap = argparse.ArgumentParser(description="ALU-ELECT management")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init-db").set_defaults(fn=cmd_init_db)

    p = sub.add_parser("create-admin")
    p.add_argument("--email", required=True)
    p.add_argument("--name")
    p.add_argument("--role", required=True, choices=[r.value for r in Role])
    p.set_defaults(fn=cmd_create_admin)

    p = sub.add_parser("create-election")
    p.add_argument("--slug", required=True)
    p.add_argument("--name", required=True)
    p.set_defaults(fn=cmd_create_election)

    p = sub.add_parser("add-position")
    p.add_argument("--election", required=True)
    p.add_argument("--slug", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--order", type=int, default=0)
    p.add_argument("--max-selections", dest="max_selections", type=int, default=1)
    p.set_defaults(fn=cmd_add_position)

    p = sub.add_parser("add-candidate")
    p.add_argument("--election", required=True)
    p.add_argument("--position", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--school")
    p.add_argument("--programme")
    p.add_argument("--symbol")
    p.set_defaults(fn=cmd_add_candidate)

    p = sub.add_parser("import-voters")
    p.add_argument("--election", required=True)
    p.add_argument("--csv", required=True)
    p.add_argument("--credentials-out")
    p.set_defaults(fn=cmd_import_voters)

    sub.add_parser("verify-chain").set_defaults(fn=cmd_verify_chain)
    sub.add_parser("status").set_defaults(fn=cmd_status)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
