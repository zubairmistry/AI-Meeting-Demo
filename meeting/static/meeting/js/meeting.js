/* ==========================================================================
   AI MEETING ASSISTANT — WORKSPACE, ASYNC POLLING & GLOBAL THEME CONTROLLER
   ========================================================================== */

(function () {
    "use strict";

    /* ==========================================================================
       1. GLOBAL THEME ENGINE (5 ENTERPRISE THEMES)
       ========================================================================== */
    const THEME_STORAGE_KEY = "ai_meeting_theme";
    const VALID_THEMES = ["classic", "light", "dark", "neon", "enterprise"];

    function getSavedTheme() {
        try {
            const saved = localStorage.getItem(THEME_STORAGE_KEY);
            if (saved && VALID_THEMES.includes(saved)) {
                return saved;
            }
        } catch (e) {}
        return "classic";
    }

    function applyTheme(themeName) {
        if (!VALID_THEMES.includes(themeName)) themeName = "classic";
        document.documentElement.setAttribute("data-theme", themeName);
        document.body.setAttribute("data-theme", themeName);

        try {
            localStorage.setItem(THEME_STORAGE_KEY, themeName);
        } catch (e) {}

        const nameMap = {
            classic: "Classic",
            light: "Light",
            dark: "Dark",
            neon: "AI Neon",
            enterprise: "Enterprise"
        };
        const displayName = nameMap[themeName] || (themeName.charAt(0).toUpperCase() + themeName.slice(1));

        const label = document.getElementById("currentThemeLabel");
        if (label) label.textContent = displayName;

        const labelGuest = document.getElementById("currentThemeLabelGuest");
        if (labelGuest) labelGuest.textContent = displayName;

        const oldLabel = document.getElementById("navbarThemeLabel");
        if (oldLabel) oldLabel.textContent = displayName;

        document.querySelectorAll(".theme-opt-btn").forEach((btn) => {
            if (btn.getAttribute("data-theme-val") === themeName) {
                btn.classList.add("active");
            } else {
                btn.classList.remove("active");
            }
        });
    }

    function initGlobalThemeSelector() {
        const pairs = [
            { btn: document.getElementById("themeSelectorBtn"), menu: document.getElementById("themeDropdownMenu") },
            { btn: document.getElementById("themeSelectorBtnGuest"), menu: document.getElementById("themeDropdownMenuGuest") }
        ];

        pairs.forEach(({ btn, menu }) => {
            if (btn && menu) {
                btn.addEventListener("click", function (e) {
                    e.preventDefault();
                    e.stopPropagation();
                    const isOpen = menu.classList.contains("show");
                    document.querySelectorAll(".theme-dropdown-menu").forEach(m => m.classList.remove("show"));
                    if (!isOpen) {
                        menu.classList.add("show");
                    }
                });
            }
        });

        document.querySelectorAll(".theme-opt-btn").forEach((optBtn) => {
            optBtn.addEventListener("click", function (e) {
                e.preventDefault();
                e.stopPropagation();
                const selectedTheme = this.getAttribute("data-theme-val");
                applyTheme(selectedTheme);
                document.querySelectorAll(".theme-dropdown-menu").forEach(m => m.classList.remove("show"));
            });
        });

        document.addEventListener("click", function (e) {
            document.querySelectorAll(".theme-dropdown-menu").forEach(menu => {
                const wrapper = menu.closest(".theme-selector-wrapper");
                if (!wrapper || !wrapper.contains(e.target)) {
                    menu.classList.remove("show");
                }
            });
        });

        applyTheme(getSavedTheme());
    }

    /* ==========================================================================
       2. WORKSPACE CONSTANTS & HELPERS
       ========================================================================== */
    const ALLOWED_EXTENSIONS = [".mp4", ".mov", ".avi", ".mkv", ".mp3", ".wav", ".m4a"];
    const DEFAULT_MAX_SIZE_BYTES = 52428800; // 50 MB fallback

    function getMaxUploadSizeBytes() {
        const dropzone = document.getElementById("meetingDropzone");
        if (dropzone && dropzone.dataset) {
            const raw = dropzone.dataset.maxUploadSize || dropzone.dataset.maxBytes;
            if (raw) {
                const parsed = parseInt(raw, 10);
                if (!isNaN(parsed) && parsed > 0) {
                    return parsed;
                }
            }
        }
        return DEFAULT_MAX_SIZE_BYTES;
    }

    function formatBytes(bytes) {
        if (bytes === 0) return "0 Bytes";
        const k = 1024;
        const sizes = ["Bytes", "KB", "MB", "GB"];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
    }

    function formatDurationSecs(seconds) {
        if (seconds === null || seconds === undefined || isNaN(seconds)) return "—";
        const totalSec = Math.max(0, Math.floor(Number(seconds)));
        const hours = Math.floor(totalSec / 3600);
        const minutes = Math.floor((totalSec % 3600) / 60);
        const secs = totalSec % 60;

        if (hours > 0) {
            return `${String(hours).padStart(2, "0")} hr ${String(minutes).padStart(2, "0")} min ${String(secs).padStart(2, "0")} sec`;
        } else if (minutes > 0) {
            return `${String(minutes).padStart(2, "0")} min ${String(secs).padStart(2, "0")} sec`;
        } else {
            return `${String(secs).padStart(2, "0")} sec`;
        }
    }

    function getFormattedTime() {
        const now = new Date();
        const h = String(now.getHours()).padStart(2, "0");
        const m = String(now.getMinutes()).padStart(2, "0");
        const s = String(now.getSeconds()).padStart(2, "0");
        return `${h}:${m}:${s}`;
    }

    function getFormattedDate() {
        const now = new Date();
        const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
        const day = String(now.getDate()).padStart(2, "0");
        const month = months[now.getMonth()];
        const year = now.getFullYear();
        return `${day} ${month} ${year}`;
    }

    /* ==========================================================================
       3. ASYNC STATE CONTROLLER & REAL-TIME POLLING ENGINE
       ========================================================================== */
    let isProcessing = false;
    let activeMeetingId = null;
    let pollingTimer = null;
    let consecutiveNetworkErrors = 0;
    let lastLoggedStage = null;

    function stopPolling() {
        if (pollingTimer) {
            clearTimeout(pollingTimer);
            pollingTimer = null;
        }
        activeMeetingId = null;
    }

    function appendActivityLog(message, iconClass = "bi-check-circle text-success") {
        const stream = document.getElementById("activityLogStream");
        if (!stream) return;

        const emptyPlaceholder = document.getElementById("activityLogEmpty");
        if (emptyPlaceholder) {
            emptyPlaceholder.remove();
        }

        const entry = document.createElement("div");
        entry.className = "d-flex align-items-start gap-2 activity-log-entry mb-1";
        entry.innerHTML = `
            <span class="text-muted small font-monospace">[${getFormattedTime()}]</span>
            <i class="bi ${iconClass} mt-1"></i>
            <span>${message}</span>
        `;
        stream.appendChild(entry);
        stream.scrollTop = stream.scrollHeight;
    }

    function getStageDisplayName(stage) {
        switch (stage) {
            case "queued": return "Queued for processing";
            case "extracting_audio": return "Extracting Audio (MP3 16kHz)...";
            case "uploading_to_ai": return "Uploading Audio to Gemini...";
            case "waiting_for_ai": return "Processing Audio with AI...";
            case "transcribing": return "Synthesizing Verbatim Transcript...";
            case "generating_summary": return "Synthesizing AI Summary Report...";
            case "completed": return "Analysis Complete";
            case "failed": return "Processing Failed";
            default: return "Processing Meeting...";
        }
    }

    function getStageLogMessage(stage) {
        switch (stage) {
            case "queued": return "Meeting queued in background worker";
            case "extracting_audio": return "Extracting audio track (32kbps MP3 / 16kHz mono)";
            case "uploading_to_ai": return "Uploading audio asset to Gemini API";
            case "waiting_for_ai": return "Remote audio indexing in progress";
            case "transcribing": return "Generating verbatim meeting transcript";
            case "generating_summary": return "Synthesizing executive summary & action items";
            case "completed": return "Processing complete! All insights ready.";
            case "failed": return "Processing interrupted";
            default: return `Stage transition: ${stage}`;
        }
    }

    function updateStepperUI(stage, status) {
        const stages = [
            document.getElementById("stepperStage1"),
            document.getElementById("stepperStage2"),
            document.getElementById("stepperStage3"),
            document.getElementById("stepperStage4"),
            document.getElementById("stepperStage5"),
            document.getElementById("stepperStage6"),
            document.getElementById("stepperStage7"),
            document.getElementById("stepperStage8")
        ];
        const connectors = [
            document.getElementById("stepperConnector1"),
            document.getElementById("stepperConnector2"),
            document.getElementById("stepperConnector3"),
            document.getElementById("stepperConnector4"),
            document.getElementById("stepperConnector5"),
            document.getElementById("stepperConnector6"),
            document.getElementById("stepperConnector7")
        ];

        let activeIndex = 0; // 0-based
        if (status === "completed" || stage === "completed") {
            activeIndex = 7;
        } else if (stage === "generating_summary") {
            activeIndex = 5;
        } else if (stage === "transcribing") {
            activeIndex = 3;
        } else if (stage === "waiting_for_ai" || stage === "uploading_to_ai") {
            activeIndex = 3;
        } else if (stage === "extracting_audio") {
            activeIndex = 2;
        } else if (stage === "queued") {
            activeIndex = 1;
        }

        stages.forEach((node, idx) => {
            if (!node) return;
            node.classList.remove("completed", "active");
            if (idx < activeIndex) {
                node.classList.add("completed");
            } else if (idx === activeIndex) {
                if (status === "completed") {
                    node.classList.add("completed", "active");
                } else {
                    node.classList.add("active");
                }
            }
        });

        connectors.forEach((conn, idx) => {
            if (!conn) return;
            conn.classList.remove("active");
            if (idx < activeIndex) {
                conn.classList.add("active");
            }
        });
    }

    function ensureTranscriptSection(transcriptText) {
        let transcriptBox = document.getElementById("meetingTranscriptContent");
        if (!transcriptBox) {
            const container = document.getElementById("transcriptContainer");
            if (!container) return;

            container.innerHTML = `
                <div id="sectionTranscript" class="meeting-card-3d mb-3">
                    <div class="meeting-section-header">
                        <div>
                            <h3 class="meeting-section-title">
                                <span class="step-num-badge">3</span>
                                <span>Transcript (Live Preview)</span>
                                <span class="badge px-3 py-1 fw-bold rounded-pill small ms-2" style="background: rgba(99, 102, 241, 0.15); color: var(--primary); border: 1px solid var(--primary-glow); font-size: 0.7rem;">Verbatim</span>
                            </h3>
                            <p class="meeting-section-subtitle">
                                Full verbatim transcription synthesized from 16kHz audio
                            </p>
                        </div>
                        <div class="d-flex align-items-center gap-2">
                            <button type="button" id="btnCopyTranscript" class="btn-action-pill">
                                <i class="bi bi-clipboard"></i> Copy Transcript
                            </button>
                            <button type="button" id="btnDownloadTranscriptTxt" class="btn-action-pill">
                                <i class="bi bi-download"></i> Download TXT
                            </button>
                        </div>
                    </div>
                    <div class="meeting-output-box">
                        <pre id="meetingTranscriptContent" class="meeting-output-pre"></pre>
                    </div>
                </div>
            `;
            initActionButtons();
            transcriptBox = document.getElementById("meetingTranscriptContent");
        }

        if (transcriptBox && transcriptText) {
            transcriptBox.textContent = transcriptText;
        }
    }

    function ensureReportSection(reportText) {
        let reportBox = document.getElementById("meetingReportContent");
        if (!reportBox) {
            const container = document.getElementById("reportContainer");
            if (!container) return;

            container.innerHTML = `
                <div id="sectionReport" class="meeting-card-3d mb-3">
                    <div class="meeting-section-header">
                        <div>
                            <h3 class="meeting-section-title">
                                <span class="step-num-badge">4</span>
                                <span>AI Executive Summary</span>
                                <span class="badge px-3 py-1 fw-bold rounded-pill small ms-2" style="background: rgba(16, 185, 129, 0.15); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.3); font-size: 0.7rem;">Synthesis Complete</span>
                            </h3>
                            <p class="meeting-section-subtitle">
                                Executive summary, key takeaways, and action items
                            </p>
                        </div>
                        <div class="d-flex align-items-center gap-2">
                            <button type="button" id="btnCopyReport" class="btn-action-pill">
                                <i class="bi bi-clipboard"></i> Copy Summary
                            </button>
                            <button type="button" id="btnDownloadReportTxt" class="btn-action-pill">
                                <i class="bi bi-download"></i> Download Report
                            </button>
                        </div>
                    </div>
                    <div class="meeting-output-box">
                        <pre id="meetingReportContent" class="meeting-output-pre"></pre>
                    </div>
                </div>
            `;
            initActionButtons();
            reportBox = document.getElementById("meetingReportContent");
        }

        if (reportBox && reportText) {
            reportBox.textContent = reportText;
        }
    }

    /**
     * Phase 2.1 — Step 3: Frontend JavaScript Live Sidebar Synchronization.
     * Synchronizes Right Sidebar Meeting Information (Status, Duration, Last Used)
     * using live polling data from GET /meeting/status/<meeting_id>/.
     * Tolerates null/missing fields, missing DOM nodes, and unknown statuses defensively.
     */
    function syncSidebarMeetingInfo(data) {
        if (!data || typeof data !== "object") return;

        try {
            // 1. Synchronize Processing Status (#infoProcessingStatus)
            const infoStatus = document.getElementById("infoProcessingStatus");
            if (infoStatus && data.status) {
                const s = String(data.status).toLowerCase().trim();
                if (s === "completed") {
                    infoStatus.textContent = "COMPLETED";
                    infoStatus.className = "info-item-value text-success fw-bold";
                } else if (s === "failed") {
                    infoStatus.textContent = "FAILED";
                    infoStatus.className = "info-item-value text-danger fw-bold";
                } else if (s === "processing" || s === "running" || s === "queued") {
                    infoStatus.textContent = "RUNNING";
                    infoStatus.className = "info-item-value text-primary fw-bold";
                } else if (s === "ready") {
                    infoStatus.textContent = "READY";
                    infoStatus.className = "info-item-value text-muted";
                } else {
                    infoStatus.textContent = s.toUpperCase();
                    infoStatus.className = "info-item-value text-primary fw-bold";
                }
            }

            // 2. Synchronize Runtime Duration (#infoRuntimeDuration)
            if (data.duration !== undefined && data.duration !== null && data.duration !== "") {
                const numDuration = Number(data.duration);
                if (!isNaN(numDuration) && numDuration >= 0) {
                    const durationEl = document.getElementById("infoRuntimeDuration");
                    if (durationEl) {
                        durationEl.textContent = formatDurationSecs(numDuration);
                    }
                }
            }

            // 3. Synchronize Last Used Date (#infoLastUsed) on completion
            if (data.status === "completed") {
                const lastUsedEl = document.getElementById("infoLastUsed");
                if (lastUsedEl) {
                    const currentVal = (lastUsedEl.textContent || "").trim();
                    if (!currentVal || currentVal === "—" || currentVal === "No recent meetings") {
                        lastUsedEl.textContent = getFormattedDate();
                    }
                }
            }

            // Note on Storage Display (Requirement 4):
            // The status endpoint (/meeting/status/<id>/) returns per-meeting data,
            // but does not expose user-aggregate storage metrics. To avoid ungrounded
            // client-side calculations, the server-rendered storage metrics are preserved.
        } catch (syncErr) {
            console.warn("Sidebar synchronization non-fatal error:", syncErr);
        }
    }

    async function pollMeetingStatus(meetingId) {
        if (!isProcessing || activeMeetingId !== meetingId) return;

        try {
            const response = await fetch(`/meeting/status/${meetingId}/`, {
                headers: {
                    "X-Requested-With": "XMLHttpRequest",
                    "Accept": "application/json"
                }
            });

            if (response.status === 200) {
                consecutiveNetworkErrors = 0;
                const result = await response.json();

                if (result.success && result.data) {
                    const data = result.data;
                    const stage = data.stage;
                    const status = data.status;
                    const progress = data.progress_percentage || 0;

                    // 1. Update Progress Bar & Stage Label
                    const progressBar = document.getElementById("meetingProgressBar");
                    const percentLabel = document.getElementById("processingPercentLabel");
                    const stageLabel = document.getElementById("processingStageLabel");

                    if (progressBar) {
                        progressBar.style.width = `${progress}%`;
                        progressBar.setAttribute("aria-valuenow", String(progress));
                    }
                    if (percentLabel) percentLabel.textContent = `${progress}%`;
                    if (stageLabel) stageLabel.textContent = getStageDisplayName(stage);

                    // 2. Update Stepper
                    updateStepperUI(stage, status);

                    // 3. Update Activity Log on Stage Change
                    if (stage && stage !== lastLoggedStage) {
                        appendActivityLog(getStageLogMessage(stage), "bi-arrow-right-circle text-primary");
                        lastLoggedStage = stage;
                    }

                    // 4. Update Transcript if available
                    if (data.has_transcript && data.transcript) {
                        ensureTranscriptSection(data.transcript);
                    }

                    // 5. Update Report if available
                    if (data.has_ai_report && data.ai_report) {
                        ensureReportSection(data.ai_report);
                    }

                    // 6. Synchronize Right Sidebar Meeting Information (Phase 2.1 Step 3)
                    syncSidebarMeetingInfo(data);

                    // 7. Check Terminal State
                    if (status === "completed") {
                        stopPolling();
                        isProcessing = false;

                        if (progressBar) {
                            progressBar.style.width = "100%";
                            progressBar.setAttribute("aria-valuenow", "100");
                            progressBar.classList.remove("progress-bar-animated");
                        }
                        if (percentLabel) percentLabel.textContent = "100%";
                        if (stageLabel) stageLabel.textContent = "Analysis Complete";

                        const statusBadge = document.getElementById("processingStatusBadge");
                        if (statusBadge) {
                            statusBadge.textContent = "100% Completed";
                            statusBadge.style.background = "rgba(16, 185, 129, 0.15)";
                            statusBadge.style.color = "#10b981";
                            statusBadge.style.border = "1px solid rgba(16, 185, 129, 0.3)";
                        }

                        const infoStatus = document.getElementById("infoProcessingStatus");
                        if (infoStatus) {
                            infoStatus.textContent = "COMPLETED";
                            infoStatus.className = "info-item-value text-success fw-bold";
                        }

                        appendActivityLog("Meeting processing completed successfully!", "bi-check2-all text-success");

                        const analyzeBtn = document.getElementById("btnAnalyzeMeeting");
                        if (analyzeBtn) {
                            analyzeBtn.classList.remove("loading");
                            analyzeBtn.disabled = false;
                            analyzeBtn.innerHTML = `<i class="bi bi-stars"></i><span>Analyze Meeting with AI</span>`;
                        }
                        return;
                    } else if (status === "failed") {
                        stopPolling();
                        isProcessing = false;

                        if (progressBar) {
                            progressBar.classList.remove("bg-primary", "progress-bar-animated");
                            progressBar.classList.add("bg-danger");
                        }
                        if (stageLabel) stageLabel.textContent = "Processing Failed";

                        const statusBadge = document.getElementById("processingStatusBadge");
                        if (statusBadge) {
                            statusBadge.textContent = "Failed";
                            statusBadge.style.background = "rgba(239, 68, 68, 0.15)";
                            statusBadge.style.color = "#ef4444";
                            statusBadge.style.border = "1px solid rgba(239, 68, 68, 0.3)";
                        }

                        const infoStatus = document.getElementById("infoProcessingStatus");
                        if (infoStatus) {
                            infoStatus.textContent = "FAILED";
                            infoStatus.className = "info-item-value text-danger fw-bold";
                        }

                        const errMsg = data.error_message || "An error occurred during meeting analysis.";
                        const alertBox = document.getElementById("fileValidationAlert");
                        if (alertBox) {
                            alertBox.innerHTML = `
                                <div class="d-flex align-items-center justify-content-between flex-wrap gap-2">
                                    <div><i class="bi bi-exclamation-triangle-fill me-2"></i> ${errMsg}</div>
                                    <button type="button" id="btnRetryActiveMeeting" class="btn btn-sm btn-outline-danger rounded-pill fw-bold px-3 py-1">
                                        <i class="bi bi-arrow-clockwise me-1"></i> Retry Analysis
                                    </button>
                                </div>
                            `;
                            alertBox.classList.remove("d-none");
                            const retryBtn = document.getElementById("btnRetryActiveMeeting");
                            if (retryBtn) {
                                retryBtn.addEventListener("click", function (e) {
                                    e.preventDefault();
                                    retryMeeting(meetingId);
                                });
                            }
                        }
                        appendActivityLog(`Failed: ${errMsg}`, "bi-x-circle text-danger");

                        const analyzeBtn = document.getElementById("btnAnalyzeMeeting");
                        if (analyzeBtn) {
                            analyzeBtn.classList.remove("loading");
                            analyzeBtn.disabled = false;
                            analyzeBtn.innerHTML = `<i class="bi bi-stars"></i><span>Analyze Meeting with AI</span>`;
                        }
                        return;
                    }
                }
            } else if (response.status === 401 || response.status === 403) {
                stopPolling();
                isProcessing = false;
                appendActivityLog("Authentication required. Please refresh or log in again.", "bi-lock text-warning");
                return;
            } else if (response.status === 404) {
                stopPolling();
                isProcessing = false;
                appendActivityLog("Meeting task was not found.", "bi-exclamation-octagon text-danger");
                return;
            }
        } catch (err) {
            consecutiveNetworkErrors++;
            console.warn("Status polling network retry:", err);
            if (consecutiveNetworkErrors === 6) {
                appendActivityLog("Network connectivity issue detected. Continuing to retry in background...", "bi-wifi-off text-warning");
            }
        }

        // Schedule next poll interval (approx 2000 ms)
        if (isProcessing && activeMeetingId === meetingId) {
            pollingTimer = setTimeout(() => pollMeetingStatus(meetingId), 2000);
        }
    }

    function getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== "") {
            const cookies = document.cookie.split(";");
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + "=")) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }

    async function retryMeeting(meetingId) {
        if (isProcessing) return;
        isProcessing = true;
        activeMeetingId = meetingId;
        lastLoggedStage = null;
        consecutiveNetworkErrors = 0;

        const validationAlert = document.getElementById("fileValidationAlert");
        if (validationAlert) {
            validationAlert.classList.add("d-none");
            validationAlert.innerHTML = "";
        }

        const analyzeBtn = document.getElementById("btnAnalyzeMeeting");
        if (analyzeBtn) {
            analyzeBtn.classList.add("loading");
            analyzeBtn.disabled = true;
            analyzeBtn.innerHTML = `
                <span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>
                <span>Retrying Processing with AI...</span>
            `;
        }

        const progressBar = document.getElementById("meetingProgressBar");
        const percentLabel = document.getElementById("processingPercentLabel");
        const stageLabel = document.getElementById("processingStageLabel");
        const statusBadge = document.getElementById("processingStatusBadge");
        const infoStatus = document.getElementById("infoProcessingStatus");

        if (progressBar) {
            progressBar.style.width = "10%";
            progressBar.setAttribute("aria-valuenow", "10");
            progressBar.className = "progress-bar bg-primary progress-bar-striped progress-bar-animated";
        }
        if (percentLabel) percentLabel.textContent = "10%";
        if (stageLabel) stageLabel.textContent = "Resuming processing from checkpoint...";
        if (statusBadge) {
            statusBadge.textContent = "In Progress";
            statusBadge.style.background = "rgba(99, 102, 241, 0.15)";
            statusBadge.style.color = "var(--primary)";
            statusBadge.style.border = "1px solid var(--primary-glow)";
        }
        if (infoStatus) {
            infoStatus.textContent = "RUNNING";
            infoStatus.className = "info-item-value text-primary fw-bold";
        }

        updateStepperUI("queued", "processing");
        appendActivityLog("Retrying meeting processing from checkpoint...", "bi-arrow-clockwise text-primary");

        try {
            const csrfToken = getCookie("csrftoken") || document.querySelector("[name=csrfmiddlewaretoken]")?.value || "";
            const response = await fetch(`/meeting/retry/${meetingId}/`, {
                method: "POST",
                headers: {
                    "X-Requested-With": "XMLHttpRequest",
                    "X-CSRFToken": csrfToken,
                    "Accept": "application/json"
                }
            });

            if (response.status === 202) {
                const result = await response.json();
                if (result.success && result.data) {
                    const taskId = result.data.task_id || "";
                    appendActivityLog(`Retry task registered (ID: ${taskId.substring(0, 8)}...). Polling status...`, "bi-play-circle text-primary");
                    pollMeetingStatus(meetingId);
                } else {
                    throw new Error(result.error ? result.error.message : "Unexpected retry response structure.");
                }
            } else {
                let errMessage = "Retry failed. Please check AI settings.";
                try {
                    const errJson = await response.json();
                    if (errJson.error && errJson.error.message) {
                        errMessage = errJson.error.message;
                    }
                } catch (pErr) {}

                showValidationMessage(errMessage);
                appendActivityLog(`Retry failed: ${errMessage}`, "bi-x-circle text-danger");

                isProcessing = false;
                if (analyzeBtn) {
                    analyzeBtn.classList.remove("loading");
                    analyzeBtn.disabled = false;
                    analyzeBtn.innerHTML = `<i class="bi bi-stars"></i><span>Analyze Meeting with AI</span>`;
                }
            }
        } catch (netErr) {
            console.error("Retry request error:", netErr);
            showValidationMessage("Network error while submitting retry request. Please check your connection.");
            appendActivityLog("Network connection error on retry.", "bi-wifi-off text-danger");

            isProcessing = false;
            if (analyzeBtn) {
                analyzeBtn.classList.remove("loading");
                analyzeBtn.disabled = false;
                analyzeBtn.innerHTML = `<i class="bi bi-stars"></i><span>Analyze Meeting with AI</span>`;
            }
        }
    }

    // Expose for external page triggers
    window.retryMeetingAnalysis = retryMeeting;
    window.syncSidebarMeetingInfo = syncSidebarMeetingInfo;

    /* ==========================================================================
       4. WORKSPACE FILE SELECTION, DRAG & DROP AND ASYNC SUBMISSION
       ========================================================================== */
    function initFileUploadWorkspace() {
        const dropzone = document.getElementById("meetingDropzone");
        const fileInput = document.getElementById("meeting_file_input");
        const btnBrowse = document.getElementById("btnBrowseFiles");
        const previewName = document.getElementById("previewFileName");
        const previewSize = document.getElementById("previewFileSize");
        const previewExt = document.getElementById("previewFileExt");
        const previewDuration = document.getElementById("previewFileDuration");
        const previewStatus = document.getElementById("previewFileStatus");
        const btnRemove = document.getElementById("btnRemoveFile");
        const audioPlayer = document.getElementById("audioPreviewPlayer");
        const validationAlert = document.getElementById("fileValidationAlert");
        const analyzeBtn = document.getElementById("btnAnalyzeMeeting");
        const uploadForm = document.getElementById("meetingUploadForm");

        if (!dropzone || !fileInput) return;

        function showValidationMessage(msg) {
            if (validationAlert) {
                validationAlert.innerHTML = `<i class="bi bi-exclamation-triangle-fill me-2"></i> ${msg}`;
                validationAlert.classList.remove("d-none");
            } else {
                alert(msg);
            }
        }

        function hideValidationMessage() {
            if (validationAlert) {
                validationAlert.classList.add("d-none");
                validationAlert.innerHTML = "";
            }
        }

        function handleFile(file) {
            hideValidationMessage();

            if (!file) {
                resetFilePreview();
                return;
            }

            const fileName = file.name;
            const ext = "." + fileName.split(".").pop().toLowerCase();

            if (!ALLOWED_EXTENSIONS.includes(ext)) {
                resetFilePreview(true);
                showValidationMessage(
                    "Unsupported file format. Please upload MP4, MOV, AVI, MKV, MP3, or WAV."
                );
                return;
            }

            const maxSizeBytes = getMaxUploadSizeBytes();
            if (file.size > maxSizeBytes) {
                resetFilePreview(true);
                const limitMb = Math.round(maxSizeBytes / (1024 * 1024));
                showValidationMessage(
                    `File size (${formatBytes(file.size)}) exceeds the limit of ${limitMb} MB.`
                );
                return;
            }

            // Populate preview box
            if (previewName) previewName.textContent = fileName;
            if (previewSize) previewSize.textContent = formatBytes(file.size);
            const cleanExt = ext.replace(".", "").toUpperCase();
            if (previewExt) previewExt.textContent = cleanExt;
            if (previewStatus) {
                previewStatus.textContent = "File ready to upload";
                previewStatus.className = "small fw-bold text-success";
            }
            if (btnRemove) btnRemove.style.display = "inline-flex";

            // Update Input Format in right sidebar
            const infoFormat = document.getElementById("infoInputFormat");
            if (infoFormat) infoFormat.textContent = cleanExt;

            // Inspect Duration via temporary audio element if possible
            if (previewDuration) {
                if (file.type.startsWith("audio/") || ext === ".mp3" || ext === ".wav" || ext === ".m4a") {
                    try {
                        const tempAudio = new Audio();
                        tempAudio.src = URL.createObjectURL(file);
                        tempAudio.addEventListener("loadedmetadata", function () {
                            const secs = Math.floor(tempAudio.duration);
                            const m = Math.floor(secs / 60);
                            const s = secs % 60;
                            previewDuration.textContent = `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
                        });
                    } catch (e) {
                        previewDuration.textContent = "Ready";
                    }
                } else {
                    previewDuration.textContent = "Video Media";
                }
            }

            // Audio Player preview for audio files
            if (audioPlayer) {
                if (file.type.startsWith("audio/") || ext === ".mp3" || ext === ".wav" || ext === ".m4a") {
                    try {
                        const objectUrl = URL.createObjectURL(file);
                        audioPlayer.src = objectUrl;
                        audioPlayer.classList.remove("d-none");
                    } catch (e) {
                        audioPlayer.classList.add("d-none");
                    }
                } else {
                    audioPlayer.src = "";
                    audioPlayer.classList.add("d-none");
                }
            }

            if (analyzeBtn) analyzeBtn.disabled = false;
        }

        function resetFilePreview(preserveAlert = false) {
            if (previewName) previewName.textContent = "No file selected";
            if (previewSize) previewSize.textContent = "—";
            if (previewExt) previewExt.textContent = "MP4";
            if (previewDuration) previewDuration.textContent = "—";
            if (previewStatus) {
                previewStatus.textContent = "Waiting for upload";
                previewStatus.className = "small text-muted";
            }
            if (btnRemove) btnRemove.style.display = "none";
            if (audioPlayer) {
                audioPlayer.src = "";
                audioPlayer.classList.add("d-none");
            }
            if (fileInput) fileInput.value = "";
            const infoFormat = document.getElementById("infoInputFormat");
            if (infoFormat) infoFormat.textContent = "MP4";
            if (analyzeBtn) analyzeBtn.disabled = true;
            if (!preserveAlert) {
                hideValidationMessage();
            }
        }

        // Browse Files button click
        if (btnBrowse) {
            btnBrowse.addEventListener("click", function (e) {
                e.preventDefault();
                e.stopPropagation();
                fileInput.click();
            });
        }

        // Dropzone box click
        dropzone.addEventListener("click", function (e) {
            if (e.target.closest("#btnRemoveFile") || e.target.closest("audio") || e.target.closest("#btnBrowseFiles")) {
                return;
            }
            fileInput.click();
        });

        // Input change listener
        fileInput.addEventListener("change", function () {
            if (this.files && this.files.length > 0) {
                handleFile(this.files[0]);
            }
        });

        // Drag & Drop events
        ["dragenter", "dragover"].forEach((eventName) => {
            dropzone.addEventListener(eventName, function (e) {
                e.preventDefault();
                e.stopPropagation();
                dropzone.classList.add("is-dragover");
            });
        });

        ["dragleave", "dragend", "drop"].forEach((eventName) => {
            dropzone.addEventListener(eventName, function (e) {
                e.preventDefault();
                e.stopPropagation();
                dropzone.classList.remove("is-dragover");
            });
        });

        dropzone.addEventListener("drop", function (e) {
            e.preventDefault();
            e.stopPropagation();
            dropzone.classList.remove("is-dragover");
            const dt = e.dataTransfer;
            if (dt && dt.files && dt.files.length > 0) {
                fileInput.files = dt.files;
                handleFile(dt.files[0]);
            }
        });

        // Remove file button
        if (btnRemove) {
            btnRemove.addEventListener("click", function (e) {
                e.preventDefault();
                e.stopPropagation();
                resetFilePreview();
            });
        }

        // Asynchronous Form Submission (AJAX POST -> 202 Accepted -> Polling)
        if (uploadForm) {
            uploadForm.addEventListener("submit", async function (e) {
                e.preventDefault();

                if (isProcessing) return;

                if (!fileInput.files || fileInput.files.length === 0) {
                    showValidationMessage("Please select an audio or video meeting recording before analyzing.");
                    return;
                }

                hideValidationMessage();
                isProcessing = true;

                if (analyzeBtn) {
                    analyzeBtn.classList.add("loading");
                    analyzeBtn.disabled = true;
                    analyzeBtn.innerHTML = `
                        <span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>
                        <span>Processing Meeting with AI...</span>
                    `;
                }

                // Initialize progress UI
                const progressBar = document.getElementById("meetingProgressBar");
                const percentLabel = document.getElementById("processingPercentLabel");
                const stageLabel = document.getElementById("processingStageLabel");
                const statusBadge = document.getElementById("processingStatusBadge");
                const infoStatus = document.getElementById("infoProcessingStatus");
                const infoLastUsed = document.getElementById("infoLastUsed");

                if (progressBar) {
                    progressBar.style.width = "10%";
                    progressBar.setAttribute("aria-valuenow", "10");
                    progressBar.className = "progress-bar bg-primary progress-bar-striped progress-bar-animated";
                }
                if (percentLabel) percentLabel.textContent = "10%";
                if (stageLabel) stageLabel.textContent = "Uploading & Queuing Meeting...";
                if (statusBadge) {
                    statusBadge.textContent = "In Progress";
                    statusBadge.style.background = "rgba(99, 102, 241, 0.15)";
                    statusBadge.style.color = "var(--primary)";
                    statusBadge.style.border = "1px solid var(--primary-glow)";
                }
                if (infoStatus) {
                    infoStatus.textContent = "RUNNING";
                    infoStatus.className = "info-item-value text-primary fw-bold";
                }
                if (infoLastUsed) {
                    infoLastUsed.textContent = getFormattedDate();
                }

                updateStepperUI("queued", "processing");
                lastLoggedStage = "queued";

                // Clear previous activity log stream
                const stream = document.getElementById("activityLogStream");
                if (stream) stream.innerHTML = "";
                appendActivityLog("Meeting uploaded. Starting background AI pipeline...", "bi-cloud-upload text-primary");

                const formData = new FormData(uploadForm);

                try {
                    const response = await fetch("/meeting/analyze/", {
                        method: "POST",
                        body: formData,
                        headers: {
                            "X-Requested-With": "XMLHttpRequest"
                        }
                    });

                    if (response.status === 202) {
                        const result = await response.json();
                        if (result.success && result.data) {
                            const meetingId = result.data.meeting_id;
                            const taskId = result.data.task_id || "";
                            activeMeetingId = meetingId;

                            appendActivityLog(`Task registered (ID: ${taskId.substring(0, 8)}...). Polling status...`, "bi-play-circle text-primary");

                            // Begin polling
                            pollMeetingStatus(meetingId);
                        } else {
                            throw new Error(result.error ? result.error.message : "Unexpected response structure.");
                        }
                    } else {
                        let errMessage = "Upload failed. Please check file and AI settings.";
                        try {
                            const errJson = await response.json();
                            if (errJson.error && errJson.error.message) {
                                errMessage = errJson.error.message;
                            }
                        } catch (pErr) {}

                        showValidationMessage(errMessage);
                        appendActivityLog(`Upload failed: ${errMessage}`, "bi-x-circle text-danger");

                        isProcessing = false;
                        if (analyzeBtn) {
                            analyzeBtn.classList.remove("loading");
                            analyzeBtn.disabled = false;
                            analyzeBtn.innerHTML = `<i class="bi bi-stars"></i><span>Analyze Meeting with AI</span>`;
                        }
                        if (statusBadge) {
                            statusBadge.textContent = "Ready";
                            statusBadge.style.background = "rgba(125, 125, 125, 0.15)";
                            statusBadge.style.color = "var(--text-muted)";
                            statusBadge.style.border = "none";
                        }
                    }
                } catch (netErr) {
                    console.error("Analyze request error:", netErr);
                    showValidationMessage("Network error while submitting meeting recording. Please check your connection.");
                    appendActivityLog("Network connection error on upload.", "bi-wifi-off text-danger");

                    isProcessing = false;
                    if (analyzeBtn) {
                        analyzeBtn.classList.remove("loading");
                        analyzeBtn.disabled = false;
                        analyzeBtn.innerHTML = `<i class="bi bi-stars"></i><span>Analyze Meeting with AI</span>`;
                    }
                }
            });
        }
    }

    /* ==========================================================================
       5. COPY & DOWNLOAD ACTIONS
       ========================================================================== */
    function fallbackCopyText(text, btnElement) {
        const textarea = document.createElement("textarea");
        textarea.value = text;
        textarea.style.position = "fixed";
        textarea.style.opacity = "0";
        document.body.appendChild(textarea);
        textarea.select();
        try {
            document.execCommand("copy");
            showCopyFeedback(btnElement);
        } catch (err) {
            console.error("Fallback copy failed:", err);
        }
        document.body.removeChild(textarea);
    }

    function showCopyFeedback(btnElement) {
        if (!btnElement) return;
        const originalHtml = btnElement.innerHTML;
        btnElement.innerHTML = `<i class="bi bi-check2 me-1"></i> Copied!`;
        btnElement.classList.add("btn-success");
        setTimeout(() => {
            btnElement.innerHTML = originalHtml;
            btnElement.classList.remove("btn-success");
        }, 2000);
    }

    function initActionButtons() {
        // Copy Transcript
        const btnCopyTranscript = document.getElementById("btnCopyTranscript");
        const transcriptElement = document.getElementById("meetingTranscriptContent");

        if (btnCopyTranscript && transcriptElement) {
            btnCopyTranscript.onclick = function () {
                const text = transcriptElement.innerText || transcriptElement.textContent;
                if (navigator.clipboard && window.isSecureContext) {
                    navigator.clipboard.writeText(text).then(() => {
                        showCopyFeedback(btnCopyTranscript);
                    }).catch(() => {
                        fallbackCopyText(text, btnCopyTranscript);
                    });
                } else {
                    fallbackCopyText(text, btnCopyTranscript);
                }
            };
        }

        // Copy Report
        const btnCopyReport = document.getElementById("btnCopyReport");
        const reportElement = document.getElementById("meetingReportContent");

        if (btnCopyReport && reportElement) {
            btnCopyReport.onclick = function () {
                const text = reportElement.innerText || reportElement.textContent;
                if (navigator.clipboard && window.isSecureContext) {
                    navigator.clipboard.writeText(text).then(() => {
                        showCopyFeedback(btnCopyReport);
                    }).catch(() => {
                        fallbackCopyText(text, btnCopyReport);
                    });
                } else {
                    fallbackCopyText(text, btnCopyReport);
                }
            };
        }

        // Download Transcript TXT
        const btnDownloadTxt = document.getElementById("btnDownloadTranscriptTxt");
        if (btnDownloadTxt && transcriptElement) {
            btnDownloadTxt.onclick = function () {
                const text = transcriptElement.innerText || transcriptElement.textContent;
                const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = "meeting-transcript.txt";
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                URL.revokeObjectURL(url);
            };
        }

        // Download Executive Report TXT
        const btnDownloadReport = document.getElementById("btnDownloadReportTxt");
        if (btnDownloadReport && reportElement) {
            btnDownloadReport.onclick = function () {
                const text = reportElement.innerText || reportElement.textContent;
                const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = "meeting-executive-report.txt";
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                URL.revokeObjectURL(url);
            };
        }

        // Analyze Another Meeting (Quick Reset & Scroll)
        const btnAnalyzeAnother = document.getElementById("btnAnalyzeAnother");
        if (btnAnalyzeAnother) {
            btnAnalyzeAnother.onclick = function () {
                stopPolling();
                isProcessing = false;

                const uploadSection = document.getElementById("sectionUpload");
                if (uploadSection) {
                    uploadSection.scrollIntoView({ behavior: "smooth", block: "start" });
                }

                // Reset file input & preview
                const fileInput = document.getElementById("meeting_file_input");
                if (fileInput) fileInput.value = "";
                const previewName = document.getElementById("previewFileName");
                if (previewName) previewName.textContent = "No file selected";
                const previewSize = document.getElementById("previewFileSize");
                if (previewSize) previewSize.textContent = "—";
                const previewStatus = document.getElementById("previewFileStatus");
                if (previewStatus) {
                    previewStatus.textContent = "Waiting for upload";
                    previewStatus.className = "small text-muted";
                }
                const btnRemove = document.getElementById("btnRemoveFile");
                if (btnRemove) btnRemove.style.display = "none";
                const audioPlayer = document.getElementById("audioPreviewPlayer");
                if (audioPlayer) {
                    audioPlayer.src = "";
                    audioPlayer.classList.add("d-none");
                }

                // Reset progress UI
                const progressBar = document.getElementById("meetingProgressBar");
                const percentLabel = document.getElementById("processingPercentLabel");
                const stageLabel = document.getElementById("processingStageLabel");
                const statusBadge = document.getElementById("processingStatusBadge");
                const infoStatus = document.getElementById("infoProcessingStatus");

                if (progressBar) {
                    progressBar.style.width = "0%";
                    progressBar.setAttribute("aria-valuenow", "0");
                    progressBar.className = "progress-bar bg-primary progress-bar-striped progress-bar-animated";
                }
                if (percentLabel) percentLabel.textContent = "0%";
                if (stageLabel) stageLabel.textContent = "Ready to process";
                if (statusBadge) {
                    statusBadge.textContent = "Ready";
                    statusBadge.style.background = "rgba(125, 125, 125, 0.15)";
                    statusBadge.style.color = "var(--text-muted)";
                    statusBadge.style.border = "none";
                }
                if (infoStatus) {
                    infoStatus.textContent = "READY";
                    infoStatus.className = "info-item-value text-muted";
                }

                updateStepperUI("ready", "ready");

                // Clear activity log
                const stream = document.getElementById("activityLogStream");
                if (stream) {
                    stream.innerHTML = `
                        <div id="activityLogEmpty" class="text-center pt-1" style="color: var(--text-muted);">
                            <i class="bi bi-hourglass-split me-1"></i> Activity stream ready. Upload meeting to start pipeline.
                        </div>
                    `;
                }

                // Clear transcript & report containers
                const transContainer = document.getElementById("transcriptContainer");
                if (transContainer) transContainer.innerHTML = "";
                const repContainer = document.getElementById("reportContainer");
                if (repContainer) repContainer.innerHTML = "";

                const analyzeBtn = document.getElementById("btnAnalyzeMeeting");
                if (analyzeBtn) {
                    analyzeBtn.classList.remove("loading");
                    analyzeBtn.disabled = false;
                    analyzeBtn.innerHTML = `<i class="bi bi-stars"></i><span>Analyze Meeting with AI</span>`;
                }
            };
        }
    }

    /* ==========================================================================
       INITIALIZE ON DOM READY
       ========================================================================== */
    document.addEventListener("DOMContentLoaded", function () {
        initGlobalThemeSelector();
        initFileUploadWorkspace();
        initActionButtons();
    });
})();
