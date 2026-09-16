#!/usr/bin/env python3
"""
Browser verification of the ALU-ELECT administration console.

Drives the real page against the real API and the real database, for every
one of the five roles, and checks both halves of authorisation:

  * what the UI offers a role, and
  * what the SERVER does when that role's browser asks anyway.

The second half matters more. A console that merely hides a button has not
enforced anything.
"""

import csv
import json
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1]
CREDS = sys.argv[2]
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

results, console_errors, failed_req = [], [], []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print("%-62s %s %s" % (name, "PASS" if ok else "FAIL", str(detail)[:60]))


def load_creds():
    admins, voters = {}, []
    with open(CREDS, newline="") as fh:
        for row in csv.DictReader(fh):
            if row["kind"] == "admin":
                admins[row["role"]] = (row["identifier"], row["password"])
            else:
                voters.append((row["identifier"], row["password"]))
    return admins, voters


# Permission matrix as declared in app/governance.py. The point of
# restating it here is that the test fails if the server's behaviour and
# the documented model ever drift apart.
MATRIX = {
    "SUPER_ADMIN": {"election.create", "election.edit", "election.transition",
                    "election.certify", "candidate.manage", "voter.manage",
                    "results.view", "results.publish", "audit.view",
                    "security.view", "admin.manage"},
    "ELECTION_ADMIN": {"election.edit", "election.transition",
                       "candidate.manage", "voter.manage", "results.view",
                       "audit.view"},
    "RESULTS_OFFICER": {"results.view", "results.publish", "audit.view"},
    "AUDITOR": {"results.view", "audit.view", "security.view"},
    "READ_ONLY_ADMIN": {"results.view"},
}

# (label, permission the server requires, request)
PROBES = [
    ("GET /admin/elections", "results.view",
     "() => fetch('/api/admin/elections')"),
    ("GET /admin/audit", "audit.view", "() => fetch('/api/admin/audit')"),
    ("GET /admin/security", "security.view",
     "() => fetch('/api/admin/security')"),
    ("GET /admin/voters", "voter.manage",
     "() => fetch('/api/admin/elections/%(eid)s/voters')"),
]


def api_login(page, email, password):
    return page.evaluate(
        """async ([e, p]) => {
            const r = await fetch('/api/admin/login', {
                method: 'POST', credentials: 'include',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({email: e, password: p})});
            const d = await r.json().catch(() => ({}));
            if (d.csrf_token) { window.__csrf = d.csrf_token; }
            return {status: r.status, body: d};
        }""", [email, password])


def main():
    admins, voters = load_creds()

    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        ctx = b.new_context(viewport={"width": 1440, "height": 1000})
        page = ctx.new_page()
        page.on("console", lambda m: console_errors.append(m.text)
                if m.type == "error" else None)
        page.on("requestfailed",
                lambda r: failed_req.append("%s %s" % (r.method, r.url)))

        # =============================================== 1. the gate
        page.goto("%s/admin.html" % BASE, wait_until="networkidle")
        page.wait_for_timeout(1500)

        check("1 admin.html loads",
              page.title() == "Admin Dashboard | ALU-ELECT", page.title())
        check("2 admin.js executed",
              page.evaluate("() => typeof ALUAdmin === 'object'"))
        check("3 sign-in screen shown when not authenticated",
              page.is_visible("#adminLoginScreen"))
        check("4 console is HIDDEN before sign-in",
              not page.is_visible("#adminShell"))
        body = page.inner_text("body")
        for leak in ("Total Votes Cast", "Eligible Voters", "Audit"):
            pass
        check("4b no election data on screen before sign-in",
              "Loading candidate data" not in body and
              "Amina Otieno" not in body)

        # Bad password must be refused.
        page.fill("#adminLoginEmail", admins["SUPER_ADMIN"][0])
        page.fill("#adminLoginPassword", "not-the-password")
        page.click("#adminLoginSubmit")
        page.wait_for_timeout(1500)
        check("5 wrong password refused, console stays hidden",
              page.is_visible("#adminLoginError") and
              not page.is_visible("#adminShell"),
              page.inner_text("#adminLoginError")[:50])

        # =========================================== 2. SUPER_ADMIN
        email, pw = admins["SUPER_ADMIN"]
        page.fill("#adminLoginEmail", email)
        page.fill("#adminLoginPassword", pw)
        page.click("#adminLoginSubmit")
        page.wait_for_timeout(2500)

        check("6 correct password signs in",
              page.is_visible("#adminShell") and
              not page.is_visible("#adminLoginScreen"))
        check("6b password field cleared after sign-in",
              page.input_value("#adminLoginPassword") == "")
        check("7 real administrator identity shown",
              email.split("@")[0].replace(".", " ").title()
              in page.inner_text("#adminUserName") or
              email in page.inner_text("#adminUserName") or
              page.inner_text("#adminUserName") != "Election Administrator",
              page.inner_text("#adminUserName"))
        check("7b real role shown",
              "Super Admin" in page.inner_text("#adminUserRole"),
              page.inner_text("#adminUserRole"))

        # ------------------------------------------- dashboard vs API
        summary = page.evaluate(
            """async () => {
                const l = await (await fetch('/api/admin/elections')).json();
                const id = l.elections.filter(e => e.state === 'OPEN')[0].id;
                const s = await (await fetch(
                    '/api/admin/elections/' + id + '/summary')).json();
                return {id: id, s: s};
            }""")
        eid = summary["id"]
        c = summary["s"]["counts"]

        check("8 eligible voters match the database",
              str(c["eligible_voters"]) in page.inner_text("#eligibleVoters"),
              "DOM %s / API %s" % (page.inner_text("#eligibleVoters"),
                                   c["eligible_voters"]))
        check("8b positions match the database",
              page.inner_text("#totalPositions") == str(c["positions"]),
              "DOM %s / API %s" % (page.inner_text("#totalPositions"),
                                   c["positions"]))
        check("8c candidates match the database (withdrawn excluded)",
              page.inner_text("#totalCandidates") == str(c["candidates"]),
              "DOM %s / API %s" % (page.inner_text("#totalCandidates"),
                                   c["candidates"]))
        check("8d ballots match the database",
              page.inner_text("#totalVotes").replace(",", "")
              == str(c["ballots"]),
              "DOM %s / API %s" % (page.inner_text("#totalVotes"),
                                   c["ballots"]))
        check("8e turnout matches the database",
              str(c["turnout_percent"]) in page.inner_text(
                  "#turnoutPercentage"),
              "DOM %s / API %s" % (page.inner_text("#turnoutPercentage"),
                                   c["turnout_percent"]))
        check("8f no invented 'change since' figure on a cold load",
              "Baseline" in page.inner_text("#votesChange") or
              "No change" in page.inner_text("#votesChange"),
              page.inner_text("#votesChange"))

        # ------------------------------------------------- candidates
        page.click('[data-admin-section="candidates"]')
        page.wait_for_timeout(800)
        roster = page.evaluate(
            "async (id) => (await fetch('/api/admin/elections/' + id + "
            "'/positions')).json()", eid)
        all_c = [c2 for pos in roster["positions"]
                 for c2 in pos["candidates"]]
        rows = page.query_selector_all("#candidateTableBody tr")
        check("9 candidate table shows every nomination incl. withdrawn",
              len(rows) == len(all_c),
              "%d rows / %d in API" % (len(rows), len(all_c)))
        table = page.inner_text("#candidateTableBody")
        check("9b real candidate names in the table",
              all(x["full_name"] in table for x in all_c))
        check("9c withdrawn candidate visible and labelled to an admin",
              any(not x["is_active"] for x in all_c) and
              "Withdrawn" in table)
        check("9d no 'Loading candidate data' left behind",
              "Loading candidate data" not in table)

        res = page.evaluate(
            "async (id) => (await fetch('/api/admin/elections/' + id + "
            "'/results')).json()", eid)
        votes = {cc["name"]: cc["votes"] for pp in res["positions"]
                 for cc in pp["candidates"]}
        leader = max(votes, key=votes.get)
        check("10 candidate vote counts come from the results API",
              str(votes[leader]) in table, "%s=%s" % (leader, votes[leader]))

        # ----------------------------------------------------- voters
        page.click('[data-admin-section="voters"]')
        page.wait_for_timeout(800)
        vlist = page.evaluate(
            "async (id) => (await fetch('/api/admin/elections/' + id + "
            "'/voters')).json()", eid)
        vrows = page.query_selector_all("#voterTableBody tr")
        check("11 voter table shows the real roll",
              len(vrows) == len(vlist["voters"]),
              "%d rows / %d in API" % (len(vrows), len(vlist["voters"])))
        vtable = page.inner_text("#voterTableBody")
        check("11b voter table never shows a candidate name",
              not any(x["full_name"] in vtable for x in all_c))
        check("11c voter table shows no per-voter timestamp",
              "Last Activity" not in page.inner_text("#voters"))
        voted = len([v for v in vlist["voters"] if v["has_voted"]])
        check("11d ballot-recorded count matches the database",
              vtable.count("Ballot recorded") == voted,
              "DOM %d / API %d" % (vtable.count("Ballot recorded"), voted))

        # ------------------------------------------------------ audit
        page.click('[data-admin-section="audit"]')
        page.wait_for_timeout(900)
        audit = page.evaluate(
            "async () => (await fetch('/api/admin/audit')).json()")
        alog = page.inner_text("#auditLog")
        check("12 audit log rendered from the real ledger",
              ("#%d" % audit["events"][0]["seq"]) in alog,
              "newest seq %s" % audit["events"][0]["seq"])
        check("12b hash chain state reported truthfully",
              ("intact" in alog.lower()) == bool(audit["chain"]["ok"]),
              "chain ok=%s" % audit["chain"]["ok"])
        check("12c real entry hashes shown",
              audit["events"][0]["entry_hash"][:12] in alog)

        # ------------------------------------- ledger honesty (no fake chain)
        ledger = page.evaluate(
            "async () => (await fetch('/api/admin/ledger')).json()")
        lpanel = page.inner_text("#blockchain")
        check("13 ledger panel visible with the audit trail",
              page.is_visible("#blockchain"))
        if not ledger["blockchain_connected"]:
            check("13b does NOT claim a blockchain is connected",
                  "no blockchain network connected"
                  in page.inner_text("#ledgerStatus").lower(),
                  page.inner_text("#ledgerStatus")[:60])
            check("13c no invented block height",
                  "Not applicable" in page.inner_text("#latestBlock"),
                  page.inner_text("#latestBlock"))
            check("13d no invented node count",
                  "Not applicable" in page.inner_text("#networkNodes"),
                  page.inner_text("#networkNodes"))
            check("13e no invented consensus status",
                  "Not applicable" in page.inner_text("#consensusStatus"),
                  page.inner_text("#consensusStatus"))
        check("13f real entry count from the ledger",
              str(ledger["entries"]) in page.inner_text("#verifiedRecords"),
              "%s entries" % ledger["entries"])
        check("13g real head hash shown",
              (ledger.get("head_hash") or "")[:16] in
              page.inner_text("#electionHash"),
              page.inner_text("#electionHash")[:24])

        # --------------------------------------------------- security
        page.click('[data-admin-section="security"]')
        page.wait_for_timeout(800)
        sec = page.evaluate(
            "async () => (await fetch('/api/admin/security')).json()")
        stable = page.inner_text("#authenticationTableBody")
        check("14 the failed sign-in from this test is in the log",
              "admin login failed" in stable.lower() or
              any("login_failed" in e["kind"] for e in sec["events"]),
              "%d events" % len(sec["events"]))

        # ================================= 3. step-up authentication
        page.click('[data-admin-section="election"]')
        page.wait_for_timeout(600)

        # Freezing results requires the admin's own password server-side.
        bad = page.evaluate(
            """async ([id, pw]) => {
                const r = await fetch('/api/admin/elections/' + id +
                    '/results-visibility', {
                    method: 'POST', credentials: 'include',
                    headers: {'Content-Type': 'application/json',
                              'X-CSRF-Token': window.__csrf ||
                                  ALUApp.config.csrfToken},
                    body: JSON.stringify({frozen: true, password: pw})});
                return {status: r.status, body: await r.json()};
            }""", [eid, "wrong-password"])
        check("15 server refuses a critical action without the password",
              bad["status"] == 403 and
              bad["body"].get("code") == "reauth_required",
              json.dumps(bad)[:70])

        frozen_now = page.evaluate(
            "async (id) => (await (await fetch('/api/admin/elections/' + id "
            "+ '/summary')).json()).election.results_frozen", eid)
        check("15b the refused action changed nothing",
              frozen_now is False, "results_frozen=%s" % frozen_now)

        # Now do it properly, through the UI dialog.
        page.click("#criticalFreezeResults")
        page.wait_for_timeout(500)
        check("16 confirmation dialog opens for a critical action",
              page.is_visible("#adminConfirmationModal"))
        check("16b dialog names the signed-in administrator",
              email in page.inner_text("#confirmationAdministrator"))
        page.fill("#adminConfirmationCode", pw)
        page.click("#confirmAdminAction")
        page.wait_for_timeout(2500)
        frozen_now = page.evaluate(
            "async (id) => (await (await fetch('/api/admin/elections/' + id "
            "+ '/summary')).json()).election.results_frozen", eid)
        check("17 correct password carries the action out",
              frozen_now is True, "results_frozen=%s" % frozen_now)
        check("17b password is not left in the DOM",
              page.input_value("#adminConfirmationCode") == "")
        check("17c the public results endpoint really is frozen now",
              page.evaluate(
                  "async () => (await fetch('/api/election/results')).status")
              == 423)

        # Unfreeze so the rest of the system is left as found.
        page.click("#criticalFreezeResults")
        page.wait_for_timeout(500)
        page.fill("#adminConfirmationCode", pw)
        page.click("#confirmAdminAction")
        page.wait_for_timeout(2500)
        check("18 unfreeze restores public results",
              page.evaluate(
                  "async () => (await fetch('/api/election/results')).status")
              == 200)

        # ------------------------------- the freeze/unfreeze is in the ledger
        audit2 = page.evaluate(
            "async () => (await fetch('/api/admin/audit')).json()")
        check("19 the action was written to the audit ledger",
              any(e["type"] == "results_visibility_changed"
                  for e in audit2["events"]))
        check("19b the ledger still verifies after the change",
              audit2["chain"]["ok"] is True)

        # =================================== 4. illegal state transition
        illegal = page.evaluate(
            """async ([id, pw]) => {
                const r = await fetch('/api/admin/elections/action', {
                    method: 'POST', credentials: 'include',
                    headers: {'Content-Type': 'application/json',
                              'X-CSRF-Token': window.__csrf ||
                                  ALUApp.config.csrfToken},
                    body: JSON.stringify({election_id: id,
                        target_state: 'CERTIFIED', password: pw})});
                return {status: r.status, body: await r.json()};
            }""", [eid, pw])
        check("20 OPEN cannot jump straight to CERTIFIED",
              illegal["status"] == 409, json.dumps(illegal["body"])[:70])
        state_now = page.evaluate(
            "async (id) => (await (await fetch('/api/admin/elections/' + id "
            "+ '/summary')).json()).election.state", eid)
        check("20b the election is still OPEN", state_now == "OPEN",
              state_now)

        # Sign out through the real button, which is also the only path a
        # user has. (Doing it with a raw fetch fails CSRF - as it should.)
        page.click("#adminLogoutButton")
        page.wait_for_timeout(1500)
        check("20c Sign Out returns to the sign-in screen",
              page.is_visible("#adminLoginScreen") and
              not page.is_visible("#adminShell"))
        check("20d the server really ended the session",
              page.evaluate(
                  "async () => (await fetch('/api/admin/me',"
                  "{credentials:'include'})).status") == 401)

        # ======================================= 5. THE RBAC MATRIX
        for role in ("ELECTION_ADMIN", "RESULTS_OFFICER", "AUDITOR",
                     "READ_ONLY_ADMIN"):
            remail, rpw = admins[role]
            ctx2 = b.new_context(viewport={"width": 1440, "height": 1000})
            rp = ctx2.new_page()
            rp.goto("%s/admin.html" % BASE, wait_until="networkidle")
            rp.wait_for_timeout(800)
            rp.fill("#adminLoginEmail", remail)
            rp.fill("#adminLoginPassword", rpw)
            rp.click("#adminLoginSubmit")
            rp.wait_for_timeout(2500)

            check("%s signs in" % role, rp.is_visible("#adminShell"),
                  "" if rp.is_visible("#adminShell")
                  else rp.inner_text("#adminLoginError")[:60])
            perms = set(rp.evaluate("() => ALUAdmin.state.permissions"))
            check("%s permissions match governance.py" % role,
                  perms == MATRIX[role],
                  "extra=%s missing=%s" % (sorted(perms - MATRIX[role]),
                                           sorted(MATRIX[role] - perms)))

            # The server is the real gate: probe it directly.
            for label, needed, js in PROBES:
                status = rp.evaluate(
                    "async () => (await (%s)()).status"
                    % (js % {"eid": eid}))
                allowed = needed in MATRIX[role]
                check("%s: server %s -> %s" % (role, label,
                                               "200" if allowed else "403"),
                      status == (200 if allowed else 403),
                      "got %s" % status)

            # And a write it must not be able to perform.
            if "election.transition" not in MATRIX[role]:
                out = rp.evaluate(
                    """async (id) => {
                        const t = await (await fetch('/api/csrf',
                            {credentials:'include'})).json();
                        const r = await fetch('/api/admin/elections/action', {
                            method:'POST', credentials:'include',
                            headers:{'Content-Type':'application/json',
                                     'X-CSRF-Token': t.csrf_token},
                            body: JSON.stringify({election_id:id,
                                target_state:'PAUSED'})});
                        return r.status;
                    }""", eid)
                check("%s: server refuses a state change" % role,
                      out == 403, "got %s" % out)

            if "candidate.manage" not in MATRIX[role]:
                add = rp.query_selector("#addCandidateButton")
                check("%s: Add Candidate disabled in the UI" % role,
                      add is None or add.is_disabled())
                out = rp.evaluate(
                    """async () => {
                        const t = await (await fetch('/api/csrf',
                            {credentials:'include'})).json();
                        const r = await fetch(
                            '/api/admin/positions/1/candidates', {
                            method:'POST', credentials:'include',
                            headers:{'Content-Type':'application/json',
                                     'X-CSRF-Token': t.csrf_token},
                            body: JSON.stringify({full_name:'Injected'})});
                        return r.status;
                    }""")
                check("%s: server refuses adding a candidate" % role,
                      out == 403, "got %s" % out)

            if "voter.manage" not in MATRIX[role]:
                check("%s: voter roll not shown in the UI" % role,
                      "does not permit"
                      in rp.inner_text("#voterTableBody").lower(),
                      rp.inner_text("#voterTableBody")[:40])

            if "security.view" not in MATRIX[role]:
                link = rp.query_selector('[data-admin-section="security"]')
                check("%s: security section hidden in the UI" % role,
                      link is None or link.get_attribute("hidden") is not None
                      or not link.is_visible())

            ctx2.close()

        # ========================== 6. a voter session is not an admin
        vs, vp = voters[0]
        ctx3 = b.new_context()
        vpage = ctx3.new_page()
        vpage.goto("%s/admin.html" % BASE, wait_until="networkidle")
        out = vpage.evaluate(
            """async ([sn, pw]) => {
                await fetch('/api/election/login', {
                    method:'POST', credentials:'include',
                    headers:{'Content-Type':'application/json'},
                    body: JSON.stringify({student_no: sn, password: pw})});
                const r = await fetch('/api/admin/me',
                                      {credentials:'include'});
                return r.status;
            }""", [vs, vp])
        check("21 a signed-in VOTER is not an admin (401)", out == 401,
              "got %s" % out)
        vpage.reload(wait_until="networkidle")
        vpage.wait_for_timeout(1500)
        check("21b and the console stays hidden for them",
              not vpage.is_visible("#adminShell"))
        ctx3.close()

        # ================================== 7. screenshots + responsive
        page.goto("%s/admin.html" % BASE, wait_until="networkidle")
        page.wait_for_timeout(800)
        page.fill("#adminLoginEmail", email)
        page.fill("#adminLoginPassword", pw)
        page.click("#adminLoginSubmit")
        page.wait_for_timeout(2500)

        for w in (320, 375, 390, 414, 768, 1024, 1440):
            page.set_viewport_size({"width": w, "height": 900})
            page.wait_for_timeout(350)
            over = page.evaluate(
                "() => document.documentElement.scrollWidth "
                "> window.innerWidth + 2")
            check("responsive @%dpx no horizontal overflow" % w, not over,
                  "scrollWidth=%s" % page.evaluate(
                      "() => document.documentElement.scrollWidth"))

        page.set_viewport_size({"width": 1440, "height": 1050})
        page.wait_for_timeout(500)
        page.screenshot(path="/mnt/user-data/outputs/alu-admin-dashboard.png")
        page.click('[data-admin-section="audit"]')
        page.wait_for_timeout(800)
        page.screenshot(path="/mnt/user-data/outputs/alu-admin-audit.png")
        page.click("#adminLogoutButton")
        page.wait_for_timeout(1200)
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(1200)
        page.screenshot(path="/mnt/user-data/outputs/alu-admin-login.png")
        b.close()

    real = [e for e in console_errors
            if "favicon" not in e.lower() and "401" not in e and "403" not in e]
    badreq = [r for r in failed_req if "favicon" not in r.lower()]
    print("\nconsole errors: %s" % ("\n  ".join(real[:10]) or "none"))
    print("failed requests: %s" % ("\n  ".join(badreq[:6]) or "none"))
    ok = sum(1 for _, o, _ in results if o)
    print("\n%d/%d admin checks passed" % (ok, len(results)))
    bad = [n for n, o, _ in results if not o]
    if bad:
        print("FAILED: " + "; ".join(bad))
    return 0 if ok == len(results) and not real else 1


if __name__ == "__main__":
    sys.exit(main())
