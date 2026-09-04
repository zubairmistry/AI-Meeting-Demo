/* ==========================================================================
   AI MEETING ASSISTANT — WORKSPACE & GLOBAL THEME CONTROLLER
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
        // Toggle dropdowns for both authenticated and guest selectors
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
                    // Close all other menus
                    document.querySelectorAll(".theme-dropdown-menu").forEach(m => m.classList.remove("show"));
                    if (!isOpen) {
                        menu.classList.add("show");
                    }
                });
            }
        });

        // Theme option buttons click
        document.querySelectorAll(".theme-opt-btn").forEach((optBtn) => {
            optBtn.addEventListener("click", function (e) {
                e.preventDefault();
                e.stopPropagation();
                const selectedTheme = this.getAttribute("data-theme-val");
                applyTheme(selectedTheme);
                document.querySelectorAll(".theme-dropdown-menu").forEach(m => m.classList.remove("show"));
            });
        });

        // Close dropdown when clicking anywhere outside
        document.addEventListener("click", function (e) {
            document.querySelectorAll(".theme-dropdown-menu").forEach(menu => {
                const wrapper = menu.closest(".theme-selector-wrapper");
                if (!wrapper || !wrapper.contains(e.target)) {
                    menu.classList.remove("show");
                }
            });
        });

        // Initial application
        applyTheme(getSavedTheme());
    }

    /* ==========================================================================
       2. WORKSPACE FILE SELECTION, DRAG & DROP AND PREVIEW
       ========================================================================== */
    const ALLOWED_EXTENSIONS = [".mp4", ".mov", ".avi", ".mkv", ".mp3", ".wav", ".m4a"];
    const MAX_SIZE_BYTES = 52428800; // 50 MB

    function formatBytes(bytes) {
        if (bytes === 0) return "0 Bytes";
        const k = 1024;
        const sizes = ["Bytes", "KB", "MB", "GB"];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
    }

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
                showValidationMessage(
                    "Unsupported file format. Please upload MP4, MOV, AVI, MKV, MP3, or WAV."
                );
                fileInput.value = "";
                resetFilePreview();
                return;
            }

            if (file.size > MAX_SIZE_BYTES) {
                showValidationMessage(
                    `File size (${formatBytes(file.size)}) exceeds the demo limit of 50 MB.`
                );
                fileInput.value = "";
                resetFilePreview();
                return;
            }

            // Populate preview box
            if (previewName) previewName.textContent = fileName;
            if (previewSize) previewSize.textContent = formatBytes(file.size);
            if (previewExt) previewExt.textContent = ext.replace(".", "").toUpperCase();
            if (previewStatus) {
                previewStatus.textContent = "File ready to upload";
                previewStatus.className = "small fw-bold text-success";
            }
            if (btnRemove) btnRemove.style.display = "inline-flex";

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

        function resetFilePreview() {
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
            hideValidationMessage();
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

        // Form Submit & Loading State (Non-blocking native POST submission)
        if (uploadForm) {
            uploadForm.addEventListener("submit", function (e) {
                if (!fileInput.files || fileInput.files.length === 0) {
                    e.preventDefault();
                    showValidationMessage("Please select an audio or video meeting recording before analyzing.");
                    return;
                }

                if (analyzeBtn) {
                    if (analyzeBtn.classList.contains("loading")) {
                        e.preventDefault();
                        return;
                    }
                    analyzeBtn.classList.add("loading");
                    analyzeBtn.innerHTML = `
                        <span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>
                        <span>Processing Meeting with AI...</span>
                    `;
                }
            });
        }
    }

    /* ==========================================================================
       3. COPY & DOWNLOAD ACTIONS
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
            btnCopyTranscript.addEventListener("click", function () {
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
            });
        }

        // Copy Report
        const btnCopyReport = document.getElementById("btnCopyReport");
        const reportElement = document.getElementById("meetingReportContent");

        if (btnCopyReport && reportElement) {
            btnCopyReport.addEventListener("click", function () {
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
            });
        }

        // Download Transcript TXT
        const btnDownloadTxt = document.getElementById("btnDownloadTranscriptTxt");
        if (btnDownloadTxt && transcriptElement) {
            btnDownloadTxt.addEventListener("click", function () {
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
            });
        }

        // Download Executive Report TXT
        const btnDownloadReport = document.getElementById("btnDownloadReportTxt");
        if (btnDownloadReport && reportElement) {
            btnDownloadReport.addEventListener("click", function () {
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
            });
        }

        // Analyze Another Meeting (Quick Reset & Scroll)
        const btnAnalyzeAnother = document.getElementById("btnAnalyzeAnother");
        if (btnAnalyzeAnother) {
            btnAnalyzeAnother.addEventListener("click", function () {
                const uploadSection = document.getElementById("sectionUpload");
                if (uploadSection) {
                    uploadSection.scrollIntoView({ behavior: "smooth", block: "start" });
                }
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
            });
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
