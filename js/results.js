/* =========================================================
   ALU-ELECT — LIVE RESULTS JAVASCRIPT
   File: js/results.js
   ========================================================= */

"use strict";

window.ALU_ELECT = window.ALU_ELECT || {};

const ALUResults = {
    state: {
        election: null,
        positions: [],
        totalVotes: 0,
        totalEligibleVoters: 0,
        totalVotersWhoVoted: 0,
        lastUpdated: null,
        connection: "connecting",
        filter: "all",
        refreshTimer: null,
        isLoading: false
    },

    config: {
        resultsEndpoint: "/api/election/results",
        trendEndpoint: "/api/election/results/trend",
        refreshInterval: 10000
    }
};

/* =========================================================
   INITIALIZATION
   ========================================================= */

document.addEventListener("DOMContentLoaded", () => {
    ALUResults.init();
});

ALUResults.init = function () {
    ALUResults.bindControls();
    ALUResults.initialize();
};

/* =========================================================
   INITIALIZE RESULTS
   ========================================================= */

ALUResults.initialize = async function () {
    ALUResults.setConnection("connecting");

    try {
        const data =
            await ALUResults.loadResults();

        if (data) {
            ALUResults.applyResults(data);
        } else if (ALUApp.config.developmentMode) {
            ALUResults.loadDemoResults();
        } else {
            /*
             * Published results with no data are zeroes, not invented
             * numbers. An empty election must look empty.
             */
            ALUResults.state.positions = [];
            ALUResults.setConnection("disconnected");
        }

        ALUResults.renderAll();
        ALUResults.startAutoRefresh();

    } catch (error) {
        console.error(
            "[ALU-ELECT RESULTS]",
            error
        );

        ALUResults.setConnection(
            "disconnected"
        );

        ALUResults.showError();
    }
};

/* =========================================================
   LOAD RESULTS
   ========================================================= */

ALUResults.loadResults = async function () {
    try {
        return await ALUApp.api(
            ALUResults.config.resultsEndpoint
        );
    } catch (error) {
        /*
         * Development fallback only when backend
         * endpoint does not yet exist.
         */
        if (error.status === 404) {
            return null;
        }

        throw error;
    }
};

/* =========================================================
   DEVELOPMENT DATA
   ========================================================= */

ALUResults.loadDemoResults = function () {
    const now =
        new Date();

    ALUResults.state.election = {
        id: "alu-election-2026",
        name: "ALU Student Elections 2026",
        status: "live",
        provisional: true
    };

    ALUResults.state.positions = [
        {
            id: "president",
            title: "Student President",
            candidates: [
                {
                    id: "candidate-1",
                    name: "Candidate One",
                    symbol: "A",
                    school: "School of Computing",
                    votes: 1240
                },
                {
                    id: "candidate-2",
                    name: "Candidate Two",
                    symbol: "B",
                    school: "School of Business",
                    votes: 1032
                },
                {
                    id: "candidate-3",
                    name: "Candidate Three",
                    symbol: "C",
                    school: "School of Science",
                    votes: 718
                }
            ]
        },
        {
            id: "vice-president",
            title: "Vice President",
            candidates: [
                {
                    id: "candidate-4",
                    name: "Candidate Four",
                    symbol: "D",
                    school: "School of Health",
                    votes: 1510
                },
                {
                    id: "candidate-5",
                    name: "Candidate Five",
                    symbol: "E",
                    school: "School of Education",
                    votes: 1187
                }
            ]
        },
        {
            id: "secretary-general",
            title: "Secretary General",
            candidates: [
                {
                    id: "candidate-6",
                    name: "Candidate Six",
                    symbol: "F",
                    school: "School of Computing",
                    votes: 982
                },
                {
                    id: "candidate-7",
                    name: "Candidate Seven",
                    symbol: "G",
                    school: "School of Business",
                    votes: 921
                }
            ]
        }
    ];

    ALUResults.state.totalEligibleVoters =
        5000;

    ALUResults.state.totalVotersWhoVoted =
        2990;

    ALUResults.state.totalVotes =
        ALUResults.calculateTotalVotes();

    ALUResults.state.lastUpdated =
        now;

    ALUResults.setConnection("connected");
};

/* =========================================================
   APPLY BACKEND RESULTS
   ========================================================= */

ALUResults.applyResults = function (
    data
) {
    /*
     * Normalise the real API payload (GET /api/election/results).
     *
     * The server nests counters under `totals` and names a position
     * `position_id`; the render functions here expect flat counters and
     * `position.id`. Mapping in one place keeps the verified API contract
     * unchanged and leaves every renderer untouched.
     */
    const totals = data.totals || {};

    ALUResults.state.election =
        data.election || null;

    ALUResults.state.positions =
        Array.isArray(data.positions)
            ? data.positions.map(function (p) {
                  return {
                      id: p.position_id !== undefined
                          ? p.position_id
                          : p.id,
                      slug: p.slug,
                      title: p.title,
                      votesCast: p.votes_cast || 0,
                      leader: p.leader || null,
                      tied: Boolean(p.tied),
                      tiedBetween: p.tied_between || [],
                      lead: p.lead || 0,
                      candidates: (p.candidates || []).map(
                          function (c) {
                              return {
                                  id: c.candidate_id,
                                  name: c.name,
                                  school: c.school || "",
                                  symbol: c.symbol || "",
                                  photo: c.photo || "",
                                  votes: Number(c.votes || 0),
                                  percentage: Number(c.percentage || 0),
                                  rank: c.rank
                              };
                          }
                      )
                  };
              })
            : [];

    ALUResults.state.totalVotes =
        Number(
            totals.ballots !== undefined
                ? totals.ballots
                : (data.total_votes ||
                   data.totalVotes ||
                   ALUResults.calculateTotalVotes())
        );

    ALUResults.state.totalEligibleVoters =
        Number(
            totals.eligible_voters !== undefined
                ? totals.eligible_voters
                : (data.total_eligible_voters ||
                   data.totalEligibleVoters ||
                   0)
        );

    ALUResults.state.totalVotersWhoVoted =
        Number(
            totals.voted !== undefined
                ? totals.voted
                : (data.total_voters_who_voted ||
                   data.totalVotersWhoVoted ||
                   0)
        );

    ALUResults.state.lastUpdated =
        data.generated_at
            ? new Date(data.generated_at)
            : (data.last_updated
                ? new Date(data.last_updated)
                : new Date());

    ALUResults.setConnection(
        "connected"
    );
};

/* =========================================================
   CALCULATE TOTAL VOTES
   ========================================================= */

ALUResults.calculateTotalVotes = function () {
    return ALUResults.state.positions.reduce(
        (total, position) => {
            const candidates =
                Array.isArray(
                    position.candidates
                )
                    ? position.candidates
                    : [];

            return (
                total +
                candidates.reduce(
                    (sum, candidate) =>
                        sum +
                        Number(
                            candidate.votes || 0
                        ),
                    0
                )
            );
        },
        0
    );
};

/* =========================================================
   BIND CONTROLS
   ========================================================= */

ALUResults.bindControls = function () {
    const filter =
        document.getElementById(
            "raceFilter"
        );

    if (filter) {
        filter.addEventListener(
            "change",
            () => {
                ALUResults.state.filter =
                    filter.value || "all";

                ALUResults.renderRaceTracker();
            }
        );
    }

    document.querySelectorAll(
        "[data-results-refresh]"
    ).forEach((button) => {
        button.addEventListener(
            "click",
            () => {
                ALUResults.refresh(button);
            }
        );
    });

    document.querySelectorAll(
        "[data-results-auto-refresh]"
    ).forEach((control) => {
        control.addEventListener(
            "change",
            () => {
                if (control.checked) {
                    ALUResults.startAutoRefresh();
                } else {
                    ALUResults.stopAutoRefresh();
                }
            }
        );
    });
};

/* =========================================================
   RENDER EVERYTHING
   ========================================================= */

ALUResults.renderAll = function () {
    ALUResults.renderOverview();
    ALUResults.renderLeaders();
    ALUResults.renderRaceTracker();
    ALUResults.renderTrend();
    ALUResults.renderSchoolTurnout();
    ALUResults.renderVerification();
    ALUResults.renderCertification();
    ALUResults.updateTimestamp();
};

/* =========================================================
   OVERVIEW STATISTICS
   ========================================================= */

ALUResults.renderOverview = function () {
    const totalVotes =
        ALUResults.state.totalVotes;

    const voters =
        ALUResults.state.totalVotersWhoVoted;

    const eligible =
        ALUResults.state.totalEligibleVoters;

    const turnout =
        eligible > 0
            ? (voters / eligible) * 100
            : 0;

    ALUResults.setText(
        "[data-total-votes]",
        ALUResults.formatNumber(totalVotes)
    );

    ALUResults.setText(
        "[data-total-voters]",
        ALUResults.formatNumber(voters)
    );

    ALUResults.setText(
        "[data-total-eligible]",
        ALUResults.formatNumber(eligible)
    );

    ALUResults.setText(
        "[data-turnout-percentage]",
        ALUResults.formatPercentage(
            turnout
        )
    );

    ALUResults.setText(
        "[data-position-count]",
        ALUResults.state.positions.length
    );

    const candidateCount =
        ALUResults.state.positions.reduce(
            (total, position) =>
                total +
                (position.candidates?.length || 0),
            0
        );

    ALUResults.setText(
        "[data-candidate-count]",
        candidateCount
    );
};

/* =========================================================
   CURRENT LEADERS
   ========================================================= */

ALUResults.renderLeaders = function () {
    const container =
        document.getElementById(
            "leadersGrid"
        );

    if (!container) {
        return;
    }

    container.innerHTML =
        ALUResults.state.positions
            .map((position) => {
                const candidates =
                    ALUResults.sortCandidates(
                        position.candidates
                    );

                const leader =
                    candidates[0];

                if (!leader) {
                    return `
                        <article class="leader-card">
                            <h3>
                                ${ALUResults.escape(
                                    position.title
                                )}
                            </h3>
                            <p>No votes recorded yet.</p>
                        </article>
                    `;
                }

                const total =
                    ALUResults.sumCandidateVotes(
                        candidates
                    );

                const percentage =
                    total > 0
                        ? (leader.votes / total) *
                          100
                        : 0;

                const second =
                    candidates[1];

                const lead =
                    second
                        ? leader.votes -
                          second.votes
                        : leader.votes;

                return `
                    <article class="leader-card">

                        <div class="leader-card-header">
                            <span class="leader-position">
                                ${ALUResults.escape(
                                    position.title
                                )}
                            </span>

                            <span class="leader-badge">
                                CURRENT LEADER
                            </span>
                        </div>

                        <div class="leader-main">

                            <div class="leader-symbol">
                                ${ALUResults.escape(
                                    leader.symbol || ""
                                )}
                            </div>

                            <div>
                                <h3>
                                    ${ALUResults.escape(
                                        leader.name
                                    )}
                                </h3>

                                <p>
                                    ${ALUResults.escape(
                                        leader.school || ""
                                    )}
                                </p>
                            </div>

                        </div>

                        <div class="leader-stat-grid">

                            <div>
                                <strong>
                                    ${ALUResults.formatNumber(
                                        leader.votes
                                    )}
                                </strong>
                                <span>Votes</span>
                            </div>

                            <div>
                                <strong>
                                    ${ALUResults.formatPercentage(
                                        percentage
                                    )}
                                </strong>
                                <span>Share</span>
                            </div>

                            <div>
                                <strong>
                                    +${ALUResults.formatNumber(
                                        lead
                                    )}
                                </strong>
                                <span>Lead</span>
                            </div>

                        </div>

                    </article>
                `;
            })
            .join("");
};

/* =========================================================
   RACE TRACKER
   ========================================================= */

ALUResults.renderRaceTracker = function () {
    const container =
        document.getElementById(
            "raceList"
        );

    if (!container) {
        return;
    }

    let positions =
        ALUResults.state.positions;

    if (
        ALUResults.state.filter !== "all"
    ) {
        positions =
            positions.filter(
                (position) =>
                    String(position.id) ===
                    String(
                        ALUResults.state.filter
                    )
            );
    }

    if (!positions.length) {
        container.innerHTML = `
            <div class="results-empty-state">
                <h3>No race selected</h3>
                <p>
                    Choose a position to view its
                    live results.
                </p>
            </div>
        `;

        return;
    }

    container.innerHTML =
        positions
            .map(
                (position) =>
                    ALUResults.renderRace(
                        position
                    )
            )
            .join("");
};

/* =========================================================
   RENDER INDIVIDUAL RACE
   ========================================================= */

ALUResults.renderRace = function (
    position
) {
    const candidates =
        ALUResults.sortCandidates(
            position.candidates
        );

    const total =
        ALUResults.sumCandidateVotes(
            candidates
        );

    const leader =
        candidates[0];

    return `
        <section
            class="race-card"
            data-race-id="${ALUResults.escape(
                position.id
            )}">

            <div class="race-header">

                <div>
                    <span class="race-label">
                        LIVE RACE
                    </span>

                    <h2>
                        ${ALUResults.escape(
                            position.title
                        )}
                    </h2>
                </div>

                ${
                    leader
                        ? `
                            <div class="race-leader-summary">
                                <span>
                                    Current Leader
                                </span>
                                <strong>
                                    ${ALUResults.escape(
                                        leader.name
                                    )}
                                </strong>
                            </div>
                        `
                        : ""
                }

            </div>

            <div class="race-candidates">

                ${candidates
                    .map(
                        (
                            candidate,
                            index
                        ) =>
                            ALUResults.renderCandidateResult(
                                candidate,
                                index,
                                total
                            )
                    )
                    .join("")}

            </div>

            <div class="race-footer">
                <span>
                    ${ALUResults.formatNumber(
                        total
                    )}
                    total votes
                </span>

                <span>
                    ${
                        leader
                            ? `Leading by ${ALUResults.formatNumber(
                                  ALUResults.getLead(
                                      candidates
                                  )
                              )}`
                            : "No current leader"
                    }
                </span>
            </div>

        </section>
    `;
};

/* =========================================================
   CANDIDATE RESULT ROW
   ========================================================= */

ALUResults.renderCandidateResult =
    function (
        candidate,
        index,
        total
    ) {
        const percentage =
            total > 0
                ? (Number(candidate.votes) /
                      total) *
                  100
                : 0;

        const isLeader =
            index === 0 &&
            Number(candidate.votes) > 0;

        return `
            <article
                class="result-candidate-row ${
                    isLeader
                        ? "is-leader"
                        : ""
                }">

                <div class="result-rank">
                    #${index + 1}
                </div>

                <div class="result-candidate-symbol">
                    ${ALUResults.escape(
                        candidate.symbol || ""
                    )}
                </div>

                <div class="result-candidate-info">

                    <div class="result-candidate-top">

                        <div>
                            <strong>
                                ${ALUResults.escape(
                                    candidate.name
                                )}
                            </strong>

                            ${
                                candidate.school
                                    ? `
                                        <span>
                                            ${ALUResults.escape(
                                                candidate.school
                                            )}
                                        </span>
                                    `
                                    : ""
                            }
                        </div>

                        ${
                            isLeader
                                ? `
                                    <span class="current-leader-label">
                                        CURRENT LEADER
                                    </span>
                                `
                                : ""
                        }

                    </div>

                    <div class="vote-bar">

                        <div
                            class="vote-bar-track"
                            role="progressbar"
                            aria-valuemin="0"
                            aria-valuemax="100"
                            aria-valuenow="${percentage.toFixed(
                                1
                            )}">

                            <div
                                class="vote-bar-fill"
                                style="width:${percentage.toFixed(
                                    1
                                )}%">
                            </div>

                        </div>

                    </div>

                </div>

                <div class="result-vote-count">

                    <strong>
                        ${ALUResults.formatNumber(
                            candidate.votes
                        )}
                    </strong>

                    <span>
                        ${ALUResults.formatPercentage(
                            percentage
                        )}
                    </span>

                </div>

            </article>
        `;
    };

/* =========================================================
   VOTE TREND
   ========================================================= */

ALUResults.renderTrend = async function () {
    const chart =
        document.getElementById(
            "voteTrendChart"
        );

    if (!chart) {
        return;
    }

    /*
     * If Chart.js or another chart library is later
     * included, this function can feed it the backend data.
     *
     * For now we create an accessible lightweight chart
     * without adding a third-party dependency.
     */

    let trendData = null;

    try {
        trendData =
            await ALUApp.api(
                ALUResults.config.trendEndpoint
            );
    } catch (error) {
        if (error.status !== 404) {
            console.warn(
                "Trend endpoint unavailable:",
                error
            );
        }
    }

    if (
        !trendData ||
        !Array.isArray(
            trendData.points
        )
    ) {
        trendData =
            ALUResults.createDemoTrend();
    }

    chart.innerHTML =
        ALUResults.buildTrendChart(
            trendData.points
        );
};

/* =========================================================
   DEMO TREND
   ========================================================= */

ALUResults.createDemoTrend = function () {
    const points = [];

    let value = 100;

    for (let i = 0; i < 8; i++) {
        value +=
            Math.floor(
                Math.random() * 450
            );

        points.push({
            label: `${i + 1}`,
            value
        });
    }

    return {
        points
    };
};

/* =========================================================
   BUILD LIGHTWEIGHT TREND CHART
   ========================================================= */

ALUResults.buildTrendChart = function (
    points
) {
    if (!points.length) {
        return `
            <div class="chart-empty">
                No voting activity available yet.
            </div>
        `;
    }

    const max =
        Math.max(
            ...points.map(
                (point) =>
                    Number(point.value) || 0
            )
        );

    const bars =
        points
            .map((point) => {
                const value =
                    Number(point.value) || 0;

                const height =
                    max > 0
                        ? (value / max) *
                          100
                        : 0;

                return `
                    <div class="trend-column">

                        <div
                            class="trend-bar"
                            style="height:${height}%"
                            title="${ALUResults.escape(
                                String(
                                    point.value
                                )
                            )} votes">
                        </div>

                        <span>
                            ${ALUResults.escape(
                                point.label
                            )}
                        </span>

                    </div>
                `;
            })
            .join("");

    return `
        <div
            class="trend-chart"
            role="img"
            aria-label="Voting activity trend">

            <div class="trend-bars">
                ${bars}
            </div>

        </div>
    `;
};

/* =========================================================
   SCHOOL TURNOUT
   ========================================================= */

ALUResults.renderSchoolTurnout = function () {
    const container =
        document.getElementById(
            "schoolTurnoutGrid"
        );

    if (!container) {
        return;
    }

    const schools = [
        {
            name: "School of Computing",
            voted: 620,
            eligible: 900
        },
        {
            name: "School of Business",
            voted: 510,
            eligible: 780
        },
        {
            name: "School of Science",
            voted: 420,
            eligible: 720
        },
        {
            name: "School of Health",
            voted: 380,
            eligible: 610
        },
        {
            name: "School of Education",
            voted: 310,
            eligible: 550
        }
    ];

    container.innerHTML =
        schools
            .map((school) => {
                const percentage =
                    school.eligible > 0
                        ? (school.voted /
                              school.eligible) *
                          100
                        : 0;

                return `
                    <article
                        class="school-turnout-card">

                        <div class="school-turnout-header">

                            <strong>
                                ${ALUResults.escape(
                                    school.name
                                )}
                            </strong>

                            <span>
                                ${ALUResults.formatPercentage(
                                    percentage
                                )}
                            </span>

                        </div>

                        <div class="school-turnout-bar">

                            <div
                                class="school-turnout-fill"
                                style="width:${percentage.toFixed(
                                    1
                                )}%">
                            </div>

                        </div>

                        <p>
                            ${ALUResults.formatNumber(
                                school.voted
                            )}
                            of
                            ${ALUResults.formatNumber(
                                school.eligible
                            )}
                            students voted
                        </p>

                    </article>
                `;
            })
            .join("");
};

/* =========================================================
   VERIFICATION
   ========================================================= */

ALUResults.renderVerification = function () {
    ALUResults.setText(
        "[data-verification-status]",
        "Integrity monitoring active"
    );

    ALUResults.setText(
        "[data-verification-description]",
        "Election records are continuously monitored for integrity and consistency."
    );
};

/* =========================================================
   CERTIFICATION
   ========================================================= */

ALUResults.renderCertification = function () {
    const election =
        ALUResults.state.election;

    const status =
        election?.status || "live";

    const final =
        status === "certified";

    ALUResults.setText(
        "[data-certification-status]",
        final
            ? "Certified"
            : "Not yet certified"
    );

    ALUResults.setText(
        "[data-certification-message]",
        final
            ? "The election has been formally certified."
            : "Results remain provisional until the election is closed, audited, and certified."
    );
};

/* =========================================================
   CONNECTION STATUS
   ========================================================= */

ALUResults.setConnection = function (
    status
) {
    ALUResults.state.connection =
        status;

    const labels = {
        connected: "Live",
        connecting: "Connecting...",
        disconnected: "Connection unavailable"
    };

    document
        .querySelectorAll(
            "[data-results-connection]"
        )
        .forEach((element) => {
            element.classList.remove(
                "connected",
                "connecting",
                "disconnected"
            );

            element.classList.add(
                status
            );

            element.textContent =
                labels[status] ||
                status;
        });
};

/* =========================================================
   TIMESTAMP
   ========================================================= */

ALUResults.updateTimestamp = function () {
    const date =
        ALUResults.state.lastUpdated ||
        new Date();

    document
        .querySelectorAll(
            "[data-results-updated]"
        )
        .forEach((element) => {
            element.textContent =
                ALUResults.formatDateTime(
                    date
                );
        });
};

ALUResults.formatDateTime = function (
    date
) {
    return new Intl.DateTimeFormat(
        "en-KE",
        {
            dateStyle: "medium",
            timeStyle: "medium"
        }
    ).format(date);
};

/* =========================================================
   AUTO REFRESH
   ========================================================= */

ALUResults.startAutoRefresh = function () {
    ALUResults.stopAutoRefresh();

    ALUResults.state.refreshTimer =
        window.setInterval(
            () => {
                if (
                    document.visibilityState !==
                    "visible"
                ) {
                    return;
                }

                ALUResults.refresh();
            },
            ALUResults.config.refreshInterval
        );
};

ALUResults.stopAutoRefresh = function () {
    if (
        ALUResults.state.refreshTimer
    ) {
        window.clearInterval(
            ALUResults.state.refreshTimer
        );

        ALUResults.state.refreshTimer =
            null;
    }
};

/* =========================================================
   MANUAL REFRESH
   ========================================================= */

ALUResults.refresh = async function (
    button = null
) {
    if (ALUResults.state.isLoading) {
        return;
    }

    ALUResults.state.isLoading =
        true;

    if (button) {
        ALUApp.setButtonLoading(
            button,
            true,
            "Updating..."
        );
    }

    try {
        const data =
            await ALUResults.loadResults();

        if (data) {
            ALUResults.applyResults(
                data
            );
        } else if (ALUApp.config.developmentMode) {
            ALUResults.simulateDemoUpdate();
        }
        /*
         * Production deliberately does nothing here. If no votes changed,
         * the numbers must not change: manufacturing movement to make a
         * results page look alive would be fabricating an election result.
         */

        ALUResults.renderAll();

        ALUResults.setConnection(
            "connected"
        );

    } catch (error) {
        console.error(
            "[ALU-ELECT] Results refresh failed:",
            error
        );

        ALUResults.setConnection(
            "disconnected"
        );

    } finally {
        ALUResults.state.isLoading =
            false;

        if (button) {
            ALUApp.setButtonLoading(
                button,
                false
            );
        }
    }
};

/* =========================================================
   DEMO LIVE UPDATE
   ========================================================= */

ALUResults.simulateDemoUpdate = function () {
    ALUResults.state.positions.forEach(
        (position) => {
            position.candidates?.forEach(
                (candidate) => {
                    /*
                     * Small development-only movement.
                     */
                    if (
                        Math.random() > 0.45
                    ) {
                        candidate.votes +=
                            Math.floor(
                                Math.random() *
                                    6
                            );
                    }
                }
            );
        }
    );

    ALUResults.state.totalVotersWhoVoted +=
        Math.floor(
            Math.random() * 3
        );

    ALUResults.state.totalVotes =
        ALUResults.calculateTotalVotes();

    ALUResults.state.lastUpdated =
        new Date();
};

/* =========================================================
   ERROR STATE
   ========================================================= */

ALUResults.showError = function () {
    const raceList =
        document.getElementById(
            "raceList"
        );

    if (!raceList) {
        return;
    }

    raceList.innerHTML = `
        <div class="results-error-state">

            <h3>
                Live results temporarily unavailable
            </h3>

            <p>
                We could not establish a secure
                connection to the election results service.
            </p>

            <button
                type="button"
                class="btn btn-primary"
                data-results-retry>
                Try Again
            </button>

        </div>
    `;

    const retry =
        raceList.querySelector(
            "[data-results-retry]"
        );

    if (retry) {
        retry.addEventListener(
            "click",
            () => {
                ALUResults.initialize();
            }
        );
    }
};

/* =========================================================
   SORT CANDIDATES
   ========================================================= */

ALUResults.sortCandidates = function (
    candidates
) {
    if (!Array.isArray(candidates)) {
        return [];
    }

    return [...candidates].sort(
        (a, b) =>
            Number(b.votes || 0) -
            Number(a.votes || 0)
    );
};

/* =========================================================
   SUM VOTES
   ========================================================= */

ALUResults.sumCandidateVotes = function (
    candidates
) {
    return candidates.reduce(
        (total, candidate) =>
            total +
            Number(candidate.votes || 0),
        0
    );
};

/* =========================================================
   LEAD
   ========================================================= */

ALUResults.getLead = function (
    candidates
) {
    if (!candidates.length) {
        return 0;
    }

    const first =
        Number(
            candidates[0].votes || 0
        );

    const second =
        candidates.length > 1
            ? Number(
                  candidates[1].votes ||
                      0
              )
            : 0;

    return Math.max(
        0,
        first - second
    );
};

/* =========================================================
   TEXT HELPER
   ========================================================= */

ALUResults.setText = function (
    selector,
    value
) {
    document
        .querySelectorAll(selector)
        .forEach((element) => {
            element.textContent =
                value;
        });
};

/* =========================================================
   NUMBER FORMAT
   ========================================================= */

ALUResults.formatNumber = function (
    value
) {
    const number =
        Number(value);

    if (!Number.isFinite(number)) {
        return "0";
    }

    return new Intl.NumberFormat(
        "en-KE"
    ).format(number);
};

/* =========================================================
   PERCENTAGE FORMAT
   ========================================================= */

ALUResults.formatPercentage =
    function (
        value,
        decimals = 1
    ) {
        const number =
            Number(value);

        if (!Number.isFinite(number)) {
            return "0%";
        }

        return `${number.toFixed(
            decimals
        )}%`;
    };

/* =========================================================
   HTML ESCAPE
   ========================================================= */

ALUResults.escape = function (
    value
) {
    if (
        value === null ||
        value === undefined
    ) {
        return "";
    }

    const element =
        document.createElement(
            "div"
        );

    element.textContent =
        String(value);

    return element.innerHTML;
};

/* =========================================================
   PAGE VISIBILITY
   ========================================================= */

document.addEventListener(
    "visibilitychange",
    () => {
        if (
            document.visibilityState ===
            "visible"
        ) {
            ALUResults.startAutoRefresh();
        } else {
            ALUResults.stopAutoRefresh();
        }
    }
);

/* =========================================================
   CLEANUP
   ========================================================= */

window.addEventListener(
    "beforeunload",
    () => {
        ALUResults.stopAutoRefresh();
    }
);

/* =========================================================
   INITIALIZATION MESSAGE
   ========================================================= */

console.info(
    "%cALU-ELECT RESULTS",
    "font-weight:900;font-size:16px;"
);

console.info(
    "Live results interface initialized."
);