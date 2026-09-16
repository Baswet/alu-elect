#!/usr/bin/env python3
"""
DEVELOPMENT / STAGING SEED. Never run this against a real election.

Builds a realistic-but-clearly-fictional dataset so the UI can be exercised
against a real database: several positions, candidates spread across schools
and programmes, some with photos and some without, one withdrawn candidate
that must NOT appear anywhere, and a voter roll with generated passwords.

It refuses to run unless ALU_SEED_CONFIRM=yes is set, and it refuses to touch
an election that is CERTIFIED or ARCHIVED.
"""

import csv
import os
import secrets
import sys

from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker

from app import ledger
from app.auth import hash_password
from app.models import (AdminUser, Ballot, BallotSelection, Base, Candidate,
                        Election, ElectionState, Position, Receipt, ResultTally,
                        Role, Voter)
from app.voting import hash_student_no

SLUG = os.environ.get("ALU_SEED_ELECTION", "ge-2026")

POSITIONS = [
    ("president", "Student President", 1, 1,
     "Leads the student council and represents students to the university "
     "senate."),
    ("vice-president", "Vice President", 2, 1,
     "Deputises for the president and chairs the welfare committee."),
    ("secretary", "Secretary General", 3, 1,
     "Keeps council records and publishes minutes of every sitting."),
    ("treasurer", "Treasurer", 4, 1,
     "Accounts for the student activity fund and publishes quarterly "
     "statements."),
    ("delegate", "School Delegates", 5, 2,
     "Two delegates carry school-level concerns into council meetings."),
]

# (position slug, name, symbol, school, programme, year, photo, manifesto,
#  active, order)
CANDIDATES = [
    ("president", "Amina Otieno", "Lantern", "SESS",
     "BSc Computer Science", "Year 3", "img/candidates/amina-otieno.jpg",
     "Publish every council expenditure within seven days. Extend library "
     "opening hours to midnight during examinations. Negotiate a fixed "
     "shuttle timetable with the transport office so evening students are "
     "not stranded.", True, 1),
    ("president", "Brian Kiptoo", "Torch", "SHS",
     "BSc Nursing", "Year 4", "",
     "A students' council that meets in public. Monthly open forums in each "
     "school, minutes posted the same week, and a standing complaints desk "
     "at the health unit.", True, 2),
    ("president", "Cynthia Wafula", "Sunflower", "SBEHRD",
     "BCom Finance", "Year 2", "img/candidates/cynthia-wafula.jpg",
     "Cut the cost of studying: bulk printing at cost price, a textbook "
     "exchange run by the council, and an emergency fund for students who "
     "cannot clear fees before examinations.", True, 3),

    ("vice-president", "Dennis Barasa", "Anchor", "SESS",
     "BEd Science", "Year 3", "",
     "Welfare first. A functioning counselling referral, hostel maintenance "
     "reported through one channel, and a written response to every case "
     "within fourteen days.", True, 1),
    ("vice-president", "Faith Nasimiyu", "Dove", "SHS",
     "BSc Public Health", "Year 3", "img/candidates/faith-nasimiyu.jpg",
     "Safety and dignity on campus: lighting audits every term, a published "
     "anti-harassment procedure, and a student escort scheme after dark.",
     True, 2),

    ("secretary", "Geoffrey Mutai", "Quill", "SBEHRD",
     "BCom Marketing", "Year 2", "",
     "Minutes within 72 hours, a searchable archive of every council "
     "decision, and an annual report students can actually read.", True, 1),
    ("secretary", "Hellen Achieng", "Scroll", "SESS",
     "BSc Mathematics", "Year 4", "img/candidates/hellen-achieng.jpg",
     "One place for every council document. No decision taken that is not "
     "written down, and no document that a student cannot request.",
     True, 2),

    ("treasurer", "Ian Cheruiyot", "Balance", "SBEHRD",
     "BCom Accounting", "Year 3", "",
     "Quarterly statements audited by a student committee, procurement "
     "above KES 50,000 put to tender, and no cash payments.", True, 1),
    ("treasurer", "Joy Wanjiku", "Ledger", "SESS",
     "BSc Statistics", "Year 2", "",
     "Every shilling traceable. A public register of council spending "
     "updated monthly, and receipts scanned and attached.", True, 2),

    ("delegate", "Kevin Omondi", "Bridge", "SHS",
     "BSc Nursing", "Year 2", "",
     "Clinical placement allowances paid on time, and a delegate who sits "
     "in the school board meetings rather than hearing about them after.",
     True, 1),
    ("delegate", "Lydia Chepkoech", "Compass", "SESS",
     "BEd Arts", "Year 3", "img/candidates/lydia-chepkoech.jpg",
     "Teaching practice logistics fixed before the term starts, and lab "
     "timetables published alongside lectures.", True, 2),
    ("delegate", "Martin Oduor", "Beacon", "SBEHRD",
     "BCom Economics", "Year 4", "",
     "A delegate for the evening class. Council business scheduled so "
     "part-time students can attend.", True, 3),

    # Withdrawn after nomination. Must never appear on the public page,
    # the ballot, or the results.
    ("president", "Nelson Wekesa (withdrawn)", "Kite", "SHS",
     "BSc Nursing", "Year 3", "",
     "This nomination was withdrawn and must not be displayed anywhere.",
     False, 4),
]

SCHOOLS = ["SESS", "SHS", "SBEHRD"]


def main():
    if os.environ.get("ALU_SEED_CONFIRM") != "yes":
        sys.exit("Refusing to seed. Set ALU_SEED_CONFIRM=yes to proceed.")
    url = os.environ.get("DATABASE_URL")
    pepper = os.environ.get("BALLOT_PEPPER")
    if not url or not pepper:
        sys.exit("DATABASE_URL and BALLOT_PEPPER must be set.")

    engine = create_engine(url, future=True)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, future=True)()

    e = db.query(Election).filter(Election.slug == SLUG).first()
    if not e:
        e = Election(slug=SLUG, name="ALU Student Council 2026")
        db.add(e)
        db.flush()
    if e.state in (ElectionState.CERTIFIED, ElectionState.ARCHIVED):
        sys.exit("Refusing to reseed a %s election." % e.state.value)

    # Wipe only this election's data, deepest table first.
    pos_ids = [p.id for p in db.query(Position)
               .filter(Position.election_id == e.id).all()]
    ballot_ids = [b.id for b in db.query(Ballot)
                  .filter(Ballot.election_id == e.id).all()]
    if ballot_ids:
        db.execute(delete(BallotSelection)
                   .where(BallotSelection.ballot_id.in_(ballot_ids)))
    db.execute(delete(Receipt).where(Receipt.election_id == e.id))
    db.execute(delete(Ballot).where(Ballot.election_id == e.id))
    db.execute(delete(ResultTally).where(ResultTally.election_id == e.id))
    db.execute(delete(Voter).where(Voter.election_id == e.id))
    if pos_ids:
        db.execute(delete(Candidate).where(Candidate.position_id.in_(pos_ids)))
    db.execute(delete(Position).where(Position.election_id == e.id))
    db.flush()

    by_slug = {}
    for slug, title, order, maxsel, desc in POSITIONS:
        p = Position(election_id=e.id, slug=slug, title=title,
                     display_order=order, max_selections=maxsel,
                     description=desc)
        db.add(p)
        db.flush()
        by_slug[slug] = p

    for (pslug, name, symbol, school, programme, year, photo, manifesto,
         active, order) in CANDIDATES:
        db.add(Candidate(position_id=by_slug[pslug].id, full_name=name,
                         symbol=symbol, school=school, programme=programme,
                         year_of_study=year, photo_path=photo,
                         manifesto=manifesto, is_active=active,
                         display_order=order))

    # Voter roll.
    rows = []
    count = int(os.environ.get("ALU_SEED_VOTERS", "40"))
    for i in range(1, count + 1):
        sn = "ALU/%04d/2026" % i
        pw = secrets.token_urlsafe(9)
        db.add(Voter(election_id=e.id, student_no_hash=hash_student_no(sn),
                     display_name="Test Voter %02d" % i,
                     school=SCHOOLS[i % len(SCHOOLS)],
                     password_hash=hash_password(pw)))
        rows.append((sn, pw))

    e.state = ElectionState.OPEN
    e.results_public = True
    e.results_frozen = False

    ledger.record_event(db, "dev_dataset_seeded", actor="seed_dev.py",
                        election_id=e.id,
                        payload={"positions": len(POSITIONS),
                                 "candidates": len(CANDIDATES),
                                 "voters": count})
    db.commit()

    # Admin accounts, one per role, for the RBAC matrix work.
    admin_rows = []
    for role in Role:
        email = "%s@alupe.test" % role.value.lower().replace("_", ".")
        if db.query(AdminUser).filter(AdminUser.email == email).first():
            continue
        pw = secrets.token_urlsafe(12)
        db.add(AdminUser(email=email, full_name=role.value.title(),
                         password_hash=hash_password(pw), role=role))
        admin_rows.append((email, role.value, pw))
    db.commit()

    out = os.environ.get("ALU_SEED_CREDENTIALS", "dev-credentials.csv")
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["kind", "identifier", "role", "password"])
        for sn, pw in rows:
            w.writerow(["voter", sn, "", pw])
        for email, role, pw in admin_rows:
            w.writerow(["admin", email, role, pw])
    os.chmod(out, 0o600)

    print("Seeded %s: %d positions, %d candidates (%d active), %d voters, "
          "%d admins." % (SLUG, len(POSITIONS), len(CANDIDATES),
                          sum(1 for c in CANDIDATES if c[8]), count,
                          len(admin_rows)))
    print("Credentials -> %s (mode 600). Development only." % out)


if __name__ == "__main__":
    main()
