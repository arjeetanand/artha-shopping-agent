import { useEffect, useRef, useState } from 'react';
import {
  confirmInstagramReference,
  getAssistantSession,
  sendAssistantTurn,
  speakText,
  transcribeAudio,
  uploadInstagramReference,
  warmVoice,
} from '../lib/api.js';
import { createSpeechRecognition } from '../lib/speechRecognition.js';
import { readAssistantSessionId, storeAssistantSessionId } from '../lib/assistantSessionStore.js';
import { Icon } from './Icon';

const STATE_LABELS = {
  ready: 'Ready for voice or text',
  listening: 'Listening…',
  transcribing: 'Transcribing…',
  thinking: 'Working on it…',
  speaking: 'Speaking…',
};

export function HomeVoiceAssistant({
  user,
  health,
  onSearchComplete,
}) {
  const firstName = (user?.name || 'Arjeet').trim().split(/\s+/)[0] || 'Arjeet';
  const [sessionId, setSessionId] = useState('');
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      text: `What are you looking for today, ${firstName}?`,
    },
  ]);
  const [sessionState, setSessionState] = useState({
    history: {},
    instagram_posts: [],
    selected_reference: null,
  });
  const [voiceState, setVoiceState] = useState('ready'); // ready | listening | transcribing | thinking | speaking
  const [transcript, setTranscript] = useState('');
  const [voiceNotice, setVoiceNotice] = useState('');
  const [autoSpeak, setAutoSpeak] = useState(true);
  const [selectedRefId, setSelectedRefId] = useState('');
  const [clothingNote, setClothingNote] = useState('');
  const [fallbackPostUrl, setFallbackPostUrl] = useState('');
  const [fallbackCaption, setFallbackCaption] = useState('');
  const [fallbackHandle, setFallbackHandle] = useState('');
  const [showUploadFallback, setShowUploadFallback] = useState(false);

  const recognitionRef = useRef(null);
  const audioRef = useRef(null);
  const abortRef = useRef(null);
  const messagesEndRef = useRef(null);
  const voiceTranscriptRef = useRef('');
  const sendVoiceOnEndRef = useRef(false);

  const stopAudio = () => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      window.speechSynthesis.cancel();
    }
  };

  const speakAssistantReply = async (text) => {
    if (!text || !autoSpeak) {
      setVoiceState('ready');
      return;
    }
    stopAudio();
    setVoiceState('speaking');
    let browserAttempted = false;
    const speakInBrowser = () => {
      if (!window.speechSynthesis || typeof window.SpeechSynthesisUtterance !== 'function') {
        throw new Error('Voice playback is unavailable in this browser. The reply is still shown in the chat.');
      }
      return new Promise((resolve, reject) => {
        const utterance = new window.SpeechSynthesisUtterance(text);
        utterance.lang = 'en-IN';
        utterance.onend = resolve;
        utterance.onerror = () => reject(new Error('Browser speech could not play. The reply is still shown in the chat.'));
        window.speechSynthesis.speak(utterance);
      });
    };
    try {
      const response = await speakText(text);
      if (response.provider === 'server' && response.blob) {
        const url = URL.createObjectURL(response.blob);
        const audio = new Audio(url);
        audioRef.current = audio;
        await new Promise((resolve, reject) => {
          const cleanup = () => {
            URL.revokeObjectURL(url);
            if (audioRef.current === audio) audioRef.current = null;
          };
          audio.onended = () => {
            cleanup();
            resolve();
          };
          audio.onerror = () => {
            cleanup();
            reject(new Error('Server voice could not play.'));
          };
          audio.play().catch((error) => {
            cleanup();
            reject(error);
          });
        });
      } else {
        browserAttempted = true;
        await speakInBrowser();
      }
    } catch (error) {
      if (!browserAttempted) {
        try {
          browserAttempted = true;
          await speakInBrowser();
          return;
        } catch {
          // The visible transcript remains available when speech is unavailable.
        }
      }
      setVoiceNotice(error.message || 'Voice playback could not start. The reply is still shown in the chat.');
    } finally {
      setVoiceState('ready');
    }
  };

  useEffect(() => {
    let active = true;
    const storedSessionId = readAssistantSessionId(user?.id);
    getAssistantSession(storedSessionId ? { sessionId: storedSessionId } : undefined)
      .then((data) => {
        if (!active || !data) return;
        const id = data.session_id || data.id || '';
        setSessionId(id);
        storeAssistantSessionId(user?.id, id);
        if (Array.isArray(data.messages) && data.messages.length > 0) {
          setMessages(data.messages);
        }
        if (data.state) {
          setSessionState({ ...data.state, history: data.history || {} });
          const firstPost = data.state.instagram_posts?.[0];
          if (firstPost?.id) setSelectedRefId(firstPost.id);
          if (data.state.awaiting_instagram_handle) setShowUploadFallback(true);
        }
      })
      .catch(() => {});
    return () => {
      active = false;
      recognitionRef.current?.abort?.();
      sendVoiceOnEndRef.current = false;
      abortRef.current?.abort?.();
      stopAudio();
    };
  }, [user?.id]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, [messages.length, sessionState.awaiting_instagram_handle, sessionState.awaiting_post_confirmation]);

  const handleResetSession = async () => {
    stopAudio();
    sendVoiceOnEndRef.current = false;
    voiceTranscriptRef.current = '';
    recognitionRef.current?.abort?.();
    abortRef.current?.abort?.();
    setVoiceState('ready');
    setVoiceNotice('');
    setTranscript('');
    setSelectedRefId('');
    setClothingNote('');
    setShowUploadFallback(false);
    try {
      const data = await getAssistantSession({ reset: true });
      const id = data.session_id || data.id || '';
      setSessionId(id);
      storeAssistantSessionId(user?.id, id);
      setMessages(data.messages || [{ role: 'assistant', text: `What are you looking for today, ${firstName}?` }]);
      setSessionState({ ...(data.state || {}), history: data.history || {} });
      if (autoSpeak && data.greeting) {
        await speakAssistantReply(data.greeting);
      }
    } catch (error) {
      setVoiceNotice(error.message || 'Could not start a new session.');
    }
  };

  const toggleMicrophone = () => {
    if (voiceState === 'thinking' || voiceState === 'speaking') return;
    stopAudio();
    setVoiceNotice('');
    if (voiceState === 'listening') {
      recognitionRef.current?.stop?.();
      return;
    }
    if (voiceState === 'transcribing') {
      sendVoiceOnEndRef.current = false;
      abortRef.current?.abort?.();
      setVoiceState('ready');
      return;
    }

    voiceTranscriptRef.current = '';
    sendVoiceOnEndRef.current = true;
    warmVoice().catch(() => {});
    const recognition = createSpeechRecognition({
      provider: health?.voice?.stt_provider || 'whisper_local',
      transcribeAudio: (blob) => {
        const controller = new AbortController();
        abortRef.current = controller;
        setVoiceState('transcribing');
        return transcribeAudio(blob, controller.signal);
      },
      onTranscript: (spokenText) => {
        const cleaned = String(spokenText || '').trim();
        if (!cleaned) return;
        voiceTranscriptRef.current = cleaned;
        setTranscript(cleaned);
      },
      onEnd: () => {
        setVoiceState((current) => (current === 'listening' || current === 'transcribing' ? 'ready' : current));
        const shouldSend = sendVoiceOnEndRef.current;
        sendVoiceOnEndRef.current = false;
        const spokenText = voiceTranscriptRef.current.trim();
        if (shouldSend && spokenText) void submitTurn(spokenText);
      },
      onError: (err) => {
        sendVoiceOnEndRef.current = false;
        voiceTranscriptRef.current = '';
        setVoiceState('ready');
        setVoiceNotice(err?.message || 'Local microphone transcription failed. You can edit or type below.');
      },
    });

    if (!recognition) {
      sendVoiceOnEndRef.current = false;
      setVoiceNotice('Local WAV microphone capture is unavailable in this browser context. Use the text box below.');
      return;
    }
    recognitionRef.current = recognition;
    setVoiceState('listening');
    try {
      recognition.start();
    } catch (error) {
      sendVoiceOnEndRef.current = false;
      setVoiceState('ready');
      setVoiceNotice(error.message || 'The microphone could not start. You can continue by typing.');
    }
  };

  const submitTurn = async (overrideMessage = null) => {
    const textToSend = String(overrideMessage !== null ? overrideMessage : transcript).trim();
    if (!textToSend || voiceState === 'thinking' || voiceState === 'speaking') return;
    stopAudio();
    setVoiceNotice('');
    setTranscript('');
    voiceTranscriptRef.current = '';

    const optimisticMessages = [...messages, { role: 'user', text: textToSend }];
    setMessages(optimisticMessages);
    setVoiceState('thinking');

    try {
      const response = await sendAssistantTurn({
        session_id: sessionId,
        message: textToSend,
      });
      const nextSessionId = response.session_id || sessionId;
      setSessionId(nextSessionId);
      storeAssistantSessionId(user?.id, nextSessionId);
      if (Array.isArray(response.messages)) {
        setMessages(response.messages);
      }
      if (response.state) {
        setSessionState({ ...response.state, history: response.history || sessionState.history || {} });
        const posts = response.state.instagram_posts || [];
        if (posts.length > 0 && !posts.some((post) => post.id === selectedRefId)) {
          setSelectedRefId(posts[0].id);
        }
        if (posts.length > 0) setShowUploadFallback(false);
        if (
          response.state.awaiting_instagram_handle ||
          ['requires_login', 'private_account', 'capture_failed', 'needs_handle'].includes(response.instagram_resolution?.status)
        ) {
          setShowUploadFallback(true);
        }
      }
      if (response.search_result && typeof onSearchComplete === 'function') {
        onSearchComplete(response.search_result);
      }
      if (response.reply || response.assistant_message) {
        await speakAssistantReply(response.reply || response.assistant_message);
      } else {
        setVoiceState('ready');
      }
    } catch (error) {
      setVoiceState('ready');
      setVoiceNotice(error.message || 'Could not process conversation turn.');
    }
  };

  const handleConfirmPost = async (refId = selectedRefId) => {
    const targetId = refId || selectedRefId || sessionState.instagram_posts?.[0]?.id;
    if (!targetId || !sessionId) return;
    stopAudio();
    setVoiceNotice('');
    setVoiceState('thinking');
    try {
      const response = await confirmInstagramReference({
        session_id: sessionId,
        reference_id: targetId,
        item_hint: clothingNote || sessionState.product || 'T-shirt',
      });
      const nextSessionId = response.session_id || sessionId;
      setSessionId(nextSessionId);
      storeAssistantSessionId(user?.id, nextSessionId);
      if (Array.isArray(response.messages)) setMessages(response.messages);
      if (response.state) setSessionState({ ...response.state, history: response.history || sessionState.history || {} });
      if (response.search_result && typeof onSearchComplete === 'function') {
        onSearchComplete(response.search_result);
      }
      if (response.reply || response.assistant_message) {
        await speakAssistantReply(response.reply || response.assistant_message);
      } else {
        setVoiceState('ready');
      }
    } catch (error) {
      setVoiceState('ready');
      setVoiceNotice(error.message || 'Could not confirm the Instagram reference.');
    }
  };

  const handleFileUpload = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setVoiceNotice('');
    try {
      const dataUrl = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result));
        reader.onerror = () => reject(new Error('Could not read uploaded screenshot.'));
        reader.readAsDataURL(file);
      });
      const res = await uploadInstagramReference({
        session_id: sessionId,
        image_base64: dataUrl,
        mime_type: file.type,
        source_url: fallbackPostUrl,
        caption: fallbackCaption || clothingNote,
        handle: fallbackHandle,
        friend_name: sessionState.friend_name || 'Paras',
      });
      if (res.session) {
        const nextSessionId = res.session.session_id || res.session.id || sessionId;
        setSessionId(nextSessionId);
        storeAssistantSessionId(user?.id, nextSessionId);
        setMessages(res.session.messages || messages);
        setSessionState({ ...(res.session.state || sessionState), history: sessionState.history || {} });
        setShowUploadFallback(false);
      }
      if (res.reference?.id) {
        setSelectedRefId(res.reference.id);
      }
    } catch (error) {
      setVoiceNotice(error.message || 'Failed to upload reference screenshot.');
    }
  };

  const handleSaveFallbackLink = async () => {
    const reference = fallbackPostUrl.trim() || (fallbackHandle.trim() ? `Instagram @${fallbackHandle.trim().replace(/^@/, '')}` : '');
    if (!reference) {
      setVoiceNotice('Paste an Instagram post or profile link, enter a handle, or upload a screenshot to use this reference.');
      return;
    }
    const details = fallbackCaption.trim() || clothingNote.trim();
    await submitTurn(`${reference}${details ? ` — ${details}` : ''}`);
  };

  const slots = {
    product: sessionState.product,
    destination: sessionState.destination,
    budget_max: sessionState.budget,
    size: sessionState.size,
    size_is_temporary: sessionState.preference_scope?.size === 'temporary_current_purchase',
    size_confirmed: sessionState.size_confirmed,
    fit: sessionState.fit,
  };
  const historySummary = {
    usual_top_size: sessionState.history?.usual_sizes?.top,
    conflicting_top_sizes: sessionState.history?.conflicts?.top_size?.conflicting_values || [],
  };
  const instagramPosts = sessionState?.instagram_posts || [];
  const confirmedRef = sessionState?.selected_reference || null;
  const exampleBrief = "I like my friend Paras’s dressing sense. Find me a relaxed outfit for a Goa weekend.";
  return (
    <section id="home-voice-assistant" className="home-voice-assistant home-voice-assistant--primary" aria-label="Voice Shopping Assistant">
      <div className="home-voice-header">
        <div>
          <div className="eyebrow">Your personal shopping assistant</div>
          <h1 className="home-voice-title">
            Tell me the look.<br />
            <span>I’ll find the pieces.</span>
          </h1>
          <p className="home-voice-subtitle">
            Tell Artha what you love. Mention Paras’s style or share an Instagram post; it checks real retailer options.
          </p>
        </div>
        <div className="home-voice-controls-bar">
          <span className={`voice-state-pill state-${voiceState}`} data-testid="voice-state-indicator">
            <span className="voice-state-dot" />
            {STATE_LABELS[voiceState] || STATE_LABELS.ready}
          </span>
          <label className="voice-toggle-label">
            <input
              type="checkbox"
              checked={autoSpeak}
              onChange={(e) => {
                setAutoSpeak(e.target.checked);
                if (!e.target.checked) stopAudio();
              }}
            />
            Speak replies
          </label>
          <button type="button" className="ghost-button" onClick={handleResetSession} disabled={voiceState === 'thinking'}>
            New Conversation
          </button>
        </div>
      </div>

      {/* History & Active Shopping Brief Badges */}
      <div className="home-voice-context-strip">
        {historySummary?.usual_top_size && (
          <span className="context-chip" title="Loaded from your past orders and searches">
            Saved usual size: <strong>{historySummary.usual_top_size}</strong>
            {historySummary.conflicting_top_sizes?.length > 0
              ? ` (past orders also had ${historySummary.conflicting_top_sizes.join(', ')})`
              : ''}
          </span>
        )}
        {slots.product && (
          <span className="context-chip active">
            Item: <strong>{slots.product}</strong>
          </span>
        )}
        {slots.destination && (
          <span className="context-chip active">
            Destination: <strong>{slots.destination}</strong>
          </span>
        )}
        {slots.budget_max && (
          <span className="context-chip active">
            Budget: <strong>₹{Number(slots.budget_max).toLocaleString('en-IN')}</strong>
          </span>
        )}
        {slots.size && (
          <span className="context-chip active">
            Size: <strong>{slots.size}</strong>
            {slots.size_is_temporary ? ' (this trip only)' : slots.size_confirmed ? ' (confirmed)' : ''}
          </span>
        )}
        {slots.fit && (
          <span className="context-chip active">
            Fit: <strong>{slots.fit}</strong>
          </span>
        )}
      </div>

      {/* Microphone + Editable Transcript + Text Fallback */}
      <div className="home-voice-composer">
        <div className="mic-button-column">
          <button
            type="button"
            className={`primary-mic-button ${voiceState === 'listening' ? 'recording' : ''}`}
            onClick={toggleMicrophone}
            disabled={voiceState === 'thinking' || voiceState === 'speaking'}
            aria-pressed={voiceState === 'listening' || voiceState === 'transcribing'}
            data-testid="home-mic-button"
          >
            <Icon name={voiceState === 'listening' ? 'waveform' : 'mic'} size={28} />
            {voiceState === 'listening'
              ? 'Finish & send'
              : voiceState === 'transcribing'
              ? 'Cancel transcription'
              : voiceState === 'thinking'
              ? 'Artha is thinking'
              : voiceState === 'speaking'
              ? 'Artha is speaking'
              : 'Start speaking'}
          </button>
          <span className="mic-caption">
            {voiceState === 'listening'
              ? 'Listening now · tap to finish and send'
              : voiceState === 'thinking' || voiceState === 'speaking'
              ? 'Artha will reply here and speak the answer aloud.'
              : 'Speak naturally. Your message is sent when you finish.'}
          </span>
        </div>

        <div className="transcript-editor-column">
          <details className="voice-text-fallback" open={Boolean(transcript)}>
            <summary>{transcript ? 'Edit transcript or type a message' : 'Type instead'}</summary>
            <label htmlFor="editable-voice-transcript" className="sr-only">
              Editable voice transcript or text message
            </label>
            <textarea
              id="editable-voice-transcript"
              data-testid="editable-transcript-input"
              rows={2}
              value={transcript}
              disabled={voiceState === 'thinking' || voiceState === 'speaking'}
              onChange={(e) => {
                setTranscript(e.target.value);
                voiceTranscriptRef.current = e.target.value;
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  submitTurn();
                }
              }}
              placeholder={`Try: "I like my friend Paras's dressing sense"`}
            />
            <div className="transcript-actions">
              <div className="quick-example-chips">
                <button
                  type="button"
                  className="chip-btn"
                  onClick={() => setTranscript("I'm going to Goa and want to buy a T-shirt.")}
                >
                  “I’m going to Goa and want to buy a T-shirt.”
                </button>
                <button
                  type="button"
                  className="chip-btn"
                  onClick={() => setTranscript('Around ₹1,500. Yes, use my usual size M.')}
                >
                  “Around ₹1,500. Use size M.”
                </button>
                <button
                  type="button"
                  className="chip-btn"
                  onClick={() => setTranscript("I liked something in my friend Paras's recent Instagram post.")}
                >
                  “Paras’s recent Instagram post”
                </button>
              </div>
              <button
                type="button"
                className="primary-send-button"
                data-testid="send-turn-button"
                disabled={!transcript.trim() || voiceState === 'thinking' || voiceState === 'speaking'}
                onClick={() => submitTurn()}
              >
                {voiceState === 'thinking' ? 'Processing…' : 'Send'}
              </button>
            </div>
          </details>
        </div>
      </div>

      {/* Keep the spoken entry point before the transcript in visual and reading order. */}
      <div className="home-voice-thread" data-testid="conversation-thread" aria-live="polite">
        <div className="voice-thread-heading">Conversation <span>YOUR BRIEF TAKES SHAPE HERE</span></div>
        {messages.map((msg, idx) => (
          <div
            key={`${msg.role}-${idx}`}
            className={`voice-turn-bubble ${msg.role === 'user' ? 'user-turn' : 'assistant-turn'}`}
          >
            <div className="turn-role-label">
              {msg.role === 'user' ? firstName : 'Artha Assistant'}
            </div>
            <div className="turn-text">{msg.text}</div>
          </div>
        ))}
        {messages.length === 1 && voiceState === 'ready' && !transcript && !instagramPosts.length && !confirmedRef ? (
          <aside className="voice-style-story" aria-label="Example of a voice brief becoming a shopping shortlist">
            <div className="voice-style-story__heading">
              <span>TRY A VOICE BRIEF</span>
              <span>PARAS · GOA</span>
            </div>
            <p className="voice-style-story__phrase">“{exampleBrief}”</p>
            <p className="voice-style-story__caption">Add a budget, size, or public Instagram link as you talk.</p>
            <button
              type="button"
              className="voice-style-story__action"
              onClick={() => {
                setTranscript(exampleBrief);
                voiceTranscriptRef.current = exampleBrief;
                requestAnimationFrame(() => document.getElementById('editable-voice-transcript')?.focus({ preventScroll: true }));
              }}
            >
              Try this brief <Icon name="arrow" size={16} />
            </button>
          </aside>
        ) : null}
        <div ref={messagesEndRef} />
      </div>

      {voiceNotice && (
        <div className="voice-warning-banner" role="status">
          <span>{voiceNotice}</span>
          <button type="button" className="ghost-button" onClick={() => setVoiceNotice('')}>
            Dismiss
          </button>
        </div>
      )}

      {/* Instagram Reference Section: Ambiguity / Handle / Upload Fallback / Captured Screenshots */}
      {(sessionState.awaiting_instagram_handle ||
        sessionState.awaiting_post_confirmation ||
        instagramPosts.length > 0 ||
        confirmedRef ||
        showUploadFallback) && (
        <div className="instagram-reference-panel" data-testid="instagram-reference-panel">
          <div className="instagram-panel-header">
            <div>
              <div className="eyebrow">Instagram Shopping Reference</div>
              <h3>
                {confirmedRef
                  ? `Confirmed Reference from @${confirmedRef.handle || 'instagram'}`
                  : instagramPosts.length > 0
                  ? 'Select the Instagram post & confirm the clothing item'
                  : 'Resolve Instagram Profile or Upload Reference Screenshot'}
              </h3>
            </div>
            <button
              type="button"
              className="ghost-button"
              onClick={() => setShowUploadFallback((v) => !v)}
            >
              {showUploadFallback ? 'Hide Upload / Link Fallback' : 'Upload Screenshot / Paste Link Fallback'}
            </button>
          </div>

          {instagramPosts.length > 0 && (
            <div className="instagram-posts-grid" data-testid="instagram-posts-grid">
              {instagramPosts.map((post, index) => {
                const isSelected = (selectedRefId || instagramPosts[0]?.id) === post.id;
                return (
                  <div
                    key={post.id || index}
                    className={`instagram-post-card ${isSelected ? 'selected' : ''}`}
                  >
                    <button
                      type="button"
                      className="instagram-post-select"
                      onClick={() => setSelectedRefId(post.id)}
                      aria-pressed={isSelected}
                      data-testid={`instagram-post-card-${index}`}
                    >
                      <div className="instagram-post-image-wrap">
                        {post.screenshot_url ? (
                          <img
                            src={post.screenshot_url}
                            alt={post.caption || `Instagram post ${index + 1}`}
                            loading="lazy"
                          />
                        ) : (
                          <div className="instagram-no-screenshot">
                            No screenshot file captured (metadata/caption fallback)
                          </div>
                        )}
                        <span className="instagram-post-badge">Post #{index + 1}</span>
                      </div>
                      <div className="instagram-post-meta">
                        <div className="instagram-post-caption">
                          {post.caption || 'Instagram reference post'}
                        </div>
                      </div>
                    </button>
                    <div className="instagram-post-links">
                      {post.post_url && (
                        <a href={post.post_url} target="_blank" rel="noreferrer">
                          Source Post ↗
                        </a>
                      )}
                      {post.captured_at && (
                        <span className="capture-time" title="Local screenshot capture timestamp">
                          Captured: {new Date(post.captured_at).toLocaleString()}
                        </span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {instagramPosts.length > 0 && (
            <div className="instagram-confirm-bar">
              <input
                type="text"
                value={clothingNote}
                onChange={(e) => setClothingNote(e.target.value)}
                placeholder="Optional: specify which clothing item in the post (e.g., relaxed sage green textured t-shirt)"
                data-testid="clothing-item-note-input"
              />
              <button
                type="button"
                className="primary-send-button"
                data-testid="confirm-instagram-post-button"
                disabled={voiceState === 'thinking'}
                onClick={() => handleConfirmPost(selectedRefId || instagramPosts[0]?.id)}
              >
                Confirm Post & Analyze Clothing Locally
              </button>
            </div>
          )}

          {confirmedRef?.attributes && (
            <div className="analyzed-attributes-card" data-testid="analyzed-attributes-card">
              <div className="eyebrow">
                Local Vision Clothing Analysis ({confirmedRef.attributes.analysis_model || 'local'})
              </div>
              <div className="attributes-chip-row">
                {confirmedRef.attributes.category && (
                  <span className="context-chip">Category: <strong>{confirmedRef.attributes.category}</strong></span>
                )}
                {confirmedRef.attributes.color && (
                  <span className="context-chip">Color: <strong>{confirmedRef.attributes.color}</strong></span>
                )}
                {confirmedRef.attributes.pattern && (
                  <span className="context-chip">Pattern: <strong>{confirmedRef.attributes.pattern}</strong></span>
                )}
                {confirmedRef.attributes.fit && (
                  <span className="context-chip">Fit: <strong>{confirmedRef.attributes.fit}</strong></span>
                )}
                {confirmedRef.attributes.material && (
                  <span className="context-chip">Material: <strong>{confirmedRef.attributes.material}</strong></span>
                )}
                {confirmedRef.attributes.design && (
                  <span className="context-chip">Design: <strong>{confirmedRef.attributes.design}</strong></span>
                )}
              </div>
            </div>
          )}

          {showUploadFallback && (
            <div className="instagram-fallback-box" data-testid="instagram-fallback-box">
              <p className="fallback-help-text">
                If Instagram requires a login wall or the account is private, upload a screenshot of the post or paste the direct post URL and description below:
              </p>
              <div className="fallback-inputs-row">
                <input
                  type="text"
                  value={fallbackHandle}
                  onChange={(e) => setFallbackHandle(e.target.value)}
                  placeholder="Friend's handle (e.g. @paras)"
                />
                <input
                  type="url"
                  value={fallbackPostUrl}
                  onChange={(e) => setFallbackPostUrl(e.target.value)}
                  placeholder="https://www.instagram.com/p/..."
                />
                <input
                  type="text"
                  value={fallbackCaption}
                  onChange={(e) => setFallbackCaption(e.target.value)}
                  placeholder="Describe the clothing item (e.g. sage green relaxed linen-cotton resort t-shirt)"
                />
              </div>
              <div className="fallback-actions-row">
                <label className="upload-screenshot-btn">
                  Upload Post Screenshot
                  <input type="file" accept="image/jpeg,image/png,image/webp" onChange={handleFileUpload} hidden />
                </label>
                <button
                  type="button"
                  className="ghost-button"
                  onClick={handleSaveFallbackLink}
                >
                  Save Pasted Reference
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
