import test from 'node:test';
import assert from 'node:assert/strict';
import { getConnectionNotice, hasMeaningfulTasteGraphData } from '../src/lib/tasteGraph.js';

test('disconnected retailer hubs do not hide the empty taste graph state', () => {
  assert.equal(hasMeaningfulTasteGraphData([
    { group: 'root' },
    { group: 'store' },
  ]), false);
  assert.equal(hasMeaningfulTasteGraphData([
    { group: 'root' },
    { group: 'store' },
    { group: 'memory' },
  ]), true);
});

test('connection notices hide browser automation errors behind a useful retry message', () => {
  assert.equal(
    getConnectionNotice('page.waitForTimeout: Target page, context or browser has been closed'),
    'The retailer tab closed before the sync finished. Reconnect and try again.',
  );
  assert.equal(getConnectionNotice('Sign in to the retailer tab to continue.'), 'Sign in to the retailer tab to continue.');
});
