"""Local-first voice service: local Whisper/on-device STT and local Kokoro / macOS say TTS.

Hosted speech services (SLNG, ElevenLabs, and cloud-backed browser Web Speech API)
are excluded from the active default voice flow so speech recognition, speech
synthesis, and conversation processing run locally on the user's machine without
paid API keys.
"""

from __future__ import annotations

import base64
import binascii
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import wave
from functools import lru_cache
from pathlib import Path
from threading import RLock
from typing import Any

from .settings import is_production, setting
from .usage import record_usage


class VoiceError(RuntimeError):
    pass


KOKORO_MODEL_REPO = "hexgrad/Kokoro-82M"
KOKORO_SAMPLE_RATE = 24_000
MAX_KOKORO_TEXT_CHARS = 1_200
KOKORO_WARMUP_TEXT = "Artha is ready to read your purchase plan clearly."
SLNG_TTS_MODEL = "aura-2-thalia-en"
DEFAULT_WHISPER_MODEL = "openai/whisper-tiny.en"
_KOKORO_LOCK = RLock()
_WHISPER_LOCK = RLock()
_KOKORO_WARMED: set[tuple[str, str, str, float, str]] = set()


def _ffmpeg_bin() -> str | None:
    for candidate in (
        shutil.which("ffmpeg"),
        "/opt/homebrew/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
    ):
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def _say_bin() -> str | None:
    for candidate in (shutil.which("say"), "/usr/bin/say"):
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


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


def _macos_say_audio(text: str) -> bytes:
    """Synthesize speech 100% locally on macOS using /usr/bin/say into 22.05kHz PCM WAV."""
    cleaned = " ".join((text or "").split())[:MAX_KOKORO_TEXT_CHARS]
    if not cleaned:
        raise VoiceError("There is nothing to speak yet.")
    say_bin = _say_bin()
    if not say_bin:
        raise VoiceError("Local speech synthesis requires Kokoro or macOS /usr/bin/say.")
    voice_name = setting("MACOS_SAY_VOICE", "")
    with tempfile.NamedTemporaryFile(prefix="artha-tts-", suffix=".wav", delete=False) as tmp:
        wav_path = Path(tmp.name)
    try:
        cmd = [say_bin, "-o", str(wav_path), "--data-format=LEI16@22050"]
        if voice_name:
            cmd.extend(["-v", voice_name])
        cmd.append(cleaned)
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20, check=False)
        if proc.returncode != 0 or not wav_path.is_file() or wav_path.stat().st_size <= 44:
            # Retry without custom voice name in case the voice isn't installed
            if voice_name:
                proc = subprocess.run(
                    [say_bin, "-o", str(wav_path), "--data-format=LEI16@22050", cleaned],
                    capture_output=True,
                    text=True,
                    timeout=20,
                    check=False,
                )
        if proc.returncode != 0 or not wav_path.is_file() or wav_path.stat().st_size <= 44:
            raise VoiceError("Local macOS speech synthesis failed to generate audio.")
        return wav_path.read_bytes()
    finally:
        try:
            wav_path.unlink(missing_ok=True)
        except OSError:
            pass


def _kokoro_warm() -> bool:
    options = _kokoro_options()
    with _KOKORO_LOCK:
        if options in _KOKORO_WARMED:
            return False
        _kokoro_audio_with_options(KOKORO_WARMUP_TEXT, options)
        _KOKORO_WARMED.add(options)
    return True


def _normalize_to_16k_wav(audio_bytes: bytes, content_type: str) -> bytes:
    """Ensure audio is 16kHz mono 16-bit PCM WAV for local STT."""
    base_mime = content_type.split(";", 1)[0].strip().lower()
    if base_mime == "audio/wav" and audio_bytes[:4] == b"RIFF":
        try:
            with wave.open(io.BytesIO(audio_bytes), "rb") as wav_in:
                if wav_in.getnchannels() == 1 and wav_in.getsampwidth() == 2 and wav_in.getframerate() == 16000:
                    return audio_bytes
        except wave.Error:
            pass
    ffmpeg = _ffmpeg_bin()
    if not ffmpeg:
        if audio_bytes[:4] == b"RIFF":
            return audio_bytes
        raise VoiceError("Install ffmpeg (/opt/homebrew/bin/ffmpeg) to convert non-WAV recordings for local speech recognition.")
    ext = {
        "audio/webm": ".webm",
        "audio/ogg": ".ogg",
        "audio/mp4": ".m4a",
        "audio/mpeg": ".mp3",
        "audio/wav": ".wav",
    }.get(base_mime, ".bin")
    with tempfile.NamedTemporaryFile(prefix="artha-stt-in-", suffix=ext, delete=False) as src_tmp, \
         tempfile.NamedTemporaryFile(prefix="artha-stt-out-", suffix=".wav", delete=False) as dst_tmp:
        src_path = Path(src_tmp.name)
        dst_path = Path(dst_tmp.name)
        src_tmp.write(audio_bytes)
    try:
        proc = subprocess.run(
            [ffmpeg, "-y", "-i", str(src_path), "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(dst_path)],
            capture_output=True,
            timeout=15,
            check=False,
        )
        if proc.returncode != 0 or not dst_path.is_file() or dst_path.stat().st_size <= 44:
            raise VoiceError("Could not decode the microphone recording into 16kHz PCM WAV.")
        return dst_path.read_bytes()
    finally:
        src_path.unlink(missing_ok=True)
        dst_path.unlink(missing_ok=True)


@lru_cache(maxsize=1)
def _faster_whisper_model() -> Any | None:
    try:
        from faster_whisper import WhisperModel
        model_name = setting("WHISPER_MODEL", "base.en")
        return WhisperModel(model_name, device="cpu", compute_type="int8")
    except Exception:
        return None


@lru_cache(maxsize=1)
def _transformers_whisper_pipeline() -> Any | None:
    try:
        from transformers import pipeline
        model_id = setting("WHISPER_HF_MODEL", DEFAULT_WHISPER_MODEL)
        allow_download = setting("WHISPER_ALLOW_DOWNLOAD", "1").lower() not in {"0", "false", "no"}
        try:
            return pipeline(
                "automatic-speech-recognition",
                model=model_id,
                device=_kokoro_device(),
                model_kwargs={"local_files_only": True},
            )
        except Exception:
            if not allow_download:
                return None
            return pipeline(
                "automatic-speech-recognition",
                model=model_id,
                device=_kokoro_device(),
            )
    except Exception:
        return None


def _whisper_cli_bin() -> str | None:
    for name in ("whisper-cli", "whisper-cpp", "whisper"):
        found = shutil.which(name)
        if found:
            return found
        for prefix in ("/opt/homebrew/bin", "/usr/local/bin"):
            candidate = os.path.join(prefix, name)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
    return None


def _local_stt_status() -> dict[str, Any]:
    try:
        import faster_whisper  # noqa: F401
        return {"provider": "faster_whisper", "model": setting("WHISPER_MODEL", "base.en"), "local": True, "ready": True}
    except ImportError:
        pass
    cli = _whisper_cli_bin()
    if cli:
        return {"provider": "whisper_cli", "model": Path(cli).name, "local": True, "ready": True}
    try:
        import transformers  # noqa: F401
        import torch  # noqa: F401
        return {
            "provider": "transformers_whisper",
            "model": setting("WHISPER_HF_MODEL", DEFAULT_WHISPER_MODEL),
            "local": True,
            "ready": True,
        }
    except ImportError:
        pass
    return {
        "provider": "local_whisper_unconfigured",
        "model": DEFAULT_WHISPER_MODEL,
        "local": True,
        "ready": False,
    }


def _transcribe_local_wav(wav_bytes: bytes) -> tuple[str, str]:
    """Run local speech-to-text on 16kHz mono PCM WAV bytes without cloud APIs."""
    with tempfile.NamedTemporaryFile(prefix="artha-whisper-", suffix=".wav", delete=False) as tmp:
        wav_path = Path(tmp.name)
        tmp.write(wav_bytes)
    try:
        with _WHISPER_LOCK:
            # 1. Try faster-whisper if installed
            fw_model = _faster_whisper_model()
            if fw_model is not None:
                segments, _ = fw_model.transcribe(str(wav_path), language="en", beam_size=1, vad_filter=True)
                text = " ".join(seg.text.strip() for seg in segments if seg.text.strip()).strip()
                return text, f"faster-whisper:{setting('WHISPER_MODEL', 'base.en')}"

            # 2. Try whisper-cli / whisper binary if installed
            cli = _whisper_cli_bin()
            if cli:
                model_path = setting("WHISPER_CPP_MODEL", "")
                if Path(cli).name in {"whisper-cli", "whisper-cpp"} and model_path and Path(model_path).is_file():
                    proc = subprocess.run(
                        [cli, "-m", model_path, "-f", str(wav_path), "-nt", "-l", "en"],
                        capture_output=True,
                        text=True,
                        timeout=30,
                        check=False,
                    )
                    if proc.returncode == 0 and proc.stdout.strip():
                        return proc.stdout.strip(), "whisper-cpp"

            # 3. Try HuggingFace transformers Whisper pipeline (installed in .venv)
            pipe = _transformers_whisper_pipeline()
            if pipe is not None:
                import numpy as np
                with wave.open(str(wav_path), "rb") as wf:
                    frames = wf.readframes(wf.getnframes())
                    samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
                result = pipe({"raw": samples, "sampling_rate": 16000})
                text = str(result.get("text") if isinstance(result, dict) else result or "").strip()
                return text, setting("WHISPER_HF_MODEL", DEFAULT_WHISPER_MODEL)
    finally:
        wav_path.unlink(missing_ok=True)

    raise VoiceError(
        "Local Whisper model weights are not cached yet. Run `.venv/bin/hf download openai/whisper-tiny.en` "
        "or `.venv/bin/pip install faster-whisper` once while online, or edit the transcript directly."
    )


class VoiceService:
    def __init__(self) -> None:
        self.preference = setting("VOICE_PROVIDER", "local").lower()
        self.api_key = setting("ELEVENLABS_API_KEY")
        self.voice_id = setting("ELEVENLABS_VOICE_ID")
        self.model_id = setting("ELEVENLABS_MODEL_ID", "eleven_flash_v2_5")
        self.slng_api_key = setting("SLNG_API_KEY")
        self.slng_api_base_url = setting("SLNG_API_BASE_URL", "https://in.api.slng.ai").rstrip("/") or "https://in.api.slng.ai"

    def transcribe(self, audio: str, content_type: str) -> str:
        if not isinstance(audio, str) or not audio or len(audio) > 2_800_000:
            raise ValueError("Record a voice message of up to 30 seconds.")
        if not isinstance(content_type, str) or content_type.split(";", 1)[0] not in {"audio/webm", "audio/ogg", "audio/mp4", "audio/wav", "audio/mpeg"}:
            raise ValueError("Unsupported voice recording format.")
        try:
            decoded = base64.b64decode(audio, validate=True)
        except (ValueError, binascii.Error) as error:
            raise ValueError("Invalid voice recording.") from error
        if not decoded or len(decoded) > 2_000_000:
            raise ValueError("The voice recording is empty or too large.")

        # Legacy contract tests explicitly set VOICE_PROVIDER=slng with a mock key
        if self.preference == "slng":
            if not self.slng_api_key:
                raise VoiceError("SLNG_API_KEY is required for voice transcription.")
            request = urllib.request.Request(
                f"{self.slng_api_base_url}/v1/stt/slng/deepgram/nova:3-en",
                data=json.dumps({"audio": audio, "language": "en"}).encode(),
                headers={"Authorization": f"Bearer {self.slng_api_key}", "Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    body = json.loads(response.read(1_000_000))
                text = body["results"]["channels"][0]["alternatives"][0]["transcript"]
                if not isinstance(text, str):
                    raise ValueError("Invalid transcript")
            except urllib.error.HTTPError as error:
                if error.code in {401, 403}:
                    raise VoiceError("SLNG rejected the configured API key.") from error
                raise VoiceError("SLNG could not transcribe this recording. Please try again.") from error
            except (urllib.error.URLError, TimeoutError, ValueError, KeyError, IndexError, TypeError) as error:
                raise VoiceError("SLNG could not transcribe this recording. Please try again.") from error
            record_usage("slng", "voice_transcription", model="nova-3", output_bytes=len(text.encode()))
            return text.strip()[:4000]

        wav_bytes = _normalize_to_16k_wav(decoded, content_type)
        text, model_used = _transcribe_local_wav(wav_bytes)
        record_usage("local_whisper", "voice_transcription", model=model_used, output_bytes=len(text.encode()))
        return text.strip()[:4000]

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.voice_id)

    @staticmethod
    def _local_provider() -> str:
        return setting("LOCAL_VOICE_PROVIDER", "kokoro").lower()

    def _resolve_local_provider(self) -> str:
        local = self._local_provider()
        if local in {"kokoro", "local-kokoro", "studio", "auto", "local"}:
            if _kokoro_dependencies() is not None:
                return "kokoro"
            if _say_bin() is not None:
                return "macos_say"
            return "browser"
        if local in {"macos", "macos_say", "say"}:
            return "macos_say" if _say_bin() is not None else "browser"
        return "browser"

    @property
    def provider(self) -> str:
        if self.preference in {"local", "auto"} and not is_production():
            return self._resolve_local_provider()
        if self.preference in {"browser", "local-browser"}:
            return "browser"
        if self.preference in {"macos", "macos_say", "say"}:
            return "macos_say" if _say_bin() is not None else "browser"
        if self.preference in {"kokoro", "local-kokoro", "studio"}:
            return "kokoro" if _kokoro_dependencies() is not None else ("macos_say" if _say_bin() is not None else "kokoro-unavailable")
        if self.preference == "slng":
            return "slng"
        if self.preference == "elevenlabs":
            return "elevenlabs" if self.configured else "unconfigured"
        if is_production():
            return "elevenlabs" if self.configured else "unconfigured"
        return self._resolve_local_provider()

    def status(self) -> dict[str, object]:
        provider = self.provider
        requested_local = self._local_provider()
        stt_info = _local_stt_status()
        if provider == "elevenlabs":
            label = "ElevenLabs voice"
        elif provider == "kokoro":
            label = "Local Kokoro voice (with macOS fallback)"
        elif provider == "macos_say":
            label = "Local macOS neural voice"
        elif provider == "kokoro-unavailable":
            label = "Local Kokoro voice unavailable"
        elif provider == "slng":
            label = "SLNG voice" if self.slng_api_key else "SLNG voice not configured"
        elif provider == "unconfigured":
            label = "ElevenLabs voice not configured"
        elif requested_local in {"kokoro", "local-kokoro", "studio"}:
            label = "Local browser voice (Kokoro unavailable)"
        else:
            label = "Local browser voice"
        is_local = provider in {"browser", "kokoro", "macos_say", "kokoro-unavailable"}
        return {
            "provider": provider,
            "label": label,
            "model": (
                SLNG_TTS_MODEL if provider == "slng" else
                self.model_id if provider == "elevenlabs" else
                KOKORO_MODEL_REPO if provider == "kokoro" else
                "macos-say-pcm" if provider == "macos_say" else "browser-speech"
            ),
            "configured": bool(self.slng_api_key) if provider == "slng" else provider not in {"unconfigured", "kokoro-unavailable"},
            "local": is_local,
            "stt_provider": "slng" if provider == "slng" else stt_info["provider"],
            "stt_model": "nova-3" if provider == "slng" else stt_info["model"],
            "stt_local": provider != "slng",
            "browser_speech_is_local": False,
            "processing_note": (
                "Speech is recorded as 16kHz PCM WAV in the browser, transcribed locally on your Mac via Whisper, "
                "processed by local Ollama, and synthesized locally via Kokoro-82M / macOS say. "
                "Browser Web Speech API (webkitSpeechRecognition) is not assumed to be local because Chromium streams audio to Google servers."
            ),
            "requested_local_provider": requested_local,
            "ready": bool(self.slng_api_key) if provider == "slng" else (
                True if provider in {"macos_say", "browser"} else (provider != "kokoro" or bool(_KOKORO_WARMED) or _say_bin() is not None)
            ),
        }

    def warm(self) -> dict[str, object]:
        provider = self.provider
        if provider == "kokoro":
            try:
                return {"provider": provider, "warmed": _kokoro_warm(), "ready": True}
            except VoiceError:
                if _say_bin() is not None:
                    return {"provider": "macos_say", "warmed": False, "ready": True}
                raise
        if provider == "macos_say":
            return {"provider": provider, "warmed": False, "ready": True}
        if provider == "slng":
            if not self.slng_api_key:
                raise VoiceError("SLNG_API_KEY is required when VOICE_PROVIDER=slng.")
            return {"provider": provider, "warmed": False, "ready": True}
        if provider == "browser":
            return {"provider": provider, "warmed": False, "ready": True}
        if provider == "unconfigured":
            raise VoiceError("ElevenLabs is required in production but its API key or voice ID is missing.")
        raise VoiceError("Kokoro local voice is unavailable. Install backend/requirements-kokoro.txt and restart the app.")

    def speak(self, text: str) -> tuple[bytes, str]:
        provider = self.provider
        if provider == "browser":
            raise VoiceError("Local browser voice is selected; speech is synthesized in the browser.")
        if provider == "kokoro":
            normalized = " ".join((text or "").split())
            if not normalized:
                raise VoiceError("There is nothing to speak yet.")
            try:
                audio = _kokoro_audio(normalized)
                record_usage("kokoro", "voice_synthesis", model=KOKORO_MODEL_REPO, input_characters=len(normalized), output_bytes=len(audio))
                return audio, "audio/wav"
            except VoiceError:
                if _say_bin() is not None:
                    audio = _macos_say_audio(normalized)
                    record_usage("macos_say", "voice_synthesis", model="macos-say", input_characters=len(normalized), output_bytes=len(audio))
                    return audio, "audio/wav"
                raise
        if provider == "macos_say":
            normalized = " ".join((text or "").split())
            audio = _macos_say_audio(normalized)
            record_usage("macos_say", "voice_synthesis", model="macos-say", input_characters=len(normalized), output_bytes=len(audio))
            return audio, "audio/wav"
        if provider == "kokoro-unavailable":
            raise VoiceError("Kokoro local voice is unavailable. Install backend/requirements-kokoro.txt and restart the app.")
        if provider == "slng":
            text = " ".join((text or "").split())
            if not text:
                raise VoiceError("There is nothing to speak yet.")
            if not self.slng_api_key:
                raise VoiceError("SLNG_API_KEY is required when VOICE_PROVIDER=slng.")
            request = urllib.request.Request(
                f"{self.slng_api_base_url}/v1/tts/deepgram/aura:2",
                data=json.dumps({"model": SLNG_TTS_MODEL, "text": text, "encoding": "linear16", "container": "wav"}).encode("utf-8"),
                headers={"Authorization": f"Bearer {self.slng_api_key}", "Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=45) as response:
                    audio = response.read()
                    if not audio:
                        raise VoiceError("SLNG returned no audio.")
                    record_usage("slng", "voice_synthesis", model=SLNG_TTS_MODEL, input_characters=len(text), output_bytes=len(audio))
                    content_type = response.headers.get_content_type() if response.headers.get("Content-Type") else "audio/wav"
                    return audio, content_type
            except urllib.error.HTTPError as error:
                if error.code in {401, 403}:
                    raise VoiceError("SLNG rejected the configured API key.") from error
                raise VoiceError("SLNG could not synthesize speech right now.") from error
            except urllib.error.URLError as error:
                raise VoiceError("SLNG could not synthesize speech right now.") from error
        if provider != "elevenlabs":
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
                audio = response.read()
                record_usage("elevenlabs", "voice_synthesis", model=self.model_id, input_characters=len(text), output_bytes=len(audio))
                return audio, response.headers.get_content_type() or "audio/mpeg"
        except urllib.error.HTTPError as error:
            if error.code in {401, 403}:
                raise VoiceError("ElevenLabs rejected the configured API key or voice access. Check ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID.") from error
            raise VoiceError("ElevenLabs could not synthesize this edit right now.") from error
        except urllib.error.URLError as error:
            raise VoiceError("ElevenLabs could not synthesize this edit right now.") from error
