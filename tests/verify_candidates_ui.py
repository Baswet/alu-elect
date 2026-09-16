#!/usr/bin/env python3
"""
Browser verification of the ALU-ELECT candidates page against the real API.

Everything asserted here is compared against what GET /api/election/candidates
actually returned out of PostgreSQL, so a page that renders convincing but
invented people fails rather than passes.
"""

import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1]
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

results, console_errors, failed_req = [], [], []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print("%-56s %s %s" % (name, "PASS" if ok else "FAIL", str(detail)[:70]))


def main():
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        page = b.new_context(viewport={"width": 1280, "height": 1000}).new_page()
        page.on("console", lambda m: console_errors.append(m.text)
                if m.type == "error" else None)
        page.on("requestfailed",
                lambda r: failed_req.append("%s %s" % (r.method, r.url)))

        page.goto("%s/candidates.html" % BASE, wait_until="networkidle")
        page.wait_for_timeout(1200)

        # ------------------------------------------------- ground truth
        api = page.evaluate(
            "async () => (await fetch('/api/election/candidates')).json()")
        flat = [dict(c, _pos=pos["title"], _slug=pos["slug"])
                for pos in api["positions"] for c in pos["candidates"]]
        names = [c["name"] for c in flat]

        check("1 page title", page.title() == "Candidates | ALU-ELECT",
              page.title())
        check("2 candidates.js executed",
              page.evaluate("() => typeof ALUCandidates === 'object'"))
        check("3 state loaded from the API",
              page.evaluate("() => ALUCandidates.state.loaded === true"))

        # ----------------------------------------- MODAL CLOSED ON LOAD
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(1200)
        vis = page.is_visible("#candidateProfileModal")
        check("4 profile modal is NOT visible on page load", not vis,
              "visible=%s" % vis)
        check("4b modal marked aria-hidden on load",
              page.get_attribute("#candidateProfileModal", "aria-hidden")
              == "true")
        check("4c no modal backdrop covering the page on load",
              not page.evaluate(
                  "() => { const o=document.querySelector("
                  "'#candidateProfileModal .modal-overlay');"
                  " if(!o) return false; const r=o.getBoundingClientRect();"
                  " return r.width>0 && r.height>0; }"))
        # The other pages share the same modal CSS.
        page.goto("%s/election.html" % BASE, wait_until="networkidle")
        page.wait_for_timeout(600)
        check("4d election.html success modal also closed on load",
              not page.is_visible("#successModal") and
              not page.is_visible("#confirmationModal"))
        page.goto("%s/candidates.html" % BASE, wait_until="networkidle")
        page.wait_for_timeout(1200)

        # -------------------------------------------------- real data
        cards = page.query_selector_all("#candidateGrid .candidate-card")
        check("5 one card per active candidate",
              len(cards) == len(flat), "%d cards / %d in API" %
              (len(cards), len(flat)))

        grid = page.inner_text("#candidateGrid")
        check("6 every real name rendered",
              all(n in grid for n in names), ", ".join(names[:4]) + " ...")

        dom_ids = page.evaluate(
            "() => Array.from(document.querySelectorAll("
            "'#candidateGrid .candidate-card')).map("
            "e => e.getAttribute('data-candidate-id'))")
        api_ids = [str(c["candidate_id"]) for c in flat]
        check("7 real candidate ids on the cards",
              sorted(dom_ids) == sorted(api_ids),
              "dom=%s" % dom_ids[:5])

        check("8 positions rendered on cards",
              all(c["_pos"] in grid for c in flat),
              ", ".join(sorted({c["_pos"] for c in flat})))

        # ------------------------------------------ no placeholder text
        for bad in ("Candidate Name", "Contesting Position",
                    "Candidate manifesto information will appear here",
                    "Candidate biography will appear here",
                    "Candidate priority", "Loading candidates..."):
            check("9 no placeholder %r on the page" % bad[:26],
                  bad not in page.inner_text("body"))

        # ---------------------------------------------- withdrawn hidden
        check("10 withdrawn candidate absent from API",
              not any("withdrawn" in n.lower() for n in names))
        check("10b withdrawn candidate absent from the page",
              "withdrawn" not in page.inner_text("body").lower())

        # ------------------------------------------------------- photos
        with_photo = [c for c in flat if c.get("photo")]
        no_photo = [c for c in flat if not c.get("photo")]
        loaded = page.evaluate(
            "() => Array.from(document.querySelectorAll("
            "'#candidateGrid img.candidate-photo')).filter("
            "i => i.complete && i.naturalWidth > 0).length")
        check("11 photos load for candidates that have one",
              loaded == len(with_photo),
              "%d loaded / %d expected" % (loaded, len(with_photo)))
        ph = page.evaluate(
            "() => document.querySelectorAll('#candidateGrid "
            ".candidate-photo-placeholder').length")
        check("11b initials placeholder for candidates without a photo",
              ph == len(no_photo), "%d placeholders / %d expected"
              % (ph, len(no_photo)))

        # ---------------------------------------------------- manifesto
        m = [c for c in flat if c.get("manifesto")][0]
        check("12 manifesto text rendered on the card",
              m["manifesto"][:50] in grid, m["name"])

        # ------------------------------------------------------ counter
        check("13 result counter reports the real total",
              str(len(flat)) in page.inner_text("#candidateCount"),
              page.inner_text("#candidateCount"))

        # ------------------------------------------------- filters real
        tabs = page.evaluate(
            "() => Array.from(document.querySelectorAll("
            "'#positionTabs .position-tab')).map(e => "
            "e.getAttribute('data-position'))")
        check("14 position tabs built from the API",
              sorted(tabs) == sorted(["all"] + [p["slug"]
                                                for p in api["positions"]]),
              str(tabs))

        target = api["positions"][1]
        page.click("#positionTabs [data-position='%s']" % target["slug"])
        page.wait_for_timeout(400)
        shown = page.query_selector_all("#candidateGrid .candidate-card")
        check("15 position tab filters to that race",
              len(shown) == len(target["candidates"]),
              "%s -> %d cards / %d expected" %
              (target["slug"], len(shown), len(target["candidates"])))
        check("15b filtered grid shows only that race's candidates",
              all(c["name"] in page.inner_text("#candidateGrid")
                  for c in target["candidates"]))

        page.click("#clearCandidateFilters")
        page.wait_for_timeout(300)
        check("16 clear filters restores everything",
              len(page.query_selector_all(
                  "#candidateGrid .candidate-card")) == len(flat))

        school = flat[0]["school"]
        page.select_option("#schoolFilter", school)
        page.wait_for_timeout(400)
        expect = len([c for c in flat if c["school"] == school])
        check("17 school filter uses real schools",
              len(page.query_selector_all(
                  "#candidateGrid .candidate-card")) == expect,
              "%s -> %d expected" % (school, expect))
        page.click("#clearCandidateFilters")
        page.wait_for_timeout(300)

        # -------------------------------------------------------- search
        page.fill("#candidateSearch", flat[0]["name"].split()[0])
        page.wait_for_timeout(500)
        n_found = len(page.query_selector_all("#candidateGrid .candidate-card"))
        check("18 search finds a real candidate", n_found >= 1,
              "%d result(s)" % n_found)

        # ---------------------------------------------------- empty state
        page.fill("#candidateSearch", "zzzz-no-such-candidate-zzzz")
        page.wait_for_timeout(500)
        check("19 empty state appears when nothing matches",
              page.is_visible("#candidateEmptyState") and
              len(page.query_selector_all(
                  "#candidateGrid .candidate-card")) == 0)
        page.click("#emptyStateClearFilters")
        page.wait_for_timeout(400)
        check("19b empty state clears back to the full list",
              not page.is_visible("#candidateEmptyState") and
              len(page.query_selector_all(
                  "#candidateGrid .candidate-card")) == len(flat))

        # -------------------------------------------------- modal opens
        first = flat[0]
        page.click("[data-candidate='%s']" % first["candidate_id"])
        page.wait_for_timeout(500)
        check("20 modal opens on selecting a candidate",
              page.is_visible("#candidateProfileModal"))
        check("20b modal shows THAT candidate's real name",
              page.inner_text("#candidateProfileTitle") == first["name"],
              page.inner_text("#candidateProfileTitle"))
        modal_text = page.inner_text("#candidateProfileModal")
        check("20c modal shows the real position",
              first["_pos"] in modal_text)
        check("20d modal shows the real school and programme",
              first["school"] in modal_text and
              first["programme"] in modal_text)
        check("20e modal shows the real symbol",
              (first["symbol"] or "") in modal_text, first["symbol"])
        check("20f modal shows the real manifesto",
              first["manifesto"][:60] in modal_text.replace("\n", " "))
        check("20g no invented biography section",
              page.evaluate("() => document.getElementById("
                            "'profileBioSection').hidden === true"))
        check("20h no invented priorities section",
              page.evaluate("() => document.getElementById("
                            "'profilePrioritiesSection').hidden === true"))
        check("20i manifesto is not restated as fake priorities",
              modal_text.count(first["manifesto"].split(".")[0][:40]) == 1,
              "occurrences=%d" % modal_text.count(
                  first["manifesto"].split(".")[0][:40]))

        page.click("#closeCandidateProfile")
        page.wait_for_timeout(400)
        check("21 modal closes again",
              not page.is_visible("#candidateProfileModal"))

        # A candidate with no photo must open with initials, not the
        # previous candidate's picture.
        if no_photo:
            page.click("[data-candidate='%s']" % no_photo[0]["candidate_id"])
            page.wait_for_timeout(400)
            check("22 no-photo candidate opens with initials, not a "
                  "stale photo",
                  page.evaluate(
                      "() => !!document.querySelector("
                      "'.candidate-profile-photo .candidate-photo-placeholder')"
                      " && !document.querySelector("
                      "'.candidate-profile-photo img')"))
            check("22b that candidate's own name is shown",
                  page.inner_text("#candidateProfileTitle")
                  == no_photo[0]["name"])
            page.keyboard.press("Escape")
            page.wait_for_timeout(400)
            check("22c Escape closes the modal",
                  not page.is_visible("#candidateProfileModal"))

        # -------------------------------------------------- error state
        page.evaluate("""() => {
            window.__f = window.fetch;
            window.fetch = () => Promise.reject(new Error('offline'));
        }""")
        page.evaluate("() => ALUCandidates.load()")
        page.wait_for_timeout(1200)
        check("23 error state shown when the API is unreachable",
              page.is_visible("#candidateErrorState"))
        check("23b no candidate cards invented during the failure",
              len(page.query_selector_all(
                  "#candidateGrid .candidate-card")) == 0)
        body = page.inner_text("body")
        check("23c no fabricated names during the failure",
              not any(n in body for n in names))

        page.evaluate("() => { window.fetch = window.__f; }")
        page.click("#retryCandidates")
        page.wait_for_timeout(1500)
        check("24 retry recovers the real list",
              not page.is_visible("#candidateErrorState") and
              len(page.query_selector_all(
                  "#candidateGrid .candidate-card")) == len(flat))

        # ------------------------------------------------------- XSS
        check("25 candidate text is escaped, no injected markup",
              page.evaluate(
                  "() => !document.querySelector("
                  "'#candidateGrid script, #candidateGrid iframe')"))

        # -------------------------------------------------- responsive
        for w in (320, 375, 390, 414, 768, 1024, 1440):
            page.set_viewport_size({"width": w, "height": 900})
            page.wait_for_timeout(350)
            over = page.evaluate(
                "() => document.documentElement.scrollWidth "
                "> window.innerWidth + 2")
            check("responsive @%dpx no horizontal overflow" % w, not over,
                  "scrollWidth=%s" % page.evaluate(
                      "() => document.documentElement.scrollWidth"))

        page.set_viewport_size({"width": 1280, "height": 1100})
        page.wait_for_timeout(400)
        page.screenshot(path="/mnt/user-data/outputs/alu-candidates.png",
                        full_page=False)
        page.click("[data-candidate='%s']" % flat[0]["candidate_id"])
        page.wait_for_timeout(600)
        page.screenshot(path="/mnt/user-data/outputs/alu-candidate-modal.png")
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(400)
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
        page.screenshot(path="/mnt/user-data/outputs/alu-candidates-mobile.png")
        b.close()

    real = [e for e in console_errors if "favicon" not in e.lower()]
    badreq = [r for r in failed_req if "favicon" not in r.lower()]
    print("\nconsole errors: %s" % ("\n  ".join(real[:8]) or "none"))
    print("failed requests: %s" % ("\n  ".join(badreq[:8]) or "none"))
    ok = sum(1 for _, o, _ in results if o)
    print("\n%d/%d candidate-UI checks passed" % (ok, len(results)))
    bad = [n for n, o, _ in results if not o]
    if bad:
        print("FAILED: " + "; ".join(bad))
    return 0 if ok == len(results) and not real and not badreq else 1


if __name__ == "__main__":
    sys.exit(main())
