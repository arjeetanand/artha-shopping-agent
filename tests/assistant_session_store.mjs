import test from 'node:test';
import assert from 'node:assert/strict';
import { readAssistantSessionId, storeAssistantSessionId } from '../src/lib/assistantSessionStore.js';

test('assistant session IDs stay scoped to the current user and tab session', () => {
  const values = new Map();
  globalThis.window = { sessionStorage: {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  } };

  storeAssistantSessionId('user-1', 'session-a');
  storeAssistantSessionId('user-2', 'session-b');
  assert.equal(readAssistantSessionId('user-1'), 'session-a');
  assert.equal(readAssistantSessionId('user-2'), 'session-b');
  storeAssistantSessionId('user-1', '');
  assert.equal(readAssistantSessionId('user-1'), '');
  assert.equal(readAssistantSessionId('user-2'), 'session-b');
  delete globalThis.window;
});

test('assistant session storage failures leave voice chat usable', () => {
  globalThis.window = { sessionStorage: {
    getItem: () => { throw new Error('storage disabled'); },
    setItem: () => { throw new Error('storage disabled'); },
    removeItem: () => { throw new Error('storage disabled'); },
  } };
  assert.equal(readAssistantSessionId(), '');
  assert.doesNotThrow(() => storeAssistantSessionId(undefined, 'session-a'));
  delete globalThis.window;
});
