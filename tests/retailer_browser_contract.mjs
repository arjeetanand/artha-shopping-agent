import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {test} from 'node:test';
import {chromium} from 'playwright';
import {openHistory,historyWindowLimited} from '../backend/retailer_browser.mjs';

test('Amazon Business renders its year filter late and ignores the URL filter', async () => {
  const server=createServer((request,response)=>response.end(`<!doctype html><body><script>
    setTimeout(()=>{
      document.body.innerHTML='<select id="timeFilterDropdown"><option value="yoPast3months">Last 3 months</option><option value="2026">2026</option></select><p id="result">You have not placed any orders in Last 3 months.</p>';
      document.querySelector('select').onchange=()=>setTimeout(()=>document.querySelector('#result').textContent='You have not placed any orders in 2026.',100);
    },100);
  </script></body>`));
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const browser=await chromium.launch({channel:'chrome',headless:true});
  try {
    const page=await browser.newPage();
    await openHistory(page,`http://127.0.0.1:${server.address().port}/orders?orderFilter=year-2026`,'amazon');
    assert.equal(await page.locator('#timeFilterDropdown').inputValue(),'2026');
    assert.equal(await historyWindowLimited(page),false);
    await page.locator('#timeFilterDropdown').selectOption('yoPast3months');
    assert.equal(await historyWindowLimited(page),true);
  } finally {await browser.close();await new Promise(resolve=>server.close(resolve));}
});
