import { chromium } from 'playwright';
import { mkdir, writeFile, readFile, chmod } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { RETAILERS, retailerUrl, parseOrderEvidence, historyUrls } from './retailer_extract.mjs';
import { isPublicHttpUrl } from './social_network.mjs';

const emit = (event) => process.stdout.write(`${JSON.stringify(event)}\n`);
const log = (step, status, details = {}) => emit({type:'log',step,status,details});
const routeName = (url) => {
  try {
    const route = new URL(url).pathname.toLowerCase();
    return /invoice|tax.?bill/.test(route) ? 'invoice' : /order/.test(route) ? 'orders' : /login|signin/.test(route) ? 'login' : 'other';
  } catch { return 'invalid'; }
};

async function snapshot(page, config) {
  return page.locator('body').evaluate((root, selectors) => {
    const scopes = [...root.querySelectorAll(selectors.items)];
    const anchors = new Set(scopes.flatMap(scope=>[...scope.querySelectorAll(selectors.products)]));
    const products = [...anchors].map((anchor) => {
      const container = anchor.closest('[data-component="item"], [class*="item"], [class*="Item"]') || anchor.parentElement;
      const name = anchor.innerText?.trim() || anchor.querySelector('img')?.alt || '';
      return {name, url:anchor.href, text:container?.innerText?.slice(0,3000) || '',
        price:container?.querySelector('.a-price .a-offscreen, [data-testid="item-price"]')?.textContent || '',
        brand:container?.querySelector('[data-testid="brand"], [class*="brandName"]')?.textContent?.trim() || ''};
    });
    const invoiceLinks = [...root.querySelectorAll('a[href]')]
      .filter(a => /invoice|tax.?bill/i.test(`${a.textContent} ${a.href}`) && !/request|send|email/i.test(a.textContent))
      .map(a => a.href);
    return {text:root.innerText.slice(0,160000), products, invoiceLinks,
      deliveryLocation:root.querySelector('.displayAddressCityStateOrRegionPostalCode, [data-testid="delivery-city-pincode"]')?.textContent?.replace(/\s+/g,' ').trim() || '',
      orderId:root.getAttribute('data-order-id') || '',
      orderDate:root.querySelector('[data-testid="order-date"], [data-component="orderDate"]')?.textContent || ''};
  }, config);
}

async function savePdf(buffer, directory, orderId) {
  if (buffer.length > 20 * 1024 * 1024 || buffer.subarray(0,5).toString() !== '%PDF-') return false;
  const sha256 = createHash('sha256').update(buffer).digest('hex');
  const filename = `${sha256}.pdf`;
  await writeFile(path.join(directory, filename), buffer, {mode:0o600});
  log('invoice_saved','info',{response_bytes:buffer.length});
  emit({type:'invoice', retailer_order_id:orderId, filename, sha256});
  return true;
}

async function fetchInvoice(context, url, directory, orderId, provider, visited = new Set()) {
  if (visited.has(url) || visited.size > 12) {
    log('invoice_fetch','warning',{error_code:'duplicate_or_limit'});
    return 0;
  }
  visited.add(url);
  for (let redirect = 0; redirect < 5; redirect++) {
    if (!(await isPublicHttpUrl(url))) {
      log('invoice_fetch','warning',{error_code:'unsafe_url'});
      return false;
    }
    const response = await context.request.get(url, {maxRedirects:0, timeout:20000});
    if (response.status() >= 300 && response.status() < 400) {
      const location = response.headers().location;
      if (!location) {
        log('invoice_fetch','warning',{http_status:response.status(),error_code:'redirect_without_location'});
        return false;
      }
      log('invoice_fetch','info',{route:routeName(url),http_status:response.status()});
      url = new URL(location,url).href;
      continue;
    }
    if (!response.ok() || Number(response.headers()['content-length'] || 0) > 20*1024*1024) {
      log('invoice_fetch','warning',{route:routeName(url),http_status:response.status(),error_code:response.ok()?'invoice_too_large':'http_error'});
      return false;
    }
    const content = await response.body();
    if (content.subarray(0,5).toString()==='%PDF-') return savePdf(content,directory,orderId);
    if (/text\/html/i.test(response.headers()['content-type'] || '') && retailerUrl(url,provider)) {
      log('invoice_fetch','info',{route:routeName(url),http_status:response.status(),response_bytes:content.length});
      const invoicePage = await context.newPage();
      try {
        await invoicePage.goto(url,{waitUntil:'domcontentloaded',timeout:20000});
        const links = await invoicePage.locator('a[href]').filter({hasText:/^(?:Invoice\s*\d*|Download Invoice|Tax Invoice|Download Tax Invoice)$/i}).evaluateAll(nodes=>nodes.map(node=>node.href));
        log('invoice_page_read',links.length?'info':'warning',{invoice_candidate_count:links.length,route:routeName(url)});
        let count=0;
        for (const link of links) count+=Number(await fetchInvoice(context,link,directory,orderId,provider,visited));
        return count;
      } finally {await invoicePage.close();}
    }
    log('invoice_fetch','warning',{route:routeName(url),http_status:response.status(),response_bytes:content.length,error_code:'not_pdf_or_invoice_page'});
    return 0;
  }
  return false;
}

async function collectInvoices(context, page, links, directory, orderId, provider, interact = true) {
  let count = 0;
  const candidates = new Set(links || []);
  log('invoice_scan','info',{invoice_candidate_count:candidates.size});
  const invoiceMenu = page.getByRole('button', {name:/^invoice$/i}).first();
  if (interact && await invoiceMenu.isVisible().catch(()=>false)) {
    await invoiceMenu.click();
    await page.waitForTimeout(300);
    for (const href of await page.locator('a').filter({hasText:/^(?:Invoice\s*\d*|Download Invoice|Tax Invoice)$/i}).evaluateAll(nodes=>nodes.map(n=>n.href))) candidates.add(href);
  }
  for (const url of candidates) {
    try { count += Number(await fetchInvoice(context,url,directory,orderId,provider)); }
    catch(error) { log('invoice_fetch','warning',{error_class:error?.name||'Error'}); }
  }
  if (!count && interact) {
    const button = page.getByRole('button',{name:/^(?:Download Invoice|Download Tax Invoice)$/i}).first();
    if (await button.isVisible().catch(()=>false)) {
      const downloadPromise = page.waitForEvent('download',{timeout:10000}).catch(()=>null);
      await button.click();
      const download = await downloadPromise;
      if (download && !await download.failure()) {
        const temporary = await download.path();
        if (temporary) count += Number(await savePdf(await readFile(temporary),directory,orderId));
      }
    }
  }
  log('invoice_scan','info',{invoice_count:count,success:count>0});
  return count;
}

async function signedIn(page, provider, config) {
  if (provider === 'instagram') {
    return (await page.context().cookies('https://www.instagram.com')).some(cookie=>cookie.name==='sessionid' && cookie.value);
  }
  if (!retailerUrl(page.url(),provider) || /\/signin|\/login|\/ap\//i.test(new URL(page.url()).pathname)) return false;
  if (await page.locator('input[type="password"]').isVisible().catch(()=>false)) return false;
  if (await page.locator(config.cards).count() || await page.locator(config.details).count()) return true;
  const text = await page.locator('body').innerText().catch(()=>'');
  return /(?:no orders|haven.t placed any orders|you have not placed|no purchases)/i.test(text);
}

export async function openHistory(page, url, provider) {
  await page.goto(url,{waitUntil:'domcontentloaded',timeout:45000});
  if (provider !== 'amazon') return;
  const year = new URL(url).searchParams.get('orderFilter')?.replace('year-','');
  await page.waitForFunction(() => document.querySelector('#timeFilterDropdown, .order-card, .js-order-card')
    || /(?:no orders|haven.t placed any orders|you have not placed)/i.test(document.body.innerText),{},{timeout:30000});
  const businessFilter = page.locator('#timeFilterDropdown');
  if (await businessFilter.count()) {
    await businessFilter.selectOption(year);
    await page.waitForFunction(expected => {
      const filter = document.querySelector('#timeFilterDropdown');
      const text = document.body.innerText;
      return filter?.value === expected && (document.querySelector('.order-card, .js-order-card')
        || new RegExp(`(?:orders? placed in|orders in)\\s*${expected}|not placed any orders in ${expected}`,'i').test(text));
    },year,{timeout:30000});
  }
}

export async function historyWindowLimited(page) {
  // Dropdown option lists contain "Last 3 months" even when a whole year is selected.
  const selected = await page.locator('select[name="orderFilter"], #timeFilterDropdown').evaluateAll(nodes=>nodes.map(n=>n.selectedOptions[0]?.textContent||n.value));
  return selected.some(value=>/last\s*(?:30 days|3 months)|past\s*3 months/i.test(value));
}

export async function runConnection(input) {
  const provider = input.provider;
  const startedAt = Date.now();
  log('sync_started','info',{cutoff:input.cutoff,until:input.until});
  const config = RETAILERS[provider];
  if (!config && provider !== 'instagram') throw new Error('Unsupported provider');
  await mkdir(input.profile_dir,{recursive:true,mode:0o700});
  await mkdir(input.invoice_dir,{recursive:true,mode:0o700});
  await chmod(input.profile_dir,0o700);
  const launch = {headless:false,acceptDownloads:true,serviceWorkers:'block',locale:'en-IN',timezoneId:'Asia/Kolkata',
    ...(process.env.SHOPPINGHELP_CHROME_PATH ? {executablePath:process.env.SHOPPINGHELP_CHROME_PATH} : {channel:'chrome'})};
  log('browser_launch','info',{outcome:'started'});
  const context = await chromium.launchPersistentContext(input.profile_dir,launch);
  log('browser_launch','info',{outcome:'complete'});
  const stop = async () => {await context.close().catch(()=>{});process.exit(0);};
  process.once('SIGTERM',stop);
  process.once('SIGINT',stop);
  // shortcut: DNS checks cannot pin Chromium's resolved IP; use an egress proxy before hosting this connector remotely.
  await context.route('**/*',async route => (await isPublicHttpUrl(route.request().url())) ? route.continue() : route.abort('blockedbyclient'));
  let page = context.pages()[0] || await context.newPage();
  const historySeeds = config ? historyUrls(provider,input.cutoff,input.until || new Date().toISOString().slice(0,10)) : [];
  const target = historySeeds.shift() || 'https://www.instagram.com/accounts/login/';
  try {
    log('history_navigation','info',{route:routeName(target)});
    await page.goto(target,{waitUntil:'domcontentloaded',timeout:45000});
    await page.bringToFront();
    log('login_window_open','info',{route:routeName(page.url())});
    emit({type:'progress',status:'awaiting_login',message:provider==='instagram' ? 'Sign in to Instagram in the opened Chrome window.' : `Sign in to ${provider}, then open Your Orders in that Chrome window. Keep it open while history is read.`});
    const deadline = Date.now() + 15*60*1000;
    while (true) {
      const tabs = context.pages().filter(tab=>!tab.isClosed());
      const authenticated = [];
      for (const tab of tabs) if (await signedIn(tab,provider,config)) authenticated.push(tab);
      if (authenticated.length) {
        page=authenticated[0];
        log('login_detected','info',{auth_detected:true,route:routeName(page.url())});
        break;
      }
      if (Date.now()>deadline) throw new Error('Sign-in timed out. Connect again when you are ready.');
      if (!tabs.length) throw new Error('Retailer sign-in window was closed');
      if (page.isClosed()) page=tabs[tabs.length-1];
      await page.waitForTimeout(2000);
      const url = page.url();
      if (config && retailerUrl(url,provider) && !/orders|signin|login|\/ap\//i.test(new URL(url).pathname)) {
        const logout = page.locator('a[href*="logout"], a[href*="sign-out"]');
        const amazonGreeting = provider==='amazon' ? await page.locator('#nav-link-accountList-nav-line-1').innerText().catch(()=>'') : '';
        if (await logout.count() || (amazonGreeting && !/sign in/i.test(amazonGreeting))) await page.goto(target,{waitUntil:'domcontentloaded',timeout:45000});
      }
    }
    if (provider === 'instagram') {
      log('connection_complete','info',{elapsed_ms:Date.now()-startedAt,auth_detected:true});
      emit({type:'complete',status:'connected',orders:0,invoices:0,coverage_complete:true});
      return;
    }
    emit({type:'progress',status:'syncing',message:'Reading order history for the last six months.'});
    log('history_read_started','info',{route:routeName(page.url())});
    await openHistory(page,target,provider);
    log('history_page_loaded','info',{route:routeName(page.url())});
    const detailUrls = new Set(), cardSnapshots = [], visitedPages = new Set();
    let historyExhausted = false, windowLimited = false, pageCount = 0;
    for (;pageCount<100;pageCount++) {
      await page.waitForTimeout(1000);
      const text = await page.locator('body').innerText();
      const signature = createHash('sha256').update(text).digest('hex');
      if (visitedPages.has(signature)) {
        log('pagination_stopped','warning',{page:pageCount+1,page_signature_duplicate:true,stop_reason:'duplicate_page'});
        break;
      }
      visitedPages.add(signature);
      windowLimited ||= await historyWindowLimited(page);
      const cards = page.locator(config.cards);
      const cardCount = await cards.count();
      for (let index=0;index<cardCount;index++) {
        const card = cards.nth(index);
        const data = await card.evaluate((node,selectors)=>({text:node.innerText,
          products:[...node.querySelectorAll(selectors.products)].map(a=>({name:a.innerText.trim()||a.querySelector('img')?.alt||'',url:a.href,text:a.parentElement?.innerText||''})),
          invoiceLinks:[...node.querySelectorAll('a[href]')].filter(a=>/invoice/i.test(a.textContent)&&!/request|send|email/i.test(a.textContent)).map(a=>a.href),
          orderId:node.getAttribute('data-order-id')||'',orderDate:node.querySelector('[data-testid="order-date"]')?.textContent||''}),config);
        cardSnapshots.push({...data,url:page.url()});
      }
      const detailHrefs = await page.locator(config.details).evaluateAll(nodes=>nodes.map(node=>node.href));
      for (const href of detailHrefs) {
        if (retailerUrl(href,provider) && !/invoice|cancel|return/i.test(new URL(href).pathname)) detailUrls.add(href);
      }
      const emptyState = /(?:no orders|haven.t placed any orders|you have not placed|no purchases)/i.test(text);
      log('history_page_scanned',cardCount||detailHrefs.length?'info':'warning',{
        page:pageCount+1,card_count:cardCount,detail_link_count:detailHrefs.length,
        body_chars:text.length,empty_state:emptyState,window_limited:windowLimited,
      });
      emit({type:'progress',status:'syncing',message:`Read ${pageCount+1} order-history pages.`,pages:pageCount+1});
      if (emptyState) {
        log('history_empty_state','info',{page:pageCount+1});
        const nextYear = historySeeds.shift();
        if (nextYear) {await openHistory(page,nextYear,provider);continue;}
        historyExhausted=true;break;
      }
      const next = page.locator(config.next).first();
      if (await next.isVisible().catch(()=>false) && await next.isEnabled().catch(()=>false)) {
        log('pagination','info',{page:pageCount+1,has_next_page:true,outcome:'next_clicked'});
        await next.click();
        continue;
      }
      let changed = false;
      for (let attempt=0;attempt<3;attempt++) {
        await page.evaluate(()=>window.scrollTo(0,document.body.scrollHeight));
        await page.waitForTimeout(1200);
        if (await page.locator('body').innerText() !== text) {changed=true;break;}
      }
      if (!changed) {
        log('pagination','info',{page:pageCount+1,scroll_changed:false,outcome:'history_end'});
        const nextYear = historySeeds.shift();
        if (nextYear) {await openHistory(page,nextYear,provider);continue;}
        historyExhausted=true;break;
      }
      log('pagination','info',{page:pageCount+1,scroll_changed:true,outcome:'scroll_loaded'});
    }
    const seenOrders = new Set();
    let orderCount=0,invoiceCount=0,missingDates=0,unreadable=0,missingInvoices=0,datedOrders=0;
    const detailPage = await context.newPage();
    async function processSnapshot(data,invoicePage,interact = true) {
      const order = parseOrderEvidence(data,provider);
      if (order.error) {
        if(order.error==='order_date_missing')missingDates++;else unreadable++;
        log('order_parse','warning',{error_code:order.error});
        return;
      }
      datedOrders++;
      if (seenOrders.has(order.id)) {log('order_parse','info',{outcome:'duplicate_skipped'});return;}
      if (order.order_date<input.cutoff) {log('order_parse','info',{outcome:'outside_window'});return;}
      log('order_parse','info',{outcome:'complete',item_count:order.items.length,invoice_candidate_count:(data.invoiceLinks||[]).length});
      seenOrders.add(order.id);
      const invoiceTotal = await collectInvoices(context,invoicePage,data.invoiceLinks,input.invoice_dir,order.id,provider,interact);
      invoiceCount += invoiceTotal;
      missingInvoices += Number(!invoiceTotal);
      order.invoice_status = invoiceTotal ? 'downloaded' : 'unavailable';
      emit({type:'order',order});
      orderCount++;
      emit({type:'progress',status:'syncing',message:`Read ${orderCount} recent orders; saved ${invoiceCount} invoices.`,orders:orderCount,invoices:invoiceCount});
    }
    for (const url of detailUrls) {
      try {
        log('order_detail_navigation','info',{route:routeName(url)});
        await detailPage.goto(url,{waitUntil:'domcontentloaded',timeout:35000});
        if (!retailerUrl(detailPage.url(),provider) || /signin|login|\/ap\//i.test(new URL(detailPage.url()).pathname)) throw new Error('Retailer session expired during sync');
        await detailPage.waitForTimeout(700);
        await processSnapshot({...await snapshot(detailPage,config),url:detailPage.url()},detailPage);
      } catch(error) {
        if (/session expired/.test(error.message)) {
          log('order_detail_read','error',{error_code:'session_expired'});
          throw error;
        }
        unreadable++;
        log('order_detail_read','warning',{error_class:error?.name||'Error'});
      }
    }
    for (const data of cardSnapshots) await processSnapshot(data,page,false);
    const empty = /(?:no orders|haven.t placed any orders|you have not placed|no purchases)/i.test(await page.locator('body').innerText());
    if (!datedOrders && !empty) {
      log('history_layout_unrecognized','error',{page:pageCount+1,card_count:cardSnapshots.length,detail_link_count:detailUrls.size,
        body_chars:(await page.locator('body').innerText()).length});
      throw new Error('Order history opened, but its current layout could not be read. No orders were invented.');
    }
    log('connection_complete','info',{elapsed_ms:Date.now()-startedAt,order_count:orderCount,invoice_count:invoiceCount,
      missing_invoices:missingInvoices,missing_dates:missingDates,unreadable_pages:unreadable,pages:pageCount+1,
      coverage_complete:historyExhausted&&!windowLimited&&!missingDates&&!unreadable,window_limited:windowLimited});
    emit({type:'complete',status:'synced',orders:orderCount,invoices:invoiceCount,missing_invoices:missingInvoices,
      missing_dates:missingDates,unreadable_pages:unreadable,pages:pageCount+1,
      coverage_complete:historyExhausted&&!windowLimited&&!missingDates&&!unreadable,
      cutoff:input.cutoff,window_limited:windowLimited});
  } finally {process.removeListener('SIGTERM',stop);process.removeListener('SIGINT',stop);await context.close();}
}

if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(new URL(import.meta.url).pathname)) {
  let input='';
  for await (const chunk of process.stdin) input+=chunk;
  try {await runConnection(JSON.parse(input));}
  catch(error) {
    const message = String(error?.message||'');
    const errorCode = message.includes('browserType.launch') ? 'chrome_launch_failed'
      : /session expired/i.test(message) ? 'session_expired'
      : /sign-in timed out/i.test(message) ? 'signin_timeout'
      : /window was closed/i.test(message) ? 'login_window_closed'
      : /current layout could not be read/i.test(message) ? 'history_layout_unrecognized'
      : /unsupported provider/i.test(message) ? 'unsupported_provider'
      : /timeout/i.test(message) ? 'timeout'
      : 'sync_failed';
    log('connection_failed','error',{error_class:error?.name||'Error',error_code:errorCode});
    emit({type:'error',message:error.message?.includes('browserType.launch')?'Chrome could not open. Run the app locally with Chrome installed.':String(error.message||'Retailer sync failed').slice(0,400)});
    process.exitCode=1;
  }
}
