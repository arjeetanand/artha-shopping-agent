import { LocalWavRecognition, SlngRecognition, supportsLocalWavRecording, supportsSlngRecording } from './slngRecognition';

export function isLocalRecorderVoice(voice) {
  if (!voice) return false;
  if (voice.provider === 'browser') return false;
  return Boolean(voice.stt_local || ['kokoro', 'macos_say', 'local', 'slng'].includes(voice.provider));
}

export function getSpeechRecognition(voice) {
  if (typeof window === 'undefined') return null;
  // Browser SpeechRecognition (webkitSpeechRecognition in Chrome/Edge) streams audio
  // to remote cloud speech servers unless on-device packs are explicitly installed.
  // When local voice is active, record 16kHz mono PCM WAV in the browser and transcribe
  // locally via POST /api/voice/transcribe (Whisper on 127.0.0.1).
  if (isLocalRecorderVoice(voice)) {
    if (supportsLocalWavRecording()) return LocalWavRecognition;
  }
  if (voice?.provider === 'slng') return supportsSlngRecording() ? SlngRecognition : null;
  return window.SpeechRecognition || window.webkitSpeechRecognition || (supportsLocalWavRecording() ? LocalWavRecognition : null);
}

export async function requestMicrophone() {
  if (!window.isSecureContext) {
    throw new Error('Microphone access needs the local app address or HTTPS.');
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new Error('This browser cannot access a microphone. Use Chrome or Edge and open the local app address.');
  }
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  if (!stream.getAudioTracks().some((track) => track.readyState === 'live')) {
    stopMicrophone(stream);
    throw new Error('No live microphone track was available. Connect or enable a microphone, then try again.');
  }
  return stream;
}

export function stopMicrophone(stream) {
  stream?.getTracks().forEach((track) => track.stop());
}

export function speechErrorMessage(error) {
  const code = error?.error || error?.name;
  if (['NotAllowedError', 'PermissionDeniedError', 'not-allowed', 'service-not-allowed'].includes(code)) {
    return 'Microphone access is blocked. Allow it in your browser and macOS microphone settings, then try again.';
  }
  if (['NotFoundError', 'DevicesNotFoundError', 'audio-capture'].includes(code)) {
    return 'No microphone is available to speech recognition. Connect or enable one, then try again.';
  }
  if (['NotReadableError', 'TrackStartError'].includes(code)) {
    return 'The microphone is busy or could not be opened. Close other apps using it, then try again.';
  }
  if (code === 'network') {
    return 'The browser speech service could not be reached. Switch to local Whisper recording or type your request.';
  }
  if (code === 'no-speech') {
    return 'No speech was detected. Try again and speak closer to the microphone.';
  }
  if (code === 'language-not-supported') {
    return 'This browser does not support the selected speech language.';
  }
  return error?.message || 'Voice input could not start. You can continue by typing.';
}
