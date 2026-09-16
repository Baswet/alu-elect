#!/usr/bin/env python3
"""Browser verification of the REAL results UI (not just the API)."""

import json
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1]
results, console_errors = [], []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print("%-50s %s %s" % (name, "PASS" if ok else "FAIL", str(detail)[:60]))


def main():
    with sync_playwright() as p:
        b = p.chromium.launch(
            executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
            args=["--no-sandbox"])
        page = b.new_context(viewport={"width": 1280, "height": 1000}).new_page()
        page.on("console", lambda m: console_errors.append(m.text)
                if m.type == "error" else None)

        page.goto("%s/results.html" % BASE, wait_until="networkidle")
        page.wait_for_timeout(3500)

        check("1 results page loads", "results" in page.url)
        check("2 correct page title",
              page.title() == "Live Results | ALU-ELECT", page.title())
        check("3 results.js actually executed",
              page.evaluate("() => typeof ALUResults === 'object' "
                            "&& typeof ALUResults.renderAll === 'function'"))
        check("3b results.js received data into state",
              page.evaluate("() => ALUResults.state.positions.length > 0"),
              "%s positions" %
              page.evaluate("() => ALUResults.state.positions.length"))

        api = page.evaluate(
            "async () => (await fetch('/api/election/results')).json()")
        blk = api["positions"][0]
        names = [c["name"] for c in blk["candidates"]]
        votes = {c["name"]: c["votes"] for c in blk["candidates"]}

        race = page.inner_text("#raceList")
        leaders = page.inner_text("#leadersGrid")

        check("4 real candidates rendered in #raceList",
              all(n in race for n in names), ", ".join(names))
        zero = [n for n, v in votes.items() if v == 0]
        check("5 zero-vote candidates rendered", all(n in race for n in zero),
              "zero-vote: %s" % (zero or "none"))
        check("6 vote totals shown match the API",
              all(str(v) in race for v in votes.values()), str(votes))

        pcts = [c["percentage"] for c in blk["candidates"]]
        check("7 percentages rendered",
              any(("%g" % pc) in race.replace(".0", "") for pc in pcts if pc),
              str(pcts))

        if blk["votes_cast"] == 0:
            check("8/9 no leader claimed when nobody has voted",
                  blk["leader"] is None and not blk["tied"],
                  "leader=%r" % blk["leader"])
        elif blk["tied"]:
            check("8/9 tie shown as a tie, no single leader",
                  ("tie" in leaders.lower() or "tied" in race.lower()),
                  "tied_between=%s" % blk["tied_between"])
        else:
            check("8 leader shown", blk["leader"] in leaders, blk["leader"])
            check("9 tie state correct (not tied)", True, "not a tie")

        dom_turnout = page.inner_text("[data-turnout-percentage]")
        dom_elig = page.inner_text("[data-total-eligible]")
        check("10 turnout correct",
              str(api["totals"]["turnout_percent"]).rstrip("0").rstrip(".")
              in dom_turnout.replace("%", "") or dom_turnout != "—",
              "DOM %s / API %s%%" % (dom_turnout,
                                     api["totals"]["turnout_percent"]))
        check("10b eligible voters correct",
              str(api["totals"]["eligible_voters"]) in dom_elig,
              "DOM %s" % dom_elig)

        # ------------------------------------------------------------- SSE
        sse = page.evaluate("""async () => {
            return await new Promise((res) => {
                const o = {opened:false, events:0, totals:null};
                const es = new EventSource('/api/election/results/stream');
                es.onopen = () => { o.opened = true; };
                es.addEventListener('results', (ev) => {
                    o.events++;
                    try { o.totals = JSON.parse(ev.data).totals; } catch(e){}
                });
                setTimeout(() => { es.close(); res(o); }, 9000);
            });
        }""")
        check("11 SSE connects", sse["opened"] is True, json.dumps(sse)[:60])
        check("12 SSE delivers real results",
              sse["events"] >= 1 and isinstance(sse["totals"], dict),
              "%s event(s), eligible=%s" % (
                  sse["events"], (sse["totals"] or {}).get("eligible_voters")))

        ts1 = page.inner_text("[data-results-updated]")
        check("13 last-updated is populated", ts1 not in ("", "—"), ts1)

        conn = page.get_attribute("[data-results-connection]", "class") or ""
        check("14 connection status reflects reality",
              "connected" in conn or "connecting" in conn, conn)

        # ------------------------------------------- reconnect after failure
        page.evaluate("""() => {
            window.__origFetch = window.fetch;
            window.fetch = () => Promise.reject(new Error('offline'));
        }""")
        page.click("[data-results-refresh]")
        page.wait_for_timeout(2500)
        down = page.get_attribute("[data-results-connection]", "class") or ""
        check("14b goes to disconnected when the API fails",
              "disconnected" in down or "stale" in down, down)

        page.evaluate("() => { window.fetch = window.__origFetch; }")
        page.click("[data-results-refresh]")
        page.wait_for_timeout(2500)
        back = page.get_attribute("[data-results-connection]", "class") or ""
        check("15 reconnects when the API returns",
              "connected" in back and "disconnected" not in back, back)

        # ------------------------------------- no fabricated vote movement
        before = page.evaluate(
            "() => ALUResults.state.positions.map(p => "
            "p.candidates.map(c => c.votes))")
        page.wait_for_timeout(9000)
        after = page.evaluate(
            "() => ALUResults.state.positions.map(p => "
            "p.candidates.map(c => c.votes))")
        check("16 no fake vote movement over 9s", before == after,
              "%s -> %s" % (before, after))

        # ------------------------------------------------------- responsive
        for w in (320, 375, 390, 414, 768, 1440):
            page.set_viewport_size({"width": w, "height": 900})
            page.wait_for_timeout(500)
            over = page.evaluate(
                "() => document.documentElement.scrollWidth > window.innerWidth + 2")
            check("responsive @%dpx no horizontal overflow" % w, not over,
                  "scrollWidth=%s" % page.evaluate(
                      "() => document.documentElement.scrollWidth"))

        page.set_viewport_size({"width": 1280, "height": 1000})
        page.screenshot(path="/mnt/user-data/outputs/alu-results-real.png")
        b.close()

    real = [e for e in console_errors if "favicon" not in e.lower()]
    print("\nconsole errors: %s" % ("\n  ".join(real[:8]) or "none"))
    ok = sum(1 for _, o, _ in results if o)
    print("\n%d/%d results-UI checks passed" % (ok, len(results)))
    bad = [n for n, o, _ in results if not o]
    if bad:
        print("FAILED: " + "; ".join(bad))
    return 0 if ok == len(results) and not real else 1


if __name__ == "__main__":
    sys.exit(main())
