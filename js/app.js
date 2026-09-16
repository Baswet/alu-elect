/* =========================================================
   ALU-ELECT — SHARED APPLICATION JAVASCRIPT
   File: js/app.js
   ========================================================= */

"use strict";

/*
 * ALU-ELECT
 * Your Vote. Your Voice. Verifiable.
 *
 * Shared frontend behavior.
 *
 * IMPORTANT:
 * This file handles UI behavior only.
 * Authentication, vote validation, ballot storage,
 * cryptographic operations, blockchain recording,
 * and server-side authorization MUST be implemented
 * on the backend.
 */

/* ---------------------------------------------------------
   GLOBAL APPLICATION OBJECT
   --------------------------------------------------------- */

window.ALU_ELECT = window.ALU_ELECT || {};

const ALUApp = window.ALU_ELECT;

/* ---------------------------------------------------------
   CONFIGURATION
   --------------------------------------------------------- */

ALUApp.config = {
    appName: "ALU-ELECT",

    /*
     * These values are placeholders for the backend phase.
     * Do not place private keys, API secrets, or credentials here.
     */
    apiBaseUrl: "",

    /*
     * DEVELOPMENT MODE.
     *
     * Off unless the page is served from localhost, or a page explicitly
     * opts in with <meta name="alu-dev-mode" content="1">.
     *
     * When off, nothing in this application may substitute demo data for a
     * real backend response: a missing API is an error the operator must
     * see, not something to paper over with invented candidates, receipts
     * or vote counts.
     */
    developmentMode: (function () {
        /*
         * Explicit opt-in ONLY. An earlier version also treated localhost and
         * 127.0.0.1 as development, which is unsafe: a production deployment
         * behind a same-host reverse proxy is reached on 127.0.0.1, and would
         * have silently enabled demo fallbacks on a live election. A hostname
         * is not consent.
         */
        try {
            var optIn = document.querySelector(
                'meta[name="alu-dev-mode"]'
            );
            return !!(optIn && optIn.getAttribute("content") === "1");
        } catch (e) {
            return false;
        }
    })(),

    /* Set from any login response; sent on every state-changing request. */
    csrfToken: "",

    refreshInterval: 15000,

    animationDuration: 200,

    selectors: {
        header: ".site-header",
        mobileMenuButton: ".mobile-menu-toggle",
        mobileMenu: ".site-nav",
        modal: ".modal",
        modalClose: "[data-modal-close]",
        modalOpen: "[data-modal-open]"
    }
};

/* ---------------------------------------------------------
   DOM READY
   --------------------------------------------------------- */

document.addEventListener("DOMContentLoaded", () => {
    ALUApp.init();
});

/* ---------------------------------------------------------
   INITIALIZE APPLICATION
   --------------------------------------------------------- */

ALUApp.init = function () {
    ALUApp.initNavigation();
    ALUApp.initModals();
    ALUApp.initAccessibleInteractions();
    ALUApp.initCurrentPage();
    ALUApp.initExternalLinks();
    ALUApp.initBackToTop();
};

/* ---------------------------------------------------------
   NAVIGATION
   --------------------------------------------------------- */

ALUApp.initNavigation = function () {
    const menuButton = document.querySelector(
        ALUApp.config.selectors.mobileMenuButton
    );

    const nav = document.querySelector(
        ALUApp.config.selectors.mobileMenu
    );

    if (!menuButton || !nav) {
        return;
    }

    menuButton.addEventListener("click", () => {
        const isOpen =
            menuButton.getAttribute("aria-expanded") === "true";

        menuButton.setAttribute(
            "aria-expanded",
            String(!isOpen)
        );

        menuButton.classList.toggle("is-active", !isOpen);
        nav.classList.toggle("is-open", !isOpen);

        document.body.classList.toggle(
            "mobile-nav-open",
            !isOpen
        );
    });

    /*
     * Close mobile navigation when a navigation link
     * is selected.
     */
    nav.querySelectorAll("a").forEach((link) => {
        link.addEventListener("click", () => {
            menuButton.setAttribute("aria-expanded", "false");
            menuButton.classList.remove("is-active");
            nav.classList.remove("is-open");
            document.body.classList.remove("mobile-nav-open");
        });
    });

    /*
     * Close navigation when clicking outside it.
     */
    document.addEventListener("click", (event) => {
        if (!nav.classList.contains("is-open")) {
            return;
        }

        const clickedInsideNav = nav.contains(event.target);
        const clickedButton = menuButton.contains(event.target);

        if (!clickedInsideNav && !clickedButton) {
            menuButton.setAttribute("aria-expanded", "false");
            menuButton.classList.remove("is-active");
            nav.classList.remove("is-open");
            document.body.classList.remove("mobile-nav-open");
        }
    });

    /*
     * Close navigation with Escape.
     */
    document.addEventListener("keydown", (event) => {
        if (event.key !== "Escape") {
            return;
        }

        if (!nav.classList.contains("is-open")) {
            return;
        }

        menuButton.setAttribute("aria-expanded", "false");
        menuButton.classList.remove("is-active");
        nav.classList.remove("is-open");
        document.body.classList.remove("mobile-nav-open");

        menuButton.focus();
    });
};

/* ---------------------------------------------------------
   CURRENT PAGE NAVIGATION
   --------------------------------------------------------- */

ALUApp.initCurrentPage = function () {
    const currentPage =
        window.location.pathname.split("/").pop() || "index.html";

    const normalizedPage =
        currentPage === "" ? "index.html" : currentPage;

    document.querySelectorAll(".site-nav a").forEach((link) => {
        const href = link.getAttribute("href");

        if (!href) {
            return;
        }

        const linkPage = href.split("#")[0].split("/").pop();

        if (
            linkPage === normalizedPage ||
            (normalizedPage === "index.html" &&
                (linkPage === "" || linkPage === "index.html"))
        ) {
            link.classList.add("active");
            link.setAttribute("aria-current", "page");
        }
    });
};

/* ---------------------------------------------------------
   MODALS
   --------------------------------------------------------- */

ALUApp.initModals = function () {
    const modals = document.querySelectorAll(
        ALUApp.config.selectors.modal
    );

    if (!modals.length) {
        return;
    }

    document
        .querySelectorAll(ALUApp.config.selectors.modalOpen)
        .forEach((trigger) => {
            trigger.addEventListener("click", () => {
                const targetId =
                    trigger.getAttribute("data-modal-open");

                if (!targetId) {
                    return;
                }

                ALUApp.openModal(targetId);
            });
        });

    document
        .querySelectorAll(ALUApp.config.selectors.modalClose)
        .forEach((button) => {
            button.addEventListener("click", () => {
                const modal = button.closest(".modal");

                if (modal) {
                    ALUApp.closeModal(modal.id);
                }
            });
        });

    /*
     * Close modal by clicking its backdrop.
     */
    modals.forEach((modal) => {
        modal.addEventListener("click", (event) => {
            if (event.target === modal) {
                ALUApp.closeModal(modal.id);
            }
        });
    });

    /*
     * Global Escape handling.
     */
    document.addEventListener("keydown", (event) => {
        if (event.key !== "Escape") {
            return;
        }

        const openModal = document.querySelector(
            ".modal.is-open, .modal[aria-hidden='false']"
        );

        if (openModal) {
            ALUApp.closeModal(openModal.id);
        }
    });
};

/* ---------------------------------------------------------
   OPEN MODAL
   --------------------------------------------------------- */

ALUApp.openModal = function (modalId) {
    const modal = document.getElementById(modalId);

    if (!modal) {
        return;
    }

    modal.classList.add("is-open");
    modal.setAttribute("aria-hidden", "false");

    document.body.classList.add("modal-open");

    /*
     * Focus first usable element.
     */
    window.setTimeout(() => {
        const focusTarget = modal.querySelector(
            "button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href]"
        );

        if (focusTarget) {
            focusTarget.focus();
        }
    }, 50);
};

/* ---------------------------------------------------------
   CLOSE MODAL
   --------------------------------------------------------- */

ALUApp.closeModal = function (modalId) {
    const modal = document.getElementById(modalId);

    if (!modal) {
        return;
    }

    modal.classList.remove("is-open");
    modal.setAttribute("aria-hidden", "true");

    /*
     * Only remove modal-open when no other modal is open.
     */
    const anotherOpenModal = document.querySelector(
        ".modal.is-open, .modal[aria-hidden='false']"
    );

    if (!anotherOpenModal) {
        document.body.classList.remove("modal-open");
    }
};

/* ---------------------------------------------------------
   ACCESSIBILITY
   --------------------------------------------------------- */

ALUApp.initAccessibleInteractions = function () {
    /*
     * Keyboard support for elements that behave like cards.
     */
    document
        .querySelectorAll("[role='button'][tabindex='0']")
        .forEach((element) => {
            element.addEventListener("keydown", (event) => {
                if (
                    event.key !== "Enter" &&
                    event.key !== " "
                ) {
                    return;
                }

                event.preventDefault();
                element.click();
            });
        });

    /*
     * Prevent accidental form submission when Enter is used
     * inside a multi-control UI unless the form explicitly
     * permits it.
     */
    document.querySelectorAll("form[data-no-enter-submit]")
        .forEach((form) => {
            form.addEventListener("keydown", (event) => {
                if (
                    event.key === "Enter" &&
                    event.target.tagName !== "TEXTAREA"
                ) {
                    event.preventDefault();
                }
            });
        });
};

/* ---------------------------------------------------------
   EXTERNAL LINKS
   --------------------------------------------------------- */

ALUApp.initExternalLinks = function () {
    document.querySelectorAll("a[href]").forEach((link) => {
        const href = link.getAttribute("href");

        if (!href) {
            return;
        }

        if (
            href.startsWith("http://") ||
            href.startsWith("https://")
        ) {
            const currentHost = window.location.hostname;

            try {
                const url = new URL(href);

                if (
                    url.hostname &&
                    url.hostname !== currentHost
                ) {
                    link.setAttribute("target", "_blank");
                    link.setAttribute(
                        "rel",
                        "noopener noreferrer"
                    );
                }
            } catch (error) {
                /*
                 * Invalid URLs are left untouched.
                 */
            }
        }
    });
};

/* ---------------------------------------------------------
   BACK TO TOP
   --------------------------------------------------------- */

ALUApp.initBackToTop = function () {
    const button = document.querySelector(
        "[data-back-to-top]"
    );

    if (!button) {
        return;
    }

    const updateVisibility = () => {
        if (window.scrollY > 500) {
            button.classList.add("is-visible");
        } else {
            button.classList.remove("is-visible");
        }
    };

    window.addEventListener(
        "scroll",
        updateVisibility,
        { passive: true }
    );

    button.addEventListener("click", () => {
        window.scrollTo({
            top: 0,
            behavior: "smooth"
        });
    });

    updateVisibility();
};

/* ---------------------------------------------------------
   SAFE TEXT
   --------------------------------------------------------- */

ALUApp.escapeHTML = function (value) {
    if (value === null || value === undefined) {
        return "";
    }

    const element = document.createElement("div");
    element.textContent = String(value);

    return element.innerHTML;
};

/* ---------------------------------------------------------
   FORMAT NUMBER
   --------------------------------------------------------- */

ALUApp.formatNumber = function (value) {
    const number = Number(value);

    if (!Number.isFinite(number)) {
        return "0";
    }

    return new Intl.NumberFormat("en-KE").format(number);
};

/* ---------------------------------------------------------
   FORMAT PERCENTAGE
   --------------------------------------------------------- */

ALUApp.formatPercentage = function (
    value,
    decimals = 1
) {
    const number = Number(value);

    if (!Number.isFinite(number)) {
        return "0%";
    }

    return `${number.toFixed(decimals)}%`;
};

/* ---------------------------------------------------------
   DEBOUNCE
   --------------------------------------------------------- */

ALUApp.debounce = function (callback, delay = 250) {
    let timeoutId = null;

    return function (...args) {
        window.clearTimeout(timeoutId);

        timeoutId = window.setTimeout(() => {
            callback.apply(this, args);
        }, delay);
    };
};

/* ---------------------------------------------------------
   THROTTLE
   --------------------------------------------------------- */

ALUApp.throttle = function (callback, delay = 250) {
    let waiting = false;

    return function (...args) {
        if (waiting) {
            return;
        }

        callback.apply(this, args);

        waiting = true;

        window.setTimeout(() => {
            waiting = false;
        }, delay);
    };
};

/* ---------------------------------------------------------
   SAFE JSON PARSER
   --------------------------------------------------------- */

ALUApp.parseJSON = function (value, fallback = null) {
    try {
        return JSON.parse(value);
    } catch (error) {
        return fallback;
    }
};

/* ---------------------------------------------------------
   LOCAL STORAGE HELPERS
   --------------------------------------------------------- */

ALUApp.storage = {
    get(key, fallback = null) {
        try {
            const value = window.localStorage.getItem(key);

            if (value === null) {
                return fallback;
            }

            return JSON.parse(value);
        } catch (error) {
            return fallback;
        }
    },

    set(key, value) {
        try {
            window.localStorage.setItem(
                key,
                JSON.stringify(value)
            );

            return true;
        } catch (error) {
            return false;
        }
    },

    remove(key) {
        try {
            window.localStorage.removeItem(key);
            return true;
        } catch (error) {
            return false;
        }
    }
};

/* ---------------------------------------------------------
   SESSION STORAGE HELPERS
   --------------------------------------------------------- */

ALUApp.session = {
    get(key, fallback = null) {
        try {
            const value =
                window.sessionStorage.getItem(key);

            if (value === null) {
                return fallback;
            }

            return JSON.parse(value);
        } catch (error) {
            return fallback;
        }
    },

    set(key, value) {
        try {
            window.sessionStorage.setItem(
                key,
                JSON.stringify(value)
            );

            return true;
        } catch (error) {
            return false;
        }
    },

    remove(key) {
        try {
            window.sessionStorage.removeItem(key);
            return true;
        } catch (error) {
            return false;
        }
    }
};

/* ---------------------------------------------------------
   API HELPER
   --------------------------------------------------------- */

/*
 * This is intentionally a generic helper.
 *
 * Authentication tokens and security-sensitive values
 * must eventually be handled through secure backend
 * mechanisms rather than hard-coded frontend values.
 */

ALUApp.api = async function (
    endpoint,
    options = {}
) {
    const requestOptions = {
        method: options.method || "GET",
        headers: {
            "Accept": "application/json",
            ...(options.headers || {})
        },
        credentials: "include"
    };

    /*
     * The API is cookie-authenticated, so every state-changing request must
     * carry the CSRF token or the server rejects it with 403.
     *
     * The token lives in the session cookie, not in the page, so after any
     * navigation or reload the in-memory copy is gone. Rather than making
     * every caller remember to prime it, fetch one on demand the first time
     * an unsafe request is made. Without this a voter who reloaded the
     * ballot page could not cast a vote at all - found in browser testing.
     */
    var unsafe = ["POST", "PUT", "PATCH", "DELETE"]
        .indexOf(requestOptions.method.toUpperCase()) !== -1;

    if (unsafe && !ALUApp.config.csrfToken && !options.skipCsrfBootstrap) {
        try {
            const tokenResponse = await fetch(
                `${ALUApp.config.apiBaseUrl}/api/csrf`,
                { credentials: "include" }
            );
            if (tokenResponse.ok) {
                const tokenData = await tokenResponse.json();
                if (tokenData && tokenData.csrf_token) {
                    ALUApp.config.csrfToken = tokenData.csrf_token;
                }
            }
        } catch (e) {
            /* Fall through: the server will reject with 403 and the caller
               will surface a real error rather than a silent failure. */
        }
    }

    if (unsafe && ALUApp.config.csrfToken) {
        requestOptions.headers["X-CSRF-Token"] =
            ALUApp.config.csrfToken;
    }

    if (
        options.body !== undefined &&
        options.body !== null
    ) {
        requestOptions.headers["Content-Type"] =
            "application/json";

        requestOptions.body =
            typeof options.body === "string"
                ? options.body
                : JSON.stringify(options.body);
    }

    const url =
        endpoint.startsWith("http://") ||
        endpoint.startsWith("https://")
            ? endpoint
            : `${ALUApp.config.apiBaseUrl}${endpoint}`;

    const response = await fetch(
        url,
        requestOptions
    );

    const contentType =
        response.headers.get("content-type") || "";

    let data;

    if (contentType.includes("application/json")) {
        data = await response.json();
    } else {
        data = await response.text();
    }

    /* Keep the newest token the server issues. */
    if (data && typeof data === "object" && data.csrf_token) {
        ALUApp.config.csrfToken = data.csrf_token;
    }

    if (!response.ok) {
        const error = new Error(
            data?.message ||
            data?.error ||
            `Request failed with status ${response.status}`
        );

        error.status = response.status;
        error.data = data;

        throw error;
    }

    return data;
};

/* ---------------------------------------------------------
   TOAST NOTIFICATIONS
   --------------------------------------------------------- */

ALUApp.toast = function (
    message,
    type = "info",
    duration = 3500
) {
    if (!message) {
        return;
    }

    let container =
        document.querySelector(".toast-container");

    if (!container) {
        container = document.createElement("div");

        container.className =
            "toast-container";

        container.setAttribute(
            "aria-live",
            "polite"
        );

        container.setAttribute(
            "aria-atomic",
            "true"
        );

        document.body.appendChild(container);
    }

    const toast =
        document.createElement("div");

    toast.className =
        `toast toast-${type}`;

    toast.setAttribute(
        "role",
        "status"
    );

    toast.textContent = message;

    container.appendChild(toast);

    requestAnimationFrame(() => {
        toast.classList.add("is-visible");
    });

    window.setTimeout(() => {
        toast.classList.remove("is-visible");

        window.setTimeout(() => {
            toast.remove();
        }, 250);
    }, duration);
};

/* ---------------------------------------------------------
   LOADING BUTTON
   --------------------------------------------------------- */

ALUApp.setButtonLoading = function (
    button,
    loading,
    loadingText = "Processing..."
) {
    if (!button) {
        return;
    }

    if (loading) {
        if (!button.dataset.originalText) {
            button.dataset.originalText =
                button.innerHTML;
        }

        button.disabled = true;
        button.setAttribute(
            "aria-busy",
            "true"
        );

        button.innerHTML = `
            <span class="button-spinner"
                  aria-hidden="true"></span>
            <span>${ALUApp.escapeHTML(
                loadingText
            )}</span>
        `;
    } else {
        button.disabled = false;
        button.removeAttribute("aria-busy");

        if (button.dataset.originalText) {
            button.innerHTML =
                button.dataset.originalText;

            delete button.dataset.originalText;
        }
    }
};

/* ---------------------------------------------------------
   NETWORK STATUS
   --------------------------------------------------------- */

ALUApp.initNetworkStatus = function () {
    const updateStatus = () => {
        document.body.classList.toggle(
            "offline",
            !navigator.onLine
        );

        document.body.classList.toggle(
            "online",
            navigator.onLine
        );
    };

    window.addEventListener(
        "online",
        updateStatus
    );

    window.addEventListener(
        "offline",
        updateStatus
    );

    updateStatus();
};

/* ---------------------------------------------------------
   INITIALIZE NETWORK STATUS
   --------------------------------------------------------- */

ALUApp.initNetworkStatus();

/* ---------------------------------------------------------
   PAGE VISIBILITY
   --------------------------------------------------------- */

ALUApp.isPageVisible = function () {
    return document.visibilityState === "visible";
};

/* ---------------------------------------------------------
   CUSTOM EVENT HELPER
   --------------------------------------------------------- */

ALUApp.emit = function (
    eventName,
    detail = {}
) {
    document.dispatchEvent(
        new CustomEvent(eventName, {
            detail
        })
    );
};

/* ---------------------------------------------------------
   SHARED LIVE STATUS
   --------------------------------------------------------- */

ALUApp.setLiveStatus = function (
    status,
    message
) {
    const elements =
        document.querySelectorAll(
            "[data-live-status]"
        );

    elements.forEach((element) => {
        element.classList.remove(
            "connected",
            "disconnected",
            "connecting"
        );

        element.classList.add(status);

        if (message) {
            element.textContent = message;
        }
    });
};

/* ---------------------------------------------------------
   CONFIRMATION HELPER
   --------------------------------------------------------- */

ALUApp.confirmAction = function ({
    title = "Confirm action",
    message = "Are you sure you want to continue?",
    confirmText = "Continue",
    cancelText = "Cancel"
} = {}) {
    return new Promise((resolve) => {
        const overlay =
            document.createElement("div");

        overlay.className =
            "modal dynamic-confirm-modal is-open";

        overlay.setAttribute(
            "aria-hidden",
            "false"
        );

        overlay.innerHTML = `
            <div class="modal-content"
                 role="dialog"
                 aria-modal="true"
                 aria-labelledby="dynamicConfirmTitle">

                <button
                    type="button"
                    class="modal-close"
                    aria-label="Close"
                    data-confirm-cancel>
                    &times;
                </button>

                <div class="modal-header">
                    <h2 id="dynamicConfirmTitle">
                        ${ALUApp.escapeHTML(title)}
                    </h2>
                </div>

                <div class="modal-body">
                    <p>
                        ${ALUApp.escapeHTML(message)}
                    </p>
                </div>

                <div class="modal-footer">
                    <button
                        type="button"
                        class="btn btn-secondary"
                        data-confirm-cancel>
                        ${ALUApp.escapeHTML(cancelText)}
                    </button>

                    <button
                        type="button"
                        class="btn btn-primary"
                        data-confirm-accept>
                        ${ALUApp.escapeHTML(confirmText)}
                    </button>
                </div>
            </div>
        `;

        document.body.appendChild(overlay);
        document.body.classList.add("modal-open");

        const finish = (result) => {
            overlay.remove();
            document.body.classList.remove(
                "modal-open"
            );
            resolve(result);
        };

        overlay
            .querySelectorAll("[data-confirm-cancel]")
            .forEach((button) => {
                button.addEventListener(
                    "click",
                    () => finish(false)
                );
            });

        overlay
            .querySelector(
                "[data-confirm-accept]"
            )
            .addEventListener(
                "click",
                () => finish(true)
            );

        overlay.addEventListener(
            "click",
            (event) => {
                if (event.target === overlay) {
                    finish(false);
                }
            }
        );

        const handleEscape = (event) => {
            if (event.key === "Escape") {
                document.removeEventListener(
                    "keydown",
                    handleEscape
                );

                finish(false);
            }
        };

        document.addEventListener(
            "keydown",
            handleEscape
        );
    });
};

/* ---------------------------------------------------------
   ERROR HANDLER
   --------------------------------------------------------- */

ALUApp.handleError = function (
    error,
    userMessage = "Something went wrong. Please try again."
) {
    console.error(
        "[ALU-ELECT]",
        error
    );

    ALUApp.toast(
        userMessage,
        "error"
    );
};

/* ---------------------------------------------------------
   PAGE UNLOAD PROTECTION
   --------------------------------------------------------- */

ALUApp.enableUnloadProtection = function (
    message =
        "You have unsaved changes. Are you sure you want to leave?"
) {
    const handler = (event) => {
        event.preventDefault();
        event.returnValue = message;
        return message;
    };

    window.addEventListener(
        "beforeunload",
        handler
    );

    return () => {
        window.removeEventListener(
            "beforeunload",
            handler
        );
    };
};

/* ---------------------------------------------------------
   FINAL INITIALIZATION
   --------------------------------------------------------- */

console.info(
    `%c${ALUApp.config.appName}`,
    "font-weight:900;font-size:16px;"
);

console.info(
    "Shared application layer initialized."
);