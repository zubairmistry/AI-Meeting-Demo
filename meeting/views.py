from django.conf import settings
from django.shortcuts import render
from django.core.files.storage import FileSystemStorage


import os
import subprocess
from datetime import datetime

from .models import AISettings, Meeting, format_duration
from .forms import (
    AISettingsForm,
    RegisterForm,
    LoginForm
)
import traceback
from django.shortcuts import redirect
from meeting.services.settings_service import SettingsService
from meeting.services.provider_factory import ProviderFactory
from meeting.services.ai_analysis_service import AIAnalysisService
from meeting.services.audio_service import AudioService
from meeting.services.transcript_service import TranscriptService

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.shortcuts import render, redirect
from django.contrib.auth import login
from .forms import RegisterForm
from django.shortcuts import get_object_or_404

@login_required(login_url="login")
def home(request):

    print("=" * 60)
    print("Gemini API Key")
    print("=" * 60)
    print("Gemini API Loaded Successfully")
    print("=" * 60)
     

    status = "Waiting for meeting upload..."
    transcript = ""
    report = ""

    if request.method == "POST":

        uploaded_file = request.FILES.get("meeting_file")

        if uploaded_file:

            user_settings = SettingsService.get_settings(request.user)
            if not user_settings or not user_settings.get("api_key"):
                status = "⚠️ Please configure your Gemini API Key in Settings before analyzing meetings."
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

            max_upload_size = getattr(settings, "MAX_UPLOAD_SIZE", 52428800)
            if uploaded_file.size > max_upload_size:
                limit_mb = max_upload_size // (1024 * 1024)
                actual_mb = round(uploaded_file.size / (1024 * 1024), 1)
                status = f"⚠️ File size ({actual_mb} MB) exceeds the demo limit of {limit_mb} MB. Please upload a shorter meeting clip."
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

                print("=" * 60)
                print("Audio Information")
                print("=" * 60)

                for key, value in audio_info.items():
                    print(f"{key} : {value}")

                print("=" * 60)    

                print("=" * 60)
                print("Audio Extracted Successfully")
                print("Audio Path :", audio_path)
                print("=" * 60)

                print("=" * 60)
                print("Generating Transcript...")
                print("=" * 60)

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

                print("=" * 60)
                print("Transcript Generated Successfully")

                print("Transcript Path :", transcript_path)
                print("=" * 60) 

                print("Transcript Saved Successfully")
                print("=" * 60)

                print("=" * 60)
                print("Meeting Transcript")
                print("=" * 60)
                print(transcript)
                print("=" * 60)

                print("=" * 60)
                print("Generating AI Report...")
                print("=" * 60)
                report = AIAnalysisService.generate_report(request.user,transcript)
                print("=" * 60)
                print("AI Report")
                print("=" * 60)
                print(report)
                print("=" * 60)

                settings_obj = SettingsService.get_settings(request.user)

                Meeting.objects.create(
                    user=request.user, 

                    meeting_name=filename,

                    original_file=filename,

                    audio_file=os.path.basename(audio_path),

                    transcript_file=os.path.basename(transcript_path),

                    provider=settings_obj["provider"],

                    model_name=settings_obj["model_name"],

                    meeting_type="",

                    transcript=transcript,

                    ai_report=report,

                    duration=meeting_info["duration"],

                    file_size=uploaded_file.size,

                    status="completed"
                )      

            except subprocess.CalledProcessError:
                status = "❌ Failed to extract audio from the uploaded media file. Please ensure a valid audio/video file is uploaded."
                return render(request, "meeting/index.html", 
                    {"status": status,
                     "transcript": transcript,
                     "report": report,
                      }
                )

            except TimeoutError:
                status = "⏳ Meeting processing timed out. Please try uploading a shorter recording clip for this demo."
                return render(request, "meeting/index.html", 
                    {"status": status,
                     "transcript": transcript,
                     "report": report,
                     }
                )

            except Exception as e:
                traceback.print_exc()
                status = f"❌ An error occurred during processing: {str(e)}"
                return render(request, "meeting/index.html", 
                    {"status": status,
                     "transcript": transcript,
                     "report": report,
                     }
                )          

            print("=" * 60)
            print("Meeting Information")
            print("=" * 60)
            for key, value in meeting_info.items():
                print(f"{key} : {value}")
            print("=" * 60)

            status = f"File Saved Successfully : {filename}"

        else:

            status = "Please select a meeting file."

    return render(
        request,
        "meeting/index.html",
        {
            "status": status,
            "transcript": transcript,
            "report": report,
        }
    ) 

@login_required(login_url="login")
def settings(request):

    settings_data = SettingsService.get_settings(request.user)
    api_key_configured = bool(settings_data and settings_data.get("api_key"))

    if request.method == "POST":

        form = AISettingsForm(request.POST)
        
        print(form.errors)
        if form.is_valid():

            print("=" * 60)
            print(form.cleaned_data)
            print("=" * 60)

            SettingsService.save_settings(
                user=request.user,
                provider=form.cleaned_data["provider"],
                api_key=form.cleaned_data["api_key"],
                model_name=form.cleaned_data["model_name"],
            )
            provider = ProviderFactory.get_provider(request.user)
            if provider:
                try:
                    result = provider.test_connection()

                    print("=" * 60)
                    print("Provider Connection Test")
                    print("=" * 60)
                    print(result)
                    print("=" * 60)

                except Exception as e:
                    print("=" * 60)
                    print("Provider Connection Failed")
                    print("=" * 60)
                    print(e)
                    print("=" * 60)    

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

    return render(
        request,
        "meeting/settings.html",
        {
            "form": form,
            "api_key_configured": api_key_configured,
        }
    )  

@login_required(login_url="login")
def dashboard(request):

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
        print("="*50)
        print(request.POST)
        print("="*50)

        print("="*50)
        print(form.errors)
        print("="*50)

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