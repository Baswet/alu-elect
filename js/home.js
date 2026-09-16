/* ============================================================
   ALU-ELECT — HOME PAGE LIVE FIGURES
   File: js/home.js

   index.html has had #homeTurnout, #homeVotesCast, #homePositions
   and #homeProgressBar in its markup all along, hard-coded to 0,
   with nothing wired to them. A visitor arriving mid-election was
   told "0% turnout, 0 votes cast, 0 positions" while the database
   held a live election - stale zeros presented as live figures.

   This fills them from GET /api/election, which is public and
   carries no voter or ballot detail.

   If the API cannot be reached the figures read "—", never 0. An
   unknown turnout and a turnout of zero are different claims, and
   on an election site the difference matters.
   ============================================================ */

(function () {
    "use strict";

    const ALUHome = {};
    window.ALUHome = ALUHome;

    const REFRESH_MS = 30000;

    const set = function (id, value) {
        const el = document.getElementById(id);
        if (el) {
            el.textContent = value;
        }
    };

    ALUHome.state = { election: null, reachable: null };

    ALUHome.init = function () {
        if (!document.getElementById("homeTurnout")) {
            return;
        }
        ALUHome.load();
        window.setInterval(function () {
            if (ALUApp.isPageVisible()) {
                ALUHome.load();
            }
        }, REFRESH_MS);
    };

    ALUHome.load = async function () {
        try {
            const data = await ALUApp.api("/api/election");
            if (!data || !data.election) {
                ALUHome.unknown("No election has been created yet.");
                return;
            }
            ALUHome.state.election = data.election;
            ALUHome.state.reachable = true;
            ALUHome.render(data.election);
        } catch (error) {
            ALUHome.state.reachable = false;
            ALUHome.unknown("Live figures are unavailable right now.");
            if (window.console) {
                window.console.warn("[home] live figures unavailable:", error);
            }
        }
    };

    ALUHome.render = function (e) {
        const turnout = Number(e.turnout_percent) || 0;

        set("homeTurnout", turnout + "%");
        set("homeVotesCast", ALUApp.formatNumber(e.votes_cast));
        set("homePositions", ALUApp.formatNumber(e.positions));

        const status = document.getElementById("homeElectionStatus");
        if (status) {
            status.textContent = e.voting_open ? "Voting Open"
                                               : ALUHome.label(e.state);
        }

        set("homeProgressText",
            ALUApp.formatNumber(e.votes_cast) + " of " +
            ALUApp.formatNumber(e.eligible_voters) + " eligible voters");

        const bar = document.getElementById("homeProgressBar");
        if (bar) {
            /* Clamped: a bar wider than its track would read as >100%
               turnout, which cannot happen and must not be drawn. */
            bar.style.width = Math.max(0, Math.min(100, turnout)) + "%";
            bar.setAttribute("role", "progressbar");
            bar.setAttribute("aria-valuenow", String(turnout));
            bar.setAttribute("aria-valuemin", "0");
            bar.setAttribute("aria-valuemax", "100");
            bar.setAttribute("aria-label", "Turnout so far");
        }
    };

    ALUHome.unknown = function (message) {
        ["homeTurnout", "homeVotesCast", "homePositions"].forEach(function (id) {
            set(id, "—");
        });
        set("homeProgressText", message);
        const bar = document.getElementById("homeProgressBar");
        if (bar) {
            bar.style.width = "0%";
        }
    };

    ALUHome.label = function (state) {
        return String(state || "")
            .replace(/_/g, " ")
            .toLowerCase()
            .replace(/\b\w/g, function (c) { return c.toUpperCase(); });
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", ALUHome.init);
    } else {
        ALUHome.init();
    }
}());
