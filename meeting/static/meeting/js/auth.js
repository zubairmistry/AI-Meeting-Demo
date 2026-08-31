/*
====================================
PASSWORD TOGGLE
====================================
*/

document.addEventListener("DOMContentLoaded", function () {

    const toggleButtons = document.querySelectorAll(".password-toggle");

    toggleButtons.forEach(function (button) {

        button.addEventListener("click", function () {

            const targetId = this.dataset.target;

            const input = document.getElementById(targetId);

            const icon = this.querySelector("i");

            if (!input) return;

            if (input.type === "password") {

                input.type = "text";

                icon.classList.remove("bi-eye");

                icon.classList.add("bi-eye-slash");

            } else {

                input.type = "password";

                icon.classList.remove("bi-eye-slash");

                icon.classList.add("bi-eye");

            }

        });

    });

});

/*
====================================
PASSWORD STRENGTH
====================================
*/

const passwordInput = 
    document.getElementById("password1") ||
    document.getElementById("password");

const strengthBox = document.getElementById("passwordStrength");
const strengthText = document.getElementById("strengthText");

if (passwordInput && strengthBox && strengthText) {

    passwordInput.addEventListener("input", function () {

        const password = this.value;

        let score = 0;

        // Minimum Length
        if (password.length >= 8) score++;

        // Uppercase
        if (/[A-Z]/.test(password)) score++;

        // Lowercase
        if (/[a-z]/.test(password)) score++;

        // Number
        if (/[0-9]/.test(password)) score++;

        // Special Character
        if (/[^A-Za-z0-9]/.test(password)) score++;

        strengthBox.classList.remove(
            "weak",
            "medium",
            "strong"
        );

        if (password.length === 0) {

            strengthText.textContent = "Password Strength";

            return;

        }

        if (score <= 2) {

            strengthBox.classList.add("weak");

            strengthText.textContent = "Weak Password";

        }
        else if (score <= 4) {

            strengthBox.classList.add("medium");

            strengthText.textContent = "Medium Password";

        }
        else {

            strengthBox.classList.add("strong");

            strengthText.textContent = "Strong Password";

        }

    });

}

/*
====================================
CONFIRM PASSWORD VALIDATION
====================================
*/

const confirmPasswordInput = document.getElementById("password2");
const passwordMatchMessage = document.getElementById("passwordMatchMessage");

function validatePasswordMatch() {

    if (
        !passwordInput ||
        !confirmPasswordInput ||
        !passwordMatchMessage
    ) {
        return;
    }

    const password = passwordInput.value;
    const confirmPassword = confirmPasswordInput.value;

    passwordMatchMessage.classList.remove(
        "success",
        "error"
    );

    // Empty field
    if (confirmPassword.length === 0) {

        passwordMatchMessage.textContent = "";

        return;

    }

    if (password === confirmPassword) {

        passwordMatchMessage.classList.add("success");

        passwordMatchMessage.textContent =
            "✓ Passwords match";

    }
    else {

        passwordMatchMessage.classList.add("error");

        passwordMatchMessage.textContent =
            "✗ Passwords do not match";

    }

}

if (
    passwordInput &&
    confirmPasswordInput &&
    passwordMatchMessage
) {

    passwordInput.addEventListener(
        "input",
        validatePasswordMatch
    );

    confirmPasswordInput.addEventListener(
        "input",
        validatePasswordMatch
    );

}

/*
====================================
FULL NAME VALIDATION
====================================
*/

const fullNameInput = document.querySelector(
    'input[name="first_name"]'
);

const fullNameMessage =
    document.getElementById("fullNameMessage");

function validateFullName() {

    if (!fullNameInput || !fullNameMessage)
        return;

    const name = fullNameInput.value.trim();

    fullNameMessage.classList.remove(
        "success",
        "error"
    );

    // Empty
    if (name.length === 0) {

        fullNameMessage.textContent = "";

        return;

    }

    // Minimum length
    if (name.length < 3) {

        fullNameMessage.classList.add("error");

        fullNameMessage.textContent =
            "Name must contain at least 3 characters.";

        return;

    }

    // Numbers only
    if (/^[0-9]+$/.test(name)) {

        fullNameMessage.classList.add("error");

        fullNameMessage.textContent =
            "Name cannot contain only numbers.";

        return;

    }

    // Valid
    fullNameMessage.classList.add("success");

    fullNameMessage.textContent =
        "✓ Valid full name";

}

if (fullNameInput) {

    fullNameInput.addEventListener(
        "input",
        validateFullName
    );

}

/*
====================================
EMAIL VALIDATION
====================================
*/

const emailInput =
    document.querySelector(
        'input[name="email"]'
    );

const emailMessage =
    document.getElementById(
        "emailMessage"
    );

function validateEmail() {

    if (!emailInput || !emailMessage)
        return;

    const email =
        emailInput.value.trim();

    emailMessage.classList.remove(
        "success",
        "error"
    );

    if (email.length === 0) {

        emailMessage.textContent = "";

        return;

    }

    const pattern =
        /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

    if (!pattern.test(email)) {

        emailMessage.classList.add("error");

        emailMessage.textContent =
            "Invalid email address.";

        return;

    }

    emailMessage.classList.add("success");

    emailMessage.textContent =
        "✓ Valid email address";

}

if (emailInput) {

    emailInput.addEventListener(
        "input",
        validateEmail
    );

}

/*
====================================
AUTH FORM LOADING
====================================
*/

const authForm = document.querySelector(".auth-form");

const authButton =
    document.getElementById("registerBtn");

if (authForm && authButton) {

    authForm.addEventListener("submit", function () {

        authButton.classList.add("loading");

    });

}