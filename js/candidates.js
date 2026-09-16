/* ============================================================
   ALU-ELECT — CANDIDATES PAGE
   Your Vote. Your Voice. Verifiable.

   Renders the public candidate list from GET /api/election/candidates.

   Three rules this file exists to keep:

     1. Nothing on this page is invented. Every name, photo, symbol,
        school, programme and manifesto shown here came out of the API
        response. If the API is unreachable the page says so; it does not
        substitute plausible-looking people. Presenting a fabricated
        candidate to a voter would be an election offence, not a
        cosmetic bug.

     2. The candidate profile dialog starts CLOSED and opens only when a
        voter chooses a candidate to read about.

     3. Nothing here reveals or influences how anyone voted. This endpoint
        carries no vote counts and no voter identity, and the page never
        calls the ballot API.
   ============================================================ */

(function () {
    "use strict";

    const ALUCandidates = {};
    window.ALUCandidates = ALUCandidates;

    /* ---------------------------------------------------------
       STATE
       --------------------------------------------------------- */

    ALUCandidates.state = {
        loaded: false,
        loading: false,
        error: null,
        election: null,
        /* Positions exactly as the API returned them. */
        positions: [],
        /* Flattened candidate list, each carrying its position. */
        candidates: [],
        filters: {
            search: "",
            position: "all",
            school: "all"
        },
        visible: []
    };

    ALUCandidates.dom = {};

    /* ---------------------------------------------------------
       BOOT
       --------------------------------------------------------- */

    ALUCandidates.init = function () {
        if (!document.getElementById("candidateGrid")) {
            return;
        }

        ALUCandidates.cacheDom();
        ALUCandidates.bindEvents();
        ALUCandidates.closeProfile();
        ALUCandidates.load();
    };

    ALUCandidates.cacheDom = function () {
        const d = ALUCandidates.dom;

        d.grid = document.getElementById("candidateGrid");
        d.loading = document.getElementById("candidateLoadingState");
        d.empty = document.getElementById("candidateEmptyState");
        d.error = document.getElementById("candidateErrorState");
        d.errorMessage = document.getElementById("candidateErrorMessage");
        d.retry = document.getElementById("retryCandidates");
        d.count = document.getElementById("candidateCount");

        d.search = document.getElementById("candidateSearch");
        d.positionFilter = document.getElementById("positionFilter");
        d.schoolFilter = document.getElementById("schoolFilter");
        d.clearFilters = document.getElementById("clearCandidateFilters");
        d.emptyClear = document.getElementById("emptyStateClearFilters");
        d.tabs = document.getElementById("positionTabs");

        d.modal = document.getElementById("candidateProfileModal");
        d.profileTitle = document.getElementById("candidateProfileTitle");
        d.profilePhoto = document.getElementById("profileCandidatePhoto");
        d.profilePosition = document.getElementById("profileCandidatePosition");
        d.profileSchool = document.getElementById("profileCandidateSchool");
        d.profileProgramme = document.getElementById("profileCandidateProgramme");
        d.profileSymbol = document.getElementById("profileCandidateSymbol");
        d.profileBio = document.getElementById("profileCandidateBio");
        d.profileBioSection = document.getElementById("profileBioSection");
        d.profileManifesto = document.getElementById("profileCandidateManifesto");
        d.profilePriorities = document.getElementById("profileCandidatePriorities");
        d.profilePrioritiesSection =
            document.getElementById("profilePrioritiesSection");
        d.closeProfileBtn = document.getElementById("closeCandidateProfile");
    };

    ALUCandidates.bindEvents = function () {
        const d = ALUCandidates.dom;

        if (d.search) {
            const run = ALUApp.debounce(function () {
                ALUCandidates.state.filters.search =
                    d.search.value.trim().toLowerCase();
                ALUCandidates.applyFilters();
            }, 180);
            d.search.addEventListener("input", run);
        }

        if (d.positionFilter) {
            d.positionFilter.addEventListener("change", function () {
                ALUCandidates.state.filters.position = d.positionFilter.value;
                ALUCandidates.syncTabs();
                ALUCandidates.applyFilters();
            });
        }

        if (d.schoolFilter) {
            d.schoolFilter.addEventListener("change", function () {
                ALUCandidates.state.filters.school = d.schoolFilter.value;
                ALUCandidates.applyFilters();
            });
        }

        [d.clearFilters, d.emptyClear].forEach(function (button) {
            if (button) {
                button.addEventListener("click", ALUCandidates.clearFilters);
            }
        });

        if (d.retry) {
            d.retry.addEventListener("click", function () {
                ALUCandidates.load();
            });
        }

        /* Position tabs are rebuilt from the API, so delegate. */
        if (d.tabs) {
            d.tabs.addEventListener("click", function (event) {
                const tab = event.target.closest(".position-tab");
                if (!tab) {
                    return;
                }
                ALUCandidates.state.filters.position =
                    tab.getAttribute("data-position") || "all";
                if (d.positionFilter) {
                    d.positionFilter.value =
                        ALUCandidates.state.filters.position;
                }
                ALUCandidates.syncTabs();
                ALUCandidates.applyFilters();
            });
        }

        /*
         * Cards are re-rendered on every filter change, so listen on the
         * grid rather than on each card.
         */
        if (d.grid) {
            d.grid.addEventListener("click", function (event) {
                const trigger = event.target.closest("[data-candidate]");
                if (!trigger) {
                    return;
                }
                const id = trigger.getAttribute("data-candidate");
                if (id) {
                    ALUCandidates.openProfile(id);
                }
            });
        }

        if (d.closeProfileBtn) {
            d.closeProfileBtn.addEventListener("click",
                ALUCandidates.closeProfile);
        }

        document
            .querySelectorAll("[data-close-candidate-profile]")
            .forEach(function (el) {
                el.addEventListener("click", ALUCandidates.closeProfile);
            });

        document.addEventListener("keydown", function (event) {
            if (event.key === "Escape" && ALUCandidates.isProfileOpen()) {
                ALUCandidates.closeProfile();
            }
        });
    };

    /* ---------------------------------------------------------
       LOAD
       --------------------------------------------------------- */

    ALUCandidates.load = async function () {
        if (ALUCandidates.state.loading) {
            return;
        }
        ALUCandidates.state.loading = true;
        ALUCandidates.state.error = null;
        ALUCandidates.showLoading();

        try {
            const data = await ALUApp.api("/api/election/candidates", {
                method: "GET"
            });

            if (!data || !Array.isArray(data.positions)) {
                throw new Error("The candidate list was not in the expected form.");
            }

            ALUCandidates.state.election = data.election || null;
            ALUCandidates.state.positions = data.positions;
            ALUCandidates.state.candidates = ALUCandidates.flatten(data.positions);
            ALUCandidates.state.loaded = true;

            ALUCandidates.buildPositionOptions();
            ALUCandidates.buildSchoolOptions();
            ALUCandidates.applyFilters();

            /*
             * A published election with no nominations is a real, if
             * unusual, state. Say that plainly instead of pretending the
             * page is still loading.
             */
            if (!ALUCandidates.state.candidates.length) {
                ALUCandidates.showEmpty(
                    data.message ||
                    "No candidates have been published for this election yet."
                );
            }
        } catch (error) {
            ALUCandidates.state.error = error;
            ALUCandidates.showError(error);
        } finally {
            ALUCandidates.state.loading = false;
        }
    };

    ALUCandidates.flatten = function (positions) {
        const out = [];

        positions.forEach(function (p) {
            (p.candidates || []).forEach(function (c) {
                out.push({
                    id: String(c.candidate_id),
                    name: c.name || "",
                    photo: c.photo || "",
                    symbol: c.symbol || "",
                    school: c.school || "",
                    programme: c.programme || "",
                    year: c.year || "",
                    manifesto: c.manifesto || "",
                    /*
                     * Not in the API today. Read here rather than derived,
                     * so the day the server does publish them the page
                     * shows the candidate's own words, not this page's.
                     */
                    biography: c.biography || "",
                    priorities: Array.isArray(c.priorities)
                        ? c.priorities
                        : [],
                    positionId: p.position_id,
                    positionSlug: p.slug || "",
                    positionTitle: p.title || ""
                });
            });
        });

        return out;
    };

    /* ---------------------------------------------------------
       FILTER CONTROLS BUILT FROM THE DATA
       --------------------------------------------------------- */

    ALUCandidates.buildPositionOptions = function () {
        const d = ALUCandidates.dom;
        const positions = ALUCandidates.state.positions;

        if (d.positionFilter) {
            d.positionFilter.innerHTML =
                '<option value="all">All Positions</option>' +
                positions.map(function (p) {
                    return '<option value="' +
                        ALUApp.escapeHTML(p.slug) + '">' +
                        ALUApp.escapeHTML(p.title) + "</option>";
                }).join("");
            d.positionFilter.value = ALUCandidates.state.filters.position;
        }

        if (d.tabs) {
            d.tabs.innerHTML =
                '<button type="button" class="position-tab" ' +
                'data-position="all">All Candidates</button>' +
                positions.map(function (p) {
                    const n = (p.candidates || []).length;
                    return '<button type="button" class="position-tab" ' +
                        'data-position="' + ALUApp.escapeHTML(p.slug) + '">' +
                        ALUApp.escapeHTML(p.title) +
                        ' <span class="position-tab-count">' + n +
                        "</span></button>";
                }).join("");
            ALUCandidates.syncTabs();
        }
    };

    ALUCandidates.buildSchoolOptions = function () {
        const d = ALUCandidates.dom;
        if (!d.schoolFilter) {
            return;
        }

        const schools = [];
        ALUCandidates.state.candidates.forEach(function (c) {
            if (c.school && schools.indexOf(c.school) === -1) {
                schools.push(c.school);
            }
        });
        schools.sort();

        d.schoolFilter.innerHTML =
            '<option value="all">All Schools</option>' +
            schools.map(function (s) {
                return '<option value="' + ALUApp.escapeHTML(s) + '">' +
                    ALUApp.escapeHTML(s) + "</option>";
            }).join("");
        d.schoolFilter.value = ALUCandidates.state.filters.school;
    };

    ALUCandidates.syncTabs = function () {
        const d = ALUCandidates.dom;
        if (!d.tabs) {
            return;
        }
        const active = ALUCandidates.state.filters.position;
        d.tabs.querySelectorAll(".position-tab").forEach(function (tab) {
            const mine = tab.getAttribute("data-position") === active;
            tab.classList.toggle("active", mine);
            tab.setAttribute("aria-pressed", mine ? "true" : "false");
        });
    };

    ALUCandidates.clearFilters = function () {
        const d = ALUCandidates.dom;
        ALUCandidates.state.filters = {
            search: "",
            position: "all",
            school: "all"
        };
        if (d.search) {
            d.search.value = "";
        }
        if (d.positionFilter) {
            d.positionFilter.value = "all";
        }
        if (d.schoolFilter) {
            d.schoolFilter.value = "all";
        }
        ALUCandidates.syncTabs();
        ALUCandidates.applyFilters();
    };

    /* ---------------------------------------------------------
       FILTER + RENDER
       --------------------------------------------------------- */

    ALUCandidates.applyFilters = function () {
        const f = ALUCandidates.state.filters;

        ALUCandidates.state.visible =
            ALUCandidates.state.candidates.filter(function (c) {
                if (f.position !== "all" && c.positionSlug !== f.position) {
                    return false;
                }
                if (f.school !== "all" && c.school !== f.school) {
                    return false;
                }
                if (f.search) {
                    const hay = [
                        c.name, c.positionTitle, c.programme, c.school,
                        c.symbol, c.year
                    ].join(" ").toLowerCase();
                    if (hay.indexOf(f.search) === -1) {
                        return false;
                    }
                }
                return true;
            });

        ALUCandidates.render();
    };

    ALUCandidates.render = function () {
        const d = ALUCandidates.dom;
        const list = ALUCandidates.state.visible;
        const total = ALUCandidates.state.candidates.length;

        ALUCandidates.hideStates();

        /* Remove previously rendered cards; keep the state panels. */
        d.grid.querySelectorAll(".candidate-card").forEach(function (el) {
            el.remove();
        });

        if (!list.length) {
            if (!total) {
                ALUCandidates.showEmpty(
                    "No candidates have been published for this election yet."
                );
            } else {
                ALUCandidates.showEmpty(
                    "No candidate matches your search or filter."
                );
            }
            ALUCandidates.updateCount(0, total);
            return;
        }

        const frag = document.createDocumentFragment();
        list.forEach(function (c) {
            frag.appendChild(ALUCandidates.card(c));
        });

        /* Insert before the state panels so they stay at the end. */
        const first = d.grid.querySelector(
            "#candidateLoadingState, #candidateErrorState, #candidateEmptyState"
        );
        if (first) {
            d.grid.insertBefore(frag, first);
        } else {
            d.grid.appendChild(frag);
        }

        ALUCandidates.updateCount(list.length, total);
    };

    /*
     * A candidate card. Built with DOM nodes and textContent rather than an
     * innerHTML template: candidate names and manifestos are operator-
     * supplied text, and this page must not become a place where a
     * nomination form can inject script into every voter's browser.
     */
    ALUCandidates.card = function (c) {
        const article = document.createElement("article");
        article.className = "candidate-card";
        article.setAttribute("data-candidate-id", c.id);
        article.setAttribute("data-position", c.positionSlug);
        article.setAttribute("data-school", c.school);

        const imageWrap = document.createElement("div");
        imageWrap.className = "candidate-card-image";
        imageWrap.appendChild(ALUCandidates.photo(c, "candidate-photo"));

        if (c.positionTitle) {
            const badge = document.createElement("span");
            badge.className = "candidate-position-badge";
            badge.textContent = c.positionTitle;
            imageWrap.appendChild(badge);
        }
        article.appendChild(imageWrap);

        const body = document.createElement("div");
        body.className = "candidate-card-body";

        if (c.symbol) {
            const sym = document.createElement("div");
            sym.className = "candidate-symbol";
            sym.textContent = c.symbol;
            body.appendChild(sym);
        }

        const h2 = document.createElement("h2");
        h2.textContent = c.name;
        body.appendChild(h2);

        const pos = document.createElement("p");
        pos.className = "candidate-position";
        pos.textContent = c.positionTitle;
        body.appendChild(pos);

        const meta = document.createElement("div");
        meta.className = "candidate-meta";
        [c.school, c.programme, c.year].forEach(function (value) {
            if (!value) {
                return;
            }
            const span = document.createElement("span");
            span.textContent = value;
            meta.appendChild(span);
        });
        if (meta.childNodes.length) {
            body.appendChild(meta);
        }

        const manifesto = document.createElement("div");
        manifesto.className = "candidate-manifesto-preview";
        const label = document.createElement("span");
        label.textContent = "MANIFESTO";
        manifesto.appendChild(label);
        const text = document.createElement("p");
        /*
         * No manifesto is a fact about the nomination, not a blank to be
         * filled with something reassuring.
         */
        text.textContent = c.manifesto
            ? ALUCandidates.summarise(c.manifesto, 180)
            : "This candidate has not submitted a manifesto.";
        if (!c.manifesto) {
            text.className = "candidate-manifesto-absent";
        }
        manifesto.appendChild(text);
        body.appendChild(manifesto);

        const button = document.createElement("button");
        button.type = "button";
        button.className =
            "button button-secondary button-full candidate-profile-button";
        button.setAttribute("data-candidate", c.id);
        button.textContent = "View Candidate Profile";
        body.appendChild(button);

        article.appendChild(body);
        return article;
    };

    /*
     * Photo, or initials if the candidate supplied none. If a supplied
     * photo fails to load, fall back to the same initials rather than
     * leaving a broken image icon.
     */
    ALUCandidates.photo = function (c, className) {
        if (c.photo) {
            const img = document.createElement("img");
            img.className = className;
            img.src = c.photo;
            img.alt = c.name;
            img.loading = "lazy";
            img.addEventListener("error", function () {
                const fallback = ALUCandidates.initialsNode(c);
                if (img.parentNode) {
                    img.parentNode.replaceChild(fallback, img);
                }
            });
            return img;
        }
        return ALUCandidates.initialsNode(c);
    };

    ALUCandidates.initialsNode = function (c) {
        const div = document.createElement("div");
        div.className = "candidate-photo-placeholder";
        div.setAttribute("aria-hidden", "true");
        div.textContent = ALUCandidates.initials(c.name);
        return div;
    };

    ALUCandidates.initials = function (name) {
        const parts = String(name || "").trim().split(/\s+/).filter(Boolean);
        if (!parts.length) {
            return "?";
        }
        if (parts.length === 1) {
            return parts[0].slice(0, 2).toUpperCase();
        }
        return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
    };

    ALUCandidates.summarise = function (text, limit) {
        const clean = String(text).replace(/\s+/g, " ").trim();
        if (clean.length <= limit) {
            return clean;
        }
        const cut = clean.slice(0, limit);
        const stop = cut.lastIndexOf(" ");
        return (stop > 60 ? cut.slice(0, stop) : cut) + "…";
    };

    ALUCandidates.updateCount = function (shown, total) {
        const d = ALUCandidates.dom;
        if (!d.count) {
            return;
        }
        if (!total) {
            d.count.textContent = "No candidates published";
            return;
        }
        d.count.textContent = shown === total
            ? "Showing all " + total + " candidate" + (total === 1 ? "" : "s")
            : "Showing " + shown + " of " + total + " candidates";
    };

    /* ---------------------------------------------------------
       PAGE STATES
       --------------------------------------------------------- */

    ALUCandidates.hideStates = function () {
        const d = ALUCandidates.dom;
        [d.loading, d.empty, d.error].forEach(function (el) {
            if (el) {
                el.hidden = true;
            }
        });
    };

    ALUCandidates.showLoading = function () {
        const d = ALUCandidates.dom;
        ALUCandidates.hideStates();
        d.grid.querySelectorAll(".candidate-card").forEach(function (el) {
            el.remove();
        });
        if (d.loading) {
            d.loading.hidden = false;
        }
        if (d.count) {
            d.count.textContent = "Loading candidates…";
        }
    };

    ALUCandidates.showEmpty = function (message) {
        const d = ALUCandidates.dom;
        ALUCandidates.hideStates();
        if (!d.empty) {
            return;
        }
        const p = d.empty.querySelector("p");
        if (p && message) {
            p.textContent = message;
        }
        /* Nothing to clear if no filter is set. */
        if (d.emptyClear) {
            const f = ALUCandidates.state.filters;
            d.emptyClear.hidden =
                f.search === "" && f.position === "all" && f.school === "all";
        }
        d.empty.hidden = false;
    };

    ALUCandidates.showError = function (error) {
        const d = ALUCandidates.dom;
        ALUCandidates.hideStates();
        d.grid.querySelectorAll(".candidate-card").forEach(function (el) {
            el.remove();
        });

        let message = "The candidate list could not be loaded. " +
            "Please try again in a moment.";
        if (error && error.status === 403) {
            message = "The candidate list has not been published for this " +
                "election yet.";
        } else if (error && error.status === 429) {
            message = "Too many requests from this connection. " +
                "Please wait a moment and try again.";
        } else if (error && error.data && error.data.error) {
            message = String(error.data.error);
        }

        if (d.errorMessage) {
            d.errorMessage.textContent = message;
        }
        if (d.error) {
            d.error.hidden = false;
        }
        if (d.count) {
            d.count.textContent = "Candidates unavailable";
        }
        /* Console, not a fabricated card. */
        if (window.console && error) {
            window.console.warn("[candidates] load failed:", error);
        }
    };

    /* ---------------------------------------------------------
       PROFILE DIALOG
       --------------------------------------------------------- */

    ALUCandidates.isProfileOpen = function () {
        const modal = ALUCandidates.dom.modal;
        return Boolean(modal) && modal.getAttribute("aria-hidden") === "false";
    };

    ALUCandidates.find = function (id) {
        const wanted = String(id);
        return ALUCandidates.state.candidates.filter(function (c) {
            return c.id === wanted;
        })[0] || null;
    };

    ALUCandidates.openProfile = function (id) {
        const d = ALUCandidates.dom;
        const c = ALUCandidates.find(id);

        /*
         * Only ever open on a candidate that is actually in the loaded
         * data. An unknown id means something is out of step; showing the
         * previous candidate's details under a new name would be worse
         * than showing nothing.
         */
        if (!c || !d.modal) {
            return;
        }

        ALUCandidates.lastTrigger = document.activeElement;

        d.profileTitle.textContent = c.name;
        d.profilePosition.textContent = c.positionTitle || "—";
        d.profileSchool.textContent = c.school || "School not stated";
        d.profileProgramme.textContent =
            [c.programme, c.year].filter(Boolean).join(" · ") ||
            "Programme not stated";
        d.profileSymbol.textContent = c.symbol || "No symbol assigned";

        /* Photo. */
        if (d.profilePhoto && d.profilePhoto.parentNode) {
            const node = ALUCandidates.photo(c, "candidate-photo");
            node.id = "profileCandidatePhoto";
            d.profilePhoto.parentNode.replaceChild(node, d.profilePhoto);
            d.profilePhoto = node;
        }

        /*
         * The nomination record carries ONE free-text field. There is no
         * separate biography and no separate list of priorities, so those
         * two sections stay hidden rather than being filled by rewording
         * or re-cutting the manifesto. A page that paraphrases a candidate
         * and presents the result under their name is putting words in
         * their mouth, however harmless the wording looks.
         *
         * If the API later grows real `biography` and `priorities` fields,
         * populate them here; until then, absent stays absent.
         */
        if (d.profileBioSection) {
            const bio = c.biography || "";
            d.profileBio.textContent = bio;
            d.profileBioSection.hidden = !bio;
        }

        if (d.profilePrioritiesSection) {
            const priorities = Array.isArray(c.priorities) ? c.priorities : [];
            d.profilePriorities.innerHTML = "";
            priorities.forEach(function (item) {
                const li = document.createElement("li");
                li.textContent = item;
                d.profilePriorities.appendChild(li);
            });
            d.profilePrioritiesSection.hidden = !priorities.length;
        }

        d.profileManifesto.innerHTML = "";
        if (c.manifesto) {
            ALUCandidates.paragraphs(c.manifesto).forEach(function (para) {
                const p = document.createElement("p");
                p.textContent = para;
                d.profileManifesto.appendChild(p);
            });
        } else {
            const p = document.createElement("p");
            p.className = "candidate-manifesto-absent";
            p.textContent = "No manifesto was submitted.";
            d.profileManifesto.appendChild(p);
        }

        d.modal.hidden = false;
        ALUApp.openModal("candidateProfileModal");
    };

    ALUCandidates.closeProfile = function () {
        const d = ALUCandidates.dom;
        if (!d.modal) {
            return;
        }
        ALUApp.closeModal("candidateProfileModal");
        d.modal.hidden = true;

        if (ALUCandidates.lastTrigger &&
            typeof ALUCandidates.lastTrigger.focus === "function") {
            ALUCandidates.lastTrigger.focus();
            ALUCandidates.lastTrigger = null;
        }
    };

    ALUCandidates.paragraphs = function (text) {
        return String(text)
            .split(/\n{2,}/)
            .map(function (s) { return s.replace(/\s+/g, " ").trim(); })
            .filter(Boolean);
    };

    /* ---------------------------------------------------------
       START
       --------------------------------------------------------- */

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", ALUCandidates.init);
    } else {
        ALUCandidates.init();
    }
}());
