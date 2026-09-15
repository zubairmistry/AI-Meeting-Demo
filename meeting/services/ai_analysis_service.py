from meeting.services.provider_factory import ProviderFactory


class AIAnalysisService:

    @staticmethod
    def generate_transcript(user, audio_path):

        provider = ProviderFactory.get_provider(user)

        if provider is None:
            return None

        if getattr(provider, "provider", "") == "claude":
            raise NotImplementedError(
                "Anthropic Claude does not natively support audio transcription. "
                "Please select an audio-capable provider (e.g. Gemini) in AI Settings to transcribe media recordings."
            )

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

    @staticmethod
    def generate_report(user, transcript):

        provider = ProviderFactory.get_provider(user)

        if provider is None:
            return "Provider Not Configured"

        return provider.generate_report(transcript)