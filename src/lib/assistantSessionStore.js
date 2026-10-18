const sessionKey = (userId) => `artha:assistant-session:${userId || 'guest'}`;

export function readAssistantSessionId(userId) {
  try {
    return window.sessionStorage.getItem(sessionKey(userId)) || '';
  } catch {
    return '';
  }
}

export function storeAssistantSessionId(userId, sessionId) {
  try {
    if (sessionId) window.sessionStorage.setItem(sessionKey(userId), sessionId);
    else window.sessionStorage.removeItem(sessionKey(userId));
  } catch {
    // The conversation still works for the current page when session storage is unavailable.
  }
}
