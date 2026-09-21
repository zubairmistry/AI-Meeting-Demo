import os
import json
import logging
import subprocess
import traceback
from datetime import datetime

from django.conf import settings as django_settings
from django.shortcuts import render, redirect, get_object_or_404
from django.core.files.storage import FileSystemStorage
from django.http import JsonResponse, Http404
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User

from .models import AISettings, Meeting, format_duration
from .forms import AISettingsForm, RegisterForm, LoginForm
from meeting.services.settings_service import SettingsService
from meeting.services.provider_factory import ProviderFactory
from meeting.services.ai_analysis_service import AIAnalysisService
from meeting.services.audio_service import AudioService
from meeting.services.transcript_service import TranscriptService
from meeting.providers.base_provider import ModelStatus
from meeting.providers.registry import ProviderRegistry
from meeting.providers.factory import ProviderFactory as BaseProviderFactory
from meeting.services.model_discovery_service import ModelDiscoveryService
from meeting.services.model_validation_service import ModelValidationService
from meeting.services.async_task_service import AsyncTaskService

logger = logging.getLogger(__name__)


@login_required(login_url="login")
def home(request):
    status = "Waiting for meeting upload..."
    transcript = ""
    report = ""

    if request.method == "POST":

        if "meeting_file" in request.FILES:
            uploaded_file = request.FILES["meeting_file"]

            user_settings = SettingsService.get_settings(request.user)
            if not user_settings or not user_settings.get("api_key"):
                status = "⚠️ Please configure your AI Provider and API Key in Settings before analyzing meetings."
                return render(request, "meeting/index.html", {"status": status})

            allowed_extensions = [
                ".mp4", 
                ".mov",
                ".avi",
                ".mkv",
                ".mp3",
                ".wav"
            ]

            file_name = uploaded_file.name.lower()

            if not any(file_name.endswith(ext) for ext in allowed_extensions):
                status = "❌ Invalid file. Please upload only MP4, MOV, AVI, MKV, MP3 or WAV."
                return render(request,"meeting/index.html",{"status": status})

            max_upload_size = getattr(django_settings, "MAX_UPLOAD_SIZE", 52428800)
            if uploaded_file.size > max_upload_size:
                limit_mb = max_upload_size // (1024 * 1024)
                actual_mb = round(uploaded_file.size / (1024 * 1024), 1)
                status = f"⚠️ File size ({actual_mb} MB) exceeds the demo limit of {limit_mb} MB. Please upload a shorter meeting clip."
                return render(request, "meeting/index.html", {"status": status})

            # Check AI Provider configuration and run pre-flight health check before saving to disk & running FFmpeg
            provider = ProviderFactory.get_provider(request.user)
            if not provider:
                status = "⚠️ Please configure your AI Provider and API Key in Settings before analyzing meetings."
                return render(request, "meeting/index.html", {"status": status})

            preflight = ModelValidationService.preflight_check(provider)
            if not preflight.is_valid:
                prefix_map = {
                    ModelStatus.ACCESS_DENIED: "❌ AI Authentication Failed",
                    ModelStatus.UNAVAILABLE: "❌ AI Model Unavailable",
                    ModelStatus.QUOTA_EXCEEDED: "❌ AI Quota Exceeded",
                    ModelStatus.RATE_LIMITED: "⏳ AI Rate Limited",
                    ModelStatus.TEMPORARILY_UNAVAILABLE: "⚠️ AI Service Busy",
                }
                prefix = prefix_map.get(preflight.status, "❌ AI Configuration Error")
                status = f"{prefix}: {preflight.message}"
                return render(request, "meeting/index.html", {"status": status})

            fs = FileSystemStorage()

            filename = fs.save(uploaded_file.name, uploaded_file)

            filepath = fs.path(filename)

            try:
                audio_path = AudioService.extract_audio(filepath)
                audio_info = AudioService.get_audio_info(audio_path)

                meeting_info = {
                    "file_name": filename,
                    "file_path": filepath,
                    "file_size": uploaded_file.size,
                    "file_extension": os.path.splitext(filename)[1],
                    "mime_type": uploaded_file.content_type,
                    "uploaded_at": datetime.now().strftime("%d-%m-%Y %H:%M:%S"),
                    "audio_path": audio_path,
                    "duration": audio_info["duration_seconds"],
                }

                logger.info("Extracting audio from '%s' -> '%s'", filename, audio_path)

                transcript = AIAnalysisService.generate_transcript(
                    request.user,
                    audio_path
                )

                if not transcript:
                    status = "❌ Failed to generate transcript. Please check your API key and model settings."
                    return render(request, "meeting/index.html", {"status": status})

                transcript_path = TranscriptService.save_transcript(
                    transcript,
                    media_path=filepath
                )

                meeting_info["transcript_path"] = transcript_path    

                logger.info("Saved transcript for '%s' to '%s'", filename, transcript_path)

                report = AIAnalysisService.generate_report(request.user,transcript)

                Meeting.objects.create(
                    user=request.user, 
                    meeting_name=filename,
                    original_file=filename,
                    audio_file=os.path.basename(audio_path),
                    transcript_file=os.path.basename(transcript_path),
                    provider=user_settings["provider"],
                    model_name=user_settings["model_name"],
                    meeting_type="",
                    transcript=transcript,
                    ai_report=report,
                    duration=meeting_info["duration"],
                    file_size=uploaded_file.size,
                    status="completed"
                )      

            except subprocess.CalledProcessError:
                logger.error("FFmpeg audio extraction failed for file '%s'", filename)
                if filepath and os.path.exists(filepath):
                    try:
                        os.remove(filepath)
                    except Exception:
                        pass
                status = "❌ Failed to extract audio from the uploaded media file. Please ensure a valid audio/video file is uploaded."
                return render(
                    request,
                    "meeting/index.html",
                    {
                        "status": status,
                        "transcript": transcript,
                        "report": report,
                    }
                )

            except TimeoutError:
                logger.warning("Meeting processing timed out for file '%s'", filename)
                if filepath and os.path.exists(filepath):
                    try:
                        os.remove(filepath)
                    except Exception:
                        pass
                status = "⏳ Meeting processing timed out. Please try uploading a shorter recording clip for this demo."
                return render(
                    request,
                    "meeting/index.html",
                    {
                        "status": status,
                        "transcript": transcript,
                        "report": report,
                    }
                )

            except Exception as e:
                logger.exception("An error occurred during meeting processing for user '%s': %s", request.user.username, e)
                if filepath and os.path.exists(filepath):
                    try:
                        os.remove(filepath)
                    except Exception:
                        pass
                status = f"❌ An error occurred during processing: {str(e)[:150]}"
                return render(
                    request,
                    "meeting/index.html",
                    {
                        "status": status,
                        "transcript": transcript,
                        "report": report,
                    }
                )

            status = f"File Saved Successfully : {filename}"

        else:

            status = "Please select a meeting file."

    max_upload_size = getattr(django_settings, "MAX_UPLOAD_SIZE", 52428800)
    max_upload_size_mb = max(1, max_upload_size // (1024 * 1024))

    return render(
        request,
        "meeting/index.html",
        {
            "status": status,
            "transcript": transcript,
            "report": report,
            "max_upload_size": max_upload_size,
            "max_upload_size_mb": max_upload_size_mb,
        }
    ) 

@login_required(login_url="login")
def settings(request):

    settings_data = SettingsService.get_settings(request.user)
    api_key_configured = bool(settings_data and settings_data.get("api_key"))

    if request.method == "POST":

        form = AISettingsForm(request.POST)
        
        if form.is_valid():

            provider_val = form.cleaned_data["provider"]
            model_val = form.cleaned_data["model_name"]

            SettingsService.save_settings(
                user=request.user,
                provider=provider_val,
                api_key=form.cleaned_data["api_key"],
                model_name=model_val,
            )
            logger.info(
                "Saved AI settings for user '%s' (provider: %s, model: %s)",
                request.user.username,
                provider_val,
                model_val,
            )
            provider = ProviderFactory.get_provider(request.user)
            if provider:
                try:
                    result = provider.test_connection()
                    logger.debug("Provider connection test result: %s", result.status.value)
                except Exception as e:
                    logger.warning("Provider connection test failed: %s", e)

            messages.success(request, f"AI Settings for {provider_val.title()} saved successfully!")
            return redirect("settings")

    else:

        if settings_data:

            form = AISettingsForm(
                initial={
                    "provider": settings_data["provider"],
                    "model_name": settings_data["model_name"],
                }
            )

        else:

            form = AISettingsForm()

    current_model = settings_data.get("model_name", "gemini-2.5-flash") if settings_data else "gemini-2.5-flash"
    current_provider = settings_data.get("provider", "gemini") if settings_data else "gemini"

    return render(
        request,
        "meeting/settings.html",
        {
            "form": form,
            "api_key_configured": api_key_configured,
            "current_model": current_model,
            "current_provider": current_provider,
        }
    )  

@login_required(login_url="login")
def dashboard(request):
    AsyncTaskService.check_and_reap_stale_tasks_for_user(request.user)

    meetings = Meeting.objects.filter(
        user=request.user
    ).order_by("-created_at")

    total_meetings = meetings.count()

    completed_meetings = meetings.filter(
        status="completed"
    ).count()

    failed_meetings = meetings.filter(
        status="failed"
    ).count()

    total_duration = sum(
        meeting.duration for meeting in meetings
    )

    formatted_duration = format_duration(total_duration)

    return render(
        request,
        "meeting/dashboard.html",
        {
            "meetings": meetings,

            "total_meetings": total_meetings,

            "completed_meetings": completed_meetings,

            "failed_meetings": failed_meetings,

            "total_duration": formatted_duration,
        }
    )

def register(request):

    if request.method == "POST":

        form = RegisterForm(request.POST)

        if form.is_valid():
            user = form.save(commit=False)
            full_name = form.cleaned_data["first_name"].strip()
            name_parts = full_name.split()
            user.first_name = name_parts[0]

            if len(name_parts) > 1:
                user.last_name = " ".join(name_parts[1:])
            else:
                user.last_name = ""

            user.username = form.cleaned_data["email"] 
            user.email = form.cleaned_data["email"]
            user.save()
            login(request, user)
            return redirect("dashboard")

    else:
        form = RegisterForm()

    return render(
        request,
        "meeting/register.html",
        {
            "form": form
        }
    )

def login_view(request):

    if request.user.is_authenticated:

        return redirect("dashboard")

    form = LoginForm()

    if request.method == "POST":

        form = LoginForm(request.POST)

        if form.is_valid():

            email = form.cleaned_data["email"]

            password = form.cleaned_data["password"]

            user = authenticate(

                request,

                username=email,

                password=password

            )

            if user is not None:

                login(request, user)

                return redirect("dashboard")

            else:

                form.add_error(

                    None,

                    "Invalid email or password."

                )

    return render(

        request,

        "meeting/login.html",

        {

            "form": form

        }

    )

def logout_view(request):

    logout(request)

    return redirect("login")

@login_required(login_url="login")
def meeting_detail(request, meeting_id):
    AsyncTaskService.check_and_reap_stale_task(meeting_id)

    meeting = get_object_or_404(
        Meeting,
        id=meeting_id,
        user=request.user
    )    

    return render(
        request,
        "meeting/meeting_detail.html",
        {
            "meeting": meeting
        }
    )


@login_required(login_url="login")
@require_POST
def discover_models_api(request):
    """
    AJAX endpoint to discover application-compatible AI models for a provider.
    Accepts JSON body or POST form data containing provider and optional unsaved api_key.
    """
    try:
        if request.content_type == "application/json" and request.body:
            try:
                body_data = json.loads(request.body)
            except json.JSONDecodeError:
                return JsonResponse(
                    {
                        "success": False,
                        "data": None,
                        "error": {
                            "code": "INVALID_JSON",
                            "message": "Malformed JSON payload.",
                        },
                    },
                    status=400,
                )
        else:
            body_data = request.POST

        provider_name = (body_data.get("provider") or "").strip().lower()
        if not provider_name:
            provider_name = "gemini"

        if not ProviderRegistry.is_registered(provider_name):
            available = ", ".join(ProviderRegistry.list_providers())
            return JsonResponse(
                {
                    "success": False,
                    "data": None,
                    "error": {
                        "code": "INVALID_PROVIDER",
                        "message": f"Provider '{provider_name}' is not supported. Supported providers: {available}.",
                    },
                },
                status=400,
            )

        api_key = (body_data.get("api_key") or "").strip()
        if not api_key:
            saved_settings = SettingsService.get_settings(request.user)
            if saved_settings and saved_settings.get("api_key"):
                api_key = saved_settings["api_key"]

        # Create provider instance
        provider_settings = {
            "provider": provider_name,
            "api_key": api_key,
        }
        provider = BaseProviderFactory.create_provider_safe(provider_name, provider_settings)
        if not provider:
            return JsonResponse(
                {
                    "success": False,
                    "data": None,
                    "error": {
                        "code": "PROVIDER_INITIALIZATION_FAILED",
                        "message": f"Could not initialize provider '{provider_name}'.",
                    },
                },
                status=400,
            )

        # Discover & filter compatible models
        compatible_models = ModelDiscoveryService.discover_and_filter(provider)

        sanitized_models = []
        for m in compatible_models:
            sanitized_models.append({
                "id": m.id,
                "display_name": m.display_name,
                "status": m.status.value,
                "status_message": m.status_message,
                "source": m.source.value,
                "is_recommended": m.is_recommended,
                "quality_score": m.quality_score,
                "speed_score": m.speed_score,
                "context_window": m.context_window,
            })

        recommended_model = ModelDiscoveryService.get_recommended_model(compatible_models)
        recommended_model_id = recommended_model.id if recommended_model else None

        return JsonResponse({
            "success": True,
            "data": {
                "models": sanitized_models,
                "recommended_model_id": recommended_model_id,
            },
            "error": None,
        })

    except Exception as exc:
        return JsonResponse(
            {
                "success": False,
                "data": None,
                "error": {
                    "code": "DISCOVERY_FAILED",
                    "message": f"Model discovery failed: {str(exc)[:120]}",
                },
            },
            status=500,
        )


@login_required(login_url="login")
@require_POST
def validate_model_api(request):
    """
    AJAX endpoint to selectively validate live access to a single AI model.
    Accepts JSON body or POST form data containing provider, model_id, and optional unsaved api_key.
    """
    try:
        if request.content_type == "application/json" and request.body:
            try:
                body_data = json.loads(request.body)
            except json.JSONDecodeError:
                return JsonResponse(
                    {
                        "success": False,
                        "data": None,
                        "error": {
                            "code": "INVALID_JSON",
                            "message": "Malformed JSON payload.",
                        },
                    },
                    status=400,
                )
        else:
            body_data = request.POST

        provider_name = (body_data.get("provider") or "").strip().lower()
        if not provider_name:
            provider_name = "gemini"

        if not ProviderRegistry.is_registered(provider_name):
            available = ", ".join(ProviderRegistry.list_providers())
            return JsonResponse(
                {
                    "success": False,
                    "data": None,
                    "error": {
                        "code": "INVALID_PROVIDER",
                        "message": f"Provider '{provider_name}' is not supported. Supported providers: {available}.",
                    },
                },
                status=400,
            )

        model_id = (body_data.get("model_id") or "").strip()
        if not model_id:
            return JsonResponse(
                {
                    "success": False,
                    "data": None,
                    "error": {
                        "code": "INVALID_MODEL_ID",
                        "message": "Model ID is required for validation.",
                    },
                },
                status=400,
            )

        api_key = (body_data.get("api_key") or "").strip()
        if not api_key:
            saved_settings = SettingsService.get_settings(request.user)
            if saved_settings and saved_settings.get("api_key"):
                api_key = saved_settings["api_key"]

        if not api_key:
            return JsonResponse(
                {
                    "success": False,
                    "data": {
                        "model_id": model_id,
                        "status": "ACCESS_DENIED",
                    },
                    "error": {
                        "code": "ACCESS_DENIED",
                        "message": "API key is required. Please provide a key or save one in AI Settings.",
                    },
                },
                status=200,
            )

        # Create provider instance
        provider_settings = {
            "provider": provider_name,
            "api_key": api_key,
            "model_name": model_id,
        }
        provider = BaseProviderFactory.create_provider_safe(provider_name, provider_settings)
        if not provider:
            return JsonResponse(
                {
                    "success": False,
                    "data": None,
                    "error": {
                        "code": "PROVIDER_INITIALIZATION_FAILED",
                        "message": f"Could not initialize provider '{provider_name}'.",
                    },
                },
                status=400,
            )

        # Check if deep E2E validation or multi-candidate fallback was requested
        deep_validate = body_data.get("deep_validate", False)
        if isinstance(deep_validate, str):
            deep_validate = deep_validate.lower() in ("true", "1", "yes")

        candidate_models = body_data.get("candidate_models")
        if candidate_models is not None:
            if isinstance(candidate_models, str):
                try:
                    candidate_models = json.loads(candidate_models)
                except Exception:
                    candidate_models = []
            if not isinstance(candidate_models, list):
                candidate_models = []

        has_multiple_candidates = bool(
            candidate_models and (len(candidate_models) > 1 or (len(candidate_models) == 1 and candidate_models[0] != model_id))
        )

        if deep_validate or has_multiple_candidates:
            if not candidate_models:
                candidate_models = [model_id]

            # Selective live model validation with automatic candidate fallback
            validation_result = ModelValidationService.validate_model_with_fallback(
                provider,
                model_id,
                candidate_models=candidate_models,
            )
        else:
            # Lightweight fast-path model access probe
            validation_result = ModelValidationService.validate_model(
                provider,
                model_id,
            )

        details = getattr(validation_result, "details", {}) or {}
        stage = getattr(validation_result, "stage", None)
        if not stage:
            stage = "validation_success" if validation_result.is_valid else "access_validation_failed"

        attempted_models = details.get("attempted_models")
        if attempted_models is None:
            attempted_models = [{
                "model_id": model_id,
                "success": validation_result.is_valid,
                "status": validation_result.status.value if isinstance(validation_result.status, ModelStatus) else str(validation_result.status),
                "stage": stage,
                "message": validation_result.message,
            }]

        if validation_result.is_valid:
            return JsonResponse({
                "success": True,
                "data": {
                    "model_id": validation_result.model_id or model_id,
                    "status": validation_result.status.value if isinstance(validation_result.status, ModelStatus) else str(validation_result.status),
                    "stage": stage,
                    "message": validation_result.message,
                    "selected_model": details.get("selected_model", model_id),
                    "verified_model": details.get("verified_model", validation_result.model_id or model_id),
                    "fallback_used": details.get("fallback_used", False),
                    "attempted_models": attempted_models,
                },
                "error": None,
            })
        else:
            return JsonResponse({
                "success": False,
                "data": {
                    "model_id": validation_result.model_id or model_id,
                    "status": validation_result.status.value if isinstance(validation_result.status, ModelStatus) else str(validation_result.status),
                    "stage": stage,
                    "selected_model": details.get("selected_model", model_id),
                    "verified_model": None,
                    "fallback_used": details.get("fallback_used", False),
                    "attempted_models": attempted_models,
                },
                "error": {
                    "code": validation_result.status.value if isinstance(validation_result.status, ModelStatus) else str(validation_result.status),
                    "stage": stage,
                    "message": validation_result.message,
                    "attempted_models": attempted_models,
                },
            }, status=200)

    except Exception as exc:
        return JsonResponse(
            {
                "success": False,
                "data": None,
                "error": {
                    "code": "VALIDATION_FAILED",
                    "message": f"Model validation error: {str(exc)[:120]}",
                },
            },
            status=500,
        )


STAGE_PROGRESS_MAP = {
    "queued": 10,
    "extracting_audio": 25,
    "uploading_to_ai": 40,
    "waiting_for_ai": 55,
    "transcribing": 70,
    "generating_summary": 85,
    "completed": 100,
    "failed": 0,
}


@login_required(login_url="login")
@require_POST
def analyze_meeting_api(request):
    """
    Asynchronous AJAX endpoint to upload and initiate background meeting processing.
    Returns immediate HTTP 202 Accepted with meeting_id, task_id, and stage: queued.
    """
    try:
        if "meeting_file" not in request.FILES:
            return JsonResponse(
                {
                    "success": False,
                    "data": None,
                    "error": {
                        "code": "MISSING_FILE",
                        "message": "Please select a meeting file.",
                    },
                },
                status=400,
            )

        uploaded_file = request.FILES["meeting_file"]

        allowed_extensions = [
            ".mp4",
            ".mov",
            ".avi",
            ".mkv",
            ".mp3",
            ".wav",
        ]
        file_name = uploaded_file.name.lower()
        if not any(file_name.endswith(ext) for ext in allowed_extensions):
            return JsonResponse(
                {
                    "success": False,
                    "data": None,
                    "error": {
                        "code": "INVALID_FILE_TYPE",
                        "message": "Invalid file. Please upload only MP4, MOV, AVI, MKV, MP3 or WAV.",
                    },
                },
                status=400,
            )

        max_upload_size = getattr(django_settings, "MAX_UPLOAD_SIZE", 52428800)
        if uploaded_file.size > max_upload_size:
            limit_mb = max_upload_size // (1024 * 1024)
            actual_mb = round(uploaded_file.size / (1024 * 1024), 1)
            return JsonResponse(
                {
                    "success": False,
                    "data": None,
                    "error": {
                        "code": "FILE_TOO_LARGE",
                        "message": f"File size ({actual_mb} MB) exceeds the demo limit of {limit_mb} MB. Please upload a shorter meeting clip.",
                    },
                },
                status=400,
            )

        user_settings = SettingsService.get_settings(request.user)
        if not user_settings or not user_settings.get("api_key"):
            return JsonResponse(
                {
                    "success": False,
                    "data": None,
                    "error": {
                        "code": "NO_API_KEY",
                        "message": "Please configure your AI Provider and API Key in Settings before analyzing meetings.",
                    },
                },
                status=400,
            )

        # Preflight validation check on configured AI Provider
        provider = ProviderFactory.get_provider(request.user)
        if not provider:
            return JsonResponse(
                {
                    "success": False,
                    "data": None,
                    "error": {
                        "code": "PROVIDER_NOT_CONFIGURED",
                        "message": "Please configure your AI Provider and API Key in Settings before analyzing meetings.",
                    },
                },
                status=400,
            )

        preflight = ModelValidationService.preflight_check(provider)
        if not preflight.is_valid:
            return JsonResponse(
                {
                    "success": False,
                    "data": None,
                    "error": {
                        "code": preflight.status.value,
                        "message": preflight.message,
                    },
                },
                status=400,
            )

        fs = FileSystemStorage()
        filename = fs.save(uploaded_file.name, uploaded_file)
        filepath = fs.path(filename)

        meeting = Meeting.objects.create(
            user=request.user,
            meeting_name=filename,
            original_file=filename,
            audio_file="",
            transcript_file="",
            provider=user_settings.get("provider", "gemini"),
            model_name=user_settings.get("model_name", "gemini-2.5-flash"),
            meeting_type="",
            transcript="",
            ai_report="",
            duration=0.0,
            file_size=uploaded_file.size,
            status="processing",
            stage="queued",
        )

        task_id = AsyncTaskService.acquire_processing_lease(meeting.id, user=request.user)
        if not task_id:
            logger.error("Failed to acquire processing lease for new meeting %d", meeting.id)
            return JsonResponse(
                {
                    "success": False,
                    "data": None,
                    "error": {
                        "code": "LEASE_ACQUISITION_FAILED",
                        "message": "Could not start background processing task.",
                    },
                },
                status=500,
            )

        # Dispatch background processing task via bounded ThreadPoolExecutor
        executor = AsyncTaskService.get_executor()
        executor.submit(
            AsyncTaskService.run_pipeline_stepwise,
            meeting.id,
            task_id,
            filepath,
        )

        return JsonResponse(
            {
                "success": True,
                "data": {
                    "meeting_id": meeting.id,
                    "task_id": task_id,
                    "status": "processing",
                    "stage": "queued",
                    "message": "Meeting uploaded successfully. Processing started in background.",
                },
                "error": None,
            },
            status=202,
        )

    except Exception as exc:
        logger.exception("Error in analyze_meeting_api: %s", exc)
        return JsonResponse(
            {
                "success": False,
                "data": None,
                "error": {
                    "code": "SERVER_ERROR",
                    "message": f"An error occurred while initiating analysis: {str(exc)[:120]}",
                },
            },
            status=500,
        )


@login_required(login_url="login")
def meeting_status_api(request, meeting_id):
    """
    AJAX polling endpoint to retrieve durable meeting processing status and checkpoints.
    Scoped strictly to the authenticated user.
    """
    # Detect and reap stale status on-demand if worker is orphaned
    AsyncTaskService.check_and_reap_stale_task(meeting_id)

    meeting = get_object_or_404(Meeting, id=meeting_id, user=request.user)

    if meeting.status == "completed":
        progress_pct = 100
    elif meeting.status == "failed":
        progress_pct = 0
    else:
        progress_pct = STAGE_PROGRESS_MAP.get(meeting.stage, 10)

    return JsonResponse(
        {
            "success": True,
            "data": {
                "meeting_id": meeting.id,
                "task_id": meeting.task_id,
                "status": meeting.status,
                "stage": meeting.stage,
                "progress_percentage": progress_pct,
                "duration": meeting.duration,
                "has_transcript": bool(meeting.transcript),
                "transcript": meeting.transcript if meeting.transcript else "",
                "has_ai_report": bool(meeting.ai_report),
                "ai_report": meeting.ai_report if meeting.ai_report else "",
                "error_message": meeting.error_message,
            },
            "error": None,
        }
    )


@login_required(login_url="login")
@require_POST
def retry_meeting_api(request, meeting_id):
    """
    Asynchronous AJAX endpoint to resume processing on a failed or stale meeting.
    Reuses existing checkpoints (audio, remote Gemini file, transcript) without duplicating Meeting row.
    """
    try:
        # Reap stale status if applicable
        AsyncTaskService.check_and_reap_stale_task(meeting_id)

        meeting = get_object_or_404(Meeting, id=meeting_id, user=request.user)

        if meeting.status == "completed":
            return JsonResponse(
                {
                    "success": False,
                    "data": None,
                    "error": {
                        "code": "ALREADY_COMPLETED",
                        "message": "Meeting analysis has already completed successfully.",
                    },
                },
                status=400,
            )

        if meeting.status == "processing":
            return JsonResponse(
                {
                    "success": False,
                    "data": None,
                    "error": {
                        "code": "ALREADY_PROCESSING",
                        "message": "Meeting is currently actively processing.",
                    },
                },
                status=409,
            )

        # Preflight validation check on configured AI Provider
        provider = ProviderFactory.get_provider(request.user)
        if not provider:
            return JsonResponse(
                {
                    "success": False,
                    "data": None,
                    "error": {
                        "code": "PROVIDER_NOT_CONFIGURED",
                        "message": "Please configure your AI Provider and API Key in Settings before analyzing meetings.",
                    },
                },
                status=400,
            )

        preflight = ModelValidationService.preflight_check(provider)
        if not preflight.is_valid:
            return JsonResponse(
                {
                    "success": False,
                    "data": None,
                    "error": {
                        "code": preflight.status.value,
                        "message": preflight.message,
                    },
                },
                status=400,
            )

        # Acquire processing lease with allow_retry=True
        task_id = AsyncTaskService.acquire_processing_lease(meeting.id, user=request.user, allow_retry=True)
        if not task_id:
            logger.error("Failed to acquire processing lease for retry on meeting %d", meeting.id)
            return JsonResponse(
                {
                    "success": False,
                    "data": None,
                    "error": {
                        "code": "LEASE_ACQUISITION_FAILED",
                        "message": "Could not acquire processing lease for retry.",
                    },
                },
                status=409,
            )

        # Resolve original media filepath if available
        media_filepath = ""
        if meeting.original_file:
            try:
                media_filepath = meeting.original_file.path
            except Exception:
                pass
            if not media_filepath or not os.path.exists(media_filepath):
                media_filepath = os.path.join(django_settings.MEDIA_ROOT, str(meeting.original_file))

        # Dispatch background processing task via ThreadPoolExecutor
        executor = AsyncTaskService.get_executor()
        executor.submit(
            AsyncTaskService.run_pipeline_stepwise,
            meeting.id,
            task_id,
            media_filepath,
        )

        return JsonResponse(
            {
                "success": True,
                "data": {
                    "meeting_id": meeting.id,
                    "task_id": task_id,
                    "status": "processing",
                    "stage": "queued",
                    "message": "Meeting processing resumed from checkpoint.",
                },
                "error": None,
            },
            status=202,
        )

    except Http404:
        raise
    except Exception as exc:
        logger.exception("Error in retry_meeting_api: %s", exc)
        return JsonResponse(
            {
                "success": False,
                "data": None,
                "error": {
                    "code": "SERVER_ERROR",
                    "message": f"An error occurred while retrying meeting analysis: {str(exc)[:120]}",
                },
            },
            status=500,
        )