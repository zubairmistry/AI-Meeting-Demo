/* ==========================================================================
   AI MEETING ASSISTANT — AUTHENTICATION & THEME CONTROLLER
   ========================================================================== */

(function () {
    "use strict";

    /* ==========================================================================
       1. THEME ENGINE & PERSISTENCE
       ========================================================================== */
    const THEME_STORAGE_KEY = "ai_meeting_theme";
    const VALID_THEMES = ["classic", "light", "dark", "neon", "enterprise"];

    function getSavedTheme() {
        try {
            const saved = localStorage.getItem(THEME_STORAGE_KEY);
            if (saved && VALID_THEMES.includes(saved)) {
                return saved;
            }
        } catch (e) {
            console.warn("LocalStorage unavailable for theme persistence:", e);
        }
        return "classic";
    }

    function applyTheme(themeName) {
        if (!VALID_THEMES.includes(themeName)) themeName = "classic";
        document.documentElement.setAttribute("data-theme", themeName);
        document.body.setAttribute("data-theme", themeName);

        try {
            localStorage.setItem(THEME_STORAGE_KEY, themeName);
        } catch (e) {
            // Storage quota or sandboxed iframe
        }

        // Update active theme label in UI if present
        const currentThemeLabel = document.getElementById("currentThemeLabel");
        if (currentThemeLabel) {
            const formatted = themeName.charAt(0).toUpperCase() + themeName.slice(1);
            currentThemeLabel.textContent = formatted;
        }

        // Update dropdown active checkmarks
        document.querySelectorAll(".theme-opt-btn").forEach((btn) => {
            if (btn.getAttribute("data-theme-val") === themeName) {
                btn.classList.add("active");
            } else {
                btn.classList.remove("active");
            }
        });
    }

    function initThemeSelector() {
        const themeBtn = document.getElementById("themeSelectorBtn");
        const themeMenu = document.getElementById("themeDropdownMenu");

        if (themeBtn && themeMenu) {
            themeBtn.addEventListener("click", function (e) {
                e.stopPropagation();
                themeMenu.classList.toggle("show");
            });

            document.querySelectorAll(".theme-opt-btn").forEach((optBtn) => {
                optBtn.addEventListener("click", function (e) {
                    e.stopPropagation();
                    const selectedTheme = this.getAttribute("data-theme-val");
                    applyTheme(selectedTheme);
                    themeMenu.classList.remove("show");
                });
            });

            // Close menu when clicking outside
            document.addEventListener("click", function (e) {
                if (!themeBtn.contains(e.target) && !themeMenu.contains(e.target)) {
                    themeMenu.classList.remove("show");
                }
            });
        }

        // Apply saved theme on boot
        applyTheme(getSavedTheme());
    }

    /* ==========================================================================
       2. PASSWORD VISIBILITY TOGGLE
       ========================================================================== */
    function initPasswordToggles() {
        const toggleButtons = document.querySelectorAll(".password-toggle");

        toggleButtons.forEach(function (button) {
            button.addEventListener("click", function () {
                const targetId = this.dataset.target;
                const input = document.getElementById(targetId);
                const icon = this.querySelector("i");

                if (!input) return;

                if (input.type === "password") {
                    input.type = "text";
                    if (icon) {
                        icon.classList.remove("bi-eye");
                        icon.classList.add("bi-eye-slash");
                    }
                    this.setAttribute("aria-label", "Hide password");
                } else {
                    input.type = "password";
                    if (icon) {
                        icon.classList.remove("bi-eye-slash");
                        icon.classList.add("bi-eye");
                    }
                    this.setAttribute("aria-label", "Show password");
                }
            });
        });
    }

    /* ==========================================================================
       3. PASSWORD STRENGTH METER (REGISTER ONLY)
       ========================================================================== */
    function initPasswordStrength() {
        const passwordInput = document.getElementById("password1");
        const strengthBox = document.getElementById("passwordStrength");
        const strengthText = document.getElementById("strengthText");

        if (!passwordInput || !strengthBox || !strengthText) return;

        passwordInput.addEventListener("input", function () {
            const password = this.value;
            let score = 0;

            if (password.length >= 8) score++;
            if (/[A-Z]/.test(password)) score++;
            if (/[a-z]/.test(password)) score++;
            if (/[0-9]/.test(password)) score++;
            if (/[^A-Za-z0-9]/.test(password)) score++;

            strengthBox.classList.remove("weak", "medium", "strong");

            if (password.length === 0) {
                strengthText.textContent = "";
                return;
            }

            if (score <= 2) {
                strengthBox.classList.add("weak");
                strengthText.textContent = "Weak password (add letters, numbers, symbols)";
            } else if (score <= 4) {
                strengthBox.classList.add("medium");
                strengthText.textContent = "Medium strength password";
            } else {
                strengthBox.classList.add("strong");
                strengthText.textContent = "Strong password";
            }
        });
    }

    /* ==========================================================================
       4. CONFIRM PASSWORD MATCH VALIDATION (REGISTER ONLY)
       ========================================================================== */
    function initConfirmPasswordValidation() {
        const passwordInput = document.getElementById("password1");
        const confirmPasswordInput = document.getElementById("password2");
        const passwordMatchMessage = document.getElementById("passwordMatchMessage");

        if (!passwordInput || !confirmPasswordInput || !passwordMatchMessage) return;

        function validatePasswordMatch() {
            const password = passwordInput.value;
            const confirmPassword = confirmPasswordInput.value;

            passwordMatchMessage.classList.remove("success", "error");
            confirmPasswordInput.classList.remove("is-valid", "is-invalid");

            if (confirmPassword.length === 0) {
                passwordMatchMessage.textContent = "";
                return;
            }

            if (password === confirmPassword) {
                passwordMatchMessage.classList.add("success");
                passwordMatchMessage.textContent = "✓ Passwords match";
                confirmPasswordInput.classList.add("is-valid");
            } else {
                passwordMatchMessage.classList.add("error");
                passwordMatchMessage.textContent = "✗ Passwords do not match";
                confirmPasswordInput.classList.add("is-invalid");
            }
        }

        passwordInput.addEventListener("input", validatePasswordMatch);
        confirmPasswordInput.addEventListener("input", validatePasswordMatch);
    }

    /* ==========================================================================
       5. FULL NAME REAL-TIME VALIDATION (REGISTER ONLY)
       ========================================================================== */
    function initFullNameValidation() {
        const fullNameInput = document.querySelector('input[name="first_name"]');
        const fullNameMessage = document.getElementById("fullNameMessage");

        if (!fullNameInput || !fullNameMessage) return;

        function validateFullName() {
            const name = fullNameInput.value.trim();

            fullNameMessage.classList.remove("success", "error");
            fullNameInput.classList.remove("is-valid", "is-invalid");

            if (name.length === 0) {
                fullNameMessage.textContent = "";
                return;
            }

            if (name.length < 3) {
                fullNameMessage.classList.add("error");
                fullNameMessage.textContent = "Name must contain at least 3 characters.";
                fullNameInput.classList.add("is-invalid");
                return;
            }

            if (/^[0-9]+$/.test(name)) {
                fullNameMessage.classList.add("error");
                fullNameMessage.textContent = "Name cannot contain only numbers.";
                fullNameInput.classList.add("is-invalid");
                return;
            }

            fullNameMessage.classList.add("success");
            fullNameMessage.textContent = "✓ Valid full name";
            fullNameInput.classList.add("is-valid");
        }

        fullNameInput.addEventListener("input", validateFullName);
    }

    /* ==========================================================================
       6. EMAIL REAL-TIME VALIDATION (COMMON TO REGISTER & LOGIN)
       ========================================================================== */
    function initEmailValidation() {
        const emailInput = document.querySelector('input[name="email"]');
        const emailMessage = document.getElementById("emailMessage");

        if (!emailInput || !emailMessage) return;

        function validateEmail() {
            const email = emailInput.value.trim();

            emailMessage.classList.remove("success", "error");
            emailInput.classList.remove("is-valid", "is-invalid");

            if (email.length === 0) {
                emailMessage.textContent = "";
                return;
            }

            const pattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

            if (!pattern.test(email)) {
                emailMessage.classList.add("error");
                emailMessage.textContent = "Invalid email address.";
                emailInput.classList.add("is-invalid");
                return;
            }

            emailMessage.classList.add("success");
            emailMessage.textContent = "✓ Valid email address";
            emailInput.classList.add("is-valid");
        }

        emailInput.addEventListener("input", validateEmail);
    }

    /* ==========================================================================
       7. FORM SUBMISSION & DOUBLE-SUBMIT PROTECTION
       ========================================================================== */
    function initFormSubmission() {
        const authForm = document.querySelector(".auth-form");
        const submitBtn =
            document.getElementById("registerBtn") ||
            document.getElementById("loginBtn") ||
            (authForm ? authForm.querySelector('button[type="submit"]') : null);

        if (authForm && submitBtn) {
            authForm.addEventListener("submit", function (e) {
                if (submitBtn.classList.contains("loading")) {
                    e.preventDefault();
                    return;
                }
                submitBtn.classList.add("loading");
            });
        }
    }

    /* ==========================================================================
       DOM READY INITIALIZATION
       ========================================================================== */
    document.addEventListener("DOMContentLoaded", function () {
        initThemeSelector();
        initPasswordToggles();
        initPasswordStrength();
        initConfirmPasswordValidation();
        initFullNameValidation();
        initEmailValidation();
        initFormSubmission();
    });
})();
