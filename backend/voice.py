"""Voice output with a local Kokoro path and an ElevenLabs production path."""

from __future__ import annotations

import io
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import wave
from functools import lru_cache
from threading import RLock
from typing import Any

from .settings import is_production, setting


class VoiceError(RuntimeError):
    pass


KOKORO_MODEL_REPO = "hexgrad/Kokoro-82M"
KOKORO_SAMPLE_RATE = 24_000
MAX_KOKORO_TEXT_CHARS = 1_200
KOKORO_WARMUP_TEXT = "Artha is ready to read your purchase plan clearly."
_KOKORO_LOCK = RLock()
_KOKORO_WARMED: set[tuple[str, str, str, float, str]] = set()


def _kokoro_speed() -> float:
    try:
        speed = float(setting("KOKORO_SPEED", "0.98"))
    except ValueError as error:
        raise VoiceError("KOKORO_SPEED must be a number between 0.8 and 1.2.") from error
    if not 0.8 <= speed <= 1.2:
        raise VoiceError("KOKORO_SPEED must be between 0.8 and 1.2.")
    return speed


def _kokoro_device() -> str:
    configured = setting("KOKORO_DEVICE", "auto").lower()
    if configured in {"cpu", "cuda", "mps"}:
        if configured == "mps":
            os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
        return configured
    if configured != "auto":
        raise VoiceError("KOKORO_DEVICE must be auto, cpu, cuda, or mps.")
    if sys.platform == "darwin":
        os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
    try:
        import torch
    except (ImportError, OSError):
        return "cpu"
    if torch.cuda.is_available():
        return "cuda"
    mps = getattr(torch.backends, "mps", None)
    if mps and mps.is_available():
        os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
        return "mps"
    return "cpu"


@lru_cache(maxsize=1)
def _kokoro_dependencies() -> tuple[Any, Any] | None:
    try:
        from kokoro import KPipeline
        import numpy as np
    except (ImportError, OSError):
        return None
    return KPipeline, np


def _kokoro_options() -> tuple[str, str, str, float, str]:
    return (
        setting("KOKORO_LANG_CODE", "a").lower(),
        setting("KOKORO_VOICE", "af_heart"),
        KOKORO_MODEL_REPO,
        _kokoro_speed(),
        _kokoro_device(),
    )


@lru_cache(maxsize=4)
def _kokoro_pipeline(lang_code: str, model_repo: str, device: str) -> Any:
    dependencies = _kokoro_dependencies()
    if dependencies is None:
        raise VoiceError("Kokoro local voice is unavailable. Install backend/requirements-kokoro.txt and restart the app.")
    pipeline_type, _ = dependencies
    try:
        return pipeline_type(lang_code=lang_code, repo_id=model_repo, device=device)
    except Exception as error:
        raise VoiceError("Kokoro could not load its local English voice. Check the model cache and KOKORO_DEVICE.") from error


def _kokoro_audio_with_options(text: str, options: tuple[str, str, str, float, str]) -> bytes:
    dependencies = _kokoro_dependencies()
    if dependencies is None:
        raise VoiceError("Kokoro local voice is unavailable. Install backend/requirements-kokoro.txt and restart the app.")
    _, np = dependencies
    lang_code, voice, model_repo, speed, device = options
    try:
        with _KOKORO_LOCK:
            pipeline = _kokoro_pipeline(lang_code, model_repo, device)
            parts: list[Any] = []
            for _, _, generated in pipeline(text, voice=voice, speed=speed, split_pattern=None):
                if generated is None:
                    continue
                if hasattr(generated, "detach"):
                    generated = generated.detach()
                if hasattr(generated, "cpu"):
                    generated = generated.cpu()
                samples = np.asarray(generated, dtype=np.float32).reshape(-1)
                if samples.size:
                    parts.append(samples)
    except VoiceError:
        raise
    except Exception as error:
        raise VoiceError("Kokoro local voice could not synthesize this purchase summary.") from error
    if not parts:
        raise VoiceError("Kokoro local voice returned no audio.")
    audio = np.concatenate(parts)
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2", copy=False)
    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(KOKORO_SAMPLE_RATE)
        wav_file.writeframes(pcm.tobytes())
    return output.getvalue()


def _kokoro_audio(text: str) -> bytes:
    text = " ".join((text or "").split())
    if not text:
        raise VoiceError("There is nothing to speak yet.")
    if len(text) > MAX_KOKORO_TEXT_CHARS:
        raise VoiceError(f"Kokoro local voice supports summaries up to {MAX_KOKORO_TEXT_CHARS:,} characters.")
    return _kokoro_audio_with_options(text, _kokoro_options())


def _kokoro_warm() -> bool:
    options = _kokoro_options()
    with _KOKORO_LOCK:
        if options in _KOKORO_WARMED:
            return False
        _kokoro_audio_with_options(KOKORO_WARMUP_TEXT, options)
        _KOKORO_WARMED.add(options)
    return True


class VoiceService:
    def __init__(self) -> None:
        self.preference = setting("VOICE_PROVIDER", "auto").lower()
        self.api_key = setting("ELEVENLABS_API_KEY")
        self.voice_id = setting("ELEVENLABS_VOICE_ID")
        self.model_id = setting("ELEVENLABS_MODEL_ID", "eleven_flash_v2_5")

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.voice_id)

    @staticmethod
    def _local_provider() -> str:
        return setting("LOCAL_VOICE_PROVIDER", "browser").lower()

    def _resolve_local_provider(self) -> str:
        local = self._local_provider()
        if local in {"kokoro", "local-kokoro", "studio"}:
            return "kokoro" if _kokoro_dependencies() is not None else "browser"
        return "browser"

    @property
    def provider(self) -> str:
        if self.preference in {"browser", "local", "local-browser"}:
            return "browser"
        if self.preference in {"kokoro", "local-kokoro", "studio"}:
            return "kokoro" if _kokoro_dependencies() is not None else "kokoro-unavailable"
        if self.preference == "elevenlabs":
            return "elevenlabs" if self.configured else "unconfigured"
        if is_production():
            return "elevenlabs" if self.configured else "unconfigured"
        return self._resolve_local_provider()

    def status(self) -> dict[str, object]:
        provider = self.provider
        requested_local = self._local_provider()
        if provider == "elevenlabs":
            label = "ElevenLabs voice"
        elif provider == "kokoro":
            label = "Local Kokoro voice"
        elif provider == "kokoro-unavailable":
            label = "Local Kokoro voice unavailable"
        elif provider == "unconfigured":
            label = "ElevenLabs voice not configured"
        elif requested_local in {"kokoro", "local-kokoro", "studio"}:
            label = "Local browser voice (Kokoro unavailable)"
        else:
            label = "Local browser voice"
        return {
            "provider": provider,
            "label": label,
            "configured": provider not in {"unconfigured", "kokoro-unavailable"},
            "local": provider in {"browser", "kokoro", "kokoro-unavailable"},
            "requested_local_provider": requested_local,
            "ready": provider != "kokoro" or bool(_KOKORO_WARMED),
        }

    def warm(self) -> dict[str, object]:
        provider = self.provider
        if provider == "kokoro":
            return {"provider": provider, "warmed": _kokoro_warm(), "ready": True}
        if provider == "browser":
            return {"provider": provider, "warmed": False, "ready": True}
        if provider == "unconfigured":
            raise VoiceError("ElevenLabs is required in production but its API key or voice ID is missing.")
        raise VoiceError("Kokoro local voice is unavailable. Install backend/requirements-kokoro.txt and restart the app.")

    def speak(self, text: str) -> tuple[bytes, str]:
        if self.provider == "browser":
            raise VoiceError("Local browser voice is selected; speech is synthesized in the browser.")
        if self.provider == "kokoro":
            return _kokoro_audio(text), "audio/wav"
        if self.provider == "kokoro-unavailable":
            raise VoiceError("Kokoro local voice is unavailable. Install backend/requirements-kokoro.txt and restart the app.")
        if self.provider != "elevenlabs":
            raise VoiceError("ElevenLabs is required in production but its API key or voice ID is missing.")
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
