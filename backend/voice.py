"""Voice output chooses a local browser path for development and ElevenLabs for production."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from .settings import is_production, setting


class VoiceError(RuntimeError):
    pass


class VoiceService:
    def __init__(self) -> None:
        self.preference = setting("VOICE_PROVIDER", "auto").lower()
        self.api_key = setting("ELEVENLABS_API_KEY")
        self.voice_id = setting("ELEVENLABS_VOICE_ID")
        self.model_id = setting("ELEVENLABS_MODEL_ID", "eleven_flash_v2_5")

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.voice_id)

    @property
    def provider(self) -> str:
        if self.preference in {"browser", "local", "local-browser"}:
            return "browser"
        if self.preference == "elevenlabs":
            return "elevenlabs" if self.configured else "unconfigured"
        return "elevenlabs" if is_production() and self.configured else "browser"

    def status(self) -> dict[str, object]:
        provider = self.provider
        return {
            "provider": provider,
            "label": "ElevenLabs voice" if provider == "elevenlabs" else "Local browser voice",
            "configured": provider != "unconfigured",
            "local": provider == "browser",
        }

    def speak(self, text: str) -> tuple[bytes, str]:
        if self.provider == "browser":
            raise VoiceError("Local browser voice is selected; speech is synthesized in the browser.")
        if self.provider != "elevenlabs":
            raise VoiceError("ElevenLabs voice is selected but its credentials are incomplete.")
        text = " ".join((text or "").split())[:1800]
        if not text:
            raise VoiceError("There is nothing to speak yet.")
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{urllib.parse.quote(self.voice_id)}/stream?output_format=mp3_44100_128"
        payload = json.dumps(
            {
                "text": text,
                "model_id": self.model_id,
                "voice_settings": {"stability": 0.42, "similarity_boost": 0.72},
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=payload,
            headers={"Accept": "audio/mpeg", "Content-Type": "application/json", "xi-api-key": self.api_key},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                return response.read(), response.headers.get_content_type() or "audio/mpeg"
        except urllib.error.HTTPError as error:
            if error.code in {401, 403}:
                raise VoiceError("ElevenLabs rejected the configured API key or voice access. Check ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID.") from error
            raise VoiceError("ElevenLabs could not synthesize this edit right now.") from error
        except urllib.error.URLError as error:
            raise VoiceError("ElevenLabs could not synthesize this edit right now.") from error
