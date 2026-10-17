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

const STATE_LABELS = {
  ready: 'Ready for voice or text',
  listening: 'Listening locally (16kHz PCM)…',
  transcribing: 'Transcribing locally via Whisper…',
  thinking: 'Thinking locally…',
  speaking: 'Speaking locally…',
};

export function HomeVoiceAssistant({
  user,
  health,
  onSearchComplete,
  location,
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
    stage: 'greeting',
    slots: {},
    history_summary: null,
    instagram_posts: [],
    confirmed_reference: null,
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
    try {
      const response = await speakText(text);
      if (response.provider === 'server' && response.blob) {
        const url = URL.createObjectURL(response.blob);
        const audio = new Audio(url);
        audioRef.current = audio;
        await new Promise((resolve) => {
          audio.onended = () => {
            URL.revokeObjectURL(url);
            if (audioRef.current === audio) audioRef.current = null;
            resolve();
          };
          audio.onerror = () => {
            URL.revokeObjectURL(url);
            if (audioRef.current === audio) audioRef.current = null;
            resolve();
          };
          audio.play().catch(() => resolve());
        });
      }
    } catch (error) {
      setVoiceNotice(error.message || 'Local speech synthesis could not play audio.');
    } finally {
      setVoiceState('ready');
    }
  };

  useEffect(() => {
    let active = true;
    getAssistantSession()
      .then((data) => {
        if (!active || !data) return;
        setSessionId(data.session_id || '');
        if (Array.isArray(data.messages) && data.messages.length > 0) {
          setMessages(data.messages);
        }
        if (data.state) {
          setSessionState(data.state);
          const firstPost = data.state.instagram_posts?.[0];
          if (firstPost?.id) setSelectedRefId(firstPost.id);
        }
      })
      .catch(() => {});
    return () => {
      active = false;
      recognitionRef.current?.abort?.();
      abortRef.current?.abort?.();
      stopAudio();
    };
  }, [user?.id]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, [messages.length, sessionState.stage]);

  const handleResetSession = async () => {
    stopAudio();
    setVoiceNotice('');
    setTranscript('');
    setSelectedRefId('');
    setClothingNote('');
    try {
      const data = await getAssistantSession({ reset: true });
      setSessionId(data.session_id || '');
      setMessages(data.messages || [{ role: 'assistant', text: `What are you looking for today, ${firstName}?` }]);
      setSessionState(data.state || {});
      if (autoSpeak && data.assistant_message) {
        await speakAssistantReply(data.assistant_message);
      }
    } catch (error) {
      setVoiceNotice(error.message || 'Could not start a new session.');
    }
  };

  const toggleMicrophone = () => {
    stopAudio();
    setVoiceNotice('');
    if (voiceState === 'listening') {
      recognitionRef.current?.stop?.();
      return;
    }
    if (voiceState === 'transcribing') {
      abortRef.current?.abort?.();
      setVoiceState('ready');
      return;
    }

    warmVoice().catch(() => {});
    const recognition = createSpeechRecognition({
      provider: health?.voice?.stt_provider || 'whisper_local',
      transcribeAudio: (blob) => {
        const controller = new AbortController();
        abortRef.current = controller;
        setVoiceState('transcribing');
        return transcribeAudio(blob, controller.signal);
      },
      onTranscript: (spokenText, isFinal) => {
        const cleaned = String(spokenText || '').trim();
        if (!cleaned) return;
        setTranscript((prev) => (prev && !isFinal ? `${prev} ${cleaned}`.trim() : cleaned));
      },
      onEnd: () => {
        setVoiceState((current) => (current === 'listening' || current === 'transcribing' ? 'ready' : current));
      },
      onError: (err) => {
        setVoiceState('ready');
        setVoiceNotice(err?.message || 'Local microphone transcription failed. You can edit or type below.');
      },
    });

    if (!recognition) {
      setVoiceNotice('Local WAV microphone capture is unavailable in this browser context. Use the text box below.');
      return;
    }
    recognitionRef.current = recognition;
    setVoiceState('listening');
    recognition.start();
  };

  const submitTurn = async (overrideMessage = null) => {
    const textToSend = String(overrideMessage !== null ? overrideMessage : transcript).trim();
    if (!textToSend || voiceState === 'thinking') return;
    stopAudio();
    setVoiceNotice('');
    if (overrideMessage === null) setTranscript('');

    const optimisticMessages = [...messages, { role: 'user', text: textToSend }];
    setMessages(optimisticMessages);
    setVoiceState('thinking');

    try {
      const response = await sendAssistantTurn({
        session_id: sessionId,
        message: textToSend,
        search_overrides: location ? { location } : undefined,
      });
      setSessionId(response.session_id || sessionId);
      if (Array.isArray(response.messages)) {
        setMessages(response.messages);
      }
      if (response.state) {
        setSessionState(response.state);
        const posts = response.state.instagram_posts || [];
        if (posts.length > 0 && !selectedRefId) {
          setSelectedRefId(posts[0].id);
        }
        if (
          response.state.stage === 'awaiting_instagram_handle' ||
          response.state.instagram_resolution?.needs_fallback
        ) {
          setShowUploadFallback(true);
        }
      }
      if (response.search_result && typeof onSearchComplete === 'function') {
        onSearchComplete(response.search_result);
      }
      if (response.assistant_message) {
        await speakAssistantReply(response.assistant_message);
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
        clothing_note: clothingNote,
        search_overrides: location ? { location } : undefined,
      });
      if (Array.isArray(response.messages)) setMessages(response.messages);
      if (response.state) setSessionState(response.state);
      if (response.search_result && typeof onSearchComplete === 'function') {
        onSearchComplete(response.search_result);
      }
      if (response.assistant_message) {
        await speakAssistantReply(response.assistant_message);
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
        image_data: dataUrl,
        post_url: fallbackPostUrl,
        caption: fallbackCaption || clothingNote,
        handle: fallbackHandle,
      });
      if (res.session) {
        setMessages(res.session.messages || messages);
        setSessionState(res.session.state || sessionState);
      }
      if (res.reference?.id) {
        setSelectedRefId(res.reference.id);
      }
    } catch (error) {
      setVoiceNotice(error.message || 'Failed to upload reference screenshot.');
    }
  };

  const handleSaveFallbackLink = async () => {
    if (!fallbackPostUrl.trim() && !fallbackCaption.trim()) return;
    setVoiceNotice('');
    try {
      const res = await uploadInstagramReference({
        session_id: sessionId,
        post_url: fallbackPostUrl.trim(),
        caption: fallbackCaption.trim() || clothingNote.trim(),
        handle: fallbackHandle.trim(),
      });
      if (res.session) {
        setMessages(res.session.messages || messages);
        setSessionState(res.session.state || sessionState);
      }
      if (res.reference?.id) {
        setSelectedRefId(res.reference.id);
      }
    } catch (error) {
      setVoiceNotice(error.message || 'Failed to save pasted Instagram post reference.');
    }
  };

  const slots = sessionState?.slots || {};
  const historySummary = sessionState?.history_summary || {};
  const instagramPosts = sessionState?.instagram_posts || [];
  const confirmedRef = sessionState?.confirmed_reference || null;
  const sttProvider = health?.voice?.stt_provider || 'whisper_local';
  const ttsProvider = health?.voice?.tts_provider || 'kokoro_local';

  return (
    <section className="home-voice-assistant" aria-label="Local Voice Shopping Assistant">
      <div className="home-voice-header">
        <div>
          <div className="eyebrow">Local Voice Shopping Assistant · 100% On-Device Speech & LLM</div>
          <h1 className="home-voice-title">
            What are you looking for today, {firstName}?
          </h1>
          <p className="home-voice-subtitle">
            Speak naturally or edit your transcript below. Voice recognition ({sttProvider}), speech synthesis ({ttsProvider}), and conversation run locally on your Mac without paid API keys.
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
          <button type="button" className="ghost-button" onClick={handleResetSession}>
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

      {/* Conversation Timeline */}
      <div className="home-voice-thread" data-testid="conversation-thread">
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
        <div ref={messagesEndRef} />
      </div>

      {/* Microphone + Editable Transcript + Text Fallback */}
      <div className="home-voice-composer">
        <div className="mic-button-column">
          <button
            type="button"
            className={`primary-mic-button ${voiceState === 'listening' ? 'recording' : ''}`}
            onClick={toggleMicrophone}
            data-testid="home-mic-button"
          >
            {voiceState === 'listening'
              ? 'Stop Recording'
              : voiceState === 'transcribing'
              ? 'Cancel Transcribe'
              : 'Tap to Speak'}
          </button>
          <span className="mic-caption">
            {voiceState === 'listening'
              ? 'Recording 16kHz WAV locally… tap again when done'
              : 'Editable transcript & text fallback'}
          </span>
        </div>

        <div className="transcript-editor-column">
          <label htmlFor="editable-voice-transcript" className="sr-only">
            Editable voice transcript or text message
          </label>
          <textarea
            id="editable-voice-transcript"
            data-testid="editable-transcript-input"
            rows={2}
            value={transcript}
            onChange={(e) => setTranscript(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                submitTurn();
              }
            }}
            placeholder={`Speak with the mic or type here — e.g. "I'm going to Goa and want to buy a T-shirt"`}
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
              disabled={!transcript.trim() || voiceState === 'thinking'}
              onClick={() => submitTurn()}
            >
              {voiceState === 'thinking' ? 'Processing…' : 'Send'}
            </button>
          </div>
        </div>
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
      {(sessionState.stage === 'awaiting_instagram_handle' ||
        sessionState.stage === 'awaiting_instagram_post_selection' ||
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
                    onClick={() => setSelectedRefId(post.id)}
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
                      <div className="instagram-post-links">
                        {post.post_url && (
                          <a href={post.post_url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>
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
                  <input type="file" accept="image/*" onChange={handleFileUpload} hidden />
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
