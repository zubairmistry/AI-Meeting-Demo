from meeting.services.provider_factory import ProviderFactory


class AIAnalysisService:

    @staticmethod
    def generate_transcript(user, audio_path):

        provider = ProviderFactory.get_provider(user)

        if provider is None:
            return None

        audio_file = provider.upload_audio(audio_path)

        audio_file = provider.wait_until_ready(audio_file)

        transcript = provider.generate_transcript(audio_file)

        return transcript

    @staticmethod
    def generate_report(user, transcript):

        provider = ProviderFactory.get_provider(user)

        if provider is None:
            return "Provider Not Configured"

        return provider.generate_report(transcript)