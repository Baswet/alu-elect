/* =========================================================
   ALU-ELECT — ELECTION / BALLOT JAVASCRIPT
   File: js/election.js
   ========================================================= */

"use strict";

window.ALU_ELECT = window.ALU_ELECT || {};

const ALUElection = {
    state: {
        positions: [],
        selections: {},
        currentPosition: 0,
        eligible: false,
        ballotLocked: false,
        submitting: false
    },

    config: {
        positionsEndpoint: "/api/election/positions",
        ballotEndpoint: "/api/election/ballot",
        receiptEndpoint: "/api/election/receipt"
    }
};

/* =========================================================
   INITIALIZATION
   ========================================================= */

document.addEventListener("DOMContentLoaded", () => {
    ALUElection.init();
});

ALUElection.init = function () {
    ALUElection.bindEvents();
    ALUElection.initializeBallot();
};

/* =========================================================
   EVENT BINDINGS
   ========================================================= */

ALUElection.bindEvents = function () {
    const submitButton =
        document.getElementById("submitVoteBtn");

    if (submitButton) {
        submitButton.addEventListener(
            "click",
            ALUElection.openConfirmation
        );
    }

    const confirmButton =
        document.getElementById("confirmVote");

    if (confirmButton) {
        confirmButton.addEventListener(
            "click",
            ALUElection.submitVote
        );
    }

    /*
     * Candidate cards may be generated dynamically,
     * so event delegation is used.
     */
    document.addEventListener(
        "click",
        (event) => {
            const candidate =
                event.target.closest(
                    "[data-candidate-id]"
                );

            if (!candidate) {
                return;
            }

            /*
             * Ignore buttons inside the card that are not
             * intended to select the candidate.
             */
            if (
                event.target.closest(
                    "[data-candidate-action]"
                )
            ) {
                return;
            }

            ALUElection.selectCandidate(
                candidate
            );
        }
    );

    /*
     * Modal close buttons.
     */
    document.querySelectorAll(
        "[data-modal-close]"
    ).forEach((button) => {
        button.addEventListener(
            "click",
            () => {
                const modal =
                    button.closest(".modal");

                if (modal) {
                    ALUApp.closeModal(
                        modal.id
                    );
                }
            }
        );
    });
};

/* =========================================================
   INITIALIZE BALLOT
   ========================================================= */

ALUElection.initializeBallot = async function () {
    try {
        ALUElection.setBallotLoading(true);

        /*
         * Backend integration will eventually provide:
         * - authenticated voter context
         * - eligibility
         * - election status
         * - positions
         * - candidates
         *
         * No ballot should be considered valid merely
         * because frontend data says the voter is eligible.
         */

        const data =
            await ALUElection.loadBallot();

        if (!data) {
            /*
             * No ballot from the server. In production that is a fault to
             * surface, never a cue to render invented candidates.
             */
            if (!ALUApp.config.developmentMode) {
                ALUElection.showBallotError();
                return;
            }
            ALUElection.loadDemoBallot();
            return;
        }

        /*
         * Map the real API payload. The server decides eligibility and
         * whether this voter has already voted; the browser only displays
         * that verdict. Field names follow GET /api/election/positions.
         */
        ALUElection.state.eligible = true;

        ALUElection.state.ballotLocked =
            Boolean(data.has_voted) ||
            (data.election && data.election.voting_open === false);

        ALUElection.state.positions =
            Array.isArray(data.positions)
                ? data.positions.map(function (p) {
                      return {
                          id: p.position_id,
                          title: p.title,
                          description: p.description || "",
                          maxSelections: p.max_selections || 1,
                          candidates: (p.candidates || []).map(
                              function (c) {
                                  return {
                                      id: c.candidate_id,
                                      name: c.name,
                                      symbol: c.symbol || "",
                                      school: c.school || "",
                                      programme: c.programme || "",
                                      year: c.year || "",
                                      manifesto: c.manifesto || "",
                                      photo: c.photo || ""
                                  };
                              }
                          )
                      };
                  })
                : [];

        ALUElection.renderBallot();

    } catch (error) {
        console.error(
            "[ALU-ELECT] Ballot initialization failed:",
            error
        );

        /*
         * Do not silently allow voting after a backend error.
         */
        ALUElection.showBallotError();

    } finally {
        ALUElection.setBallotLoading(false);
    }
};

/* =========================================================
   LOAD BALLOT FROM BACKEND
   ========================================================= */

ALUElection.loadBallot = async function () {
    /*
     * During frontend development the endpoint may not exist.
     * Once the backend is implemented this becomes the source
     * of truth.
     */

    try {
        return await ALUApp.api(
            ALUElection.config.positionsEndpoint
        );
    } catch (error) {
        /*
         * A 404 is treated as "backend not implemented yet".
         * Other errors must be treated as actual failures.
         */
        if (error.status === 404) {
            return null;
        }

        throw error;
    }
};

/* =========================================================
   DEVELOPMENT BALLOT
   ========================================================= */

ALUElection.loadDemoBallot = function () {
    /*
     * DEMO DATA ONLY.
     *
     * This must never be used as the production source
     * of candidate or voter eligibility information.
     */

    ALUElection.state.eligible = true;

    ALUElection.state.positions = [
        {
            id: "president",
            title: "Student President",
            description:
                "Choose one candidate for Student President.",
            maxSelections: 1,
            candidates: [
                {
                    id: "candidate-1",
                    name: "Candidate One",
                    symbol: "A",
                    school: "School of Computing",
                    year: "Year 3",
                    photo: ""
                },
                {
                    id: "candidate-2",
                    name: "Candidate Two",
                    symbol: "B",
                    school: "School of Business",
                    year: "Year 2",
                    photo: ""
                },
                {
                    id: "candidate-3",
                    name: "Candidate Three",
                    symbol: "C",
                    school: "School of Science",
                    year: "Year 4",
                    photo: ""
                }
            ]
        },
        {
            id: "vice-president",
            title: "Vice President",
            description:
                "Choose one candidate for Vice President.",
            maxSelections: 1,
            candidates: [
                {
                    id: "candidate-4",
                    name: "Candidate Four",
                    symbol: "D",
                    school: "School of Health",
                    year: "Year 3",
                    photo: ""
                },
                {
                    id: "candidate-5",
                    name: "Candidate Five",
                    symbol: "E",
                    school: "School of Education",
                    year: "Year 2",
                    photo: ""
                }
            ]
        }
    ];

    ALUElection.renderBallot();
};

/* =========================================================
   RENDER BALLOT
   ========================================================= */

ALUElection.renderBallot = function () {
    const container =
        document.getElementById(
            "positionsContainer"
        );

    if (!container) {
        return;
    }

    if (!ALUElection.state.eligible) {
        ALUElection.showNotEligible();
        return;
    }

    if (
        ALUElection.state.ballotLocked
    ) {
        ALUElection.showBallotLocked();
        return;
    }

    if (
        !ALUElection.state.positions.length
    ) {
        container.innerHTML = `
            <div class="empty-state">
                <h3>No ballot available</h3>
                <p>
                    There are currently no voting positions
                    available.
                </p>
            </div>
        `;

        return;
    }

    container.innerHTML =
        ALUElection.state.positions
            .map(
                (position, index) =>
                    ALUElection.renderPosition(
                        position,
                        index
                    )
            )
            .join("");

    ALUElection.updateProgress();
    ALUElection.updateReview();
};

/* =========================================================
   RENDER POSITION
   ========================================================= */

ALUElection.renderPosition = function (
    position,
    index
) {
    const candidates =
        Array.isArray(position.candidates)
            ? position.candidates
            : [];

    return `
        <section
            class="ballot-position-card"
            data-position-id="${ALUElection.escape(
                position.id
            )}"
            data-position-index="${index}">

            <div class="position-header">

                <div>
                    <span class="position-number">
                        Position ${index + 1}
                    </span>

                    <h2>
                        ${ALUElection.escape(
                            position.title
                        )}
                    </h2>

                    ${
                        position.description
                            ? `
                                <p>
                                    ${ALUElection.escape(
                                        position.description
                                    )}
                                </p>
                            `
                            : ""
                    }
                </div>

                <span class="selection-limit">
                    Select ${Number(
                        position.maxSelections || 1
                    )}
                </span>

            </div>

            <div class="candidate-selection-grid">

                ${
                    candidates.length
                        ? candidates
                              .map(
                                  (candidate) =>
                                      ALUElection.renderCandidate(
                                          candidate,
                                          position
                                      )
                              )
                              .join("")
                        : `
                            <div class="empty-state">
                                <p>
                                    No candidates are
                                    currently available.
                                </p>
                            </div>
                        `
                }

            </div>

        </section>
    `;
};

/* =========================================================
   RENDER CANDIDATE
   ========================================================= */

ALUElection.renderCandidate = function (
    candidate,
    position
) {
    const selected =
        ALUElection.isSelected(
            position.id,
            candidate.id
        );

    const photo =
        candidate.photo ||
        "assets/images/default-candidate.jpg";

    return `
        <article
            class="candidate-selection-card ${
                selected ? "selected" : ""
            }"
            data-candidate-id="${ALUElection.escape(
                candidate.id
            )}"
            data-position-id="${ALUElection.escape(
                position.id
            )}"
            tabindex="0"
            role="button"
            aria-pressed="${selected}">

            <div class="candidate-selection-check">
                ${
                    selected
                        ? "✓"
                        : ""
                }
            </div>

            <div class="candidate-photo-wrap">
                <img
                    src="${ALUElection.escape(
                        photo
                    )}"
                    alt="${ALUElection.escape(
                        candidate.name
                    )}"
                    class="candidate-photo"
                    loading="lazy"
                    onerror="this.style.display='none';"
                >
            </div>

            <div class="candidate-selection-content">

                <span class="candidate-symbol">
                    ${ALUElection.escape(
                        candidate.symbol || ""
                    )}
                </span>

                <h3>
                    ${ALUElection.escape(
                        candidate.name
                    )}
                </h3>

                ${
                    candidate.school
                        ? `
                            <p class="candidate-meta">
                                ${ALUElection.escape(
                                    candidate.school
                                )}
                            </p>
                        `
                        : ""
                }

                ${
                    candidate.year
                        ? `
                            <p class="candidate-meta">
                                ${ALUElection.escape(
                                    candidate.year
                                )}
                            </p>
                        `
                        : ""
                }

                ${
                    candidate.manifesto
                        ? `
                            <p class="candidate-manifesto">
                                ${ALUElection.escape(
                                    candidate.manifesto
                                )}
                            </p>
                        `
                        : ""
                }

            </div>

        </article>
    `;
};

/* =========================================================
   CANDIDATE SELECTION
   ========================================================= */

ALUElection.selectCandidate = function (
    candidateElement
) {
    if (
        ALUElection.state.ballotLocked ||
        ALUElection.state.submitting
    ) {
        return;
    }

    const positionId =
        candidateElement.dataset.positionId;

    const candidateId =
        candidateElement.dataset.candidateId;

    if (!positionId || !candidateId) {
        return;
    }

    const position =
        ALUElection.state.positions.find(
            (item) =>
                String(item.id) ===
                String(positionId)
        );

    if (!position) {
        return;
    }

    const maxSelections =
        Number(
            position.maxSelections || 1
        );

    let selected =
        ALUElection.state.selections[
            positionId
        ] || [];

    /*
     * Toggle selection.
     */
    if (selected.includes(candidateId)) {
        selected =
            selected.filter(
                (id) =>
                    id !== candidateId
            );
    } else {

        /*
         * For normal student positions only one
         * candidate should be selected.
         *
         * If a position allows multiple selections,
         * support up to maxSelections.
         */
        if (
            selected.length >=
            maxSelections
        ) {
            if (maxSelections === 1) {
                selected = [];
            } else {
                ALUApp.toast(
                    `You can select only ${maxSelections} candidates for this position.`,
                    "warning"
                );

                return;
            }
        }

        selected.push(candidateId);
    }

    ALUElection.state.selections[
        positionId
    ] = selected;

    ALUElection.updatePositionUI(
        positionId
    );

    ALUElection.updateProgress();
    ALUElection.updateReview();
};

/* =========================================================
   KEYBOARD SELECTION
   ========================================================= */

document.addEventListener(
    "keydown",
    (event) => {
        const candidate =
            event.target.closest(
                ".candidate-selection-card"
            );

        if (!candidate) {
            return;
        }

        if (
            event.key !== "Enter" &&
            event.key !== " "
        ) {
            return;
        }

        event.preventDefault();

        ALUElection.selectCandidate(
            candidate
        );
    }
);

/* =========================================================
   POSITION UI UPDATE
   ========================================================= */

ALUElection.updatePositionUI = function (
    positionId
) {
    const position =
        ALUElection.state.positions.find(
            (item) =>
                String(item.id) ===
                String(positionId)
        );

    if (!position) {
        return;
    }

    document
        .querySelectorAll(
            `[data-position-id="${CSS.escape(
                String(positionId)
            )}"][data-candidate-id]`
        )
        .forEach((card) => {
            const candidateId =
                card.dataset.candidateId;

            const selected =
                ALUElection.isSelected(
                    positionId,
                    candidateId
                );

            card.classList.toggle(
                "selected",
                selected
            );

            card.setAttribute(
                "aria-pressed",
                String(selected)
            );

            const indicator =
                card.querySelector(
                    ".candidate-selection-check"
                );

            if (indicator) {
                indicator.textContent =
                    selected ? "✓" : "";
            }
        });
};

/* =========================================================
   CHECK SELECTION
   ========================================================= */

ALUElection.isSelected = function (
    positionId,
    candidateId
) {
    const selected =
        ALUElection.state.selections[
            positionId
        ] || [];

    return selected.includes(
        candidateId
    );
};

/* =========================================================
   PROGRESS
   ========================================================= */

ALUElection.updateProgress = function () {
    const total =
        ALUElection.state.positions.length;

    if (!total) {
        return;
    }

    let completed = 0;

    ALUElection.state.positions.forEach(
        (position) => {
            const selected =
                ALUElection.state.selections[
                    position.id
                ] || [];

            const required =
                Number(
                    position.maxSelections || 1
                );

            if (
                selected.length >= required
            ) {
                completed++;
            }
        }
    );

    const percentage =
        Math.round(
            (completed / total) * 100
        );

    document.querySelectorAll(
        "[data-ballot-progress]"
    ).forEach((element) => {
        element.textContent =
            `${completed} of ${total}`;
    });

    document.querySelectorAll(
        "[data-ballot-progress-bar]"
    ).forEach((element) => {
        element.style.width =
            `${percentage}%`;

        element.setAttribute(
            "aria-valuenow",
            String(percentage)
        );
    });

    const submitButton =
        document.getElementById(
            "submitVoteBtn"
        );

    if (submitButton) {
        submitButton.disabled =
            completed !== total;
    };
};

/* =========================================================
   REVIEW
   ========================================================= */

ALUElection.updateReview = function () {
    const review =
        document.getElementById(
            "reviewList"
        );

    const count =
        document.getElementById(
            "reviewCount"
        );

    if (!review) {
        return;
    }

    let selectedCount = 0;

    const html =
        ALUElection.state.positions
            .map((position) => {
                const selected =
                    ALUElection.state.selections[
                        position.id
                    ] || [];

                selectedCount +=
                    selected.length;

                const names =
                    selected.map(
                        (candidateId) => {
                            const candidate =
                                position.candidates?.find(
                                    (item) =>
                                        String(
                                            item.id
                                        ) ===
                                        String(
                                            candidateId
                                        )
                                );

                            return candidate
                                ? candidate.name
                                : "Selected candidate";
                        }
                    );

                return `
                    <div class="review-item">
                        <div>
                            <strong>
                                ${ALUElection.escape(
                                    position.title
                                )}
                            </strong>

                            ${
                                names.length
                                    ? `
                                        <div class="review-selection">
                                            ${names
                                                .map(
                                                    (name) =>
                                                        `<span>${ALUElection.escape(
                                                            name
                                                        )}</span>`
                                                )
                                                .join("")}
                                        </div>
                                    `
                                    : `
                                        <span class="review-empty">
                                            Not selected
                                        </span>
                                    `
                            }
                        </div>
                    </div>
                `;
            })
            .join("");

    review.innerHTML = html;

    if (count) {
        count.textContent =
            String(selectedCount);
    }
};

/* =========================================================
   OPEN CONFIRMATION
   ========================================================= */

ALUElection.openConfirmation = function () {
    if (
        ALUElection.state.submitting ||
        ALUElection.state.ballotLocked
    ) {
        return;
    }

    if (!ALUElection.isBallotComplete()) {
        ALUApp.toast(
            "Please complete every position before submitting your ballot.",
            "warning"
        );

        return;
    }

    const list =
        document.getElementById(
            "confirmationList"
        );

    if (list) {
        list.innerHTML =
            ALUElection.buildConfirmationList();
    }

    const modal =
        document.getElementById(
            "confirmationModal"
        );

    if (modal) {
        ALUApp.openModal(
            "confirmationModal"
        );
    }
};

/* =========================================================
   CONFIRMATION LIST
   ========================================================= */

ALUElection.buildConfirmationList = function () {
    return ALUElection.state.positions
        .map((position) => {
            const selected =
                ALUElection.state.selections[
                    position.id
                ] || [];

            const names =
                selected.map(
                    (candidateId) => {
                        const candidate =
                            position.candidates?.find(
                                (item) =>
                                    String(
                                        item.id
                                    ) ===
                                    String(
                                        candidateId
                                    )
                            );

                        return candidate
                            ? candidate.name
                            : "Selected candidate";
                    }
                );

            return `
                <div class="confirmation-item">
                    <strong>
                        ${ALUElection.escape(
                            position.title
                        )}
                    </strong>

                    <span>
                        ${names
                            .map(
                                (name) =>
                                    ALUElection.escape(
                                        name
                                    )
                            )
                            .join(", ")}
                    </span>
                </div>
            `;
        })
        .join("");
};

/* =========================================================
   BALLOT COMPLETENESS
   ========================================================= */

ALUElection.isBallotComplete = function () {
    return ALUElection.state.positions.every(
        (position) => {
            const selected =
                ALUElection.state.selections[
                    position.id
                ] || [];

            const required =
                Number(
                    position.maxSelections || 1
                );

            return (
                selected.length >=
                required
            );
        }
    );
};

/* =========================================================
   SUBMIT VOTE
   ========================================================= */

ALUElection.submitVote = async function () {
    if (
        ALUElection.state.submitting ||
        ALUElection.state.ballotLocked
    ) {
        return;
    }

    if (!ALUElection.isBallotComplete()) {
        ALUApp.toast(
            "Your ballot is incomplete.",
            "warning"
        );

        return;
    }

    const confirmButton =
        document.getElementById(
            "confirmVote"
        );

    try {
        ALUElection.state.submitting =
            true;

        if (confirmButton) {
            ALUApp.setButtonLoading(
                confirmButton,
                true,
                "Securing vote..."
            );
        }

        /*
         * CRITICAL SECURITY NOTE:
         *
         * The frontend sends a voting request to the backend.
         *
         * The backend must:
         * 1. Verify authentication.
         * 2. Verify election is open.
         * 3. Verify voter eligibility.
         * 4. Verify voter has not already voted.
         * 5. Validate every selected candidate.
         * 6. Separate voter identity from ballot content.
         * 7. Encrypt/sign the ballot.
         * 8. Record the vote securely.
         * 9. Create an integrity commitment.
         * 10. Record the appropriate blockchain/audit proof.
         * 11. Generate a verification receipt.
         *
         * Never trust these frontend values by themselves.
         */

        const payload =
            ALUElection.buildVotePayload();

        let response;

        try {
            response =
                await ALUApp.api(
                    ALUElection.config.ballotEndpoint,
                    {
                        method: "POST",
                        body: payload
                    }
                );
        } catch (error) {
            /*
             * A vote is the one thing that must never be faked. In
             * production every failure propagates, so the voter is told
             * their ballot was NOT recorded rather than being shown a
             * receipt for a vote that does not exist.
             */
            if (
                error.status === 404 &&
                ALUApp.config.developmentMode
            ) {
                response =
                    ALUElection.createDemoReceipt();
            } else {
                throw error;
            }
        }

        ALUElection.state.ballotLocked =
            true;

        ALUElection.showSuccess(
            response
        );

    } catch (error) {
        console.error(
            "[ALU-ELECT] Vote submission failed:",
            error
        );

        ALUApp.handleError(
            error,
            "Your vote could not be submitted. No successful vote has been recorded."
        );

    } finally {
        ALUElection.state.submitting =
            false;

        if (confirmButton) {
            ALUApp.setButtonLoading(
                confirmButton,
                false
            );
        }
    }
};

/* =========================================================
   BUILD VOTE PAYLOAD
   ========================================================= */

ALUElection.buildVotePayload = function () {
    const selections = {};

    Object.entries(
        ALUElection.state.selections
    ).forEach(
        ([positionId, candidateIds]) => {
            selections[positionId] =
                [...candidateIds];
        }
    );

    return {
        election_id:
            document.body.dataset.electionId ||
            null,

        ballot_version:
            document.body.dataset.ballotVersion ||
            null,

        selections,

        client_timestamp:
            new Date().toISOString()
    };
};

/* =========================================================
   DEVELOPMENT RECEIPT
   ========================================================= */

ALUElection.createDemoReceipt = function () {
    const randomPart =
        Math.random()
            .toString(36)
            .substring(2, 10)
            .toUpperCase();

    return {
        success: true,
        receipt_id:
            `ALU-${Date.now()}-${randomPart}`,

        verification_reference:
            "DEMO-VERIFICATION-REFERENCE",

        timestamp:
            new Date().toISOString(),

        election:
            "ALU-ELECT Student Elections",

        proof:
            "DEMO ONLY — backend verification not connected"
    };
};

/* =========================================================
   SUCCESS
   ========================================================= */

ALUElection.showSuccess = function (
    response
) {
    const confirmationModal =
        document.getElementById(
            "confirmationModal"
        );

    if (confirmationModal) {
        ALUApp.closeModal(
            "confirmationModal"
        );
    }

    const receipt =
        response?.receipt_id ||
        response?.receipt ||
        "Pending";

    const receiptElement =
        document.getElementById(
            "receiptId"
        );

    if (receiptElement) {
        receiptElement.textContent =
            receipt;
    }

    const successModal =
        document.getElementById(
            "successModal"
        );

    if (successModal) {
        ALUApp.openModal(
            "successModal"
        );
    }

    /*
     * Prevent accidental resubmission.
     */
    const submitButton =
        document.getElementById(
            "submitVoteBtn"
        );

    if (submitButton) {
        submitButton.disabled = true;
    }

    ALUElection.lockBallotUI();
};

/* =========================================================
   LOCK BALLOT UI
   ========================================================= */

ALUElection.lockBallotUI = function () {
    document
        .querySelectorAll(
            "[data-candidate-id]"
        )
        .forEach((card) => {
            card.classList.add(
                "ballot-locked"
            );

            card.setAttribute(
                "aria-disabled",
                "true"
            );

            card.removeAttribute(
                "tabindex"
            );
        });

    document.body.classList.add(
        "ballot-submitted"
    );
};

/* =========================================================
   BALLOT LOADING
   ========================================================= */

ALUElection.setBallotLoading = function (
    loading
) {
    const container =
        document.getElementById(
            "positionsContainer"
        );

    if (!container) {
        return;
    }

    if (loading) {
        container.setAttribute(
            "aria-busy",
            "true"
        );

        container.classList.add(
            "is-loading"
        );

        return;
    }

    container.removeAttribute(
        "aria-busy"
    );

    container.classList.remove(
        "is-loading"
    );
};

/* =========================================================
   NOT ELIGIBLE
   ========================================================= */

ALUElection.showNotEligible = function () {
    const container =
        document.getElementById(
            "positionsContainer"
        );

    if (!container) {
        return;
    }

    container.innerHTML = `
        <div class="ballot-empty-state">
            <div class="empty-state-icon">
                !
            </div>

            <h2>
                You are not currently eligible to vote
            </h2>

            <p>
                Your eligibility could not be confirmed
                for this election.
            </p>

            <p>
                If you believe this is an error,
                contact the election administration team.
            </p>
        </div>
    `;

    const submit =
        document.getElementById(
            "submitVoteBtn"
        );

    if (submit) {
        submit.disabled = true;
    }
};

/* =========================================================
   BALLOT LOCKED
   ========================================================= */

ALUElection.showBallotLocked = function () {
    const container =
        document.getElementById(
            "positionsContainer"
        );

    if (!container) {
        return;
    }

    container.innerHTML = `
        <div class="ballot-empty-state">
            <div class="empty-state-icon">
                ✓
            </div>

            <h2>
                Your ballot is locked
            </h2>

            <p>
                This ballot is no longer available
                for editing.
            </p>
        </div>
    `;

    const submit =
        document.getElementById(
            "submitVoteBtn"
        );

    if (submit) {
        submit.disabled = true;
    }
};

/* =========================================================
   BACKEND ERROR
   ========================================================= */

ALUElection.showBallotError = function () {
    const container =
        document.getElementById(
            "positionsContainer"
        );

    if (!container) {
        return;
    }

    container.innerHTML = `
        <div class="ballot-error-state">
            <div class="empty-state-icon">
                !
            </div>

            <h2>
                Ballot temporarily unavailable
            </h2>

            <p>
                We could not securely load your ballot.
                Please try again.
            </p>

            <button
                type="button"
                class="btn btn-primary"
                id="retryBallotBtn">
                Try Again
            </button>
        </div>
    `;

    const retry =
        document.getElementById(
            "retryBallotBtn"
        );

    if (retry) {
        retry.addEventListener(
            "click",
            () => {
                ALUElection.initializeBallot();
            }
        );
    }
};

/* =========================================================
   HTML ESCAPING
   ========================================================= */

ALUElection.escape = function (
    value
) {
    if (
        value === null ||
        value === undefined
    ) {
        return "";
    }

    const element =
        document.createElement("div");

    element.textContent =
        String(value);

    return element.innerHTML;
};

/* =========================================================
   PREVENT DOUBLE SUBMISSION
   ========================================================= */

window.addEventListener(
    "beforeunload",
    (event) => {
        if (
            ALUElection.state.submitting
        ) {
            event.preventDefault();
            event.returnValue = "";
        }
    }
);

/* =========================================================
   FINAL MESSAGE
   ========================================================= */

console.info(
    "%cALU-ELECT ELECTION",
    "font-weight:900;font-size:16px;"
);

console.info(
    "Ballot interface initialized."
);