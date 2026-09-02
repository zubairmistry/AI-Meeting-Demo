# AI Meeting Assistant & Executive Intelligence Platform

A production-grade Django web application that transforms audio and video meeting recordings into precise transcripts, action item trackers, and structured executive summaries using pluggable, capability-aware AI providers (Google Gemini, OpenAI, and Anthropic Claude).

---

## Table of Contents
1. [Project Overview](#project-overview)
2. [Core Features](#core-features)
3. [Architecture Overview](#architecture-overview)
4. [Project & Application Structure](#project--application-structure)
5. [Authentication & Authorization](#authentication--authorization)
6. [AI Provider Architecture](#ai-provider-architecture)
7. [Model Discovery & Capability Filtering](#model-discovery--capability-filtering)
8. [Model Validation & Pre-Flight Health Checks](#model-validation--pre-flight-health-checks)
9. [Settings AJAX API Endpoints](#settings-ajax-api-endpoints)
10. [End-to-End Meeting Processing Workflow](#end-to-end-meeting-processing-workflow)
11. [Remote Cloud Asset Lifecycle Management](#remote-cloud-asset-lifecycle-management)
12. [Supported Provider Capabilities & Honest Limitations](#supported-provider-capabilities--honest-limitations)
13. [Security & Encryption Model](#security--encryption-model)
14. [Environment Variables](#environment-variables)
15. [Database Configuration & Engine Support](#database-configuration--engine-support)
16. [FFmpeg Audio Extraction & Cloud Build Setup](#ffmpeg-audio-extraction--cloud-build-setup)
17. [Static Files & WhiteNoise Setup](#static-files--whitenoise-setup)
18. [Local Installation & Setup Guide](#local-installation--setup-guide)
19. [Running Tests & Quality Checks](#running-tests--quality-checks)
20. [Production Deployment Guide (Render / Cloud Containers)](#production-deployment-guide-render--cloud-containers)
21. [Security Considerations](#security-considerations)
22. [Troubleshooting](#troubleshooting)
23. [Current Project Limitations](#current-project-limitations)
24. [Extensibility Guide: Adding a New AI Provider](#extensibility-guide-adding-a-new-ai-provider)

---

## 1. Project Overview

The **AI Meeting Assistant** provides a complete pipeline for analyzing recorded conversations, corporate meetings, and lectures. Users upload audio or video files (e.g. `.mp4`, `.mov`, `.wav`, `.mp3`), which are converted into standardized 16kHz mono PCM audio via FFmpeg, transcribed using state-of-the-art speech-to-text models, and synthesized into structured executive meeting reports featuring discussion points, decisions, and action items.

---

## 2. Core Features

- **Multi-Format Media Ingestion:** Supports `.mp4`, `.mov`, `.avi`, `.mkv`, `.mp3`, and `.wav` recordings up to 50 MB.
- **FFmpeg 16kHz Mono Extraction:** Automatically normalizes uploaded media to 16kHz 16-bit PCM WAV for optimal acoustic speech recognition.
- **Provider-Agnostic Extensibility:** Plug-and-play architecture supporting Google Gemini, OpenAI, and Anthropic Claude via unified contracts.
- **Capability-Aware Dynamic Model Discovery:** Discovers live available models from provider accounts or falls back to curated static catalogs. Automatically filters candidates against required application capabilities (`AUDIO_TRANSCRIPTION`, `TEXT_GENERATION`).
- **Selective Live Model Validation:** Probes access to individual candidate models in real time without batch-probing entire catalogs.
- **Pre-Flight Health Checks:** Validates credentials and model availability before committing uploads to disk or running CPU-intensive FFmpeg audio extraction.
- **Remote Asset Lifecycle Deletion:** Automatically deletes uploaded temporary audio assets from Google Gemini Files API via `finally` blocks, preventing cloud storage leaks.
- **Zero-Plaintext Credential Security:** Symmetrically encrypts API keys using Fernet before database storage; zero credential leakage in logs, JSON responses, or DOM templates.
- **Responsive Web Interface:** Built with Bootstrap 5 and modern responsive vanilla JavaScript with animated loading states and live validation badges.
- **Meeting Dashboard & Archive:** Tracks total processing history, duration counters, and persistent reports per authenticated user.

---

## 3. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Web Client (UI)                                │
│   - Meeting Upload Index (/index)      - Dynamic AI Settings (/settings)    │
│   - History Dashboard (/dashboard)     - Meeting Detail View (/meeting/<id>)│
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ (HTTPS / CSRF)
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            Django View Layer                                │
│   - home (Upload & Pre-Flight)         - settings (Form & Persistence)      │
│   - discover_models_api (AJAX)         - validate_model_api (AJAX)          │
└───────────────────┬──────────────────────────────────┬──────────────────────┘
                    │                                  │
                    ▼                                  ▼
┌──────────────────────────────────────┐  ┌───────────────────────────────────┐
│     Model Discovery & Validation     │  │   Meeting Processing Pipeline     │
│ - ModelDiscoveryService              │  │ - AudioService (FFmpeg 16kHz Mono)│
│ - ModelValidationService             │  │ - TranscriptService (Disk storage)│
│ - Preflight Health Checks            │  │ - AIAnalysisService (STT + Report)│
└───────────────────┬──────────────────┘  └───────────────────┬───────────────┘
                    │                                         │
                    └───────────────────┬─────────────────────┘
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     Provider Layer (BaseAIProvider)                         │
│   - ProviderRegistry                 - ProviderFactory                      │
│   - GeminiProvider                   - OpenAIProvider                       │
│   - ClaudeProvider                   - Fallback Catalogs                    │
└───────────────────────────────────────┬─────────────────────────────────────┘
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           External AI Services                              │
│   - Google Gemini API                - OpenAI (GPT-4o & Whisper)            │
│   - Anthropic Claude API             - Remote Gemini Files Deletion         │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Project & Application Structure

```
AI-Meeting-Demo/
├── config/                      # Django Project Configuration
│   ├── __init__.py
│   ├── asgi.py
│   ├── settings.py              # Environment, WhiteNoise, Security, & DB Settings
│   ├── urls.py                  # Root URL Routing
│   └── wsgi.py                  # WSGI Application Entrypoint
├── meeting/                     # Core Meeting Assistant Application
│   ├── migrations/              # Django DB Schema Migrations
│   ├── prompts/                 # Standardized AI Prompt Templates
│   │   ├── __init__.py
│   │   └── meeting_report_prompt.py
│   ├── providers/               # Multi-Provider Abstraction Layer
│   │   ├── __init__.py          # Provider Auto-Registration
│   │   ├── base_provider.py     # BaseAIProvider, Enums, & Descriptors
│   │   ├── claude_provider.py   # Anthropic Claude Implementation
│   │   ├── factory.py           # Low-Level Provider Instantiation Factory
│   │   ├── gemini_provider.py   # Google Gemini SDK Implementation
│   │   ├── openai_provider.py   # OpenAI Implementation
│   │   └── registry.py          # Centralized Provider Registry
│   ├── security/                # Cryptographic Security Utilities
│   │   ├── __init__.py
│   │   └── encryption.py        # Fernet Symmetrical Key Encryption / Decryption
│   ├── services/                # Business Logic & Orchestration
│   │   ├── __init__.py
│   │   ├── ai_analysis_service.py     # High-Level STT & Report Generation
│   │   ├── audio_service.py           # FFmpeg Extraction & Audio Metadata
│   │   ├── model_discovery_service.py # Discovery, Capability Filter, & Ranking
│   │   ├── model_validation_service.py# Selective Live Probing & Preflight
│   │   ├── provider_factory.py        # User-Settings-to-Provider Resolver
│   │   ├── settings_service.py        # AISettings Encrypted Storage Service
│   │   └── transcript_service.py      # Transcript File I/O
│   ├── static/meeting/          # CSS, JavaScript & Static Assets
│   │   ├── css/
│   │   └── js/
│   │       └── settings.js      # Dynamic Discovery & Validation AJAX Script
│   ├── templates/meeting/       # Presentation Templates (Bootstrap 5)
│   │   ├── base.html
│   │   ├── dashboard.html
│   │   ├── index.html
│   │   ├── login.html
│   │   ├── meeting_detail.html
│   │   ├── register.html
│   │   └── settings.html
│   ├── tests/                   # Comprehensive Automated Test Suite
│   │   ├── __init__.py
│   │   ├── test_ajax_api.py           # 17 AJAX Discovery & Validation Tests
│   │   ├── test_meeting_preflight_e2e.py # 10 E2E Pre-Flight Workflow Tests
│   │   ├── test_model_discovery.py    # 12 Discovery & Ranking Tests
│   │   ├── test_model_validation.py   # 15 Live Probing & Preflight Tests
│   │   ├── test_multi_provider.py     # 15 Multi-Provider & Asset Lifecycle Tests
│   │   └── test_provider_registry.py  # 10 Registry & Factory Tests
│   ├── admin.py
│   ├── apps.py
│   ├── forms.py
│   ├── models.py                # AISettings & Meeting Models
│   ├── signals.py
│   ├── urls.py
│   └── views.py
├── media/                       # Uploaded Meeting Media & Transcripts (gitignored)
├── staticfiles/                 # WhiteNoise Compressed Static Manifest
├── .env.example                 # Environment Variable Template
├── build.sh                     # Linux/Render Cloud Build Script with FFmpeg Setup
├── manage.py
├── Procfile                     # Gunicorn Production Process Descriptor
└── requirements.txt             # Python Package Dependencies
```

---

## 5. Authentication & Authorization

- **User Isolation:** All meeting transcripts, executive reports, and encrypted AI settings are partitioned strictly by `request.user`.
- **Protected Endpoints:** All core views (`home`, `settings`, `dashboard`, `meeting_detail`, `discover_models_api`, `validate_model_api`) are guarded with `@login_required(login_url="login")`.
- **Query Scoping:** Detail and dashboard views query `Meeting.objects.filter(user=request.user)` and `get_object_or_404(Meeting, id=meeting_id, user=request.user)`.

---

## 6. AI Provider Architecture

The application defines a strict provider abstraction:

1. **`BaseAIProvider` ([`meeting/providers/base_provider.py`](file:///c:/Projects/Python/AI-Meeting-Demo/meeting/providers/base_provider.py)):** Abstract base class declaring interface contracts:
   - `test_connection() -> ValidationResult`
   - `discover_models() -> List[ModelDescriptor]`
   - `filter_compatible_models(models) -> List[ModelDescriptor]`
   - `validate_model_access(model_id) -> ValidationResult`
   - `quick_preflight_check() -> ValidationResult`
   - `upload_audio(audio_path) -> Any`
   - `wait_until_ready(audio_file) -> Any`
   - `generate_transcript(audio_source) -> str`
   - `generate_report(transcript) -> str`
   - `translate_error(exc) -> ValidationResult`
   - `cleanup_audio(audio_source) -> None`
2. **`ProviderRegistry` ([`meeting/providers/registry.py`](file:///c:/Projects/Python/AI-Meeting-Demo/meeting/providers/registry.py)):** Central registry mapping provider keys (`"gemini"`, `"openai"`, `"claude"`) to class implementations.
3. **`ProviderFactory` ([`meeting/services/provider_factory.py`](file:///c:/Projects/Python/AI-Meeting-Demo/meeting/services/provider_factory.py)):** Resolves the active provider instance for a user by decrypting settings and initializing the registered provider class.
4. **Lazy SDK Imports:** Non-default SDKs (`anthropic`, `openai`) are imported dynamically inside `_ensure_client()` calls wrapped in `try ... except ImportError`. Missing packages do not prevent the app from launching.

---

## 7. Model Discovery & Capability Filtering

Model discovery operates through [`ModelDiscoveryService`](file:///c:/Projects/Python/AI-Meeting-Demo/meeting/services/model_discovery_service.py):

1. **Live Discovery vs. Static Catalog Fallback:**
   - Providers attempt live model querying (e.g. `client.models.list()`).
   - If the provider key is not yet configured or the network is offline, providers return curated fallback models tagged with `DiscoverySource.CATALOG_FALLBACK`.
2. **Capability-Aware Filtering:**
   - Evaluates discovered models against `REQUIRED_MEETING_CAPABILITIES` (`{AUDIO_TRANSCRIPTION, TEXT_GENERATION}`).
   - Rejects text-only or non-audio models from the primary meeting pipeline while preserving other supported operations.
3. **Deterministic Ranking:**
   - Sorts compatible models by:
     1. Recommended flag bonus (`+10000`)
     2. Composite performance score: `(quality_score * 0.6) + (speed_score * 0.4)`
     3. Lexicographical model ID for deterministic tie-breaking.
   - Automatically selects the highest-ranking candidate (e.g. `gemini-2.5-flash` or `gpt-4o`).

---

## 8. Model Validation & Pre-Flight Health Checks

Operates through [`ModelValidationService`](file:///c:/Projects/Python/AI-Meeting-Demo/meeting/services/model_validation_service.py):

- **Selective Live Probing:** Validates access strictly for the selected model via a sub-second probe without batch-probing the entire catalog.
- **Standardized Status Normalization:**
  - `AVAILABLE`: Credentials valid, model accessible.
  - `ACCESS_DENIED`: Invalid API key or permission denied.
  - `UNAVAILABLE`: Model ID does not exist or account lacks access.
  - `QUOTA_EXCEEDED`: Provider billing quota exhausted.
  - `RATE_LIMITED`: Requests per minute/day exceeded.
  - `TEMPORARILY_UNAVAILABLE`: Service overloaded or 503 unavailable.
- **Pre-Flight Health Check Integration:** Executed at the beginning of `views.home`. If credentials or models are invalid, processing aborts immediately with a clear error badge, saving CPU, disk I/O, and API time.

---

## 9. Settings AJAX API Endpoints

### 1. `POST /settings/api/discover-models/`
- **Authentication:** Required (`@login_required`)
- **Headers:** `X-CSRFToken`
- **Request Body (JSON or Form):**
  ```json
  {
    "provider": "gemini",
    "api_key": "optional_unsaved_key"
  }
  ```
- **Success Response:**
  ```json
  {
    "success": true,
    "data": {
      "models": [
        {
          "id": "gemini-2.5-flash",
          "display_name": "Gemini 2.5 Flash (Recommended)",
          "status": "COMPATIBLE_UNTESTED",
          "source": "CATALOG_FALLBACK",
          "is_recommended": true,
          "quality_score": 90,
          "speed_score": 95,
          "context_window": 1048576
        }
      ],
      "recommended_model_id": "gemini-2.5-flash"
    },
    "error": null
  }
  ```

### 2. `POST /settings/api/validate-model/`
- **Authentication:** Required (`@login_required`)
- **Headers:** `X-CSRFToken`
- **Request Body (JSON or Form):**
  ```json
  {
    "provider": "gemini",
    "model_id": "gemini-2.5-flash",
    "api_key": "optional_unsaved_key"
  }
  ```
- **Success Response:**
  ```json
  {
    "success": true,
    "data": {
      "model_id": "gemini-2.5-flash",
      "status": "AVAILABLE",
      "message": "Connected"
    },
    "error": null
  }
  ```

---

## 10. End-to-End Meeting Processing Workflow

```
1. User submits audio/video file through the web interface.
2. View verifies authentication, allowed extensions (.mp4, .mov, .avi, .mkv, .mp3, .wav), and size <= 50MB.
3. Pre-Flight Check: ModelValidationService verifies API credentials and model reachability.
   └── IF pre-flight fails: Abort immediately. Display user-friendly error pill.
4. Save original media to media/ directory via FileSystemStorage.
5. AudioService extracts 16kHz mono 16-bit PCM WAV using FFmpeg.
6. AIAnalysisService uploads audio to provider and waits for readiness.
7. AI Provider transcribes meeting audio to text.
8. Remote Asset Cleanup: Finally block deletes temporary remote cloud audio assets.
9. TranscriptService saves raw transcript to disk (.txt).
10. AI Provider synthesizes executive report (Key Points, Decisions, Action Items).
11. Meeting record created in database with status="completed".
12. User redirected or presented with rendered summary and dashboard link.
```

---

## 11. Remote Cloud Asset Lifecycle Management

When processing media with cloud APIs (e.g. Google Gemini Files API), uploaded audio files must not persist indefinitely in third-party storage.

In [`meeting/services/ai_analysis_service.py`](file:///c:/Projects/Python/AI-Meeting-Demo/meeting/services/ai_analysis_service.py):
```python
audio_file = None
try:
    audio_file = provider.upload_audio(audio_path)
    audio_file = provider.wait_until_ready(audio_file)
    transcript = provider.generate_transcript(audio_file)
    return transcript
finally:
    if audio_file is not None and hasattr(provider, "cleanup_audio"):
        try:
            provider.cleanup_audio(audio_file)
        except Exception:
            pass
```
- **Guaranteed Invocation:** The `finally` block ensures `cleanup_audio` runs regardless of whether transcription succeeds, times out, or fails.
- **Shielded Deletion:** Deletion errors are logged as warnings and do not crash report generation or database persistence.

---

## 12. Supported Provider Capabilities & Honest Limitations

| Provider | Supported Models | Audio Transcription | Text Reasoning / Reports | Native Audio Input | Notes |
|---|---|:---:|:---:|:---:|---|
| **Google Gemini** | `gemini-2.5-flash`<br>`gemini-2.5-pro`<br>`gemini-1.5-flash`<br>`gemini-1.5-pro` | ✅ Native | ✅ Native | ✅ Native | Full end-to-end multimodal pipeline with automatic remote file cleanup. |
| **OpenAI** | `gpt-4o`<br>`gpt-4o-mini`<br>`whisper-1`<br>`gpt-4-turbo` | ✅ Native | ✅ Native | ✅ Native | Uses Whisper (`whisper-1`) or `gpt-4o` for transcription and GPT models for reasoning. |
| **Anthropic Claude** | `claude-3-5-sonnet-20241022`<br>`claude-3-5-haiku-20241022`<br>`claude-3-opus-20240229` | ❌ Lacks Native Audio STT | ✅ Native | ❌ No Native Audio | Generates reports from existing transcripts. Honest capability filtering prevents false audio STT claims. |

---

## 13. Security & Encryption Model

- **Symmetric Key Encryption:** API keys are encrypted with `cryptography.fernet.Fernet` using the `ENCRYPTION_KEY` environment variable.
- **Zero Log Exposure:** Application code strictly avoids logging decrypted credentials, `request.POST` payloads, or `form.cleaned_data` objects.
- **Zero JSON / DOM Leakage:** Masked status indicators (`api_key_configured: true/false`) are used in templates. Plaintext keys are never sent in responses.
- **Production Headers:** When `DEBUG=False`, Django security headers are activated (`SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SECURE_BROWSER_XSS_FILTER`, `SECURE_CONTENT_TYPE_NOSNIFF`, `SECURE_PROXY_SSL_HEADER`).

---

## 14. Environment Variables

Create a `.env` file in the project root:

```env
# ==============================================================================
# Django Security & Host Settings
# ==============================================================================
SECRET_KEY=your-super-secret-django-key-min-50-characters
DEBUG=False
ALLOWED_HOSTS=localhost,127.0.0.1,.onrender.com
CSRF_TRUSTED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000,https://*.onrender.com

# ==============================================================================
# Symmetrical Encryption Key (Fernet)
# Generated via: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# ==============================================================================
ENCRYPTION_KEY=your-fernet-base64-key-here=

# ==============================================================================
# Database Configuration (Choose One)
# ==============================================================================
# 1. PostgreSQL (Cloud / Render / Supabase)
DATABASE_URL=postgres://user:password@host:5432/dbname

# 2. Local MySQL (Optional fallback)
# DB_NAME=meeting_db
# DB_USER=root
# DB_PASSWORD=yourpassword
# DB_HOST=127.0.0.1
# DB_PORT=3306

# ==============================================================================
# Optional FFmpeg Path Override (Auto-detected if on system PATH)
# ==============================================================================
# FFMPEG_PATH=/usr/bin/ffmpeg
```

---

## 15. Database Configuration & Engine Support

The project dynamically configures database backends in [`config/settings.py`](file:///c:/Projects/Python/AI-Meeting-Demo/config/settings.py):
1. **`DATABASE_URL`:** Configures PostgreSQL using `dj-database-url` (recommended for Render, Supabase, Neon).
2. **`DB_NAME`:** Configures local MySQL using `PyMySQL`.
3. **SQLite Fallback:** Automatically used if no database environment variables are set (ideal for local testing and CI/CD).

---

## 16. FFmpeg Audio Extraction & Cloud Build Setup

- **Local Development:** Ensure `ffmpeg` is installed and on your system `PATH` (or set `FFMPEG_PATH`).
- **Cloud Hosting (e.g. Render / Linux):** [`build.sh`](file:///c:/Projects/Python/AI-Meeting-Demo/build.sh) automatically downloads a standalone static Linux FFmpeg binary to `bin/ffmpeg` during build time if not present on the host system. [`AudioService`](file:///c:/Projects/Python/AI-Meeting-Demo/meeting/services/audio_service.py) automatically detects `bin/ffmpeg`.

---

## 17. Static Files & WhiteNoise Setup

Static files are managed with **WhiteNoise** using `CompressedManifestStaticFilesStorage`.

To collect static files for deployment:
```bash
python manage.py collectstatic --noinput
```

---

## 18. Local Installation & Setup Guide

### 1. Clone Repository & Create Virtual Environment
```bash
git clone https://github.com/zubairmistry/AI-Meeting-Demo.git
cd AI-Meeting-Demo
python -m venv .venv
```

### 2. Activate Virtual Environment
- **Windows (PowerShell):**
  ```powershell
  .venv\Scripts\Activate.ps1
  ```
- **Linux / macOS:**
  ```bash
  source .venv/bin/activate
  ```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Environment
Generate an encryption key:
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```
Create `.env` and add your `SECRET_KEY`, `ENCRYPTION_KEY`, and `DEBUG=True`.

### 5. Apply Migrations & Create Superuser
```bash
python manage.py migrate
python manage.py createsuperuser
```

### 6. Start Development Server
```bash
python manage.py runserver
```
Visit `http://127.0.0.1:8000/` in your browser.

---

## 19. Running Tests & Quality Checks

### Run Django System Check
```bash
python manage.py check
```

### Run Full Test Suite (79 Tests)
```bash
python manage.py test meeting.tests
```

### Test Coverage Summary:
- `test_ajax_api.py`: 17 tests (AJAX discovery, validation, CSRF, error payloads)
- `test_meeting_preflight_e2e.py`: 10 tests (End-to-end pre-flight check integration)
- `test_model_discovery.py`: 12 tests (Capability filtering, fallback ranking)
- `test_model_validation.py`: 15 tests (Live single-model access validation)
- `test_multi_provider.py`: 15 tests (Multi-provider registry, Claude/OpenAI behavior, remote audio cleanup)
- `test_provider_registry.py`: 10 tests (Registry isolation and factory instantiation)

---

## 20. Production Deployment Guide (Render / Cloud Containers)

### Deploying to Render
1. Connect your GitHub repository to Render as a **Web Service**.
2. **Environment:** `Python 3`
3. **Build Command:**
   ```bash
   ./build.sh
   ```
4. **Start Command:**
   ```bash
   gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000} --timeout 180 --workers 2
   ```
5. **Environment Variables:**
   - `SECRET_KEY` = `<strong-random-key>`
   - `ENCRYPTION_KEY` = `<fernet-base64-key>`
   - `DEBUG` = `False`
   - `DATABASE_URL` = `<postgres-connection-string>`
   - `ALLOWED_HOSTS` = `.onrender.com`

---

## 21. Security Considerations

- **Fernet Secret Protection:** Keep `ENCRYPTION_KEY` backed up securely. If lost, previously encrypted API keys cannot be decrypted.
- **Media Upload Isolation:** Uploaded meeting media in `media/` should be placed on a private object storage bucket or protected persistent volume in multi-tenant production setups.
- **CSRF Protection:** All mutating requests require valid CSRF tokens.

---

## 22. Troubleshooting

| Issue | Cause | Solution |
|---|---|---|
| `ENCRYPTION_KEY environment variable is not set` | Missing `.env` variable | Generate a Fernet key and add `ENCRYPTION_KEY=...` to `.env`. |
| `FFmpeg not found` | FFmpeg missing from PATH | Install FFmpeg locally or ensure `build.sh` executed to download the static binary. |
| `Preflight check: AI Authentication Failed` | Invalid API Key | Go to **AI Settings**, enter a valid provider API key, and click **Validate Model**. |
| `File size exceeds demo limit of 50 MB` | Upload too large | Upload a shorter clip or adjust `MAX_UPLOAD_SIZE` in `config/settings.py`. |

---

## 23. Current Project Limitations

1. **Claude Audio Limitation:** Anthropic Claude models natively process text and vision; audio transcription requires an audio-capable provider (Gemini or OpenAI Whisper).
2. **Synchronous Request Processing:** Meetings are transcribed and synthesized within the HTTP request cycle. Gunicorn is configured with `--timeout 180` to accommodate short to medium demo recordings. For enterprise-scale recordings (>30 minutes), an asynchronous Celery/Redis queue is recommended.
3. **Ephemeral Media Storage:** By default, uploaded recordings are stored in local `media/`. In stateless cloud tiers, a cloud bucket backend (e.g. S3 / GCS) is recommended for long-term file retention.

---

## 24. Extensibility Guide: Adding a New AI Provider

Adding a new AI provider (e.g., Mistral, Groq, Cohere) requires zero changes to views or UI templates:

1. **Create Provider Class:** Subclass `BaseAIProvider` in `meeting/providers/your_provider.py`.
2. **Implement Required Methods:** Implement `test_connection`, `discover_models`, `filter_compatible_models`, `validate_model_access`, `generate_transcript`, and `generate_report`.
3. **Register Provider:** In `meeting/providers/__init__.py`:
   ```python
   from meeting.providers.your_provider import YourProvider
   ProviderRegistry.register("your_provider", YourProvider)
   ```
4. **Update Form Choices:** Add `("your_provider", "Your Provider Name")` to `AISettings.PROVIDER_CHOICES` in `meeting/models.py`.

---

## License

This project is licensed under the MIT License.

