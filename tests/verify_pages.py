#!/usr/bin/env python3
"""
Whole-site layout check for ALU-ELECT after the styling pass.

Asserts, for every page at every phone/tablet/desktop width, that the
page does not scroll sideways, that nothing renders as an unstyled
block, that no element spills past the viewport, and that no dialog is
open on load. Also re-checks that the pages still boot their JS.
"""

import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1]
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

PAGES = ["index.html", "election.html", "candidates.html", "results.html",
         "verify.html", "how-it-works.html", "admin.html"]
WIDTHS = [320, 375, 390, 414, 768, 1024, 1440]

results, console_errors = [], []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    if not ok:
        print("%-58s FAIL %s" % (name, str(detail)[:60]))


def main():
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        ctx = b.new_context(viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        page.on("console", lambda m: console_errors.append(m.text)
                if m.type == "error" else None)

        for name in PAGES:
            page.goto("%s/%s" % (BASE, name), wait_until="networkidle")
            page.wait_for_timeout(900)

            check("%s loads with a title" % name,
                  page.title() and "404" not in page.title(), page.title())

            # Stylesheets must all have actually parsed.
            sheets = page.evaluate(
                """() => Array.from(document.styleSheets).map(s => {
                    try { return [s.href, s.cssRules.length]; }
                    catch (e) { return [s.href, -1]; } })""")
            check("%s every stylesheet parsed" % name,
                  all(n > 0 for _, n in sheets),
                  str([(h or "")[-18:] + ":" + str(n) for h, n in sheets]))

            # No dialog may be open on arrival.
            openm = page.evaluate(
                """() => Array.from(document.querySelectorAll(
                     '.modal, .admin-modal'))
                   .filter(m => m.offsetParent !== null)
                   .map(m => m.id || '(unnamed)')""")
            check("%s no dialog open on load" % name, not openm, str(openm))

            for w in WIDTHS:
                page.set_viewport_size({"width": w, "height": 900})
                page.wait_for_timeout(280)

                over = page.evaluate(
                    "() => document.documentElement.scrollWidth "
                    "> window.innerWidth + 2")
                check("%s @%d no sideways scroll" % (name, w), not over,
                      "scrollWidth=%s" % page.evaluate(
                          "() => document.documentElement.scrollWidth"))

                # Nothing visible may stick out past the right edge,
                # except inside something that is meant to scroll.
                spill = page.evaluate(
                    """() => Array.from(document.querySelectorAll('body *'))
                        .filter(el => {
                            if (el.offsetParent === null) return false;
                            if (el.closest('.admin-nav-container,'
                                + '.admin-table-wrapper,.position-navigation,'
                                + '[style*="overflow"]')) return false;
                            const cs = getComputedStyle(el);
                            if (cs.overflowX === 'auto'
                                || cs.overflowX === 'scroll') return false;
                            return el.getBoundingClientRect().right
                                   > window.innerWidth + 2;
                        })
                        .slice(0, 3)
                        .map(el => el.tagName + '.'
                             + String(el.className).slice(0, 34))""")
                check("%s @%d nothing spills past the edge" % (name, w),
                      not spill, str(spill))

            page.set_viewport_size({"width": 1280, "height": 900})

        # Screenshots of the pages that changed most.
        for name, w in (("index.html", 1280), ("election.html", 1280),
                        ("verify.html", 1280), ("how-it-works.html", 1280),
                        ("index.html", 390)):
            page.set_viewport_size({"width": w, "height": 1000})
            page.goto("%s/%s" % (BASE, name), wait_until="networkidle")
            page.wait_for_timeout(700)
            page.screenshot(path="/mnt/user-data/outputs/alu-%s-%d.png"
                            % (name.replace(".html", ""), w))
        b.close()

    real = [e for e in console_errors
            if "favicon" not in e.lower() and "401" not in e
            and "Sign in to continue" not in e]
    print("\nconsole errors: %s" % ("\n  ".join(real[:8]) or "none"))
    ok = sum(1 for _, o, _ in results if o)
    print("%d/%d site layout checks passed" % (ok, len(results)))
    return 0 if ok == len(results) and not real else 1


if __name__ == "__main__":
    sys.exit(main())
