import assert from 'node:assert/strict';
import dns from 'node:dns/promises';
import { mock, test } from 'node:test';
import { isPublicHttpUrl } from '../backend/social_network.mjs';

test('social scraper allows public addresses and rejects special-use addresses', async () => {
  assert.equal(await isPublicHttpUrl('https://8.8.8.8/post'), true);
  for (const url of [
    'file:///etc/passwd',
    'http://127.0.0.1/',
    'http://[::ffff:127.0.0.1]/',
    'http://169.254.169.254/latest/meta-data/',
    'http://192.0.2.1/',
    'http://[::1]/',
    'http://[fc00::1]/',
    'http://[fe80::1]/',
    'http://[2001:db8::1]/',
    'https://public.example:8443/',
  ]) {
    assert.equal(await isPublicHttpUrl(url), false, url);
  }
});

test('social scraper rejects a hostname if any DNS answer is non-public', async () => {
  const answers = [
    { address: '8.8.8.8', family: 4 },
    { address: '10.0.0.4', family: 4 },
  ];
  const lookup = mock.method(dns, 'lookup', async () => answers);
  try {
    assert.equal(await isPublicHttpUrl('https://mixed.example/'), false);
    assert.equal(lookup.mock.callCount(), 1);
  } finally {
    lookup.mock.restore();
  }
});
