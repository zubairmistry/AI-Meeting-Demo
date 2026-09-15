import os
import re
import wave
import subprocess
import shutil
from pathlib import Path


class AudioService:

    @classmethod
    def get_ffmpeg_path(cls):
        """
        Dynamically discovers the FFmpeg binary:
        1. Environment variable FFMPEG_PATH (if set)
        2. System PATH (e.g. standard Linux /usr/bin/ffmpeg)
        3. Project-local bin/ffmpeg directory (if downloaded during cloud build)
        4. Local Windows development fallback
        5. Default fallback to 'ffmpeg'
        """
        env_path = os.getenv("FFMPEG_PATH")
        if env_path:
            return env_path

        which_path = shutil.which("ffmpeg")
        if which_path:
            return which_path

        project_root = Path(__file__).resolve().parent.parent.parent
        project_bin = project_root / "bin" / "ffmpeg"
        if project_bin.exists():
            return str(project_bin)

        project_bin_exe = project_root / "bin" / "ffmpeg.exe"
        if project_bin_exe.exists():
            return str(project_bin_exe)

        win_fallback = r"C:\ffmpeg-9.0.1-essentials_build\bin\ffmpeg.exe"
        if os.path.exists(win_fallback):
            return win_fallback

        return "ffmpeg"

    @classmethod
    def extract_audio(cls, input_path, output_path=None):
        """
        Extracts 16kHz mono 32kbps MP3 audio (via libmp3lame) from input media file using FFmpeg.
        If input_path is already a valid MP3 file and no output_path is specified, returns it directly.
        If output_path explicitly ends with .wav, extracts as 16kHz mono PCM 16-bit WAV for backward compatibility.
        Guarantees input_path != output_path to prevent FFmpeg self-overwrite collisions.
        """
        base, ext = os.path.splitext(input_path)
        ext_lower = ext.lower()

        # If already an MP3 file and no custom output path requested, return directly
        if ext_lower == ".mp3" and not output_path:
            return input_path

        if not output_path:
            output_path = f"{base}.mp3"

        # Prevent input and output being the same file
        if os.path.abspath(input_path) == os.path.abspath(output_path):
            if output_path.lower().endswith(".wav"):
                output_path = f"{base}_extracted.wav"
            else:
                output_path = f"{base}_extracted.mp3"

        out_ext = os.path.splitext(output_path)[1].lower()
        ffmpeg_cmd = cls.get_ffmpeg_path()

        if out_ext == ".wav":
            # Backward-compatible WAV extraction when .wav is explicitly requested
            ffmpeg_args = [
                ffmpeg_cmd,
                "-y",
                "-i", input_path,
                "-vn",
                "-acodec", "pcm_s16le",
                "-ar", "16000",
                "-ac", "1",
                output_path,
            ]
        else:
            # Production MP3 extraction: 32kbps mono 16kHz libmp3lame
            ffmpeg_args = [
                ffmpeg_cmd,
                "-y",
                "-i", input_path,
                "-vn",
                "-acodec", "libmp3lame",
                "-b:a", "32k",
                "-ar", "16000",
                "-ac", "1",
                output_path,
            ]

        subprocess.run(
            ffmpeg_args,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        return output_path

    @classmethod
    def get_audio_info(cls, audio_path):
        """
        Inspects the audio file (MP3 or WAV) and returns metadata dictionary including duration.
        """
        duration_seconds = 0.0
        sample_rate = 16000
        channels = 1
        sample_width = 2
        total_frames = 0

        # Attempt wave.open for WAV files
        try:
            with wave.open(audio_path, "rb") as audio:
                channels = audio.getnchannels()
                sample_width = audio.getsampwidth()
                sample_rate = audio.getframerate()
                total_frames = audio.getnframes()
                duration_seconds = round(total_frames / sample_rate, 2) if sample_rate else 0.0
                return {
                    "channels": channels,
                    "sample_width": sample_width,
                    "sample_rate": sample_rate,
                    "total_frames": total_frames,
                    "duration_seconds": duration_seconds,
                }
        except Exception:
            pass

        # For MP3 or non-WAV media, inspect duration via FFmpeg
        try:
            ffmpeg_cmd = cls.get_ffmpeg_path()
            res = subprocess.run(
                [ffmpeg_cmd, "-i", audio_path],
                capture_output=True,
                text=True,
                errors="replace"
            )
            match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", res.stderr)
            if match:
                hours = float(match.group(1))
                minutes = float(match.group(2))
                seconds = float(match.group(3))
                duration_seconds = round(hours * 3600 + minutes * 60 + seconds, 2)
        except Exception:
            pass

        return {
            "channels": channels,
            "sample_width": sample_width,
            "sample_rate": sample_rate,
            "total_frames": total_frames,
            "duration_seconds": duration_seconds,
        }
