import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {test} from 'node:test';

const worker = fileURLToPath(new URL('../backend/retailer_browser.mjs',import.meta.url));

test('retailer worker emits structured startup and failure diagnostics',()=>{
  const result=spawnSync(process.execPath,[worker],{input:JSON.stringify({provider:'unknown'}),encoding:'utf8'});
  const events=result.stdout.trim().split('\n').map(line=>JSON.parse(line));
  assert.equal(result.status,1);
  assert.deepEqual(events.slice(0,2).map(event=>event.step),['sync_started','connection_failed']);
  assert.equal(events[1].details.error_code,'unsupported_provider');
  assert.equal(events[2].type,'error');
  assert.doesNotMatch(result.stdout,/password|order_id|sessionid/i);
});
