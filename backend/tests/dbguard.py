"""
A guard against the test suite destroying a real database.

Both test modules begin their fixtures with Base.metadata.drop_all(). That
is correct for a scratch database and catastrophic for any other. The
target is read from the environment, so anything that puts a real
DATABASE_URL there - sourcing a deployment .env before running pytest, a
CI job that exports production settings, a shell that still has last
command's variables - silently arms the suite at live data.

This happened during development: `set -a; . ./.env; pytest` dropped every
table in the working development database, including the voter roll and
the audit ledger. Nothing in the suite objected, because from its point of
view the URL was simply the one it had been given.

So the suite now refuses any database whose name does not declare itself
disposable. A name must contain "test", or end in "_ci" or "_scratch", or
the run is explicitly confirmed with ALU_ALLOW_DESTRUCTIVE_DB=yes. The
check is on the database NAME rather than the host: "localhost" is not a
safety property, and plenty of real elections will be run from a laptop.
"""

import os
import re
import sys

SAFE = re.compile(r"(^|[_-])(test|tests|scratch|ci)($|[_-])")


def database_name(url: str) -> str:
    """The database name out of a SQLAlchemy URL, query string ignored."""
    without_query = url.split("?", 1)[0]
    tail = without_query.rsplit("/", 1)[-1]
    return tail.strip()


def assert_disposable(url: str, variable: str) -> str:
    """Return the URL, or exit if it does not name a disposable database."""
    if os.environ.get("ALU_ALLOW_DESTRUCTIVE_DB") == "yes":
        return url

    name = database_name(url)
    if not name:
        sys.exit(
            "%s does not name a database: %r" % (variable, url))

    if SAFE.search(name.lower()):
        return url

    sys.exit(
        "\nREFUSING TO RUN.\n\n"
        "  The test suite drops every table in its target database, and\n"
        "  %s points at %r, which is not named as a test database.\n\n"
        "  If that is a real database you would lose the voter roll, the\n"
        "  ballots and the audit ledger.\n\n"
        "  Point %s at a database whose name contains \"test\" (or ends\n"
        "  in _ci / _scratch), for example:\n\n"
        "      %s=postgresql+psycopg://postgres@127.0.0.1:5432/aluelect_test\n\n"
        "  If you really do mean to wipe %r, say so explicitly:\n\n"
        "      ALU_ALLOW_DESTRUCTIVE_DB=yes pytest\n"
        % (variable, name, variable, variable, name))
