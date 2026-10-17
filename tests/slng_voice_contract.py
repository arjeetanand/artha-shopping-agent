"""Contract checks for local voice (Whisper STT + Kokoro/macOS TTS) and legacy SLNG fallback."""

from __future__ import annotations

import base64
import io
import json
import os
import sys
import unittest
import urllib.error
import wave
from email.message import Message
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _sample_wav_b64() -> str:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * 1600)
    return base64.b64encode(buf.getvalue()).decode("ascii")


class LocalAndSlngVoiceContract(unittest.TestCase):
    def test_default_voice_status_is_local_and_verifies_browser_speech_is_not_local(self) -> None:
        from backend.voice import VoiceService

        with patch.dict(os.environ, {"VOICE_PROVIDER": "local", "LOCAL_VOICE_PROVIDER": "kokoro"}, clear=False):
            status = VoiceService().status()
            self.assertTrue(status["local"])
            self.assertTrue(status["stt_local"])
            self.assertFalse(status["browser_speech_is_local"])
            self.assertIn(status["provider"], {"kokoro", "macos_say", "browser"})
            self.assertIn("not assumed to be local", str(status["processing_note"]))

    def test_local_transcription_uses_local_whisper_without_slng_key(self) -> None:
        from backend.voice import VoiceService

        wav_b64 = _sample_wav_b64()
        with patch.dict(os.environ, {"VOICE_PROVIDER": "local", "SLNG_API_KEY": ""}, clear=False), patch(
            "backend.voice._transcribe_local_wav", return_value=("I am going to Goa and want to buy a T-shirt", "faster-whisper:base.en")
        ) as local_stt, patch("backend.voice.urllib.request.urlopen") as urlopen, patch("backend.voice.record_usage"):
            transcript = VoiceService().transcribe(wav_b64, "audio/wav")
            self.assertEqual(transcript, "I am going to Goa and want to buy a T-shirt")
            local_stt.assert_called_once()
            urlopen.assert_not_called()

    def test_local_speak_synthesizes_wav_audio_locally(self) -> None:
        from backend.voice import VoiceService

        with patch.dict(os.environ, {"VOICE_PROVIDER": "macos_say", "SLNG_API_KEY": "", "ELEVENLABS_API_KEY": ""}, clear=False), patch(
            "backend.voice.record_usage"
        ):
            voice = VoiceService()
            audio, content_type = voice.speak("What are you looking for today, Arjeet?")
            self.assertEqual(content_type, "audio/wav")
            self.assertTrue(audio.startswith(b"RIFF"))
            self.assertGreater(len(audio), 44)

    def test_slng_transcription_contract(self) -> None:
        from backend.voice import VoiceService

        response = Mock()
        response.read.return_value = json.dumps({"results": {"channels": [{"alternatives": [{"transcript": "Find an office chair"}]}]}}).encode()
        opened = Mock()
        opened.__enter__ = Mock(return_value=response)
        opened.__exit__ = Mock(return_value=False)
        audio = base64.b64encode(b"recorded-webm-audio").decode()
        with patch.dict(os.environ, {"VOICE_PROVIDER": "slng", "SLNG_API_KEY": "test-key", "SLNG_API_BASE_URL": "https://in.api.slng.ai"}), patch(
            "backend.voice.urllib.request.urlopen", return_value=opened,
        ) as urlopen, patch("backend.voice.record_usage"):
            self.assertEqual(VoiceService().transcribe(audio, "audio/webm;codecs=opus"), "Find an office chair")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://in.api.slng.ai/v1/stt/slng/deepgram/nova:3-en")
        self.assertEqual(json.loads(request.data), {"audio": audio, "language": "en"})
        self.assertEqual(request.get_header("Authorization"), "Bearer test-key")

    def test_transcription_rejects_invalid_audio_before_provider_call(self) -> None:
        from backend.voice import VoiceService

        for audio, mime in [("", "audio/webm"), ("!invalid!", "audio/webm"), ("YQ==", "text/html"), ("YQ==" * 800_000, "audio/webm")]:
            with self.subTest(mime=mime, length=len(audio)), patch.dict(os.environ, {"VOICE_PROVIDER": "slng", "SLNG_API_KEY": "test-key"}), patch("backend.voice.urllib.request.urlopen") as urlopen:
                with self.assertRaises(ValueError):
                    VoiceService().transcribe(audio, mime)
                urlopen.assert_not_called()

    def test_slng_status_and_binary_tts_contract(self) -> None:
        from backend.voice import SLNG_TTS_MODEL

        audio = b"\x00\xffSLNG-audio\x10"
        headers = Message()
        headers["Content-Type"] = "audio/ogg"
        response = Mock()
        response.read.return_value = audio
        response.headers = headers
        opened = Mock()
        opened.__enter__ = Mock(return_value=response)
        opened.__exit__ = Mock(return_value=False)

        with patch.dict(os.environ, {
            "VOICE_PROVIDER": "slng",
            "SLNG_API_KEY": "test-slng-key",
            "SLNG_API_BASE_URL": "https://tts.example.test/",
        }), patch("backend.voice.urllib.request.urlopen", return_value=opened) as urlopen, patch(
            "backend.voice.record_usage"
        ) as record_usage:
            from backend.voice import VoiceService

            voice = VoiceService()
            self.assertEqual(voice.status()["provider"], "slng")
            self.assertEqual(voice.status()["model"], SLNG_TTS_MODEL)
            self.assertTrue(voice.status()["configured"])
            result_audio, content_type = voice.speak("  Hello\n  from Artha  ")

        self.assertEqual(result_audio, audio)
        self.assertEqual(content_type, "audio/ogg")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://tts.example.test/v1/tts/deepgram/aura:2")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-slng-key")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(json.loads(request.data), {"model": "aura-2-thalia-en", "text": "Hello from Artha", "encoding": "linear16", "container": "wav"})
        record_usage.assert_called_once_with(
            "slng", "voice_synthesis", model=SLNG_TTS_MODEL,
            input_characters=len("Hello from Artha"), output_bytes=len(audio),
        )

    def test_missing_key_is_reported_without_request(self) -> None:
        from backend.voice import VoiceError, VoiceService

        with patch.dict(os.environ, {"VOICE_PROVIDER": "slng", "SLNG_API_KEY": "", "SLNG_API_BASE_URL": ""}), patch(
            "backend.voice.urllib.request.urlopen"
        ) as urlopen:
            voice = VoiceService()
            self.assertEqual(voice.status()["provider"], "slng")
            self.assertFalse(voice.status()["configured"])
            self.assertEqual(voice.slng_api_base_url, "https://in.api.slng.ai")
            with self.assertRaisesRegex(VoiceError, "SLNG_API_KEY"):
                voice.speak("Hello")
        urlopen.assert_not_called()

    def test_missing_content_type_defaults_to_wav(self) -> None:
        from backend.voice import VoiceService

        headers = Message()
        response = Mock()
        response.read.return_value = b"audio"
        response.headers = headers
        opened = Mock()
        opened.__enter__ = Mock(return_value=response)
        opened.__exit__ = Mock(return_value=False)

        with patch.dict(os.environ, {"VOICE_PROVIDER": "slng", "SLNG_API_KEY": "test-slng-key"}), patch(
            "backend.voice.urllib.request.urlopen", return_value=opened,
        ):
            audio, content_type = VoiceService().speak("Hello")

        self.assertEqual(audio, b"audio")
        self.assertEqual(content_type, "audio/wav")

    def test_empty_provider_audio_is_rejected(self) -> None:
        from backend.voice import VoiceError, VoiceService

        headers = Message()
        headers["Content-Type"] = "audio/mpeg"
        response = Mock()
        response.read.return_value = b""
        response.headers = headers
        opened = Mock()
        opened.__enter__ = Mock(return_value=response)
        opened.__exit__ = Mock(return_value=False)

        with patch.dict(os.environ, {"VOICE_PROVIDER": "slng", "SLNG_API_KEY": "test-slng-key"}), patch(
            "backend.voice.urllib.request.urlopen", return_value=opened,
        ):
            with self.assertRaisesRegex(VoiceError, "no audio"):
                VoiceService().speak("Hello")

    def test_empty_text_is_rejected_without_request(self) -> None:
        from backend.voice import VoiceError, VoiceService

        with patch.dict(os.environ, {"VOICE_PROVIDER": "slng", "SLNG_API_KEY": "test-slng-key"}), patch(
            "backend.voice.urllib.request.urlopen"
        ) as urlopen:
            with self.assertRaisesRegex(VoiceError, "nothing to speak"):
                VoiceService().speak(" \n\t ")
        urlopen.assert_not_called()

    def test_provider_errors_are_sanitized(self) -> None:
        from backend.voice import VoiceError, VoiceService

        failures = [
            urllib.error.HTTPError(
                "https://tts.example.test/v1/tts/deepgram/aura:2", 401,
                "rejected", {}, None,
            ),
            urllib.error.HTTPError(
                "https://tts.example.test/v1/tts/deepgram/aura:2", 503,
                "internal provider detail", {}, None,
            ),
            urllib.error.URLError("private-network-detail"),
        ]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__, code=getattr(failure, "code", None)):
                with patch.dict(os.environ, {
                    "VOICE_PROVIDER": "slng", "SLNG_API_KEY": "test-slng-key",
                }), patch("backend.voice.urllib.request.urlopen", side_effect=failure):
                    with self.assertRaises(VoiceError) as caught:
                        VoiceService().speak("Hello")
                message = str(caught.exception)
                self.assertNotIn("test-slng-key", message)
                self.assertNotIn("private-network-detail", message)
                self.assertNotIn("internal provider detail", message)
                self.assertNotIn("tts.example.test", message)
                self.assertTrue(message.startswith("SLNG "))


if __name__ == "__main__":
    unittest.main()
