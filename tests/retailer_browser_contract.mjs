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

test('Flipkart sync reads all pages and unit invoices without duplicating orders or PDFs', async () => {
  const {mkdtemp,readFile,readdir,rm}=await import('node:fs/promises');
  const {tmpdir}=await import('node:os');
  const path=await import('node:path');
  const {readHistory}=await import('../backend/retailer_browser.mjs');
  const directory=await mkdtemp(path.join(tmpdir(),'artha-flipkart-test-'));
  const browser=await chromium.launch({channel:'chrome',headless:true});
  const events=[], detailVisits=[], invoiceRequests=[];
  const originalWrite=process.stdout.write;
  const record=(id,date)=>({
    orderMetaData:{orderId:id,orderDate:Date.parse(date)},
    orderMoneyDataBag:{amount:1299.75},
    productDataBag:{LISTING:{productBasicData:{title:'Blue linen shirt'},productAttribute:{storePath:'/shirt/p/itm12345',size:'S'}}},
    units:{UNIT:{metaData:{listingId:'LISTING',fsn:'DIFFERENT_FSN',quantity:1,status:{key:'Delivered'}},moneyDataBag:{amount:1299.75}}},
  });
  const recent=record('OD123456789012345678','2026-10-01T12:00:00Z');
  recent.units.UNIT2={...recent.units.UNIT};
  recent.units.UNIT3={...recent.units.UNIT};
  const boundary=record('OD223456789012345678','2026-04-16T20:00:00Z');
  boundary.units.UNIT2={...boundary.units.UNIT};
  const old=record('OD323456789012345678','2026-04-15T12:00:00Z');
  const future=record('OD423456789012345678','2026-10-18T12:00:00Z');
  try {
    const context=await browser.newContext({acceptDownloads:true});
    context.on('page',page=>page.on('pageerror',error=>events.push({type:'pageerror',message:error.message})));
    test.mock.method(context.request,'get',async(url,options)=>{
      assert.match(url,/^https:\/\/www\.flipkart\.com\/api\/1\/self-serve\/invoice\/download\/OD\d+$/);
      assert.equal(options.maxRedirects,0);
      assert.equal(options.headers['X-User-Agent'],'fixture-agent');
      invoiceRequests.push(url);
      if(url.endsWith(boundary.orderMetaData.orderId)) return {ok:()=>false,status:()=>403,headers:()=>({})};
      const pdf=Buffer.from('%PDF-1.4\nfixture invoice '+url);
      return {ok:()=>true,status:()=>200,headers:()=>({'content-type':'application/pdf'}),body:async()=>pdf};
    });
    await context.route('**/*', async route=>{
      const url=new URL(route.request().url());
      if(url.pathname==='/api/5/self-serve/orders/') {
        const second=url.searchParams.get('page')==='2';
        return route.fulfill({json:{SESSION:{secureToken:'private-session-must-not-be-emitted'},RESPONSE:{multipleOrderDetailsView:{orders:second?[recent,boundary,old,future]:[recent],moreOrder:!second}}}});
      }
      if(url.pathname==='/account/orders') return route.fulfill({contentType:'text/html',body:`<body><main id="orders"></main><button id="more">Load More</button><script>
        let page=1;
        async function load(){const data=await (await fetch('/api/5/self-serve/orders/?page='+page,{headers:{'X-User-Agent':'fixture-agent'}})).json();
          document.querySelector('main').innerHTML+=data.RESPONSE.multipleOrderDetailsView.orders.map(o=>'<a href="/order_details?order_id='+o.orderMetaData.orderId+'&unit_id=1">Blue linen shirt Order Confirmed, Oct 01</a>').join('');
          if(page===1)document.querySelector('main').innerHTML+='<a href="/order_details?order_id=OD123456789012345678&unit_id=2">Second unit</a><a href="/order_details?order_id=OD123456789012345678&unit_id=3">Third unit</a>';
          if(page===2)document.querySelector('main').innerHTML+='<a href="/order_details?order_id=OD223456789012345678&unit_id=2">Second unit with unavailable invoice</a>';
          if(!data.RESPONSE.multipleOrderDetailsView.moreOrder)document.querySelector('button').remove();
        }
        document.querySelector('button').onclick=()=>{page++;load()};load();
      </script>`});
      if(url.pathname==='/order_details') {
        detailVisits.push(url.searchParams.get('order_id'));
        return route.fulfill({contentType:'text/html',body:`<body><h1>Blue linen shirt</h1><p>Order Confirmed, Oct 01</p>
          <button aria-expanded="false" onclick="this.setAttribute('aria-expanded','true');document.querySelector('#invoice').hidden=false">Price details Paid ₹1,299.75</button>
          <div id="invoice" hidden onclick="throw new Error('Native download UI must not be used')">Download Invoice</div>`});
      }
      return route.abort();
    });
    const page=await context.newPage();
    process.stdout.write=function(chunk,...args){
      if(typeof chunk==='string'&&chunk.startsWith('{')) {events.push(JSON.parse(chunk));return true;}
      return originalWrite.call(this,chunk,...args);
    };
    await readHistory(context,page,{provider:'flipkart',cutoff:'2026-04-17',until:'2026-10-17',invoice_dir:directory});
    const orders=events.filter(e=>e.type==='order').map(e=>e.order);
    assert.deepEqual(orders.map(o=>o.id),[recent.orderMetaData.orderId,boundary.orderMetaData.orderId]);
    assert.equal(orders[0].items.length,3);
    assert.equal(orders[1].order_date,'2026-04-17');
    assert.deepEqual(orders.map(o=>o.invoice_status),['downloaded','unavailable']);
    assert.equal(detailVisits.filter(id=>id===recent.orderMetaData.orderId).length,1);
    assert.equal(detailVisits.filter(id=>id===boundary.orderMetaData.orderId).length,1);
    assert.ok(!detailVisits.includes(old.orderMetaData.orderId));
    assert.ok(!detailVisits.includes(future.orderMetaData.orderId));
    const complete=events.find(e=>e.type==='complete');
    assert.equal(complete.orders,2);
    assert.equal(complete.invoices,1);
    assert.equal(complete.missing_invoices,1);
    assert.equal(complete.coverage_complete,true);
    assert.equal(complete.pages,2);
    assert.equal(invoiceRequests.length,2);
    assert.equal(invoiceRequests.filter(url=>url.endsWith(recent.orderMetaData.orderId)).length,1);
    assert.equal(invoiceRequests.filter(url=>url.endsWith(boundary.orderMetaData.orderId)).length,1);
    assert.ok(!events.some(e=>e.type==='pageerror'));
    assert.doesNotMatch(JSON.stringify(events),/private-session|SESSION|secureToken/);
    const files=await readdir(directory);
    assert.equal(files.length,1);
    assert.ok((await readFile(path.join(directory,files[0]))).subarray(0,5).equals(Buffer.from('%PDF-')));
  } finally {
    process.stdout.write=originalWrite;
    await browser.close();
    await rm(directory,{recursive:true,force:true});
  }
});

test('Flipkart never claims complete coverage when the API has more pages or unreadable records', async () => {
  const {readHistory}=await import('../backend/retailer_browser.mjs');
  const browser=await chromium.launch({channel:'chrome',headless:true});
  const originalWrite=process.stdout.write;
  const oldOrder={
    orderMetaData:{orderId:'OD123456789012345678',orderDate:Date.UTC(2026,0,1)},
    productDataBag:{LISTING:{productBasicData:{title:'Blue linen shirt'},productAttribute:{storePath:'/shirt/p/itm12345'}}},
    units:{UNIT:{metaData:{listingId:'LISTING'}}},
  };
  try {
    for(const view of [
      {orders:[oldOrder],moreOrder:true},
      {orders:[oldOrder]},
      {orders:[oldOrder,{...oldOrder,orderMetaData:{orderId:'OD223456789012345678'}}],moreOrder:false},
      {orders:[],moreOrder:false},
    ]) {
      const context=await browser.newContext();
      const events=[];
      await context.route('**/*',route=>new URL(route.request().url()).pathname.includes('/api/')
        ? route.fulfill({json:{RESPONSE:{multipleOrderDetailsView:view}}})
        : route.fulfill({contentType:'text/html',body:'<body>Order history<script>fetch("/api/5/self-serve/orders/?page=1")</script>'}));
      process.stdout.write=function(chunk,...args){
        if(typeof chunk==='string'&&chunk.startsWith('{')) {events.push(JSON.parse(chunk));return true;}
        return originalWrite.call(this,chunk,...args);
      };
      const page=await context.newPage();
      await readHistory(context,page,{provider:'flipkart',cutoff:'2026-04-17',until:'2026-10-17',invoice_dir:'/unused'});
      const complete=events.find(e=>e.type==='complete');
      assert.equal(complete.orders,0);
      assert.equal(complete.coverage_complete,view.orders.length===0);
      if(view.orders.length===2) assert.equal(complete.missing_dates,1);
      assert.equal(context.listenerCount('response'),0);
      await context.close();
    }
  } finally {process.stdout.write=originalWrite;await browser.close();}
});
