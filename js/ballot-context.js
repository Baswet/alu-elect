/* ============================================================
   ALU-ELECT — BALLOT PAGE CONTEXT PANELS
   File: js/ballot-context.js

   election.html carries a voting-deadline card, a voter-context
   panel and a ballot-completion figure whose elements nothing ever
   wrote to. #votingDeadline and #voterSchool sat on the word
   "Loading..." for the whole life of the page, and
   #selectionPercentage sat on "0%".

   That is worse than leaving them blank. On the page where someone
   casts a vote, a permanent "Loading..." invites them to wait for
   information that is never coming, and a hard-coded 0% is a claim
   about their own ballot that happens to be a coincidence.

   This module is DISPLAY ONLY and deliberately separate from
   js/election.js. It reads:

       GET /api/election      - public: state and closing time
       GET /api/election/me   - the signed-in voter's own school
                                and whether they have voted

   It never touches the ballot, the selections or the submission.
   Nothing here can change what is cast.

   Where a fact does not exist - no closing time scheduled, nobody
   signed in - it says so plainly rather than counting down to a
   date that was never set.
   ============================================================ */

(function () {
    "use strict";

    const ALUBallotContext = {};
    window.ALUBallotContext = ALUBallotContext;

    const TICK_MS = 30000;

    const set = function (id, value) {
        const el = document.getElementById(id);
        if (el) {
            el.textContent = value;
        }
        return el;
    };

    ALUBallotContext.state = { closesAt: null };

    ALUBallotContext.init = function () {
        if (!document.getElementById("votingDeadline")) {
            return;
        }
        ALUBallotContext.loadElection();
        ALUBallotContext.loadVoter();
        ALUBallotContext.watchSelections();

        window.setInterval(function () {
            if (ALUApp.isPageVisible()) {
                ALUBallotContext.renderDeadline();
            }
        }, TICK_MS);
    };

    /* ----------------------------------------------- deadline */

    ALUBallotContext.loadElection = async function () {
        try {
            const data = await ALUApp.api("/api/election");
            const e = data && data.election;
            if (!e) {
                set("votingDeadline", "No election");
                set("countdownText", "No election has been created yet.");
                return;
            }
            ALUBallotContext.state.closesAt = e.closes_at || null;
            ALUBallotContext.state.state = e.state;
            ALUBallotContext.renderDeadline();
        } catch (error) {
            set("votingDeadline", "Unavailable");
            set("countdownText",
                "The closing time could not be loaded right now.");
        }
    };

    ALUBallotContext.renderDeadline = function () {
        const closes = ALUBallotContext.state.closesAt;

        if (!closes) {
            /*
             * A returning officer may run an election open-ended and
             * close it by hand. Saying so is honest; counting down to
             * a date nobody set is not.
             */
            set("votingDeadline", "Closes by announcement");
            set("countdownText",
                "No closing time has been scheduled. Voting stays open " +
                "until the returning officer closes it.");
            return;
        }

        const end = new Date(closes);
        if (isNaN(end.getTime())) {
            set("votingDeadline", "Unavailable");
            set("countdownText", "The closing time could not be read.");
            return;
        }

        set("votingDeadline", end.toLocaleString("en-GB", {
            day: "2-digit", month: "short", year: "numeric",
            hour: "2-digit", minute: "2-digit"
        }));

        const ms = end.getTime() - Date.now();
        if (ms <= 0) {
            set("countdownText", "Voting has closed.");
            return;
        }
        const mins = Math.floor(ms / 60000);
        const days = Math.floor(mins / 1440);
        const hours = Math.floor((mins % 1440) / 60);
        const rem = mins % 60;

        set("countdownText",
            (days ? days + (days === 1 ? " day " : " days ") : "") +
            (days || hours ? hours + (hours === 1 ? " hour " : " hours ") : "") +
            rem + (rem === 1 ? " minute" : " minutes") + " remaining");
    };

    /* -------------------------------------------------- voter */

    ALUBallotContext.loadVoter = async function () {
        try {
            const me = await ALUApp.api("/api/election/me");
            set("voterSchool", me.school || "Not recorded");
            const status = document.getElementById("voterStatus");
            if (status) {
                status.textContent = me.has_voted
                    ? "Ballot recorded"
                    : (me.eligible ? "Eligible to vote" : "Not eligible");
            }
        } catch (error) {
            /*
             * 401 here is the ordinary case: nobody has signed in yet.
             * It is not an error to report, but it must not be left
             * reading "Loading...".
             */
            set("voterSchool", "Sign in to view");
            const status = document.getElementById("voterStatus");
            if (status) {
                status.textContent = "Not signed in";
            }
        }
    };

    /* --------------------------------------- ballot completion */

    ALUBallotContext.watchSelections = function () {
        const pct = document.getElementById("selectionPercentage");
        const prog = document.getElementById("selectionProgress");
        if (!pct && !prog) {
            return;
        }

        const update = function () {
            /*
             * Counted from the DOM the voter is actually looking at, so
             * this figure can never disagree with the ballot in front
             * of them.
             */
            const container = document.getElementById("positionsContainer");
            if (!container) {
                return;
            }
            /*
             * The ballot is not built from radio inputs - js/election.js
             * renders each candidate as a button carrying
             * data-candidate-id and aria-pressed, inside a card carrying
             * data-position-id. Counting aria-pressed is therefore
             * counting exactly what the voter can see is selected.
             */
            /* [data-position-index] is on the position CARD only. [data-position-id]
             * is also on every candidate button inside it, which counted
             * 17 "positions" for a 5-position ballot. */
            const cards = container.querySelectorAll("[data-position-index]");
            const total = cards.length;
            let done = 0;
            cards.forEach(function (card) {
                if (card.querySelector('[data-candidate-id][aria-pressed="true"],'
                                       + " [data-candidate-id].selected")) {
                    done += 1;
                }
            });

            if (prog) {
                prog.textContent = total
                    ? done + " of " + total + " positions selected"
                    : "Ballot not loaded";
            }
            if (pct) {
                pct.textContent = total
                    ? Math.round(done * 100 / total) + "%"
                    : "—";
            }
        };

        update();
        document.addEventListener("change", function (event) {
            if (event.target && event.target.closest &&
                event.target.closest("#positionsContainer")) {
                update();
            }
        });
        /* The ballot arrives asynchronously; recount when it lands. */
        const container = document.getElementById("positionsContainer");
        if (container && window.MutationObserver) {
            new MutationObserver(update)
                .observe(container, { childList: true, subtree: true });
        }
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", ALUBallotContext.init);
    } else {
        ALUBallotContext.init();
    }
}());
