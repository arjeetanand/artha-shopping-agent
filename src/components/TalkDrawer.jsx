import React, { useCallback, useEffect, useId, useRef, useState } from 'react';
import { Icon } from './Icon';
import { speakText } from '../lib/api';

const SUGGESTIONS = [
  'Why did you rank these first?',
  'Show me a cheaper alternative',
  'Can anything arrive faster?',
  'Where is my delivery?',
];

const DRAWER_STYLES = `
  .talk-drawer__backdrop {
    position: fixed;
    inset: 0;
    z-index: 1000;
    display: flex;
    justify-content: flex-end;
    background: rgba(15, 23, 42, 0.28);
    animation: talk-drawer-fade-in 180ms ease-out;
  }

  .talk-drawer {
    display: flex;
    flex-direction: column;
    width: min(100%, 460px);
    height: 100%;
    overflow: hidden;
    color: #0f172a;
    background: #f8fafc;
    box-shadow: -18px 0 52px rgba(15, 23, 42, 0.18);
    animation: talk-drawer-slide-in 260ms cubic-bezier(0.16, 1, 0.3, 1);
  }

  .talk-drawer__header {
    position: relative;
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 20px;
    padding: 26px 24px 22px;
    color: #fff;
    background:
      radial-gradient(circle at 88% 14%, rgba(99, 213, 255, 0.26), transparent 34%),
      linear-gradient(135deg, #0c1524 0%, #16263f 100%);
  }

  .talk-drawer__eyebrow {
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 0 0 8px;
    color: #86ddff;
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 0.14em;
    line-height: 1;
    text-transform: uppercase;
  }

  .talk-drawer__live-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: #63d5ff;
    box-shadow: 0 0 0 4px rgba(99, 213, 255, 0.12), 0 0 12px rgba(99, 213, 255, 0.8);
  }

  .talk-drawer__title {
    margin: 0;
    color: #fff;
    font-family: Georgia, 'Times New Roman', serif;
    font-size: 30px;
    font-weight: 400;
    letter-spacing: -0.04em;
    line-height: 1;
  }

  .talk-drawer__subtitle {
    max-width: 300px;
    margin: 10px 0 0;
    color: #c8d8f0;
    font-size: 13px;
    line-height: 1.5;
  }

  .talk-drawer__close {
    display: inline-flex;
    flex: 0 0 auto;
    align-items: center;
    justify-content: center;
    width: 44px;
    height: 44px;
    border: 1px solid rgba(255, 255, 255, 0.22);
    border-radius: 10px;
    color: #fff;
    transition: background 160ms ease, border-color 160ms ease, transform 160ms ease;
  }

  .talk-drawer__close:hover {
    border-color: rgba(255, 255, 255, 0.48);
    background: rgba(255, 255, 255, 0.12);
    transform: translateY(-1px);
  }

  .talk-drawer__status {
    display: flex;
    align-items: center;
    gap: 8px;
    min-height: 42px;
    padding: 0 24px;
    border-bottom: 1px solid #e2e8f0;
    color: #64748b;
    background: #fff;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.01em;
  }

  .talk-drawer__status-icon {
    display: inline-flex;
    color: #0694d6;
  }

  .talk-drawer__messages {
    display: flex;
    flex: 1;
    flex-direction: column;
    gap: 16px;
    min-height: 0;
    overflow-y: auto;
    padding: 24px;
    overscroll-behavior: contain;
    scrollbar-color: #cbd5e1 transparent;
    scrollbar-width: thin;
  }

  .talk-drawer__welcome {
    margin: 0 0 2px;
    color: #64748b;
    font-size: 12px;
    line-height: 1.55;
  }

  .talk-drawer__message-row {
    display: flex;
    align-items: flex-end;
    gap: 9px;
  }

  .talk-drawer__message-row--user {
    justify-content: flex-end;
  }

  .talk-drawer__avatar {
    display: inline-flex;
    flex: 0 0 auto;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    border-radius: 9px;
    color: #fff;
    background: linear-gradient(135deg, #0694d6, #7c3aed);
    box-shadow: 0 4px 12px rgba(6, 148, 214, 0.2);
  }

  .talk-drawer__bubble {
    max-width: 84%;
    padding: 12px 14px;
    border: 1px solid #e2e8f0;
    border-radius: 15px 15px 15px 4px;
    color: #334155;
    background: #fff;
    box-shadow: 0 2px 8px rgba(15, 23, 42, 0.05);
    font-size: 13px;
    line-height: 1.55;
    white-space: pre-wrap;
  }

  .talk-drawer__message-row--user .talk-drawer__bubble {
    border-color: #0694d6;
    border-radius: 15px 15px 4px 15px;
    color: #fff;
    background: #0694d6;
    box-shadow: 0 5px 14px rgba(6, 148, 214, 0.18);
  }

  .talk-drawer__message-tools {
    display: flex;
    justify-content: flex-end;
    margin-top: 8px;
  }

  .talk-drawer__speak {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    color: #64748b;
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }

  .talk-drawer__speak:hover {
    color: #0694d6;
  }

  .talk-drawer__typing {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 13px 15px;
    border: 1px solid #e2e8f0;
    border-radius: 15px 15px 15px 4px;
    background: #fff;
  }

  .talk-drawer__typing span {
    width: 5px;
    height: 5px;
    border-radius: 50%;
    background: #94a3b8;
    animation: talk-drawer-bounce 900ms ease-in-out infinite;
  }

  .talk-drawer__typing span:nth-child(2) { animation-delay: 120ms; }
  .talk-drawer__typing span:nth-child(3) { animation-delay: 240ms; }

  .talk-drawer__suggestions {
    display: flex;
    flex-wrap: wrap;
    gap: 7px;
    padding-top: 2px;
  }

  .talk-drawer__suggestion {
    min-height: 44px;
    padding: 8px 10px;
    border: 1px solid #cbd5e1;
    border-radius: 999px;
    color: #334155;
    background: rgba(255, 255, 255, 0.7);
    font-size: 11px;
    font-weight: 700;
    line-height: 1.2;
    text-align: left;
    transition: border-color 160ms ease, color 160ms ease, background 160ms ease;
  }

  .talk-drawer__suggestion:hover {
    border-color: #0694d6;
    color: #0572a5;
    background: #effaff;
  }

  .talk-drawer__composer {
    padding: 16px 24px 22px;
    border-top: 1px solid #e2e8f0;
    background: #fff;
  }

  .talk-drawer__input-wrap {
    display: flex;
    align-items: flex-end;
    gap: 8px;
    padding: 7px 7px 7px 14px;
    border: 1px solid #cbd5e1;
    border-radius: 14px;
    background: #f8fafc;
    transition: border-color 160ms ease, box-shadow 160ms ease, background 160ms ease;
  }

  .talk-drawer__input-wrap:focus-within {
    border-color: #0694d6;
    background: #fff;
    box-shadow: 0 0 0 3px rgba(6, 148, 214, 0.12);
  }

  .talk-drawer__input {
    min-width: 0;
    flex: 1;
    min-height: 24px;
    max-height: 96px;
    padding: 4px 0;
    border: 0;
    outline: 0;
    resize: none;
    color: #0f172a;
    background: transparent;
    font-size: 13px;
    line-height: 1.4;
  }

  .talk-drawer__input::placeholder { color: #94a3b8; }

  .talk-drawer__icon-button,
  .talk-drawer__send {
    display: inline-flex;
    flex: 0 0 auto;
    align-items: center;
    justify-content: center;
    width: 44px;
    height: 44px;
    border-radius: 10px;
    transition: background 160ms ease, color 160ms ease, opacity 160ms ease, transform 160ms ease;
  }

  .talk-drawer__icon-button {
    color: #64748b;
  }

  .talk-drawer__icon-button:hover:not(:disabled) {
    color: #0694d6;
    background: #e6f8ff;
  }

  .talk-drawer__icon-button--listening {
    color: #fff;
    background: #e85555;
    box-shadow: 0 0 0 4px rgba(232, 85, 85, 0.13);
  }

  .talk-drawer__icon-button--listening:hover:not(:disabled) {
    color: #fff;
    background: #d94040;
  }

  .talk-drawer__send {
    color: #fff;
    background: #0f172a;
  }

  .talk-drawer__send:hover:not(:disabled) {
    background: #0694d6;
    transform: translateY(-1px);
  }

  .talk-drawer__hint {
    display: block;
    margin: 9px 2px 0;
    color: #94a3b8;
    font-size: 10px;
    line-height: 1.4;
  }

  @keyframes talk-drawer-fade-in { from { opacity: 0; } to { opacity: 1; } }
  @keyframes talk-drawer-slide-in { from { transform: translateX(100%); } to { transform: translateX(0); } }
  @keyframes talk-drawer-bounce { 0%, 60%, 100% { transform: translateY(0); opacity: 0.55; } 30% { transform: translateY(-3px); opacity: 1; } }

  @media (prefers-reduced-motion: reduce) {
    .talk-drawer__backdrop,
    .talk-drawer,
    .talk-drawer__typing span { animation: none; }
    .talk-drawer__close,
    .talk-drawer__suggestion,
    .talk-drawer__input-wrap,
    .talk-drawer__icon-button,
    .talk-drawer__send { transition: none; }
  }

  @media (max-width: 520px) {
    .talk-drawer__header { padding: 22px 18px 20px; }
    .talk-drawer__messages { padding: 20px 18px; }
    .talk-drawer__composer { padding: 14px 18px 18px; }
    .talk-drawer__status { padding: 0 18px; }
    .talk-drawer__bubble { max-width: 90%; }
  }

  /* Artha palette: keep the conversation surface visually native to the app. */
  .talk-drawer__backdrop { background: rgba(21, 34, 30, .24); }
  .talk-drawer { color: #15221e; background: #fff; box-shadow: -18px 0 52px rgba(24, 65, 46, .18); }
  .talk-drawer__header { color: #fff; background: linear-gradient(135deg, #173d30 0%, #1d7657 100%); }
  .talk-drawer__eyebrow { color: #c8f0d7; }
  .talk-drawer__live-dot { background: #9fe4be; box-shadow: 0 0 0 4px rgba(159, 228, 190, .14), 0 0 12px rgba(159, 228, 190, .7); }
  .talk-drawer__title { color: #fff; font-family: 'Plus Jakarta Sans', system-ui, sans-serif; font-size: 27px; font-weight: 800; letter-spacing: -.06em; }
  .talk-drawer__subtitle { color: #d7eee0; }
  .talk-drawer__status { border-color: #d9e6de; color: #6a7a73; }
  .talk-drawer__status-icon { color: #1d7657; }
  .talk-drawer__messages { scrollbar-color: #bfd2c5 transparent; }
  .talk-drawer__welcome { color: #6a7a73; }
  .talk-drawer__call-card { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px; border: 1px solid #b7dfc8; border-radius: 12px; background: #e9f7ef; }
  .talk-drawer__call-card strong { display: inline-flex; align-items: center; gap: 6px; color: #173d30; font-size: 11px; }
  .talk-drawer__call-card p { margin: 4px 0 0; color: #6a7a73; font-size: 10px; line-height: 1.4; }
  .talk-drawer__call-card button { display: inline-flex; flex: 0 0 auto; align-items: center; gap: 6px; min-height: 44px; padding: 0 12px; border-radius: 8px; background: #1d7657; color: #fff; font-size: 10px; font-weight: 800; }
  .talk-drawer__call-card button:hover:not(:disabled) { background: #155b43; }
  .talk-drawer__call-card--active { background: #173d30; border-color: #173d30; }
  .talk-drawer__call-card--active strong { color: #fff; }
  .talk-drawer__call-card--active p { color: #c8e4d4; }
  .talk-drawer__call-card--active button { background: #fff; color: #173d30; }
  .talk-drawer__call-card--active button:hover:not(:disabled) { background: #dcf4e5; }
  .talk-drawer__call-orb { width: 13px; height: 13px; flex: 0 0 auto; border-radius: 50%; background: #9fe4be; box-shadow: 0 0 0 5px rgba(159, 228, 190, .16); }
  .talk-drawer__call-orb--listening { animation: talk-call-pulse 1.4s ease-in-out infinite; }
  @keyframes talk-call-pulse { 50% { box-shadow: 0 0 0 11px rgba(159, 228, 190, 0); } }
  .talk-drawer__avatar { background: #1d7657; box-shadow: 0 4px 12px rgba(29, 118, 87, .2); }
  .talk-drawer__bubble { border-color: #d9e6de; color: #33453e; box-shadow: 0 2px 8px rgba(24, 65, 46, .05); }
  .talk-drawer__message-row--user .talk-drawer__bubble { border-color: #1d7657; background: #1d7657; box-shadow: 0 5px 14px rgba(29, 118, 87, .18); }
  .talk-drawer__speak:hover { color: #1d7657; }
  .talk-drawer__typing { border-color: #d9e6de; }
  .talk-drawer__suggestion { border-color: #bfd2c5; color: #33453e; background: #f4faf6; }
  .talk-drawer__suggestion:hover { border-color: #1d7657; color: #155b43; background: #e7f5ec; }
  .talk-drawer__composer { border-color: #d9e6de; }
  .talk-drawer__input-wrap { border-color: #bfd2c5; background: #f4faf6; }
  .talk-drawer__input-wrap:focus-within { border-color: #1d7657; box-shadow: 0 0 0 3px rgba(29, 118, 87, .14); }
  .talk-drawer__input { color: #15221e; }
  .talk-drawer__icon-button:hover:not(:disabled) { color: #1d7657; background: #e7f5ec; }
  .talk-drawer__icon-button--listening { background: #ed6a35; box-shadow: 0 0 0 4px rgba(237, 106, 53, .14); }
  .talk-drawer__icon-button--listening:hover:not(:disabled) { background: #cf5425; }
  .talk-drawer__send { background: #173d30; }
  .talk-drawer__send:hover:not(:disabled) { background: #1d7657; }
  .talk-drawer__hint { color: #8b9c94; }
  @media (prefers-reduced-motion: reduce) { .talk-drawer__call-orb--listening { animation: none; } }
  @media (max-width: 520px) { .talk-drawer__call-card { align-items: flex-start; flex-direction: column; } .talk-drawer__call-card button { width: 100%; justify-content: center; } }
`;

function createMessage(role, text) {
  return {
    id: `${role}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    role,
    text,
  };
}

function getSpeechRecognition() {
  if (typeof window === 'undefined') return null;
  return window.SpeechRecognition || window.webkitSpeechRecognition || null;
}

function getReplyText(reply) {
  if (typeof reply === 'string') return reply.trim();
  if (reply === null || reply === undefined) return '';
  return String(reply).trim();
}

function useDrawerFocusTrap(open, dialogRef, initialRef, onClose) {
  const previousFocusRef = useRef(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!open) return undefined;
    previousFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const frame = window.requestAnimationFrame(() => initialRef.current?.focus());
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== 'Tab') return;
      const dialog = dialogRef.current;
      if (!dialog) return;
      const focusable = [...dialog.querySelectorAll('a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])')]
        .filter((element) => !element.hidden && element.offsetParent !== null);
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      window.cancelAnimationFrame(frame);
      document.removeEventListener('keydown', handleKeyDown);
      const restore = previousFocusRef.current;
      if (restore && document.contains(restore)) restore.focus();
      previousFocusRef.current = null;
    };
  }, [dialogRef, initialRef, open]);
}

export function TalkDrawer({ open, onClose, onAsk, onToast, workflow = [], initialPrompt = '' }) {
  const titleId = useId();
  const descriptionId = useId();
  const inputId = useId();
  const closeButtonRef = useRef(null);
  const dialogRef = useRef(null);
  const inputRef = useRef(null);
  const messagesRef = useRef(null);
  const recognitionRef = useRef(null);
  const speechRef = useRef(null);
  const audioRef = useRef(null);
  const playbackRef = useRef(0);
  const callActiveRef = useRef(false);
  const thinkingRef = useRef(false);
  const submitPromptRef = useRef(null);
  const startListeningRef = useRef(null);
  const restartTimerRef = useRef(null);
  const mountedRef = useRef(true);
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState(() => [
    createMessage('assistant', 'Ask me to explain a ranking, find a cheaper or faster alternative, or check delivery details.'),
  ]);
  const [isListening, setIsListening] = useState(false);
  const [isThinking, setIsThinking] = useState(false);
  const [callActive, setCallActive] = useState(false);
  const [speakingMessageId, setSpeakingMessageId] = useState(null);
  const [micState, setMicState] = useState('idle');
  const workingStage = workflow.find((stage) => stage.status === 'working');

  const notify = useCallback((message) => {
    if (typeof onToast === 'function' && message) onToast(message);
  }, [onToast]);

  const stopSpeaking = useCallback(() => {
    playbackRef.current += 1;
    if (typeof window !== 'undefined' && window.speechSynthesis) window.speechSynthesis.cancel();
    if (audioRef.current) {
      audioRef.current.pause();
      URL.revokeObjectURL(audioRef.current.src);
      audioRef.current = null;
    }
    speechRef.current = null;
    setSpeakingMessageId(null);
  }, []);

  const stopListening = useCallback(() => {
    if (restartTimerRef.current) window.clearTimeout(restartTimerRef.current);
    restartTimerRef.current = null;
    const recognition = recognitionRef.current;
    recognitionRef.current = null;
    recognition?.abort();
    setIsListening(false);
    setMicState('idle');
  }, []);

  const endCall = useCallback(() => {
    callActiveRef.current = false;
    setCallActive(false);
    stopListening();
    stopSpeaking();
  }, [stopListening, stopSpeaking]);

  const closeDrawer = useCallback(() => {
    endCall();
    onClose?.();
  }, [endCall, onClose]);

  const speakMessage = useCallback(async (message) => {
    stopSpeaking();
    const run = playbackRef.current;
    setSpeakingMessageId(message.id);
    let browserAttempted = false;
    const finish = () => {
      if (!mountedRef.current || run !== playbackRef.current) return;
      speechRef.current = null;
      if (audioRef.current) {
        URL.revokeObjectURL(audioRef.current.src);
        audioRef.current = null;
      }
      setSpeakingMessageId(null);
      if (callActiveRef.current) {
        restartTimerRef.current = window.setTimeout(() => startListeningRef.current?.(true), 350);
      }
    };
    const browserSpeak = () => {
      browserAttempted = true;
      if (!window.speechSynthesis || typeof window.SpeechSynthesisUtterance !== 'function') {
        throw new Error('Voice playback is unavailable in this browser.');
      }
      const utterance = new window.SpeechSynthesisUtterance(message.text);
      utterance.lang = 'en-IN';
      speechRef.current = utterance;
      utterance.onend = finish;
      utterance.onerror = finish;
      window.speechSynthesis.speak(utterance);
    };
    try {
      const response = await speakText(message.text);
      if (!mountedRef.current || run !== playbackRef.current) return;
      if (response.blob) {
        const audio = new Audio(URL.createObjectURL(response.blob));
        audioRef.current = audio;
        audio.onended = finish;
        audio.onerror = finish;
        await audio.play();
        return;
      }
      browserSpeak();
    } catch (error) {
      if (!mountedRef.current || run !== playbackRef.current) return;
      if (audioRef.current) {
        audioRef.current.pause();
        URL.revokeObjectURL(audioRef.current.src);
        audioRef.current = null;
      }
      if (!browserAttempted) {
        try {
          browserSpeak();
          notify('Server voice is unavailable. Using your browser voice for this answer.');
          return;
        } catch {
          /* The transcript still shows the answer when browser speech is unavailable. */
        }
      }
      notify(error?.message || 'Voice playback could not start. The answer is visible in the chat.');
      finish();
    }
  }, [notify, stopSpeaking]);

  const submitPrompt = useCallback(async (prompt) => {
    const text = String(prompt || '').trim();
    if (!text || thinkingRef.current) return;

    stopListening();
    stopSpeaking();
    const playbackRun = playbackRef.current;
    setInput('');
    const userMessage = createMessage('user', text);
    setMessages((current) => [...current, userMessage]);
    thinkingRef.current = true;
    setIsThinking(true);

    try {
      const reply = getReplyText(await onAsk(text));
      const assistantMessage = createMessage(
        'assistant',
        reply || 'I could not find a clear answer for that yet. Try asking about ranking, price, speed, or delivery.',
      );
      if (!mountedRef.current) return;
      setMessages((current) => [...current, assistantMessage]);
      if (playbackRun === playbackRef.current) void speakMessage(assistantMessage);
    } catch (error) {
      if (!mountedRef.current) return;
      const fallback = 'I hit a snag while checking that. Please try again or rephrase your question.';
      setMessages((current) => [...current, createMessage('assistant', fallback)]);
      notify(error?.message || 'The copilot could not answer right now.');
      if (callActiveRef.current) {
        restartTimerRef.current = window.setTimeout(() => startListeningRef.current?.(true), 500);
      }
    } finally {
      thinkingRef.current = false;
      if (mountedRef.current) setIsThinking(false);
    }
  }, [notify, onAsk, speakMessage, stopListening, stopSpeaking]);
  submitPromptRef.current = submitPrompt;

  const startListening = useCallback((autoSubmit = false) => {
    if (thinkingRef.current || recognitionRef.current || (autoSubmit && !callActiveRef.current)) return false;
    const SpeechRecognition = getSpeechRecognition();
    if (!SpeechRecognition) {
      notify('This browser does not support speech recognition. You can still type your request.');
      inputRef.current?.focus();
      return false;
    }

    const recognition = new SpeechRecognition();
    let transcript = '';
    recognitionRef.current = recognition;
    setMicState('requesting');
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.lang = typeof navigator !== 'undefined' && navigator.language ? navigator.language : 'en-US';
    recognition.onstart = () => {
      if (mountedRef.current && recognitionRef.current === recognition) {
        setMicState('granted');
        setIsListening(true);
      }
    };
    recognition.onresult = (event) => {
      transcript = Array.from(event.results)
        .map((result) => result[0]?.transcript || '')
        .join(' ')
        .trim();
      if (mountedRef.current && transcript) setInput(transcript);
    };
    recognition.onerror = (event) => {
      if (event.error === 'not-allowed' || event.error === 'service-not-allowed') {
        callActiveRef.current = false;
        setCallActive(false);
        setMicState('denied');
        notify('Microphone access is blocked. You can continue by typing.');
      } else if (event.error !== 'aborted' && event.error !== 'no-speech') {
        callActiveRef.current = false;
        setCallActive(false);
        notify('Voice recognition stopped. You can continue by typing.');
      }
    };
    recognition.onend = () => {
      if (recognitionRef.current !== recognition) return;
      recognitionRef.current = null;
      if (mountedRef.current) setIsListening(false);
      if (autoSubmit && callActiveRef.current && transcript) {
        void submitPromptRef.current?.(transcript);
      } else if (autoSubmit && callActiveRef.current) {
        restartTimerRef.current = window.setTimeout(() => startListeningRef.current?.(true), 700);
      }
    };

    try {
      recognition.start();
      return true;
    } catch {
      recognitionRef.current = null;
      callActiveRef.current = false;
      setCallActive(false);
      setMicState('idle');
      setIsListening(false);
      notify('Voice input could not start. You can continue by typing.');
      return false;
    }
  }, [notify]);
  startListeningRef.current = startListening;

  const toggleListening = useCallback(() => {
    if (recognitionRef.current) stopListening();
    else startListening(false);
  }, [startListening, stopListening]);

  const toggleCall = useCallback(() => {
    if (callActiveRef.current) {
      endCall();
      return;
    }
    callActiveRef.current = true;
    setCallActive(true);
    stopListening();
    stopSpeaking();
    if (!startListening(true)) {
      callActiveRef.current = false;
      setCallActive(false);
    }
  }, [endCall, startListening, stopListening, stopSpeaking]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      recognitionRef.current?.abort();
      recognitionRef.current = null;
      if (restartTimerRef.current) window.clearTimeout(restartTimerRef.current);
      if (audioRef.current) {
        audioRef.current.pause();
        URL.revokeObjectURL(audioRef.current.src);
        audioRef.current = null;
      }
      if (typeof window !== 'undefined' && window.speechSynthesis) window.speechSynthesis.cancel();
      speechRef.current = null;
    };
  }, []);

  useDrawerFocusTrap(open, dialogRef, closeButtonRef, closeDrawer);

  useEffect(() => {
    if (!open) endCall();
  }, [endCall, open]);

  useEffect(() => {
    if (open && initialPrompt) setInput(initialPrompt);
  }, [initialPrompt, open]);

  useEffect(() => {
    const list = messagesRef.current;
    if (list) list.scrollTop = list.scrollHeight;
  }, [isThinking, messages]);

  if (!open) return null;

  return (
    <div
      className="talk-drawer__backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) closeDrawer();
      }}
    >
      <style>{DRAWER_STYLES}</style>
      <section
        ref={dialogRef}
        className="talk-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="talk-drawer__header">
          <div>
            <p className="talk-drawer__eyebrow"><span className="talk-drawer__live-dot" />Shopping copilot</p>
            <h2 className="talk-drawer__title" id={titleId}>Talk to Artha</h2>
            <p className="talk-drawer__subtitle" id={descriptionId}>
              Describe what you need. Artha will research, compare, and explain the next step.
            </p>
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            className="talk-drawer__close"
            onClick={closeDrawer}
            aria-label="Close shopping copilot"
          >
            <Icon name="close" size={18} />
          </button>
        </header>

        <div className="talk-drawer__status" role="status" aria-live="polite">
          {isListening ? (
            <><span className="talk-drawer__status-icon"><Icon name="waveform" size={15} /></span>Listening — speak your question</>
          ) : micState === 'requesting' ? (
            <><span className="talk-drawer__status-icon"><Icon name="mic" size={15} /></span>Allow microphone access to speak</>
          ) : isThinking ? (
            <><span className="talk-drawer__status-icon"><Icon name="spark" size={15} /></span>{workingStage ? `${workingStage.agent}: ${workingStage.detail}` : 'Checking your shortlist'}</>
          ) : speakingMessageId ? (
            <><span className="talk-drawer__status-icon"><Icon name="volume" size={15} /></span>Reading the answer aloud</>
          ) : callActive ? (
            <><span className="talk-drawer__status-icon"><Icon name="waveform" size={15} /></span>Voice call connected</>
          ) : (
            <><span className="talk-drawer__status-icon"><Icon name="spark" size={15} /></span>Ready when you are</>
          )}
        </div>

        <div className="talk-drawer__messages" ref={messagesRef} role="log" aria-live="polite" aria-busy={isThinking}>
          <p className="talk-drawer__welcome">Tell me your brief or ask about a recommendation. Your transcript and each answer stay visible here.</p>
          <div className={`talk-drawer__call-card ${callActive ? 'talk-drawer__call-card--active' : ''}`}>
            <div>
              <strong><span className={`talk-drawer__call-orb ${isListening ? 'talk-drawer__call-orb--listening' : ''}`} aria-hidden="true" /> {callActive ? 'Voice call in progress' : 'In-app voice call'}</strong>
              <p>{callActive ? (isThinking ? 'Researching your request…' : speakingMessageId ? 'Speaking the answer…' : 'Listening for your next request…') : getSpeechRecognition() ? 'Speak your brief. Artha listens, researches, and talks back.' : 'Voice calls need a browser with speech recognition. Text chat works here.'}</p>
            </div>
            <button type="button" onClick={toggleCall} disabled={!callActive && !getSpeechRecognition()} aria-pressed={callActive}>
              <Icon name={callActive ? 'close' : 'mic'} size={14} /> {callActive ? 'End call' : 'Start call'}
            </button>
          </div>
          {messages.map((message) => (
            <div className={`talk-drawer__message-row talk-drawer__message-row--${message.role}`} key={message.id}>
              {message.role === 'assistant' ? <span className="talk-drawer__avatar" aria-hidden="true"><Icon name="spark" size={15} strokeWidth={2} /></span> : null}
              <div className="talk-drawer__bubble-wrap">
                <div className="talk-drawer__bubble">{message.text}</div>
                {message.role === 'assistant' ? (
                  <div className="talk-drawer__message-tools">
                    <button
                      type="button"
                      className="talk-drawer__speak"
                      onClick={() => (speakingMessageId === message.id ? stopSpeaking() : speakMessage(message))}
                      aria-label={speakingMessageId === message.id ? 'Stop reading this answer' : 'Read this answer aloud'}
                    >
                      <Icon name={speakingMessageId === message.id ? 'pause' : 'volume'} size={13} />
                      {speakingMessageId === message.id ? 'Stop' : 'Read aloud'}
                    </button>
                  </div>
                ) : null}
              </div>
            </div>
          ))}
          {isThinking ? (
            <div className="talk-drawer__message-row talk-drawer__message-row--assistant" aria-label="Copilot is thinking">
              <span className="talk-drawer__avatar" aria-hidden="true"><Icon name="spark" size={15} strokeWidth={2} /></span>
              <div className="talk-drawer__typing" aria-hidden="true"><span /><span /><span /></div>
            </div>
          ) : null}
          <div className="talk-drawer__suggestions" aria-label="Suggested questions">
            {SUGGESTIONS.map((suggestion) => (
              <button
                type="button"
                className="talk-drawer__suggestion"
                key={suggestion}
                onClick={() => submitPrompt(suggestion)}
                disabled={isThinking}
              >
                {suggestion}
              </button>
            ))}
          </div>
        </div>

        <form
          className="talk-drawer__composer"
          onSubmit={(event) => {
            event.preventDefault();
            submitPrompt(input);
          }}
        >
          <label className="sr-only" htmlFor={inputId}>Ask the shopping copilot</label>
          <div className="talk-drawer__input-wrap">
            <textarea
              ref={inputRef}
              id={inputId}
              className="talk-drawer__input"
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault();
                  submitPrompt(input);
                }
              }}
              placeholder="Ask about rank, price, speed, or delivery…"
              rows={1}
              readOnly={isThinking}
              aria-busy={isThinking}
              autoComplete="off"
            />
            <button
              type="button"
              className={`talk-drawer__icon-button ${isListening ? 'talk-drawer__icon-button--listening' : ''}`}
              onClick={toggleListening}
              disabled={isThinking || callActive}
              aria-label={isListening ? 'Stop listening' : 'Use voice input'}
              aria-pressed={isListening}
            >
              <Icon name="mic" size={17} />
            </button>
            <button type="submit" className="talk-drawer__send" disabled={isThinking || !input.trim()} aria-label="Send question">
              <Icon name="arrow" size={17} strokeWidth={2} />
            </button>
          </div>
          <small className="talk-drawer__hint">Press Enter to ask · Shift + Enter for a new line</small>
        </form>
      </section>
    </div>
  );
}

export default TalkDrawer;
