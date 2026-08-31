import os
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
        Extracts 16kHz mono PCM 16-bit WAV audio from input media file using FFmpeg.
        If output_path is not provided, derives it from input_path with .wav extension.
        """
        if not output_path:
            output_path = os.path.splitext(input_path)[0] + ".wav"

        ffmpeg_cmd = cls.get_ffmpeg_path()

        subprocess.run(
            [
                ffmpeg_cmd,
                "-y",
                "-i",
                input_path,
                "-vn",
                "-acodec",
                "pcm_s16le",
                "-ar",
                "16000",
                "-ac",
                "1",
                output_path,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        return output_path

    @staticmethod
    def get_audio_info(audio_path):
        """
        Inspects the WAV file and returns metadata dictionary including duration.
        """
        with wave.open(audio_path, "rb") as audio:
            channels = audio.getnchannels()
            sample_width = audio.getsampwidth()
            sample_rate = audio.getframerate()
            total_frames = audio.getnframes()
            duration_seconds = (
                round(total_frames / sample_rate, 2) if sample_rate else 0.0
            )

            return {
                "channels": channels,
                "sample_width": sample_width,
                "sample_rate": sample_rate,
                "total_frames": total_frames,
                "duration_seconds": duration_seconds,
            }
