/**
 * meeting/static/meeting/js/settings.js
 * 
 * Dynamic Model Discovery & Live Model Validation for AI Settings.
 */

document.addEventListener("DOMContentLoaded", function () {
    const settingsForm = document.getElementById("ai-settings-form");
    const providerSelect = document.getElementById("id_provider");
    const apiKeyInput = document.getElementById("id_api_key");
    const modelNameInput = document.getElementById("id_model_name");
    const modelSelect = document.getElementById("model_select");
    const customModelContainer = document.getElementById("custom_model_container");
    const customModelInput = document.getElementById("custom_model_input");
    const btnDiscover = document.getElementById("btn-discover-models");
    const btnValidate = document.getElementById("btn-validate-model");
    const btnSave = settingsForm ? settingsForm.querySelector("button[type=submit]") : null;
    const statusContainer = document.getElementById("model_status_container");
    const statusBadge = document.getElementById("model_status_badge");
    const statusMessage = document.getElementById("model_status_message");
    const modelMetaContainer = document.getElementById("model_meta_container");

    const discoverUrl = window.AI_SETTINGS_CONFIG?.discoverUrl || "/settings/api/discover-models/";
    const validateUrl = window.AI_SETTINGS_CONFIG?.validateUrl || "/settings/api/validate-model/";
    let initialModelName = window.AI_SETTINGS_CONFIG?.currentModel || "";

    let discoveredModels = [];
    let isDiscovering = false;
    let isValidating = false;

    // Helper: get CSRF token
    function getCsrfToken() {
        const csrfInput = document.querySelector("[name=csrfmiddlewaretoken]");
        if (csrfInput) return csrfInput.value;
        const cookieMatch = document.cookie.match(/csrftoken=([^;]+)/);
        return cookieMatch ? cookieMatch[1] : "";
    }

    // Helper: set status UI
    function setValidationStatus(status, message, meta = null) {
        if (!statusContainer || !statusBadge || !statusMessage) return;

        statusContainer.classList.remove("d-none");
        statusMessage.textContent = message || "";

        let badgeHtml = "";
        switch (status) {
            case "AVAILABLE":
                badgeHtml = '<span class="badge bg-success text-white px-3 py-2 rounded-pill"><i class="bi bi-patch-check-fill me-1"></i> E2E Verified & Ready</span>';
                break;
            case "FALLBACK_VERIFIED":
                badgeHtml = '<span class="badge bg-success text-white px-3 py-2 rounded-pill"><i class="bi bi-arrow-repeat me-1"></i> Fallback Model Verified & Selected</span>';
                break;
            case "ALL_MODELS_FAILED":
                badgeHtml = '<span class="badge bg-danger text-white px-3 py-2 rounded-pill"><i class="bi bi-x-circle-fill me-1"></i> All Models Failed E2E</span>';
                break;
            case "ACCESS_DENIED":
                badgeHtml = '<span class="badge bg-danger text-white px-3 py-2 rounded-pill"><i class="bi bi-shield-x me-1"></i> Access Denied / Invalid API Key</span>';
                break;
            case "UNAVAILABLE":
                badgeHtml = '<span class="badge bg-warning text-dark px-3 py-2 rounded-pill"><i class="bi bi-exclamation-triangle-fill me-1"></i> Model Unavailable</span>';
                break;
            case "QUOTA_EXCEEDED":
                badgeHtml = '<span class="badge bg-danger text-white px-3 py-2 rounded-pill"><i class="bi bi-speedometer2 me-1"></i> Quota Exceeded</span>';
                break;
            case "RATE_LIMITED":
                badgeHtml = '<span class="badge bg-warning text-dark px-3 py-2 rounded-pill"><i class="bi bi-hourglass-split me-1"></i> Rate Limited</span>';
                break;
            case "TEMPORARILY_UNAVAILABLE":
                badgeHtml = '<span class="badge bg-warning text-dark px-3 py-2 rounded-pill"><i class="bi bi-pause-circle me-1"></i> Temporarily Unavailable / Busy</span>';
                break;
            case "VALIDATING":
                badgeHtml = '<span class="badge bg-primary text-white px-3 py-2 rounded-pill"><span class="spinner-border spinner-border-sm me-1" role="status"></span> Validating & Testing Sample Meeting...</span>';
                break;
            case "DISCOVERING":
                badgeHtml = '<span class="badge bg-primary text-white px-3 py-2 rounded-pill"><span class="spinner-border spinner-border-sm me-1" role="status"></span> Discovering Compatible Models...</span>';
                break;
            case "COMPATIBLE_UNTESTED":
            default:
                badgeHtml = '<span class="badge bg-secondary text-white px-3 py-2 rounded-pill"><i class="bi bi-info-circle me-1"></i> Compatible (Click Validate to Test)</span>';
                break;
        }
        statusBadge.innerHTML = badgeHtml;

        // Render meta pills if available
        if (modelMetaContainer) {
            if (meta) {
                let metaHtml = "";
                if (meta.source) {
                    const srcLabel = meta.source === "LIVE_API" ? "Live Discovery" : "Fallback Catalog";
                    metaHtml += `<span class="badge bg-light text-secondary border me-1"><i class="bi bi-broadcast"></i> ${srcLabel}</span>`;
                }
                if (meta.quality_score) {
                    metaHtml += `<span class="badge bg-light text-secondary border me-1">Quality: ${meta.quality_score}/100</span>`;
                }
                if (meta.speed_score) {
                    metaHtml += `<span class="badge bg-light text-secondary border me-1">Speed: ${meta.speed_score}/100</span>`;
                }
                if (meta.context_window) {
                    const ctxK = Math.round(meta.context_window / 1000);
                    metaHtml += `<span class="badge bg-light text-secondary border me-1">Context: ${ctxK}k tokens</span>`;
                }
                if (meta.is_recommended) {
                    metaHtml += `<span class="badge bg-success-subtle text-success border border-success me-1">⭐ Recommended</span>`;
                }
                modelMetaContainer.innerHTML = metaHtml;
                modelMetaContainer.classList.remove("d-none");
            } else {
                modelMetaContainer.innerHTML = "";
                modelMetaContainer.classList.add("d-none");
            }
        }
    }

    // Discover Models AJAX
    async function discoverModels(autoSelect = true) {
        if (!providerSelect || !modelSelect || isDiscovering) return;

        isDiscovering = true;
        const provider = providerSelect.value;
        const apiKey = apiKeyInput ? apiKeyInput.value.trim() : "";

        // UI loading state
        if (btnDiscover) {
            btnDiscover.disabled = true;
            btnDiscover.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Discovering...';
        }
        if (btnValidate) {
            btnValidate.disabled = true;
        }
        modelSelect.disabled = true;
        modelSelect.innerHTML = '<option value="">Discovering compatible models...</option>';
        setValidationStatus("DISCOVERING", `Querying compatible models for ${provider.toUpperCase()}...`);

        try {
            const response = await fetch(discoverUrl, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": getCsrfToken(),
                },
                body: JSON.stringify({
                    provider: provider,
                    api_key: apiKey,
                }),
            });

            const result = await response.json();

            if (result.success && result.data && Array.isArray(result.data.models) && result.data.models.length > 0) {
                discoveredModels = result.data.models;
                populateModelDropdown(discoveredModels, result.data.recommended_model_id, autoSelect);
            } else {
                const errMsg = result.error?.message || "No compatible models found for this provider.";
                modelSelect.innerHTML = `<option value="">${errMsg}</option>`;
                setValidationStatus("UNAVAILABLE", errMsg);
            }
        } catch (err) {
            modelSelect.innerHTML = '<option value="">Failed to connect for model discovery.</option>';
            setValidationStatus("UNKNOWN", "Network or server communication error during model discovery.");
        } finally {
            isDiscovering = false;
            if (btnDiscover) {
                btnDiscover.disabled = false;
                btnDiscover.innerHTML = '<i class="bi bi-arrow-clockwise me-1"></i> Discover Models';
            }
            if (btnValidate) {
                btnValidate.disabled = false;
            }
            modelSelect.disabled = false;
        }
    }

    // Populate model dropdown
    function populateModelDropdown(models, recommendedId, autoSelect) {
        modelSelect.innerHTML = "";

        let currentVal = initialModelName || (modelNameInput ? modelNameInput.value : "");
        let selectedOption = null;

        models.forEach((m) => {
            const option = document.createElement("option");
            option.value = m.id;
            let label = m.display_name || m.id;
            if (m.is_recommended) {
                label += " ⭐ (Recommended)";
            }
            option.textContent = label;

            // Check if matches current setting
            if (currentVal && m.id === currentVal) {
                option.selected = true;
                selectedOption = m;
            }
            modelSelect.appendChild(option);
        });

        // Add custom entry option
        const customOption = document.createElement("option");
        customOption.value = "__custom__";
        customOption.textContent = "✏️ Enter Custom Model ID...";
        modelSelect.appendChild(customOption);

        // Auto-select recommended model if none matched
        if (!selectedOption && autoSelect && recommendedId) {
            const recModel = models.find((m) => m.id === recommendedId);
            if (recModel) {
                modelSelect.value = recModel.id;
                selectedOption = recModel;
            }
        }

        // If still nothing, pick first
        if (!selectedOption && models.length > 0) {
            modelSelect.value = models[0].id;
            selectedOption = models[0];
        }

        handleModelSelectChange();
    }

    // Handle Model Selection Change
    function handleModelSelectChange() {
        const selectedValue = modelSelect.value;

        if (selectedValue === "__custom__") {
            if (customModelContainer) customModelContainer.classList.remove("d-none");
            if (customModelInput) {
                customModelInput.focus();
                if (modelNameInput) {
                    modelNameInput.value = customModelInput.value.trim();
                }
            }
            setValidationStatus("COMPATIBLE_UNTESTED", "Custom model selected. Click Validate Model to test access.");
        } else {
            if (customModelContainer) customModelContainer.classList.add("d-none");
            if (modelNameInput) {
                modelNameInput.value = selectedValue;
            }
            const foundModel = discoveredModels.find((m) => m.id === selectedValue);
            if (foundModel) {
                setValidationStatus(
                    foundModel.status || "COMPATIBLE_UNTESTED",
                    foundModel.status_message || "Ready for validation.",
                    foundModel
                );
            }
        }
    }

    // Validate Model AJAX
    async function validateSelectedModel() {
        if (isValidating) return;

        const provider = providerSelect ? providerSelect.value : "gemini";
        const modelId = modelNameInput ? modelNameInput.value.trim() : (modelSelect ? modelSelect.value : "");
        const apiKey = apiKeyInput ? apiKeyInput.value.trim() : "";

        if (!modelId || modelId === "__custom__") {
            setValidationStatus("UNAVAILABLE", "Please select or enter a valid model ID before validating.");
            return;
        }

        isValidating = true;
        // UI loading
        if (btnValidate) {
            btnValidate.disabled = true;
            btnValidate.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Validating...';
        }
        if (btnDiscover) {
            btnDiscover.disabled = true;
        }
        setValidationStatus("VALIDATING", `Validating access & testing full meeting workflow for '${modelId}' on sample video...`);

        const candidateIds = (Array.isArray(discoveredModels) && discoveredModels.length > 0)
            ? discoveredModels.map((m) => m.id)
            : [];

        try {
            const response = await fetch(validateUrl, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": getCsrfToken(),
                },
                body: JSON.stringify({
                    provider: provider,
                    model_id: modelId,
                    api_key: apiKey,
                    candidate_models: candidateIds,
                }),
            });

            const result = await response.json();
            const selectedModelObj = discoveredModels.find((m) => m.id === modelId);

            if (result.success && result.data) {
                const verifiedModel = result.data.verified_model || result.data.model_id;
                const fallbackUsed = result.data.fallback_used === true;

                if (fallbackUsed) {
                    if (modelSelect && verifiedModel) {
                        modelSelect.value = verifiedModel;
                    }
                    if (modelNameInput && verifiedModel) {
                        modelNameInput.value = verifiedModel;
                    }
                    const verifiedModelObj = discoveredModels.find((m) => m.id === verifiedModel) || selectedModelObj;
                    setValidationStatus("FALLBACK_VERIFIED", result.data.message, verifiedModelObj);
                } else {
                    setValidationStatus(
                        result.data.status || "AVAILABLE",
                        result.data.message || `Model '${modelId}' passed full end-to-end meeting transcription and summary validation!`,
                        selectedModelObj
                    );
                }
            } else {
                const isAllFailed = (result.error?.stage === "all_models_failed" || result.data?.stage === "all_models_failed");
                if (isAllFailed) {
                    setValidationStatus(
                        "ALL_MODELS_FAILED",
                        result.error?.message || "No discovered model passed the end-to-end meeting validation.",
                        selectedModelObj
                    );
                } else {
                    const errCode = result.error?.code || result.data?.status || "UNAVAILABLE";
                    const errMsg = result.error?.message || `E2E validation failed for '${modelId}'.`;
                    setValidationStatus(errCode, errMsg, selectedModelObj);
                }
            }
        } catch (err) {
            setValidationStatus("UNKNOWN", "Network or server communication error during model validation.");
        } finally {
            isValidating = false;
            if (btnValidate) {
                btnValidate.disabled = false;
                btnValidate.innerHTML = '<i class="bi bi-shield-check me-1"></i> Validate Model';
            }
            if (btnDiscover) {
                btnDiscover.disabled = false;
            }
        }
    }

    // Form Submit handling with double-submit protection
    if (settingsForm) {
        settingsForm.addEventListener("submit", function (e) {
            const selectedValue = modelSelect ? modelSelect.value : "";
            if (selectedValue === "__custom__") {
                if (customModelInput && customModelInput.value.trim()) {
                    if (modelNameInput) modelNameInput.value = customModelInput.value.trim();
                } else {
                    e.preventDefault();
                    alert("Please enter a custom model ID before saving.");
                    if (customModelInput) customModelInput.focus();
                    return;
                }
            } else if (modelSelect && modelSelect.value) {
                if (modelNameInput) modelNameInput.value = modelSelect.value;
            }

            if (btnSave) {
                btnSave.disabled = true;
                btnSave.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Saving Settings...';
            }
        });
    }

    // Event Listeners
    if (providerSelect) {
        providerSelect.addEventListener("change", function () {
            initialModelName = "";
            discoverModels(true);
        });
    }

    if (btnDiscover) {
        btnDiscover.addEventListener("click", function () {
            discoverModels(false);
        });
    }

    if (modelSelect) {
        modelSelect.addEventListener("change", function () {
            handleModelSelectChange();
        });
    }

    if (customModelInput) {
        customModelInput.addEventListener("input", function () {
            if (modelNameInput) {
                modelNameInput.value = this.value.trim();
            }
        });
    }

    if (btnValidate) {
        btnValidate.addEventListener("click", function () {
            validateSelectedModel();
        });
    }

    // Initial load: trigger discovery if provider is selected
    if (providerSelect && providerSelect.value) {
        discoverModels(false);
    }
});

