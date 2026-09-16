/* =========================================================
   ALU-ELECT — VOTE VERIFICATION JAVASCRIPT
   File: js/verify.js
   ========================================================= */

"use strict";

window.ALU_ELECT = window.ALU_ELECT || {};

const ALUVerify = {
    state: {
        verifying: false,
        verified: false,
        receipt: null
    },

    config: {
        verifyEndpoint: "/api/election/verify"
    }
};

/* =========================================================
   INITIALIZATION
   ========================================================= */

document.addEventListener("DOMContentLoaded", () => {
    ALUVerify.init();
});

ALUVerify.init = function () {
    ALUVerify.bindForm();
    ALUVerify.bindExampleActions();
    ALUVerify.hideResult();
};

/* =========================================================
   FORM
   ========================================================= */

ALUVerify.bindForm = function () {
    const form =
        document.getElementById(
            "verificationForm"
        );

    if (!form) {
        return;
    }

    form.addEventListener(
        "submit",
        (event) => {
            event.preventDefault();

            ALUVerify.verify();
        }
    );
};

/* =========================================================
   EXAMPLE / HELPER ACTIONS
   ========================================================= */

ALUVerify.bindExampleActions = function () {
    document.querySelectorAll(
        "[data-fill-receipt]"
    ).forEach((button) => {
        button.addEventListener(
            "click",
            () => {
                const value =
                    button.dataset.fillReceipt;

                const input =
                    document.getElementById(
                        "receiptIdInput"
                    );

                if (!input || !value) {
                    return;
                }

                input.value = value;
                input.focus();
            }
        );
    });
};

/* =========================================================
   VERIFY RECEIPT
   ========================================================= */

ALUVerify.verify = async function () {
    if (
        ALUVerify.state.verifying
    ) {
        return;
    }

    const input =
        document.getElementById(
            "receiptIdInput"
        );

    const button =
        document.getElementById(
            "verifyReceiptBtn"
        );

    if (!input) {
        return;
    }

    const receipt =
        input.value.trim();

    if (!receipt) {
        ALUVerify.showInputError(
            "Enter your verification reference."
        );

        input.focus();

        return;
    }

    if (
        !ALUEVerifyIsValidFormat(receipt)
    ) {
        ALUVerify.showInputError(
            "Enter a valid verification reference."
        );

        input.focus();

        return;
    }

    ALUVerify.clearInputError();

    ALUVerify.state.verifying =
        true;

    if (button) {
        ALUApp.setButtonLoading(
            button,
            true,
            "Verifying..."
        );
    }

    try {
        let result;

        try {
            result =
                await ALUApp.api(
                    ALUVerify.config.verifyEndpoint,
                    {
                        method: "POST",
                        body: {
                            reference:
                                receipt
                        }
                    }
                );
        } catch (error) {
            /*
             * Development-only fallback.
             *
             * Production must NOT treat an unavailable
             * verification service as a successful verification.
             */
            if (
                error.status === 404 &&
                ALUApp.config.developmentMode
            ) {
                result =
                    ALUVerify.createDemoResult(
                        receipt
                    );
            } else {
                throw error;
            }
        }

        ALUVerify.state.receipt =
            result;

        ALUVerify.state.verified =
            Boolean(
                result?.verified ||
                result?.success
            );

        ALUVerify.renderResult(
            result
        );

    } catch (error) {
        console.error(
            "[ALU-ELECT VERIFY]",
            error
        );

        ALUVerify.state.verified =
            false;

        ALUVerify.showVerificationError(
            error
        );

    } finally {
        ALUVerify.state.verifying =
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
   RECEIPT FORMAT VALIDATION
   ========================================================= */

function ALUEVerifyIsValidFormat(
    receipt
) {
    /*
     * Keep this validation deliberately permissive.
     *
     * The backend is the authority and must perform
     * the real verification.
     */

    if (
        receipt.length < 6 ||
        receipt.length > 160
    ) {
        return false;
    }

    return /^[A-Za-z0-9._:-]+$/.test(
        receipt
    );
}

/* =========================================================
   DEVELOPMENT RESULT
   ========================================================= */

ALUVerify.createDemoResult =
    function (
        receipt
    ) {
        return {
            success: true,
            verified: true,

            receipt_id:
                receipt,

            election:
                "ALU Student Elections 2026",

            timestamp:
                new Date().toISOString(),

            status:
                "Recorded and integrity-verified",

            message:
                "Your vote record has been found and its integrity proof is valid.",

            reference:
                receipt,

            proof:
                "DEMO-PROOF-ONLY",

            /*
             * Deliberately no candidate information.
             */
            reveals_candidate:
                false,

            reveals_identity:
                false
        };
    };

/* =========================================================
   RENDER RESULT
   ========================================================= */

ALUVerify.renderResult = function (
    result
) {
    const panel =
        document.getElementById(
            "verificationResult"
        );

    if (!panel) {
        return;
    }

    panel.hidden = false;

    const verified =
        Boolean(
            result?.verified ||
            result?.success
        );

    panel.classList.toggle(
        "is-success",
        verified
    );

    panel.classList.toggle(
        "is-error",
        !verified
    );

    ALUVerify.setText(
        "verificationStatus",
        verified
            ? "Vote Verified"
            : "Verification Failed"
    );

    ALUVerify.setText(
        "verificationMessage",
        result?.message ||
            (
                verified
                    ? "Your vote record was found and its integrity proof is valid."
                    : "We could not verify this reference."
            )
    );

    ALUVerify.setText(
        "verificationReference",
        result?.reference ||
            result?.receipt_id ||
            "Not available"
    );

    ALUVerify.setText(
        "verificationTimestamp",
        ALUVerify.formatTimestamp(
            result?.timestamp
        )
    );

    ALUVerify.setText(
        "verificationElection",
        result?.election ||
            "ALU Student Election"
    );

    ALUVerify.setText(
        "verificationProof",
        result?.proof ||
            "Integrity proof available from the election verification service."
    );

    ALUVerify.scrollToResult();
};

/* =========================================================
   HIDE RESULT
   ========================================================= */

ALUVerify.hideResult = function () {
    const panel =
        document.getElementById(
            "verificationResult"
        );

    if (!panel) {
        return;
    }

    panel.hidden = true;
};

/* =========================================================
   INPUT ERROR
   ========================================================= */

ALUVerify.showInputError = function (
    message
) {
    const input =
        document.getElementById(
            "receiptIdInput"
        );

    if (!input) {
        return;
    }

    input.classList.add(
        "input-error"
    );

    input.setAttribute(
        "aria-invalid",
        "true"
    );

    let error =
        document.getElementById(
            "receiptInputError"
        );

    if (!error) {
        error =
            document.createElement(
                "p"
            );

        error.id =
            "receiptInputError";

        error.className =
            "form-error";

        input.insertAdjacentElement(
            "afterend",
            error
        );
    }

    error.textContent =
        message;

    input.setAttribute(
        "aria-describedby",
        "receiptInputError"
    );
};

/* =========================================================
   CLEAR INPUT ERROR
   ========================================================= */

ALUVerify.clearInputError =
    function () {
        const input =
            document.getElementById(
                "receiptIdInput"
            );

        if (!input) {
            return;
        }

        input.classList.remove(
            "input-error"
        );

        input.removeAttribute(
            "aria-invalid"
        );

        input.removeAttribute(
            "aria-describedby"
        );

        const error =
            document.getElementById(
                "receiptInputError"
            );

        if (error) {
            error.remove();
        }
    };

/* =========================================================
   VERIFICATION ERROR
   ========================================================= */

ALUVerify.showVerificationError =
    function (error) {
        const panel =
            document.getElementById(
                "verificationResult"
            );

        if (!panel) {
            return;
        }

        panel.hidden = false;

        panel.classList.remove(
            "is-success"
        );

        panel.classList.add(
            "is-error"
        );

        ALUVerify.setText(
            "verificationStatus",
            "Unable to Verify"
        );

        ALUVerify.setText(
            "verificationMessage",
            "The verification service could not complete the request. Please try again."
        );

        ALUVerify.setText(
            "verificationReference",
            "Not verified"
        );

        ALUVerify.setText(
            "verificationTimestamp",
            ALUVerify.formatTimestamp(
                new Date()
            )
        );

        ALUVerify.setText(
            "verificationElection",
            "ALU Student Election"
        );

        ALUVerify.setText(
            "verificationProof",
            "No verification proof was issued."
        );

        ALUVerify.scrollToResult();

        console.error(
            "[ALU-ELECT] Verification error:",
            error
        );
    };

/* =========================================================
   SET TEXT
   ========================================================= */

ALUVerify.setText = function (
    id,
    value
) {
    const element =
        document.getElementById(id);

    if (!element) {
        return;
    }

    element.textContent =
        value ?? "";
};

/* =========================================================
   TIMESTAMP FORMAT
   ========================================================= */

ALUVerify.formatTimestamp =
    function (
        timestamp
    ) {
        if (!timestamp) {
            return "Not available";
        }

        const date =
            new Date(timestamp);

        if (
            Number.isNaN(
                date.getTime()
            )
        ) {
            return "Not available";
        }

        return new Intl.DateTimeFormat(
            "en-KE",
            {
                dateStyle: "medium",
                timeStyle: "medium"
            }
        ).format(date);
    };

/* =========================================================
   SCROLL TO RESULT
   ========================================================= */

ALUVerify.scrollToResult =
    function () {
        const panel =
            document.getElementById(
                "verificationResult"
            );

        if (!panel) {
            return;
        }

        window.setTimeout(() => {
            panel.scrollIntoView({
                behavior: "smooth",
                block: "center"
            });
        }, 100);
    };

/* =========================================================
   COPY VERIFICATION REFERENCE
   ========================================================= */

document.addEventListener(
    "click",
    async (event) => {
        const button =
            event.target.closest(
                "[data-copy-reference]"
            );

        if (!button) {
            return;
        }

        const reference =
            document.getElementById(
                "verificationReference"
            );

        if (!reference) {
            return;
        }

        const value =
            reference.textContent.trim();

        if (!value) {
            return;
        }

        try {
            await navigator.clipboard.writeText(
                value
            );

            ALUApp.toast(
                "Verification reference copied.",
                "success"
            );

        } catch (error) {
            ALUApp.toast(
                "Could not copy the reference.",
                "error"
            );
        }
    }
);

/* =========================================================
   SHARE VERIFICATION
   ========================================================= */

document.addEventListener(
    "click",
    async (event) => {
        const button =
            event.target.closest(
                "[data-share-verification]"
            );

        if (!button) {
            return;
        }

        const reference =
            document.getElementById(
                "verificationReference"
            );

        const value =
            reference?.textContent.trim();

        if (!value) {
            return;
        }

        const shareData = {
            title:
                "ALU-ELECT Vote Verification",
            text:
                `ALU-ELECT verification reference: ${value}`,
            url:
                window.location.href
        };

        if (
            navigator.share
        ) {
            try {
                await navigator.share(
                    shareData
                );
            } catch (error) {
                /*
                 * User cancelled sharing.
                 */
            }

            return;
        }

        try {
            await navigator.clipboard.writeText(
                `${shareData.text}\n${shareData.url}`
            );

            ALUApp.toast(
                "Verification information copied.",
                "success"
            );
        } catch (error) {
            ALUApp.toast(
                "Sharing is not available on this device.",
                "warning"
            );
        }
    }
);

/* =========================================================
   PRIVACY GUARD
   ========================================================= */

ALUEVerifyPrivacyGuard();

function ALUEVerifyPrivacyGuard() {
    /*
     * The verification page intentionally does not render
     * candidate choice information.
     *
     * This is a frontend safety rule only.
     * The backend must independently enforce the same
     * privacy boundary.
     */

    document.addEventListener(
        "alu-verification-data-loaded",
        (event) => {
            const data =
                event.detail;

            if (
                !data ||
                typeof data !== "object"
            ) {
                return;
            }

            /*
             * Remove fields that should never appear
             * on the public verification page.
             */
            delete data.candidate;
            delete data.candidate_id;
            delete data.choice;
            delete data.vote_choice;
            delete data.ballot_selection;
            delete data.voter_id;
            delete data.student_id;
            delete data.email;
        }
    );
}

/* =========================================================
   ENTER KEY SUPPORT
   ========================================================= */

document.addEventListener(
    "keydown",
    (event) => {
        if (
            event.key !== "Enter"
        ) {
            return;
        }

        const input =
            document.getElementById(
                "receiptIdInput"
            );

        if (
            document.activeElement ===
            input
        ) {
            event.preventDefault();

            ALUVerify.verify();
        }
    }
);

/* =========================================================
   INITIALIZATION MESSAGE
   ========================================================= */

console.info(
    "%cALU-ELECT VERIFY",
    "font-weight:900;font-size:16px;"
);

console.info(
    "Vote verification interface initialized."
);