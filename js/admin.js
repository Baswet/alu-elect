/* ============================================================
   ALU-ELECT — ELECTION ADMINISTRATION
   File: js/admin.js

   This console talks to the real admin API. Nothing on this page is
   simulated, and there is no demo mode to fall back to: an administrator
   acting on invented numbers is worse than an administrator who is told
   the system is unreachable.

   Three things worth stating plainly, because they shape every function
   below.

   1. AUTHORISATION IS SERVER-SIDE. Hiding a button here is a courtesy.
      app/governance.py re-checks the signed-in role on every request, so
      a user who unhides a control in dev-tools still gets a 403. What
      this file must never do is pretend an action succeeded because the
      button was visible.

   2. THIS PAGE CANNOT SEE HOW ANYONE VOTED, and must never appear to.
      The voter list and the ballot store share no key. The voter table
      shows eligibility and whether a ballot was recorded - never when,
      and never what.

   3. IRREVERSIBLE ACTIONS TAKE A PASSWORD. Closing, counting, certifying,
      archiving, publishing and freezing all re-check the administrator's
      own password server-side. The authorisation field in the dialog is
      that password; it is sent for exactly those actions and never
      stored.
   ============================================================ */

(function () {
    "use strict";

    const ALUAdmin = {};
    window.ALUAdmin = ALUAdmin;

    const REFRESH_MS = 20000;

    /* Actions the server will demand a password for. Kept in step with
       REAUTH_STATES in app/admin_api.py. */
    const REAUTH_STATES = ["CLOSED", "COUNTING", "CERTIFIED", "ARCHIVED"];

    ALUAdmin.state = {
        admin: null,
        permissions: [],
        election: null,
        counts: null,
        reconciles: true,
        allowedTransitions: [],
        positions: [],
        candidates: [],
        voters: [],
        results: null,
        readiness: null,
        audit: null,
        ledger: null,
        security: [],
        pending: null,
        filters: {
            candidateSearch: "",
            candidatePosition: "all",
            candidateStatus: "all",
            auditEvent: "all"
        },
        timer: null
    };

    const $ = function (id) { return document.getElementById(id); };

    const text = function (id, value) {
        const el = $(id);
        if (el) {
            el.textContent = value === null || value === undefined || value === ""
                ? "—"
                : String(value);
        }
    };

    /* ---------------------------------------------------------
       BOOT
       --------------------------------------------------------- */

    ALUAdmin.init = function () {
        if (!document.body.classList.contains("admin-page")) {
            return;
        }
        ALUAdmin.bindLogin();
        ALUAdmin.bindNavigation();
        ALUAdmin.bindControls();
        ALUAdmin.bindConfirmation();
        ALUAdmin.bindCandidateModal();
        ALUAdmin.resume();
    };

    /*
     * Ask the server whether this browser already holds an admin session.
     * The answer comes from the server, never from anything this page
     * stored about itself.
     */
    ALUAdmin.resume = async function () {
        try {
            const me = await ALUApp.api("/api/admin/me");
            ALUAdmin.onAuthenticated(me);
        } catch (error) {
            ALUAdmin.showLogin();
        }
    };

    ALUAdmin.showLogin = function (message) {
        const screen = $("adminLoginScreen");
        const shell = $("adminShell");
        if (screen) {
            screen.hidden = false;
        }
        if (shell) {
            shell.hidden = true;
        }
        ALUAdmin.stopAutoRefresh();
        if (message) {
            ALUAdmin.loginError(message);
        }
        const email = $("adminLoginEmail");
        if (email) {
            email.focus();
        }
    };

    ALUAdmin.loginError = function (message) {
        const box = $("adminLoginError");
        if (!box) {
            return;
        }
        box.textContent = message || "";
        box.hidden = !message;
    };

    ALUAdmin.bindLogin = function () {
        const form = $("adminLoginForm");
        if (form) {
            form.addEventListener("submit", async function (event) {
                event.preventDefault();
                ALUAdmin.loginError("");

                const email = ($("adminLoginEmail").value || "").trim();
                const password = $("adminLoginPassword").value || "";
                if (!email || !password) {
                    ALUAdmin.loginError(
                        "Enter your administrator email and password.");
                    return;
                }

                const button = $("adminLoginSubmit");
                ALUApp.setButtonLoading(button, true, "Signing in…");
                try {
                    const data = await ALUApp.api("/api/admin/login", {
                        method: "POST",
                        body: { email: email, password: password }
                    });
                    $("adminLoginPassword").value = "";
                    ALUAdmin.onAuthenticated(data.admin || {});
                } catch (error) {
                    /*
                     * The server answers every failure the same way on
                     * purpose - wrong password, unknown account, locked
                     * account. Repeating its message keeps that property.
                     */
                    ALUAdmin.loginError(
                        error.status === 429
                            ? "Too many attempts from this connection. " +
                              "Wait a moment before trying again."
                            : (error.message ||
                               "Those sign-in details were not accepted."));
                } finally {
                    ALUApp.setButtonLoading(button, false);
                }
            });
        }

        const out = $("adminLogoutButton");
        if (out) {
            out.addEventListener("click", async function () {
                try {
                    await ALUApp.api("/api/admin/logout", { method: "POST" });
                } catch (error) {
                    /* Signing out locally regardless is the safe default. */
                }
                ALUAdmin.state.admin = null;
                ALUAdmin.state.permissions = [];
                ALUApp.config.csrfToken = "";
                ALUAdmin.showLogin();
            });
        }
    };

    ALUAdmin.onAuthenticated = function (admin) {
        ALUAdmin.state.admin = admin;
        ALUAdmin.state.permissions = Array.isArray(admin.permissions)
            ? admin.permissions
            : [];

        const screen = $("adminLoginScreen");
        const shell = $("adminShell");
        if (screen) {
            screen.hidden = true;
        }
        if (shell) {
            shell.hidden = false;
        }

        text("adminUserName", admin.name || admin.email || "Administrator");
        text("adminUserRole", ALUAdmin.roleLabel(admin.role));
        const avatar = document.querySelector(".admin-avatar");
        if (avatar) {
            avatar.textContent = ALUAdmin.initials(admin.name || admin.email);
        }

        ALUAdmin.applyPermissions();
        ALUAdmin.loadAll();
        ALUAdmin.startAutoRefresh();
    };

    ALUAdmin.roleLabel = function (role) {
        return String(role || "")
            .replace(/_/g, " ")
            .toLowerCase()
            .replace(/\b\w/g, function (ch) { return ch.toUpperCase(); });
    };

    ALUAdmin.initials = function (value) {
        const parts = String(value || "").replace(/@.*/, "")
            .split(/[\s._-]+/).filter(Boolean);
        if (!parts.length) {
            return "?";
        }
        return (parts.length === 1
            ? parts[0].slice(0, 2)
            : parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
    };

    ALUAdmin.can = function (permission) {
        return ALUAdmin.state.permissions.indexOf(permission) !== -1;
    };

    /*
     * Controls the signed-in role cannot use are disabled and labelled
     * rather than deleted. An operator who simply cannot find an action
     * goes looking for somebody else's login; one who can see it is not
     * theirs to use does not.
     */
    ALUAdmin.applyPermissions = function () {
        document
            .querySelectorAll("[data-requires-permission]")
            .forEach(function (el) {
                const needed = el.getAttribute("data-requires-permission");
                const allowed = ALUAdmin.can(needed);
                el.disabled = !allowed;
                el.setAttribute("aria-disabled", allowed ? "false" : "true");
                el.classList.toggle("admin-denied", !allowed);
                if (!allowed && !el.title) {
                    el.title = "Your role does not permit this action.";
                }
            });

        /* Whole sections the role has no business in. */
        const gated = {
            audit: "audit.view",
            security: "security.view",
            candidates: "candidate.manage",
            voters: "voter.manage"
        };
        Object.keys(gated).forEach(function (section) {
            const link = document.querySelector(
                '[data-admin-section="' + section + '"]');
            if (link) {
                link.hidden = !ALUAdmin.can(gated[section]);
            }
        });
    };

    /* ---------------------------------------------------------
       NAVIGATION
       --------------------------------------------------------- */

    ALUAdmin.bindNavigation = function () {
        document
            .querySelectorAll("[data-admin-section]")
            .forEach(function (link) {
                link.addEventListener("click", function (event) {
                    event.preventDefault();
                    ALUAdmin.showSection(
                        link.getAttribute("data-admin-section"));
                });
            });
        ALUAdmin.showSection("dashboard");
    };

    ALUAdmin.showSection = function (name) {
        document.querySelectorAll(".admin-section").forEach(function (s) {
            s.hidden = s.id !== name;
        });
        /* The ledger panel lives with the audit trail. */
        const blockchain = $("blockchain");
        if (blockchain) {
            blockchain.hidden = name !== "audit";
        }
        document
            .querySelectorAll("[data-admin-section]")
            .forEach(function (link) {
                const mine =
                    link.getAttribute("data-admin-section") === name;
                link.classList.toggle("active", mine);
                if (mine) {
                    link.setAttribute("aria-current", "page");
                } else {
                    link.removeAttribute("aria-current");
                }
            });
    };

    /* ---------------------------------------------------------
       LOAD EVERYTHING THIS ROLE MAY SEE
       --------------------------------------------------------- */

    ALUAdmin.loadAll = async function () {
        await ALUAdmin.loadElection();
        await Promise.all([
            ALUAdmin.loadRoster(),
            ALUAdmin.loadVoters(),
            ALUAdmin.loadResults(),
            ALUAdmin.loadAudit(),
            ALUAdmin.loadLedger(),
            ALUAdmin.loadSecurity()
        ]);
    };

    ALUAdmin.electionId = function () {
        return ALUAdmin.state.election && ALUAdmin.state.election.id;
    };

    ALUAdmin.loadElection = async function () {
        try {
            const list = await ALUApp.api("/api/admin/elections");
            const elections = list.elections || [];
            if (!elections.length) {
                ALUAdmin.state.election = null;
                ALUAdmin.showBanner(
                    "No election has been created yet.", "info");
                return;
            }
            /* Prefer the one that is live; otherwise the newest. */
            const open = elections.filter(function (e) {
                return e.state === "OPEN";
            });
            const chosen = open.length === 1 ? open[0] : elections[0];

            const summary = await ALUApp.api(
                "/api/admin/elections/" + chosen.id + "/summary");
            ALUAdmin.state.election = summary.election;
            ALUAdmin.state.counts = summary.counts;
            ALUAdmin.state.reconciles = summary.reconciles !== false;
            ALUAdmin.state.allowedTransitions =
                summary.election.allowed_transitions || [];
            ALUAdmin.renderDashboard();
            ALUAdmin.renderElectionPanel();
        } catch (error) {
            ALUAdmin.handle(error, "election summary");
        }
    };

    ALUAdmin.loadRoster = async function () {
        const id = ALUAdmin.electionId();
        if (!id || !ALUAdmin.can("results.view")) {
            return;
        }
        try {
            const data = await ALUApp.api(
                "/api/admin/elections/" + id + "/positions");
            ALUAdmin.state.positions = data.positions || [];
            ALUAdmin.state.candidates = [];
            ALUAdmin.state.positions.forEach(function (p) {
                (p.candidates || []).forEach(function (c) {
                    ALUAdmin.state.candidates.push({
                        id: c.candidate_id,
                        name: c.full_name,
                        school: c.school || "",
                        programme: c.programme || "",
                        symbol: c.symbol || "",
                        manifesto: c.manifesto || "",
                        year: c.year_of_study || "",
                        active: c.is_active !== false,
                        positionId: p.position_id,
                        positionSlug: p.slug,
                        positionTitle: p.title
                    });
                });
            });
            ALUAdmin.renderPositions();
            ALUAdmin.renderCandidates();
            ALUAdmin.fillPositionSelects();
        } catch (error) {
            ALUAdmin.handle(error, "candidate roster");
        }
    };

    ALUAdmin.loadVoters = async function () {
        const id = ALUAdmin.electionId();
        if (!id || !ALUAdmin.can("voter.manage")) {
            ALUAdmin.renderVoters();
            return;
        }
        try {
            const data = await ALUApp.api(
                "/api/admin/elections/" + id + "/voters");
            ALUAdmin.state.voters = data.voters || [];
            ALUAdmin.renderVoters();
        } catch (error) {
            ALUAdmin.handle(error, "voter roll");
            ALUAdmin.tableMessage("voterTableBody", 6,
                                  "The voter roll could not be loaded.");
        }
    };

    ALUAdmin.loadResults = async function () {
        const id = ALUAdmin.electionId();
        if (!id || !ALUAdmin.can("results.view")) {
            return;
        }
        try {
            ALUAdmin.state.results = await ALUApp.api(
                "/api/admin/elections/" + id + "/results");
        } catch (error) {
            ALUAdmin.state.results = null;
            ALUAdmin.handle(error, "results");
        }
        try {
            ALUAdmin.state.readiness = await ALUApp.api(
                "/api/admin/elections/" + id + "/readiness");
        } catch (error) {
            ALUAdmin.state.readiness = null;
        }
        ALUAdmin.renderResults();
        ALUAdmin.renderCandidates();
    };

    ALUAdmin.loadAudit = async function () {
        if (!ALUAdmin.can("audit.view")) {
            return;
        }
        try {
            ALUAdmin.state.audit = await ALUApp.api("/api/admin/audit");
            ALUAdmin.renderAudit();
        } catch (error) {
            ALUAdmin.handle(error, "audit log");
        }
    };

    ALUAdmin.loadLedger = async function () {
        if (!ALUAdmin.can("audit.view")) {
            return;
        }
        try {
            ALUAdmin.state.ledger = await ALUApp.api("/api/admin/ledger");
            ALUAdmin.renderLedger();
        } catch (error) {
            ALUAdmin.handle(error, "ledger status");
        }
    };

    ALUAdmin.loadSecurity = async function () {
        if (!ALUAdmin.can("security.view")) {
            return;
        }
        try {
            const data = await ALUApp.api("/api/admin/security");
            ALUAdmin.state.security = data.events || [];
            ALUAdmin.renderSecurity();
        } catch (error) {
            ALUAdmin.handle(error, "security events");
        }
    };

    /* ---------------------------------------------------------
       DASHBOARD
       --------------------------------------------------------- */

    ALUAdmin.renderDashboard = function () {
        const c = ALUAdmin.state.counts;
        const e = ALUAdmin.state.election;
        if (!c || !e) {
            return;
        }

        text("totalVotes", ALUApp.formatNumber(c.ballots));
        text("turnoutPercentage", c.turnout_percent + "%");
        text("turnoutCount",
             c.voted + " of " + c.eligible_voters + " eligible voters");
        text("totalPositions", c.positions);
        text("totalCandidates", c.candidates);
        text("eligibleVoters", ALUApp.formatNumber(c.eligible_voters));
        text("votersWhoVoted", ALUApp.formatNumber(c.voted));
        text("votersRemaining", ALUApp.formatNumber(c.not_voted));
        text("flaggedVoters", ALUApp.formatNumber(c.suspended_voters));

        /*
         * "Change since last refresh" is a real measured delta or it is
         * nothing. It is never a plausible-looking number.
         */
        const previous = ALUAdmin.lastBallots;
        const changeEl = $("votesChange");
        if (changeEl) {
            if (typeof previous === "number") {
                const delta = c.ballots - previous;
                changeEl.textContent = delta === 0
                    ? "No change since last refresh"
                    : (delta > 0 ? "+" : "") + delta + " since last refresh";
            } else {
                changeEl.textContent = "Baseline for this session";
            }
        }
        ALUAdmin.lastBallots = c.ballots;

        text("electionStatusBadge", ALUAdmin.stateLabel(e.state));
        text("lastSystemUpdate", ALUAdmin.now());
        text("verifiedRecords", ALUApp.formatNumber(c.ballots));

        /*
         * Ballots and voters marked as having voted are counted in two
         * tables that share no key. If they disagree, something is wrong
         * and an operator must be told, loudly, rather than shown
         * whichever number happens to be rendered first.
         */
        ALUAdmin.renderReconciliation();
    };

    ALUAdmin.renderReconciliation = function () {
        const host = $("dashboard");
        if (!host) {
            return;
        }
        let box = $("adminReconcileWarning");
        if (ALUAdmin.state.reconciles) {
            if (box) {
                box.remove();
            }
            return;
        }
        if (!box) {
            box = document.createElement("div");
            box.id = "adminReconcileWarning";
            box.className = "admin-reconcile-warning";
            box.setAttribute("role", "alert");
            const container = host.querySelector(".container") || host;
            container.insertBefore(box, container.firstChild);
        }
        const c = ALUAdmin.state.counts || {};
        box.textContent =
            "Reconciliation failed: " + c.ballots + " ballots recorded but " +
            c.voted + " voters marked as having voted. Do not certify this " +
            "election until the difference is explained.";
    };

    ALUAdmin.stateLabel = function (state) {
        return ALUAdmin.roleLabel(state);
    };

    ALUAdmin.now = function () {
        return new Date().toLocaleString("en-GB", {
            day: "2-digit", month: "short", year: "numeric",
            hour: "2-digit", minute: "2-digit"
        });
    };

    /* ---------------------------------------------------------
       ELECTION PANEL
       --------------------------------------------------------- */

    ALUAdmin.renderElectionPanel = function () {
        const e = ALUAdmin.state.election;
        if (!e) {
            return;
        }

        text("electionId", e.slug);
        text("electionState", ALUAdmin.stateLabel(e.state));
        text("electionPanelStatus", ALUAdmin.stateLabel(e.state));
        text("electionStart", e.opens_at
            ? new Date(e.opens_at).toLocaleString("en-GB")
            : "Not scheduled");
        text("electionEnd", e.closes_at
            ? new Date(e.closes_at).toLocaleString("en-GB")
            : "Not scheduled");

        const name = $("adminElectionName");
        if (name) {
            name.value = e.name || "";
        }
        const status = $("adminElectionStatus");
        if (status) {
            /*
             * The state is set by the lifecycle controls, which the server
             * validates against the allowed-transition table. A free
             * dropdown would suggest states can be jumped to arbitrarily.
             */
            status.innerHTML =
                '<option value="' + ALUApp.escapeHTML(e.state) + '">' +
                ALUApp.escapeHTML(ALUAdmin.stateLabel(e.state)) +
                "</option>";
            status.disabled = true;
            ALUAdmin.note(status,
                "Set with the lifecycle controls; the server rejects any " +
                "transition that is not allowed from the current state.");
        }

        const publicToggle = $("enablePublicResults");
        if (publicToggle) {
            publicToggle.checked = Boolean(e.results_public);
        }
        text("publicResultsStatus", e.results_frozen
            ? "Frozen by the returning officer"
            : (e.results_public ? "Published to students"
                                : "Not published"));

        ALUAdmin.updateLifecycleButtons();
    };

    ALUAdmin.note = function (el, message) {
        if (!el || !el.parentNode) {
            return;
        }
        if (el.parentNode.querySelector(".admin-permission-note")) {
            return;
        }
        const small = document.createElement("small");
        small.className = "admin-permission-note";
        small.textContent = message;
        el.parentNode.appendChild(small);
    };

    /* Which lifecycle button leads where. */
    const LIFECYCLE = {
        openElectionButton: "OPEN",
        pauseElectionButton: "PAUSED",
        closeElectionButton: "CLOSED",
        criticalPauseElection: "PAUSED",
        criticalCloseElection: "CLOSED",
        criticalCertifyElection: "CERTIFIED"
    };

    ALUAdmin.updateLifecycleButtons = function () {
        const allowed = ALUAdmin.state.allowedTransitions || [];
        Object.keys(LIFECYCLE).forEach(function (id) {
            const button = $(id);
            if (!button) {
                return;
            }
            const target = LIFECYCLE[id];
            const permitted = ALUAdmin.can("election.transition") &&
                (target !== "CERTIFIED" || ALUAdmin.can("election.certify"));
            const legal = allowed.indexOf(target) !== -1;
            const ok = permitted && legal;

            button.disabled = !ok;
            button.setAttribute("aria-disabled", ok ? "false" : "true");
            button.classList.toggle("admin-denied", !ok);
            button.title = ok
                ? ""
                : (!permitted
                    ? "Your role does not permit this action."
                    : "Not allowed from the current state (" +
                      ALUAdmin.stateLabel(
                          (ALUAdmin.state.election || {}).state) + ").");
        });

        const freeze = $("criticalFreezeResults");
        if (freeze) {
            const ok = ALUAdmin.can("results.publish");
            freeze.disabled = !ok;
            freeze.setAttribute("aria-disabled", ok ? "false" : "true");
            freeze.classList.toggle("admin-denied", !ok);
            const e = ALUAdmin.state.election || {};
            const label = freeze.querySelector("strong");
            if (label) {
                label.textContent = e.results_frozen
                    ? "Unfreeze Results"
                    : "Freeze Results";
            }
        }
    };

    ALUAdmin.bindControls = function () {
        Object.keys(LIFECYCLE).forEach(function (id) {
            const button = $(id);
            if (!button) {
                return;
            }
            button.addEventListener("click", function () {
                if (button.disabled) {
                    return;
                }
                ALUAdmin.confirm({
                    kind: "transition",
                    target: LIFECYCLE[id],
                    title: ALUAdmin.stateLabel(LIFECYCLE[id]) + " election",
                    message: ALUAdmin.transitionWarning(LIFECYCLE[id]),
                    action: "Move election to " +
                            ALUAdmin.stateLabel(LIFECYCLE[id]),
                    reauth: REAUTH_STATES.indexOf(LIFECYCLE[id]) !== -1
                });
            });
        });

        const freeze = $("criticalFreezeResults");
        if (freeze) {
            freeze.addEventListener("click", function () {
                if (freeze.disabled) {
                    return;
                }
                const e = ALUAdmin.state.election || {};
                ALUAdmin.confirm({
                    kind: "freeze",
                    frozen: !e.results_frozen,
                    title: e.results_frozen
                        ? "Unfreeze results" : "Freeze results",
                    message: e.results_frozen
                        ? "Students will be able to see live results again."
                        : "Students will stop seeing results until you " +
                          "unfreeze them. The count itself is unaffected.",
                    action: e.results_frozen
                        ? "Unfreeze published results"
                        : "Freeze published results",
                    reauth: true
                });
            });
        }

        const publicToggle = $("enablePublicResults");
        if (publicToggle) {
            publicToggle.addEventListener("change", function () {
                const wanted = publicToggle.checked;
                /* Revert until the server confirms. */
                publicToggle.checked = !wanted;
                ALUAdmin.confirm({
                    kind: "publish",
                    make_public: wanted,
                    title: wanted ? "Publish results" : "Unpublish results",
                    message: wanted
                        ? "Every student will be able to see the current " +
                          "provisional totals."
                        : "Students will no longer be able to see results.",
                    action: wanted ? "Publish results to students"
                                   : "Withdraw published results",
                    reauth: true
                });
            });
        }

        const refresh = $("refreshDashboardButton");
        if (refresh) {
            refresh.addEventListener("click", function () {
                ALUAdmin.setRefreshState(true);
                ALUAdmin.loadAll().finally(function () {
                    ALUAdmin.setRefreshState(false);
                    ALUApp.toast("Refreshed from the server.", "success");
                });
            });
        }

        const refreshVoters = $("refreshVotersButton");
        if (refreshVoters) {
            refreshVoters.addEventListener("click", function () {
                ALUAdmin.loadVoters();
            });
        }

        const settings = $("electionSettingsForm");
        if (settings) {
            settings.addEventListener("submit", function (event) {
                event.preventDefault();
                /*
                 * There is no server endpoint that renames a live election
                 * or moves its dates, and inventing a success message for
                 * a request that was never sent is exactly the failure this
                 * console must not have.
                 */
                ALUApp.toast(
                    "Election name and schedule are not editable from this " +
                    "console. Use the management CLI on the server.",
                    "info", 6000);
            });
        }

        const verify = $("runBlockchainVerification");
        if (verify) {
            verify.addEventListener("click", async function () {
                ALUApp.setButtonLoading(verify, true, "Verifying…");
                try {
                    await ALUAdmin.loadAudit();
                    await ALUAdmin.loadLedger();
                    const chain = (ALUAdmin.state.audit || {}).chain || {};
                    ALUApp.toast(
                        chain.ok
                            ? "Audit chain verified: " + chain.entries +
                              " entries, no break found."
                            : "Audit chain BROKEN at entry " +
                              chain.broken_at + ".",
                        chain.ok ? "success" : "error", 8000);
                } finally {
                    ALUApp.setButtonLoading(verify, false);
                }
            });
        }

        const copy = $("copyElectionHash");
        if (copy) {
            copy.addEventListener("click", function () {
                const code = $("electionHash");
                const value = code ? code.textContent.trim() : "";
                if (!value || value.indexOf(" ") !== -1) {
                    ALUApp.toast("There is no commitment hash to copy yet.",
                                 "info");
                    return;
                }
                navigator.clipboard.writeText(value).then(function () {
                    ALUApp.toast("Hash copied.", "success");
                }, function () {
                    ALUApp.toast("Could not copy to the clipboard.", "error");
                });
            });
        }

        const exportAudit = $("exportAuditLogButton");
        if (exportAudit) {
            exportAudit.addEventListener("click", ALUAdmin.exportAudit);
        }

        document.querySelectorAll("[data-report]").forEach(function (button) {
            button.addEventListener("click", function () {
                ALUAdmin.report(button.getAttribute("data-report"), button);
            });
        });

        const search = $("candidateAdminSearch");
        if (search) {
            search.addEventListener("input", ALUApp.debounce(function () {
                ALUAdmin.state.filters.candidateSearch =
                    search.value.trim().toLowerCase();
                ALUAdmin.renderCandidates();
            }, 160));
        }
        ["candidatePositionFilter", "candidateStatusFilter"].forEach(
            function (id) {
                const el = $(id);
                if (el) {
                    el.addEventListener("change", function () {
                        ALUAdmin.state.filters[
                            id === "candidatePositionFilter"
                                ? "candidatePosition" : "candidateStatus"
                        ] = el.value;
                        ALUAdmin.renderCandidates();
                    });
                }
            });

        const auditFilter = $("auditEventFilter");
        if (auditFilter) {
            auditFilter.addEventListener("change", function () {
                ALUAdmin.state.filters.auditEvent = auditFilter.value;
                ALUAdmin.renderAudit();
            });
        }
    };

    ALUAdmin.transitionWarning = function (target) {
        const map = {
            OPEN: "Voting will open immediately. Ballots cast from this " +
                  "moment are final.",
            PAUSED: "Ballot submissions stop. Voters who are mid-ballot " +
                    "will not be able to submit until you resume.",
            CLOSED: "Voting closes permanently for this election. This " +
                    "cannot be undone.",
            COUNTING: "The election moves to counting. Voting cannot be " +
                      "reopened.",
            CERTIFIED: "Certification makes the result official and cannot " +
                       "be undone.",
            ARCHIVED: "The election is withdrawn from publication."
        };
        return map[target] || "Confirm this change to the election state.";
    };

    ALUAdmin.setRefreshState = function (busy) {
        const button = $("refreshDashboardButton");
        if (button) {
            ALUApp.setButtonLoading(button, busy, "Refreshing…");
        }
    };

    /* ---------------------------------------------------------
       CONFIRMATION DIALOG  (with real step-up authentication)
       --------------------------------------------------------- */

    ALUAdmin.bindConfirmation = function () {
        const close = function () { ALUAdmin.closeConfirm(); };

        [$("closeAdminConfirmation"), $("cancelAdminAction")]
            .forEach(function (el) {
                if (el) {
                    el.addEventListener("click", close);
                }
            });
        document.querySelectorAll("[data-close-admin-modal]")
            .forEach(function (el) { el.addEventListener("click", close); });

        const confirm = $("confirmAdminAction");
        if (confirm) {
            confirm.addEventListener("click", ALUAdmin.runPending);
        }

        document.addEventListener("keydown", function (event) {
            const modal = $("adminConfirmationModal");
            if (event.key === "Escape" && modal && !modal.hidden) {
                close();
            }
        });
    };

    ALUAdmin.confirm = function (pending) {
        ALUAdmin.state.pending = pending;

        text("adminConfirmationTitle", pending.title);
        text("adminConfirmationMessage", pending.message);
        text("confirmationAction", pending.action);
        text("confirmationAdministrator",
             (ALUAdmin.state.admin || {}).email || "—");

        const field = $("adminConfirmationCode");
        if (field) {
            field.value = "";
            const wrapper = field.closest(".admin-authentication-field");
            if (wrapper) {
                wrapper.hidden = !pending.reauth;
            }
            const label = document.querySelector(
                'label[for="adminConfirmationCode"]');
            if (label) {
                label.textContent = "Your account password";
            }
            field.placeholder = "Re-enter your password to authorise";
        }

        const modal = $("adminConfirmationModal");
        if (modal) {
            modal.hidden = false;
            modal.setAttribute("aria-hidden", "false");
            modal.classList.add("is-open");
            document.body.classList.add("modal-open");
            window.setTimeout(function () {
                if (pending.reauth && field) {
                    field.focus();
                } else {
                    const btn = $("confirmAdminAction");
                    if (btn) {
                        btn.focus();
                    }
                }
            }, 40);
        }
    };

    ALUAdmin.closeConfirm = function () {
        const modal = $("adminConfirmationModal");
        if (modal) {
            modal.hidden = true;
            modal.setAttribute("aria-hidden", "true");
            modal.classList.remove("is-open");
        }
        document.body.classList.remove("modal-open");
        const field = $("adminConfirmationCode");
        if (field) {
            /* Never leave a password sitting in the DOM. */
            field.value = "";
        }
        ALUAdmin.state.pending = null;
    };

    ALUAdmin.runPending = async function () {
        const pending = ALUAdmin.state.pending;
        if (!pending) {
            return;
        }
        const field = $("adminConfirmationCode");
        const password = field ? field.value : "";

        if (pending.reauth && !password) {
            ALUApp.toast("Re-enter your password to authorise this action.",
                         "error");
            return;
        }

        const button = $("confirmAdminAction");
        ALUApp.setButtonLoading(button, true, "Authorising…");

        const id = ALUAdmin.electionId();
        try {
            if (pending.kind === "transition") {
                await ALUApp.api("/api/admin/elections/action", {
                    method: "POST",
                    body: {
                        election_id: id,
                        target_state: pending.target,
                        reason: pending.action,
                        password: password
                    }
                });
            } else if (pending.kind === "freeze") {
                await ALUApp.api(
                    "/api/admin/elections/" + id + "/results-visibility", {
                        method: "POST",
                        body: { frozen: pending.frozen, password: password }
                    });
            } else if (pending.kind === "publish") {
                await ALUApp.api(
                    "/api/admin/elections/" + id + "/results-visibility", {
                        method: "POST",
                        body: { public: pending.make_public,
                                password: password }
                    });
            } else if (pending.kind === "withdraw") {
                await ALUApp.api("/api/admin/candidates/" + pending.candidate, {
                    method: "PATCH",
                    body: { is_active: pending.active }
                });
            } else if (pending.kind === "eligibility") {
                await ALUApp.api("/api/admin/voters/" + pending.voter, {
                    method: "PATCH",
                    body: { is_eligible: pending.eligible,
                            reason: pending.reason || "" }
                });
            }

            if (field) {
                field.value = "";
            }
            ALUAdmin.closeConfirm();
            ALUApp.toast("Done. Recorded in the audit ledger.", "success");
            await ALUAdmin.loadAll();
        } catch (error) {
            /*
             * A failed action stays failed and stays on screen. The one
             * thing this must never do is close the dialog and report
             * success for a request the server refused.
             */
            ALUApp.toast(
                error.status === 403 && error.data &&
                error.data.code === "reauth_required"
                    ? "That password was not accepted. The action was NOT " +
                      "carried out."
                    : (error.message || "The server refused this action."),
                "error", 8000);
            if (field) {
                field.value = "";
                field.focus();
            }
        } finally {
            ALUApp.setButtonLoading(button, false);
        }
    };

    /* ---------------------------------------------------------
       POSITIONS
       --------------------------------------------------------- */

    ALUAdmin.renderPositions = function () {
        const grid = $("positionAdminGrid");
        if (!grid) {
            return;
        }
        grid.innerHTML = "";

        if (!ALUAdmin.state.positions.length) {
            const p = document.createElement("p");
            p.className = "table-empty-state";
            p.textContent = "No positions have been created for this election.";
            grid.appendChild(p);
            return;
        }

        ALUAdmin.state.positions.forEach(function (pos) {
            const active = (pos.candidates || []).filter(function (c) {
                return c.is_active !== false;
            }).length;
            const withdrawn = (pos.candidates || []).length - active;

            const card = document.createElement("div");
            card.className = "position-admin-card";

            const h = document.createElement("h4");
            h.textContent = pos.title;
            card.appendChild(h);

            const meta = document.createElement("p");
            meta.textContent = active + " candidate" +
                (active === 1 ? "" : "s") +
                (withdrawn ? " · " + withdrawn + " withdrawn" : "") +
                " · " + pos.max_selections + " to elect";
            card.appendChild(meta);

            grid.appendChild(card);
        });
    };

    ALUAdmin.fillPositionSelects = function () {
        const options = ALUAdmin.state.positions.map(function (p) {
            return '<option value="' + p.position_id + '">' +
                ALUApp.escapeHTML(p.title) + "</option>";
        }).join("");

        const modalSelect = $("candidatePosition");
        if (modalSelect) {
            modalSelect.innerHTML =
                '<option value="">Select position</option>' + options;
        }
        const filter = $("candidatePositionFilter");
        if (filter) {
            const current = filter.value || "all";
            filter.innerHTML = '<option value="all">All positions</option>' +
                ALUAdmin.state.positions.map(function (p) {
                    return '<option value="' + p.position_id + '">' +
                        ALUApp.escapeHTML(p.title) + "</option>";
                }).join("");
            filter.value = current;
        }
    };

    /* ---------------------------------------------------------
       CANDIDATES
       --------------------------------------------------------- */

    ALUAdmin.candidateVotes = function (candidateId) {
        const results = ALUAdmin.state.results;
        if (!results || !Array.isArray(results.positions)) {
            return null;
        }
        for (let i = 0; i < results.positions.length; i += 1) {
            const found = (results.positions[i].candidates || [])
                .filter(function (c) {
                    return c.candidate_id === candidateId;
                })[0];
            if (found) {
                return found.votes;
            }
        }
        return null;
    };

    ALUAdmin.renderCandidates = function () {
        const body = $("candidateTableBody");
        if (!body) {
            return;
        }
        const f = ALUAdmin.state.filters;

        const rows = ALUAdmin.state.candidates.filter(function (c) {
            if (f.candidatePosition !== "all" &&
                String(c.positionId) !== String(f.candidatePosition)) {
                return false;
            }
            if (f.candidateStatus === "active" && !c.active) {
                return false;
            }
            if (f.candidateStatus === "withdrawn" && c.active) {
                return false;
            }
            if (f.candidateSearch) {
                const hay = (c.name + " " + c.school + " " + c.programme +
                             " " + c.positionTitle).toLowerCase();
                if (hay.indexOf(f.candidateSearch) === -1) {
                    return false;
                }
            }
            return true;
        });

        body.innerHTML = "";

        if (!rows.length) {
            ALUAdmin.tableMessage("candidateTableBody", 6,
                ALUAdmin.state.candidates.length
                    ? "No candidate matches this filter."
                    : "No candidates have been nominated yet.");
            return;
        }

        const manage = ALUAdmin.can("candidate.manage");

        rows.forEach(function (c) {
            const tr = document.createElement("tr");

            tr.appendChild(ALUAdmin.cell(c.name));
            tr.appendChild(ALUAdmin.cell(c.positionTitle));
            tr.appendChild(ALUAdmin.cell(c.school || "—"));

            const status = document.createElement("td");
            const badge = document.createElement("span");
            badge.className = "admin-badge " +
                (c.active ? "badge-active" : "badge-withdrawn");
            badge.textContent = c.active ? "Standing" : "Withdrawn";
            status.appendChild(badge);
            tr.appendChild(status);

            /*
             * Votes come from the results endpoint or they are shown as
             * unavailable. A dash is honest; a zero would not be.
             */
            const votes = ALUAdmin.candidateVotes(c.id);
            tr.appendChild(ALUAdmin.cell(
                votes === null ? "—" : ALUApp.formatNumber(votes)));

            const actions = document.createElement("td");
            const button = document.createElement("button");
            button.type = "button";
            button.className = "button button-small button-secondary";
            button.textContent = c.active ? "Withdraw" : "Reinstate";
            button.disabled = !manage;
            button.setAttribute("aria-disabled", manage ? "false" : "true");
            if (!manage) {
                button.classList.add("admin-denied");
                button.title = "Your role does not permit this action.";
            }
            button.addEventListener("click", function () {
                if (button.disabled) {
                    return;
                }
                ALUAdmin.confirm({
                    kind: "withdraw",
                    candidate: c.id,
                    active: !c.active,
                    title: (c.active ? "Withdraw " : "Reinstate ") + c.name,
                    message: c.active
                        ? "This candidate stops appearing on the ballot and " +
                          "on the public candidate list. The nomination " +
                          "record is kept, not deleted, so any votes already " +
                          "cast remain explicable."
                        : "This candidate returns to the ballot and the " +
                          "public candidate list.",
                    action: (c.active ? "Withdraw" : "Reinstate") +
                            " candidate " + c.name,
                    reauth: false
                });
            });
            actions.appendChild(button);
            tr.appendChild(actions);

            body.appendChild(tr);
        });
    };

    ALUAdmin.cell = function (value) {
        const td = document.createElement("td");
        td.textContent = value === null || value === undefined || value === ""
            ? "—" : String(value);
        return td;
    };

    ALUAdmin.tableMessage = function (bodyId, cols, message) {
        const body = $(bodyId);
        if (!body) {
            return;
        }
        body.innerHTML = "";
        const tr = document.createElement("tr");
        const td = document.createElement("td");
        td.colSpan = cols;
        const div = document.createElement("div");
        div.className = "table-empty-state";
        div.textContent = message;
        td.appendChild(div);
        tr.appendChild(td);
        body.appendChild(tr);
    };

    ALUAdmin.bindCandidateModal = function () {
        const open = $("addCandidateButton");
        const modal = $("candidateModal");
        const form = $("candidateForm");

        const close = function () {
            if (modal) {
                modal.hidden = true;
                modal.setAttribute("aria-hidden", "true");
                modal.classList.remove("is-open");
            }
            document.body.classList.remove("modal-open");
        };

        if (open) {
            open.addEventListener("click", function () {
                if (!ALUAdmin.can("candidate.manage")) {
                    ALUApp.toast("Your role does not permit this action.",
                                 "error");
                    return;
                }
                if (form) {
                    form.reset();
                }
                text("candidateModalTitle", "Add Candidate");
                if (modal) {
                    modal.hidden = false;
                    modal.setAttribute("aria-hidden", "false");
                    modal.classList.add("is-open");
                    document.body.classList.add("modal-open");
                }
            });
        }

        [$("closeCandidateModal"), $("cancelCandidateButton")]
            .forEach(function (el) {
                if (el) {
                    el.addEventListener("click", close);
                }
            });
        document.querySelectorAll("[data-close-candidate-modal]")
            .forEach(function (el) { el.addEventListener("click", close); });

        if (form) {
            form.addEventListener("submit", async function (event) {
                event.preventDefault();
                const positionId = $("candidatePosition").value;
                const name = ($("candidateName").value || "").trim();
                if (!positionId || !name) {
                    ALUApp.toast("A candidate name and a position are "
                                 + "required.", "error");
                    return;
                }
                const button = form.querySelector('button[type="submit"]');
                ALUApp.setButtonLoading(button, true, "Saving…");
                try {
                    await ALUApp.api(
                        "/api/admin/positions/" + positionId + "/candidates", {
                            method: "POST",
                            body: {
                                full_name: name,
                                school: $("candidateSchool").value || "",
                                programme: $("candidateProgramme").value || "",
                                symbol: $("candidateSymbol").value || ""
                            }
                        });
                    close();
                    ALUApp.toast("Candidate added. Recorded in the audit "
                                 + "ledger.", "success");
                    await ALUAdmin.loadRoster();
                    await ALUAdmin.loadElection();
                } catch (error) {
                    ALUApp.toast(error.message ||
                                 "The candidate was not saved.", "error", 7000);
                } finally {
                    ALUApp.setButtonLoading(button, false);
                }
            });
        }
    };

    /* ---------------------------------------------------------
       VOTERS
       --------------------------------------------------------- */

    ALUAdmin.renderVoters = function () {
        const body = $("voterTableBody");
        if (!body) {
            return;
        }
        if (!ALUAdmin.can("voter.manage")) {
            ALUAdmin.tableMessage("voterTableBody", 6,
                "Your role does not permit access to the voter roll.");
            return;
        }
        const rows = ALUAdmin.state.voters;
        if (!rows.length) {
            ALUAdmin.tableMessage("voterTableBody", 6,
                                  "No voters are registered for this election.");
            return;
        }

        body.innerHTML = "";
        rows.forEach(function (v) {
            const tr = document.createElement("tr");

            /*
             * A reference, not a student number. The roll stores only a
             * peppered hash of the student number, so there is nothing here
             * that can be walked back to a person's ballot.
             */
            tr.appendChild(ALUAdmin.cell(
                v.display_name || ("Voter #" + v.id)));
            tr.appendChild(ALUAdmin.cell(v.school || "—"));

            const elig = document.createElement("td");
            const eb = document.createElement("span");
            eb.className = "admin-badge " +
                (v.eligible ? "badge-active" : "badge-suspended");
            eb.textContent = v.eligible ? "Eligible" : "Suspended";
            elig.appendChild(eb);
            tr.appendChild(elig);

            const voted = document.createElement("td");
            const vb = document.createElement("span");
            vb.className = "admin-badge " +
                (v.has_voted ? "badge-voted" : "badge-withdrawn");
            vb.textContent = v.has_voted ? "Ballot recorded" : "Not yet voted";
            voted.appendChild(vb);
            tr.appendChild(voted);

            tr.appendChild(ALUAdmin.cell(v.suspended_reason || "—"));

            const actions = document.createElement("td");
            const button = document.createElement("button");
            button.type = "button";
            button.className = "button button-small button-secondary";
            button.textContent = v.eligible ? "Suspend" : "Reinstate";
            button.addEventListener("click", function () {
                ALUAdmin.confirm({
                    kind: "eligibility",
                    voter: v.id,
                    eligible: !v.eligible,
                    reason: v.eligible ? "Suspended by administrator" : "",
                    title: (v.eligible ? "Suspend " : "Reinstate ") +
                           (v.display_name || ("voter #" + v.id)),
                    message: v.eligible
                        ? "This voter will not be able to sign in or cast a " +
                          "ballot. Any ballot already recorded is unaffected " +
                          "and cannot be withdrawn - it is not linked to them."
                        : "This voter regains the right to cast a ballot.",
                    action: (v.eligible ? "Suspend" : "Reinstate") +
                            " voter #" + v.id,
                    reauth: false
                });
            });
            actions.appendChild(button);
            tr.appendChild(actions);

            body.appendChild(tr);
        });
    };

    /* ---------------------------------------------------------
       RESULTS
       --------------------------------------------------------- */

    ALUAdmin.renderResults = function () {
        const r = ALUAdmin.state.results;

        text("lastResultsCalculation",
             r && r.generated_at
                 ? new Date(r.generated_at).toLocaleString("en-GB")
                 : "Not available");
        text("recordsProcessed",
             r && r.totals ? ALUApp.formatNumber(r.totals.ballots) : "—");

        const readiness = ALUAdmin.state.readiness;
        if (readiness) {
            const failing = (readiness.checks || []).filter(function (c) {
                return !c.ok;
            });
            text("resultsIntegrityStatus", readiness.ready
                ? "All reconciliation checks pass"
                : failing.length + " check" +
                  (failing.length === 1 ? "" : "s") + " not satisfied: " +
                  failing.map(function (c) { return c.check; }).join("; "));
        } else {
            text("resultsIntegrityStatus", "Not available");
        }
    };

    /* ---------------------------------------------------------
       AUDIT
       --------------------------------------------------------- */

    ALUAdmin.renderAudit = function () {
        const host = $("auditLog");
        if (!host) {
            return;
        }
        const data = ALUAdmin.state.audit;
        host.innerHTML = "";

        if (!data) {
            const p = document.createElement("p");
            p.className = "table-empty-state";
            p.textContent = "The audit log could not be loaded.";
            host.appendChild(p);
            return;
        }

        const chain = data.chain || {};
        const banner = document.createElement("div");
        banner.className = chain.ok
            ? "audit-chain-ok" : "admin-reconcile-warning";
        banner.textContent = chain.ok
            ? "Hash chain intact across " + chain.entries + " entries."
            : "HASH CHAIN BROKEN at entry " + chain.broken_at +
              ". The audit log has been altered.";
        host.appendChild(banner);

        const filter = ALUAdmin.state.filters.auditEvent;
        const events = (data.events || []).filter(function (e) {
            return filter === "all" || e.type === filter;
        });

        /* Build the filter list from event types actually present. */
        const select = $("auditEventFilter");
        if (select) {
            const types = [];
            (data.events || []).forEach(function (e) {
                if (types.indexOf(e.type) === -1) {
                    types.push(e.type);
                }
            });
            types.sort();
            const current = select.value || "all";
            select.innerHTML = '<option value="all">All events</option>' +
                types.map(function (t) {
                    return '<option value="' + ALUApp.escapeHTML(t) + '">' +
                        ALUApp.escapeHTML(t.replace(/_/g, " ")) + "</option>";
                }).join("");
            select.value = types.indexOf(current) === -1 ? "all" : current;
        }

        if (!events.length) {
            const p = document.createElement("p");
            p.className = "table-empty-state";
            p.textContent = "No audit entries match this filter.";
            host.appendChild(p);
            return;
        }

        events.forEach(function (e) {
            const row = document.createElement("div");
            row.className = "audit-entry";

            const head = document.createElement("div");
            head.className = "audit-entry-head";

            const seq = document.createElement("code");
            seq.textContent = "#" + e.seq;
            head.appendChild(seq);

            const type = document.createElement("strong");
            type.textContent = String(e.type).replace(/_/g, " ");
            head.appendChild(type);

            const when = document.createElement("small");
            when.textContent = new Date(e.at).toLocaleString("en-GB");
            head.appendChild(when);

            row.appendChild(head);

            const who = document.createElement("p");
            who.textContent = "Actor: " + (e.actor || "system");
            row.appendChild(who);

            if (e.payload && Object.keys(e.payload).length) {
                const pre = document.createElement("pre");
                pre.textContent = JSON.stringify(e.payload);
                row.appendChild(pre);
            }

            const hash = document.createElement("code");
            hash.className = "audit-hash";
            hash.textContent = e.entry_hash;
            row.appendChild(hash);

            host.appendChild(row);
        });
    };

    ALUAdmin.exportAudit = function () {
        const data = ALUAdmin.state.audit;
        if (!data || !(data.events || []).length) {
            ALUApp.toast("There is nothing in the audit log to export.",
                         "info");
            return;
        }
        const rows = [["seq", "at", "type", "actor", "entry_hash", "payload"]];
        data.events.forEach(function (e) {
            rows.push([e.seq, e.at, e.type, e.actor || "", e.entry_hash,
                       JSON.stringify(e.payload || {})]);
        });
        const csv = rows.map(function (r) {
            return r.map(function (v) {
                return '"' + String(v).replace(/"/g, '""') + '"';
            }).join(",");
        }).join("\r\n");

        const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "alu-elect-audit-" +
            new Date().toISOString().slice(0, 10) + ".csv";
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
        ALUApp.toast("Audit log exported.", "success");
    };

    /* ---------------------------------------------------------
       LEDGER

       This panel is the one most likely to be misread, so it says
       exactly what is and is not true. The audit trail is a
       hash-chained table in PostgreSQL: tamper-EVIDENT, because any
       edit breaks the chain, but not distributed and not a
       blockchain. Until a real network is configured, this panel
       says so rather than displaying block heights and node counts
       that would imply one exists.
       --------------------------------------------------------- */

    ALUAdmin.renderLedger = function () {
        const l = ALUAdmin.state.ledger || {};
        const connected = l.blockchain_connected === true;

        text("ledgerStatus", connected
            ? "Connected to " + (l.network || "the configured network")
            : "Local hash-chained audit ledger (no blockchain network "
              + "connected)");
        text("ledgerNetwork", connected ? (l.network || "—")
                                        : "Not connected");
        text("ledgerIntegrity", l.chain_valid === true
            ? "Chain verified"
            : (l.chain_valid === false ? "CHAIN BROKEN" : "Unknown"));

        /*
         * Block height, block time, node count and consensus state are
         * properties of a blockchain network. With no network connected
         * there is no honest value for them, so they read "not
         * applicable" instead of a number that would suggest otherwise.
         */
        const na = connected ? null : "Not applicable — no network connected";
        text("latestBlock", connected ? l.latest_block : na);
        text("latestBlockTime", connected ? l.latest_block_time : na);
        text("networkNodes", connected ? l.nodes : na);
        text("consensusStatus", connected ? l.consensus : na);

        text("blockchainHealth", connected
            ? "Connected" : "Local ledger only");
        text("verifiedRecords", ALUApp.formatNumber(l.entries || 0));

        const hash = $("electionHash");
        if (hash) {
            hash.textContent = l.head_hash ||
                "No ledger entries have been written yet.";
        }
    };

    /* ---------------------------------------------------------
       SECURITY
       --------------------------------------------------------- */

    ALUAdmin.renderSecurity = function () {
        const events = ALUAdmin.state.security || [];

        const list = $("securityAlertList");
        if (list) {
            list.innerHTML = "";
            const notable = events.filter(function (e) {
                return String(e.kind).indexOf("failed") !== -1 ||
                       String(e.kind).indexOf("blocked") !== -1 ||
                       String(e.kind).indexOf("rejected") !== -1;
            }).slice(0, 20);

            if (!notable.length) {
                const li = document.createElement("li");
                li.className = "table-empty-state";
                li.textContent = "No failed sign-ins or rejected ballots "
                    + "have been recorded.";
                list.appendChild(li);
            } else {
                notable.forEach(function (e) {
                    const li = document.createElement("li");
                    const strong = document.createElement("strong");
                    strong.textContent = String(e.kind).replace(/_/g, " ");
                    li.appendChild(strong);
                    const small = document.createElement("small");
                    small.textContent = " " + (e.detail || "") + " · " +
                        new Date(e.at).toLocaleString("en-GB");
                    li.appendChild(small);
                    list.appendChild(li);
                });
            }
        }

        const body = $("authenticationTableBody");
        if (body) {
            const auth = events.filter(function (e) {
                return String(e.kind).indexOf("login") !== -1 ||
                       String(e.kind).indexOf("reauth") !== -1;
            }).slice(0, 50);

            if (!auth.length) {
                ALUAdmin.tableMessage("authenticationTableBody", 5,
                    "No authentication events have been recorded.");
            } else {
                body.innerHTML = "";
                auth.forEach(function (e) {
                    const tr = document.createElement("tr");
                    tr.appendChild(ALUAdmin.cell(
                        new Date(e.at).toLocaleString("en-GB")));
                    tr.appendChild(ALUAdmin.cell(
                        String(e.kind).replace(/_/g, " ")));
                    tr.appendChild(ALUAdmin.cell(e.actor || "—"));
                    tr.appendChild(ALUAdmin.cell(e.ip || "—"));
                    tr.appendChild(ALUAdmin.cell(e.detail || "—"));
                    body.appendChild(tr);
                });
            }
        }

        text("securityAlerts", ALUApp.formatNumber(events.filter(function (e) {
            return String(e.kind).indexOf("failed") !== -1;
        }).length));
    };

    /* ---------------------------------------------------------
       REPORTS

       Generated in the browser from data already fetched from the
       server, so a report can never contain a figure the API did not
       produce.
       --------------------------------------------------------- */

    ALUAdmin.report = function (kind, button) {
        const s = ALUAdmin.state;
        let rows = null;
        let name = kind;

        if (kind === "summary") {
            const c = s.counts || {};
            rows = [["metric", "value"]].concat(
                Object.keys(c).map(function (k) { return [k, c[k]]; }));
        } else if (kind === "results") {
            if (!s.results) {
                ALUApp.toast("Results are not available to your role.",
                             "error");
                return;
            }
            rows = [["position", "candidate", "votes", "percentage"]];
            (s.results.positions || []).forEach(function (p) {
                (p.candidates || []).forEach(function (c) {
                    rows.push([p.title, c.name, c.votes, c.percentage]);
                });
            });
        } else if (kind === "security") {
            rows = [["at", "kind", "actor", "ip", "detail"]].concat(
                (s.security || []).map(function (e) {
                    return [e.at, e.kind, e.actor || "", e.ip || "",
                            e.detail || ""];
                }));
        } else if (kind === "audit" || kind === "archive") {
            ALUAdmin.exportAudit();
            return;
        } else if (kind === "integrity") {
            const r = s.readiness;
            if (!r) {
                ALUApp.toast("Integrity checks are not available.", "error");
                return;
            }
            rows = [["check", "passed", "detail"]].concat(
                (r.checks || []).map(function (c) {
                    return [c.check, c.ok, c.detail];
                }));
        }

        if (!rows || rows.length <= 1) {
            ALUApp.toast("There is no data for that report yet.", "info");
            return;
        }

        const csv = rows.map(function (r) {
            return r.map(function (v) {
                return '"' + String(v).replace(/"/g, '""') + '"';
            }).join(",");
        }).join("\r\n");

        const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "alu-elect-" + name + "-" +
            new Date().toISOString().slice(0, 10) + ".csv";
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
        ALUApp.toast("Report downloaded.", "success");
        if (button) {
            ALUApp.setButtonLoading(button, false);
        }
    };

    /* ---------------------------------------------------------
       REFRESH / ERRORS
       --------------------------------------------------------- */

    ALUAdmin.startAutoRefresh = function () {
        ALUAdmin.stopAutoRefresh();
        ALUAdmin.state.timer = window.setInterval(function () {
            if (!ALUApp.isPageVisible()) {
                return;
            }
            ALUAdmin.loadElection();
            ALUAdmin.loadResults();
        }, REFRESH_MS);
    };

    ALUAdmin.stopAutoRefresh = function () {
        if (ALUAdmin.state.timer) {
            window.clearInterval(ALUAdmin.state.timer);
            ALUAdmin.state.timer = null;
        }
    };

    ALUAdmin.showBanner = function (message, kind) {
        ALUApp.toast(message, kind || "info", 6000);
    };

    ALUAdmin.handle = function (error, what) {
        if (error && error.status === 401) {
            /* The session expired or was revoked. Stop showing stale data. */
            ALUAdmin.state.admin = null;
            ALUAdmin.showLogin("Your session has ended. Please sign in again.");
            return;
        }
        if (error && error.status === 403) {
            /* Expected for a role without the permission; not an error. */
            return;
        }
        if (window.console) {
            window.console.warn("[admin] " + what + " failed:", error);
        }
        ALUApp.toast("Could not load " + what + ". " +
                     (error && error.message ? error.message : ""),
                     "error", 7000);
    };

    /* ---------------------------------------------------------
       START
       --------------------------------------------------------- */

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", ALUAdmin.init);
    } else {
        ALUAdmin.init();
    }
}());
