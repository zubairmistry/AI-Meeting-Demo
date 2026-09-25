# AI Meeting Assistant & Executive Intelligence Platform

[![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12-blue.svg)](https://www.python.org/)
[![Django](https://img.shields.io/badge/Django-5.2-green.svg)](https://www.djangoproject.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Release: Phase 2.1](https://img.shields.io/badge/Release-Phase%202.1%20Premium-purple.svg)](https://github.com/zubairmistry/AI-Meeting-Demo)
[![Sample Meetings](https://img.shields.io/badge/Sample%20Recordings-v1-orange.svg)](https://github.com/zubairmistry/AI-Meeting-Demo/releases/tag/sample-meetings-v1)

A production-grade, enterprise-ready Django application that transforms audio and video meeting recordings into accurate verbatim transcripts, structured executive summaries, and action item trackers. Built for high privacy, local Windows execution, multi-provider AI intelligence (Google Gemini, OpenAI, Anthropic Claude), and zero-friction 1-click management.

---

## Table of Contents

1. [Platform Overview](#1-platform-overview)
2. [What's New in Phase 2.1 — Premium Meeting Experience](#2-whats-new-in-phase-21--premium-meeting-experience)
3. [System Requirements](#3-system-requirements)
4. [Windows 1-Click Quick Start](#4-windows-1-click-quick-start)
5. [First-Time Application Setup & AI Configuration](#5-first-time-application-setup--ai-configuration)
6. [Analyzing Your First Meeting](#6-analyzing-your-first-meeting)
7. [Sample Meeting Recordings (Download & Test)](#7-sample-meeting-recordings-download--test)
8. [Current Capabilities vs. Planned ("Soon") Roadmap](#8-current-capabilities-vs-planned-soon-roadmap)
9. [Local Windows vs. Cloud (Render) Deployment](#9-local-windows-vs-cloud-render-deployment)
10. [AI Provider Architecture & Model Intelligence](#10-ai-provider-architecture--model-intelligence)
11. [Security, Encryption & Privacy Model](#11-security-encryption--privacy-model)
12. [Comprehensive Troubleshooting & Diagnostics](#12-comprehensive-troubleshooting--diagnostics)
13. [Developer Guide & Architecture](#13-developer-guide--architecture)
14. [Running Tests & Quality Assurance](#14-running-tests--quality-assurance)
15. [Extensibility Guide: Adding New AI Providers](#15-extensibility-guide-adding-new-ai-providers)

---

## 1. Platform Overview

The **AI Meeting Assistant** provides a secure, private pipeline for converting recorded discussions, video conferences, webinars, and lectures into actionable business intelligence.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          8-STAGE PIPELINE WORKFLOW                          │
└─────────────────────────────────────────────────────────────────────────────┘
  1. [ Uploading ]       Submit audio/video recording (.mp4, .mov, .avi, .mkv, .mp3, .wav)
            │
            ▼
  2. [ Pre-flight ]      Validate credentials & model reachability before processing
            │
            ▼
  3. [ Extraction ]      FFmpeg extracts standardized 16kHz 16-bit Mono PCM audio
            │
            ▼
  4. [ Transcription ]   Speech-to-text conversion via audio-capable provider (Gemini/OpenAI)
            │
            ▼
  5. [ AI Analysis ]     Contextual analysis and discussion topic extraction
            │
            ▼
  6. [ Report ]          Synthesis of structured summary, key decisions, and action items
            │
            ▼
  7. [ Cleanup ]         Automatic deletion of temporary remote cloud audio assets
            │
            ▼
  8. [ Completed ]       Rendered executive summary and synchronized verbatim transcript
```

### Key Capabilities

- **Universal Media Ingestion:** Process `.mp4`, `.mov`, `.avi`, `.mkv`, `.mp3`, and `.wav` media files directly.
- **Acoustic Audio Normalization:** Automatic conversion to 16kHz mono 16-bit PCM WAV using FFmpeg for optimal speech recognition accuracy.
- **Multi-Provider AI Abstraction:** Unified architecture supporting **Google Gemini**, **OpenAI**, and **Anthropic Claude**.
- **Dynamic Model Discovery:** Automatically queries live available models from your account or uses curated catalogs, with intelligent capability filtering.
- **Pre-Flight Health Checks:** Validates credentials and model availability before committing uploads to disk or running intensive audio conversion.
- **Verbatim Transcripts & Executive Summaries:** Generates complete speech transcripts alongside structured summaries containing key topics, decisions made, and assigned action items.
- **Zero-Plaintext Security:** Symmetric 256-bit Fernet encryption protects all API keys in the local database. Credentials are never written to disk unencrypted, logged, or exposed in HTML.
- **100% Private Local Operation:** Runs on `http://127.0.0.1:8000/`. Meeting media and database records stay entirely on your computer.

---

## 2. What's New in Phase 2.1 — Premium Meeting Experience

The latest release (**Phase 2.1**, commit `2faf0cd`) introduces a refined, responsive two-column layout and live reactive client synchronization:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      PHASE 2.1 INTERACTIVE LAYOUT                           │
├────────────────────────────────────────┬────────────────────────────────────┤
│           MEETING WORKSPACE            │            LIVE SIDEBAR            │
│                                        │                                    │
│  [ Upload Media & Meeting Topic ]      │  📊 Metrics:                       │
│                                        │     • Total Meetings               │
│  [ 8-Stage Progress Stepper: ]         │     • Processed Minutes            │
│    1. Uploading     5. AI Analysis     │     • Active Provider Badge        │
│    2. Pre-flight    6. Report          │                                    │
│    3. Extraction    7. Cleanup         │  🕒 Recent Meetings:               │
│    4. Transcription 8. Completed       │     • 1-Click Meeting Switching    │
│                                        │     • Live Status Badges           │
│  [ Executive Summary & Action Items ]  │     • Relative Timestamps ("2m ago")│
│  [ Verbatim Synchronized Transcript ]  │                                    │
│                                        │  🎨 Theme Selector: 5 Styles       │
└────────────────────────────────────────┴────────────────────────────────────┘
```

- **8-Stage Pipeline Stepper:** Visual tracking across all eight pipeline stages (`1. Uploading` &rarr; `2. Pre-flight` &rarr; `3. Extraction` &rarr; `4. Transcription` &rarr; `5. AI Analysis` &rarr; `6. Report` &rarr; `7. Cleanup` &rarr; `8. Completed`) with animated nodes, connector bars, stage labels, and state indicators.
- **Synchronized Live Sidebar:**
  - **Aggregate Metrics:** Live counters for Total Meetings, Total Processed Minutes, and Active AI Provider.
  - **Recent Meetings Drawer:** Quick-access list of recent meetings showing live status pills (`Completed`, `Processing`, `Failed`, `Pending`), duration counters, relative timestamps, and one-click active selection.
  - **Dynamic State Refresh:** Real-time client-side polling with intelligent exponential backoff and error recovery.
- **Visual Polish & Error Handling:** User-friendly error badges with one-click retry for transient network hiccups, empty states for new workspaces, and non-blocking background workers.
- **Theme Engine:** Instant switching across 5 enterprise-grade themes (**Classic Blue**, **Modern Light**, **Dark Tech**, **AI Neon**, and **Executive Clean**).

---

## 3. System Requirements

Before running the application on your computer, ensure your system meets the following specifications:

| Requirement | Minimum Specification | Recommended Specification |
|---|---|---|
| **Operating System** | Windows 10 (64-bit) | Windows 11 (64-bit) |
| **Python Runtime** | Python 3.10 | **Python 3.11** or 3.12 (64-bit) |
| **Python PATH Setting** | Must check **"Add Python to PATH"** during installation | Verified on system PATH |
| **Audio Engine (FFmpeg)** | FFmpeg on system PATH or `bin/ffmpeg.exe` | Standalone `bin/ffmpeg.exe` in project root |
| **Memory (RAM)** | 4 GB | 8 GB or higher |
| **Disk Space** | 2 GB free space | 10 GB+ free space (for storing meeting media) |
| **AI API Key** | At least one valid API key | Valid API key for **Google Gemini**, **OpenAI**, or **Anthropic Claude** |

> [!IMPORTANT]
> **Python Installation Note:** When installing Python from [python.org](https://www.python.org/downloads/), you **must check the box labeled "Add Python to PATH"** at the bottom of the first installer screen. If you skip this, Windows will not be able to locate Python.

---

## 4. Windows 1-Click Quick Start

The application includes automated Windows batch scripts. You **do not** need to type terminal commands, manually create virtual environments, or run `pip install` commands.

```
Project Folder
├── Setup Application.bat     <-- Step 1: Run once to install
├── Verify Installation.bat    <-- Step 2: Run once to test health
└── Start Application.bat     <-- Step 3: Run daily to launch
```

### Step 1: Initial Setup (`Setup Application.bat`)

1. Open the project folder in Windows Explorer.
2. Double-click `Setup Application.bat`.
3. The automated setup script will:
   - Verify Python is installed and compatible (3.10–3.12).
   - Create an isolated virtual environment (`.venv`).
   - Install all required Python libraries.
   - Generate secure local encryption keys in `.env`.
   - Initialize the local SQLite database (`db.sqlite3`).
   - Create storage directories (`media/`, `media/audio/`, `media/transcripts/`).
   - Verify the FFmpeg audio extraction engine.
4. When finished, you will see `AI MEETING ASSISTANT - SETUP COMPLETED SUCCESSFULLY`. Press any key to close the window.

### Step 2: System Health Verification (`Verify Installation.bat`)

1. Double-click `Verify Installation.bat`.
2. The verification tool executes 10 non-destructive diagnostic checks:
   - `[1/10]` Project Files Structure
   - `[2/10]` Python Runtime Compatibility
   - `[3/10]` Virtual Environment Health
   - `[4/10]` Core Dependencies
   - `[5/10]` Security & Fernet Encryption Keys
   - `[6/10]` Database Engine & Migrations
   - `[7/10]` FFmpeg Audio Engine
   - `[8/10]` Media Storage Directories
   - `[9/10]` Django System Configuration Check
   - `[10/10]` Upload Capacity Limits (2 GB local)
3. If everything is green, it will report: `STATUS: ALL CHECKS PASSED`.

### Step 3: Launch the Application (`Start Application.bat`)

1. Double-click `Start Application.bat`.
2. The launcher will perform a quick pre-flight check, start the local server, and automatically launch your default web browser to:
   ```
   http://127.0.0.1:8000/
   ```
   *(If port 8000 is occupied by another service, it automatically selects an available port between 8001 and 8010).*
3. **Keep the launcher window open** while you work. When you are done, click inside the launcher window and press `CTRL+C` to stop the server cleanly.

> [!TIP]
> **Daily Routine:** You only need to run `Setup Application.bat` once. For daily use, simply double-click `Start Application.bat`.

---

## 5. First-Time Application Setup & AI Configuration

Once the web application opens in your browser:

### 1. Register a Local User Account
- Click **Register** on the top navigation bar.
- Choose a username, email address, and password.
- Log in to your new private account.

### 2. Configure Your AI Provider
- Navigate to **Settings** (or **AI Settings**) in the navigation menu.
- **Select AI Provider:**
  - **Google Gemini:** Directly processes meeting audio via multimodal API and generates structured reports. Get a key at [Google AI Studio](https://aistudio.google.com/).
  - **OpenAI:** Uses Whisper for speech-to-text audio transcription and GPT models for report synthesis. Get a key at [OpenAI Platform](https://platform.openai.com/).
  - **Anthropic Claude:** Generates executive summaries, key decisions, and action items from transcripts. Get a key at [Anthropic Console](https://console.anthropic.com/).
- **Enter API Key:** Paste your key into the secure API Key input field.
- **Discover Models:** Click **Discover Models**. The system contacts your provider to discover live compatible models.
- **Select Model:** Select your preferred model (e.g. `gemini-2.5-flash`, `gpt-4o`, or `claude-3-5-sonnet-20241022`).
- **Validate Model:** Click **Validate Model**. The application runs a lightweight live probe to confirm credentials and quota.
- **Save Settings:** Click **Save Settings**. Your API key is encrypted using 256-bit Fernet encryption and stored in your local database.

---

## 6. Analyzing Your First Meeting

1. In the navigation bar, click **Meeting**.
2. **Select Media File:** Drag and drop your audio or video file into the upload zone, or click to browse.
   - Supported extensions: `.mp4`, `.mov`, `.avi`, `.mkv`, `.mp3`, `.wav`.
   - Local upload capacity: Up to **2 GB**.
3. **Meeting Topic (Optional):** Enter a meeting title or agenda topic.
4. **Click "Analyze Meeting with AI":** The application begins processing:
   - **Uploading & Pre-flight:** Media is received and credentials/model reachability are confirmed.
   - **Audio Extraction:** FFmpeg extracts a standardized 16kHz mono audio track.
   - **Transcription & AI Analysis:** The audio is transcribed to text and analyzed for key topics.
   - **Report Synthesis & Cleanup:** Discussion points, decisions, and action items are synthesized, and temporary cloud audio assets are removed.
5. **Review Results:**
   - **Executive Summary:** Overview, key points, and action items.
   - **Full Transcript:** Complete, searchable dialogue with speaker segments.

---

## 7. Sample Meeting Recordings (Download & Test)

If you don't have a meeting recording on hand, you can download pre-tested sample recordings from the official GitHub Release:

[![Download Sample Meetings](https://img.shields.io/badge/Download-Sample%20Meeting%20Recordings-blue?style=for-the-badge&logo=github)](https://github.com/zubairmistry/AI-Meeting-Demo/releases/tag/sample-meetings-v1)

### Available Sample Files

1. **`August_17,_2021_Grade_11_Oral_Communication_in_Context_Lesson_2__Prelims_(360p).mp4`**
   - **Format:** MP4 Video
   - **Exact Size:** 62,344,242 bytes (~59.46 MB)
   - **Description:** Educational oral communication lesson recording. Useful for testing structured instructional summaries and lecture notes.

2. **`Sec_Growth_DataScience_staff_meeting_Sep_14_2022(360p).mp4`**
   - **Format:** MP4 Video
   - **Exact Size:** 43,763,192 bytes (~41.74 MB)
   - **Description:** Multi-participant data science staff meeting recording. Useful for evaluating conversational dialogue transcription, team discussion points, and action item detection.

### How to Use Sample Recordings
1. Visit the [Sample Meetings Release Page](https://github.com/zubairmistry/AI-Meeting-Demo/releases/tag/sample-meetings-v1).
2. Under **Assets**, click to download either `.mp4` file to your computer.
3. Open the AI Meeting Assistant in your browser (`http://127.0.0.1:8000/`).
4. Drag and drop the downloaded `.mp4` file onto the Meeting upload page and click **Analyze Meeting with AI**.

> [!NOTE]
> Sample media files are distributed as downloadable GitHub Release Assets rather than committed to the Git repository tree. This keeps repository cloning fast and lightweight.

---

## 8. Current Capabilities vs. Planned ("Soon") Roadmap

To ensure total transparency, the following matrix details what is currently active in the application versus planned roadmap features:

| Feature / Module | Status | Details |
|---|:---:|---|
| **Meeting Assistant** | **Available** | Multi-format upload, 8-stage stepper, verbatim transcripts, executive summary, action items. |
| **Live Sidebar & Metrics** | **Available** | Dynamic counts (total meetings, processed minutes, active provider), recent meetings list. |
| **Multi-Provider AI** | **Available** | Support for Google Gemini, OpenAI, and Anthropic Claude. |
| **Dynamic Model Discovery** | **Available** | Real-time model listing, fallback catalogs, capability filtering (`AUDIO_TRANSCRIPTION`). |
| **Live Model Validation** | **Available** | Pre-flight connectivity and access check before uploading media. |
| **Theme Engine** | **Available** | 5 switchable enterprise themes (Classic, Light, Dark, AI Neon, Executive). |
| **1-Click Windows Package** | **Available** | Automated `Setup`, `Verify`, and `Start` batch scripts. |
| **Local 2 GB Uploads** | **Available** | Accommodates large meeting recordings on local Windows instances. |
| **Meetings Calendar / Scheduler** | *Roadmap ("Soon")* | Interactive scheduling and calendar integration. |
| **Advanced Reports Analytics** | *Roadmap ("Soon")* | Aggregate trend analytics, speaker time share, and sentiment metrics. |
| **AI Providers Management Tab** | *Roadmap ("Soon")* | Centralized enterprise provider dashboard for team accounts. |
| **Activity & Audit Logs** | *Roadmap ("Soon")* | Detailed administrative event logs and exportable audit trails. |
| **Document Export (Excel / PDF)** | *Roadmap ("Soon")* | 1-click export of transcripts and summaries to `.xlsx` and `.pdf`. |
| **Outlook / Teams / Meet Connectors**| *Roadmap ("Soon")* | Direct API sync with Microsoft 365 and Google Workspace. |

---

## 9. Local Windows vs. Cloud (Render) Deployment

The application supports both local workstation deployment and cloud container hosting:

| Feature | Local Windows Installation | Cloud Demo (e.g., Render) |
|---|---|---|
| **Primary Use Case** | Daily production use, long corporate meetings | Web demonstration, quick preview |
| **Upload Size Limit** | **2 GB (2048 MB)** | **50 MB** (demo capacity) |
| **Meeting Media Retention** | 100% private in local `db.sqlite3` & `media/` | Ephemeral disk or managed PostgreSQL |
| **Network Exposure** | Strictly localhost (`127.0.0.1`) | Public HTTPS URL (`*.onrender.com`) |
| **Audio Engine** | Local `bin/ffmpeg.exe` or system PATH | Auto-downloaded Linux binary via [`build.sh`](file:///c:/Projects/Python/AI-Meeting-Demo/build.sh) |
| **Launcher** | 1-click `Start Application.bat` | Managed Gunicorn process via [`Procfile`](file:///c:/Projects/Python/AI-Meeting-Demo/Procfile) |

---

## 10. AI Provider Architecture & Model Intelligence

The platform features an extensible provider abstraction layer located in [`meeting/providers/`](file:///c:/Projects/Python/AI-Meeting-Demo/meeting/providers/):

```
                       BaseAIProvider
                             │
     ┌───────────────────────┼───────────────────────┐
     ▼                       ▼                       ▼
GeminiProvider         OpenAIProvider          ClaudeProvider
(Audio STT + Reports   (Whisper STT + GPT      (Text Synthesis &
 via Gemini API)        Reports via OpenAI API) Executive Reports)
```

### Provider Capabilities & Models

| Provider | Supported Models | Audio Transcription | Report Synthesis | Notes |
|---|---|:---:|:---:|---|
| **Google Gemini** | `gemini-2.5-flash`<br>`gemini-2.5-flash-lite`<br>`gemini-1.5-flash`<br>`gemini-1.5-pro` | Native | Native | Direct multimodal audio ingestion with automatic remote cloud asset deletion in `finally` blocks. |
| **OpenAI** | `gpt-4o`<br>`gpt-4o-mini`<br>`whisper-1` | Native (Whisper) | Native (GPT-4o) | Uses Whisper for speech-to-text and GPT models for structured executive report synthesis. |
| **Anthropic Claude** | `claude-3-5-sonnet-20241022`<br>`claude-3-5-haiku-20241022`<br>`claude-3-opus-20240229` | Lacks Native Audio STT | Native | Generates executive summaries from text transcripts. Requires an audio-capable provider for media files. |

### Capability Filtering & Pre-Flight Checks
- **Capability Filtering:** Models that lack audio transcription capabilities are automatically identified by [`ModelDiscoveryService`](file:///c:/Projects/Python/AI-Meeting-Demo/meeting/services/model_discovery_service.py) so incompatible selections are prevented.
- **Pre-Flight Health Checks:** Before uploading media files or executing FFmpeg extraction, [`ModelValidationService`](file:///c:/Projects/Python/AI-Meeting-Demo/meeting/services/model_validation_service.py) verifies that your configured API credentials are valid and reachable. If an API key is invalid or quota is exhausted, processing halts early with a clear diagnostic badge.

---

## 11. Security, Encryption & Privacy Model

The application is built according to privacy-first and defense-in-depth security principles:

1. **Symmetric API Key Encryption:**
   - Provider API keys are encrypted at rest using industry-standard **Fernet (AES-128-CBC with HMAC-SHA256)** encryption via the `cryptography` library.
   - The private key is stored in your local `.env` file (`ENCRYPTION_KEY`).
2. **Zero Plaintext Credential Exposure:**
   - API keys are never printed in console logs, server outputs, or error traces.
   - Decrypted keys are never returned in JSON AJAX responses or embedded in HTML templates.
3. **Localhost Network Isolation:**
   - The local server binds exclusively to `127.0.0.1` (localhost). It cannot be reached by other devices on your local Wi-Fi or local area network.
4. **Automated Remote Cloud Cleanup:**
   - When using cloud APIs (such as Google Gemini Files API), uploaded audio assets are automatically deleted in `finally` blocks immediately after transcription completes, preventing cloud storage accumulation.
5. **User Scoping & Isolation:**
   - All meetings, transcripts, and settings are strictly partitioned by authenticated user (`request.user`).

---

## 12. Comprehensive Troubleshooting & Diagnostics

If you encounter an issue during installation or everyday use, consult this reference guide. The application assigns specific reference codes to help you pinpoint the problem quickly:

### Common Issues & Solutions

| Reference Code | Problem | Cause | Solution |
|---|---|---|---|
| **`SETUP-PYTHON-001`** | Python not detected on system PATH | Python is not installed or "Add to PATH" was not checked | Install Python 3.11 from [python.org](https://www.python.org/downloads/) and make sure to check **"Add Python to PATH"**. |
| **`SETUP-PYTHON-002`** | Unsupported Python version | Installed Python is older than 3.10 | Install Python 3.11 or 3.12 (64-bit). |
| **`SETUP-VENV-001`** | Virtual environment error | Corrupted or incomplete `.venv` directory | Delete the `.venv` folder in the project and run `Setup Application.bat` again. |
| **`SETUP-FFMPEG-001`** | FFmpeg audio engine not found | FFmpeg is not installed or missing from `bin/` | Download FFmpeg and place `ffmpeg.exe` inside the project's `bin/` folder, or add FFmpeg to your Windows system PATH. |
| **`SETUP-ENV-001`** | Security configuration missing | `.env` file is missing or `ENCRYPTION_KEY` is empty | Run `Setup Application.bat` to automatically generate a fresh `.env` and encryption key. |
| **`START-PORT-001`** | Port 8000–8010 in use | Another local program is occupying the ports | Close other running web servers or background applications using port 8000. |
| **`AI-AUTH-401`** | Pre-flight: AI Authentication Failed | Invalid or expired API Key | Go to **AI Settings**, enter your correct API key, click **Validate Model**, and click **Save Settings**. |
| **`AI-QUOTA-429`** | Quota Exceeded / Rate Limited | Provider account billing exhausted | Check your API quota and billing balance on your AI provider's developer console. |
| **`CLAUDE-NO-AUDIO`** | Audio transcription failed with Claude | Claude lacks native audio transcription | Select **Google Gemini** or **OpenAI** in AI Settings for media files. |
| **`UPLOAD-SIZE-LIMIT`** | File size exceeds limit | Upload exceeds 2 GB locally or 50 MB on cloud demo | Check the file size. For local runs, ensure your file is under 2048 MB. |

### Diagnostic Report Files
When running setup or verification, the system writes diagnostic logs:
- `setup_log.txt`: Step-by-step setup log.
- `verify_report.txt`: Output of the 10-point verification check.
- `SETUP_GUIDE.txt`: In-depth offline text documentation with IT escalation procedures.

> [!CAUTION]
> If sharing `verify_report.txt` or logs with IT support, rest assured that all sensitive credentials and encryption keys are automatically redacted. **Never share your `.env` file or API keys.**

---

## 13. Developer Guide & Architecture

### Project Structure

```
AI-Meeting-Demo/
├── config/                      # Django Core Configuration
│   ├── asgi.py
│   ├── settings.py              # Environment, WhiteNoise, Security, & DB Settings
│   ├── urls.py                  # Root URL Routing
│   └── wsgi.py                  # WSGI Application Entrypoint
├── meeting/                     # Meeting Application
│   ├── migrations/              # Database Schema Migrations
│   ├── prompts/                 # Prompt Engineering Templates
│   │   └── meeting_report_prompt.py
│   ├── providers/               # AI Provider Abstraction
│   │   ├── base_provider.py     # BaseAIProvider Contract
│   │   ├── gemini_provider.py   # Google Gemini SDK Implementation
│   │   ├── openai_provider.py   # OpenAI & Whisper Implementation
│   │   ├── claude_provider.py   # Anthropic Claude Implementation
│   │   └── registry.py          # Provider Registry
│   ├── security/                # Cryptography & Security
│   │   └── encryption.py        # Fernet Symmetrical Key Encryption
│   ├── services/                # Business Logic & Orchestration
│   │   ├── ai_analysis_service.py     # STT & Executive Report Orchestration
│   │   ├── async_task_service.py      # Background Task Runner & State Machine
│   │   ├── audio_service.py           # FFmpeg Extraction & Normalization
│   │   ├── model_discovery_service.py # Discovery & Capability Filter
│   │   ├── model_validation_service.py# Live Probing & Preflight Checks
│   │   ├── provider_factory.py        # Settings-to-Provider Resolver
│   │   └── transcript_service.py      # Transcript File I/O
│   ├── static/meeting/          # Static Assets
│   │   ├── css/style.css        # Responsive CSS & 5 Enterprise Themes
│   │   └── js/
│   │       ├── meeting.js       # Phase 2.1 Reactive Stepper & Sidebar Sync
│   │       └── settings.js      # Discovery & Live Validation AJAX
│   ├── templates/meeting/       # HTML Templates (Bootstrap 5)
│   │   ├── base.html            # Core Shell & Navbar
│   │   ├── index.html           # Phase 2.1 2-Column Meeting Workspace
│   │   ├── dashboard.html       # Meeting History & Metrics
│   │   ├── meeting_detail.html  # Meeting Report View
│   │   ├── settings.html        # AI Provider Configuration
│   │   ├── login.html           # User Authentication
│   │   └── register.html        # User Registration
│   ├── tests/                   # Automated Test Suite (270 Tests)
│   ├── admin.py
│   ├── forms.py
│   ├── models.py                # AISettings & Meeting Models
│   ├── urls.py
│   └── views.py                 # Views & Context Hydration
├── bin/                         # Local FFmpeg Binaries (gitignored)
├── media/                       # Uploaded Media & Transcripts (gitignored)
├── staticfiles/                 # WhiteNoise Compiled Manifest (gitignored)
├── Setup Application.bat        # Windows 1-Click Setup Script
├── Verify Installation.bat      # Windows 1-Click Verification Script
├── Start Application.bat        # Windows 1-Click Server Launcher
├── SETUP_GUIDE.txt              # Plaintext Offline User & Setup Guide
├── .env.example                 # Environment Configuration Template
├── build.sh                     # Linux / Render Cloud Build Script
├── Procfile                     # Gunicorn Production Configuration
├── render.yaml                  # Render Cloud Deployment Blueprint
└── requirements.txt             # Python Package Dependencies
```

---

## 14. Running Tests & Quality Assurance

The codebase includes an extensive automated test suite covering all services, provider abstractions, encryption routines, views, and pre-flight workflows.

### Run Django System Check
```powershell
.\.venv\Scripts\python.exe manage.py check
```

### Run Database Migration Integrity Check
```powershell
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
```

### Run Full Test Suite (270 Tests)
```powershell
.\.venv\Scripts\python.exe manage.py test meeting.tests
```

**Test Coverage Highlights:**
- `test_phase2_context_hydration.py`: Verifies sidebar metrics, aggregate duration calculations, and recent meeting status hydration.
- `test_ajax_api.py`: Tests AJAX discovery, model validation, CSRF validation, and error payload formatting.
- `test_meeting_preflight_e2e.py`: End-to-end testing of pre-flight credential and model verification.
- `test_model_discovery.py`: Capability filtering, fallback catalog sorting, and deterministic model ranking.
- `test_model_validation.py`: Live single-model access probing and error status translation.
- `test_multi_provider.py`: Provider isolation, Claude/OpenAI behavior, and cloud asset lifecycle cleanup.
- `test_provider_registry.py`: Registry isolation and dynamic provider factory instantiation.

---

## 15. Extensibility Guide: Adding New AI Providers

Adding a new AI provider (e.g., Mistral, Groq, Cohere, DeepSeek) requires zero modifications to existing views or template files:

1. **Subclass `BaseAIProvider`:** Create a new provider module in [`meeting/providers/your_provider.py`](file:///c:/Projects/Python/AI-Meeting-Demo/meeting/providers/):
   ```python
   from meeting.providers.base_provider import BaseAIProvider, ModelDescriptor, ValidationResult

   class YourProvider(BaseAIProvider):
       provider_key = "your_provider"
       display_name = "Your Provider Name"

       def test_connection(self) -> ValidationResult:
           ...

       def discover_models(self):
           ...

       def filter_compatible_models(self, models):
           ...

       def validate_model_access(self, model_id: str) -> ValidationResult:
           ...

       def generate_transcript(self, audio_source) -> str:
           ...

       def generate_report(self, transcript: str) -> str:
           ...
   ```

2. **Register the Provider:** In [`meeting/providers/__init__.py`](file:///c:/Projects/Python/AI-Meeting-Demo/meeting/providers/__init__.py):
   ```python
   from meeting.providers.your_provider import YourProvider
   ProviderRegistry.register("your_provider", YourProvider)
   ```

3. **Update Provider Choices:** Add `("your_provider", "Your Provider Name")` to `AISettings.PROVIDER_CHOICES` in [`meeting/models.py`](file:///c:/Projects/Python/AI-Meeting-Demo/meeting/models.py).

---

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.

