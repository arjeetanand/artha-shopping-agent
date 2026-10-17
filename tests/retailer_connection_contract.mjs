import assert from 'node:assert/strict';
import test from 'node:test';
import { RETAILERS, parseFlipkartOrder, parseFlipkartOrderPage, parseOrderDate, parseOrderEvidence, parseMoney, retailerUrl, historyUrls } from '../backend/retailer_extract.mjs';

test('retailer evidence preserves money, order date and multiple items', () => {
  const order=parseOrderEvidence({
    url:'https://www.amazon.in/gp/your-account/order-details?orderID=111-1234567-1234567',
    text:'Order placed\n17 October 2026\nOrder Total: ₹2,399.75\nDelivered',
    products:[{name:'Blue linen shirt',url:'https://www.amazon.in/dp/ABCDEFGHIJ',text:'Size: L\nColor: Blue',price:'₹1,299.50'},
              {name:'White cotton shirt',url:'https://www.amazon.in/dp/KLMNOPQRST',text:'Size: M',price:'₹1,100.25'}],
  },'amazon');
  assert.equal(order.total,2399.75);
  assert.equal(order.order_date,'2026-10-17');
  assert.equal(order.items.length,2);
  assert.equal(order.items[0].size,'L');
  assert.equal(order.items[0].price,1299.50);
  assert.equal(order.evidence_hash.length,64);
});

test('a delivery date cannot silently become the order date',()=>{
  const order=parseOrderEvidence({url:'https://www.flipkart.com/order_details?order_id=OD1234567890123',
    text:'Delivered on 17 October 2026',products:[]},'flipkart');
  assert.equal(order.error,'order_date_missing');
});

test('Flipkart API evidence normalizes its timestamp, product attributes, and INR amounts',()=>{
  const order=parseFlipkartOrder({
    orderMetaData:{orderId:'OD12345678901234567890',orderDate:Date.UTC(2026,9,17)},
    orderMoneyDataBag:{amountValueMultiCurrency:[{currency:'INR',inrValue:2399.75}]},
    productDataBag:{FSN123:{productBasicData:{title:'Blue linen shirt'},productAttribute:{
      storePath:'/blue-linen-shirt/p/itm12345',brand:'Example',size:'L',color:'Blue',
    }}},
    units:{UNIT123:{metaData:{fsn:'FSN123',quantity:1,status:{key:'Delivered'}},moneyDataBag:{
      amountValueMultiCurrency:[{currency:'INR',inrValue:2399.75}],
    }}},
  });
  assert.equal(order.id,'OD12345678901234567890');
  assert.equal(order.order_date,'2026-10-17');
  assert.equal(order.total,2399.75);
  assert.equal(order.items.length,1);
  assert.equal(order.items[0].name,'Blue linen shirt');
  assert.equal(order.items[0].url,'https://www.flipkart.com/blue-linen-shirt/p/itm12345');
  assert.equal(order.items[0].brand,'Example');
  assert.equal(order.items[0].size,'L');
  assert.equal(order.items[0].color,'Blue');
  assert.equal(order.items[0].price,2399.75);
  assert.equal(order.status,'delivered');
  assert.equal(order.evidence_hash.length,64);
});

test('Flipkart API evidence rejects missing dates and unmapped products',()=>{
  const base={orderMetaData:{orderId:'OD12345678901234567890'},units:{}};
  assert.equal(parseFlipkartOrder(base).error,'order_date_missing');
  for (const orderDate of [null, '', 0, -1, 'invalid']) {
    assert.equal(parseFlipkartOrder({...base,orderMetaData:{...base.orderMetaData,orderDate}}).error,'order_date_missing');
  }
  assert.equal(parseFlipkartOrder({...base,orderMetaData:{...base.orderMetaData,orderDate:Date.UTC(2026,9,17)}}).error,'order_items_missing');
});

test('Flipkart joins products by listing ID and uses the purchase day in India',()=>{
  const order=parseFlipkartOrder({
    orderMetaData:{orderId:'OD12345678901234567890',orderDate:Date.UTC(2026,9,16,20)},
    productDataBag:{LISTING123:{productBasicData:{title:'Blue linen shirt'},productAttribute:{storePath:'/shirt/p/itm12345'}}},
    units:{UNIT123:{metaData:{listingId:'LISTING123',fsn:'FSN123',quantity:1}}},
  });
  assert.equal(order.error,undefined);
  assert.equal(order.order_date,'2026-10-17');
  assert.equal(order.items.length,1);
  assert.equal(order.total,null);
  assert.equal(order.items[0].price,null);
});

test('Flipkart API page parser ignores session fields and preserves pagination state',()=>{
  const result=parseFlipkartOrderPage({
    SESSION:{secureToken:'must not be returned'},
    RESPONSE:{multipleOrderDetailsView:{orders:[{
      orderMetaData:{orderId:'OD12345678901234567890',orderDate:Date.UTC(2026,9,17)},
      productDataBag:{FSN123:{productBasicData:{title:'Blue linen shirt'},productAttribute:{storePath:'/shirt/p/itm12345'}}},
      units:{UNIT123:{metaData:{fsn:'FSN123',quantity:1}}},
    }],moreOrder:true}},
  });
  assert.equal(result.orderCount,1);
  assert.equal(result.moreOrder,true);
  assert.equal(result.orders.length,1);
  assert.equal(result.orders[0].id,'OD12345678901234567890');
  assert.equal(Object.hasOwn(result,'session'),false);
  assert.equal(parseFlipkartOrderPage({RESPONSE:{}}).error,'orders_payload_missing');
  assert.equal(parseFlipkartOrderPage({RESPONSE:{multipleOrderDetailsView:{orders:[]}}}).moreOrder,null);
});

test('unknown totals stay unknown and invalid dates are rejected',()=>{
  assert.equal(parseMoney('Price unavailable'),null);
  assert.equal(parseOrderDate('31 February 2026'),null);
  assert.equal(parseOrderDate('Oct 17, 2026'),'2026-10-17');
  assert.equal(parseOrderDate('17/10/2026'),'2026-10-17');
});

test('order detail navigation cannot leave the selected retailer',()=>{
  assert.equal(retailerUrl('https://www.amazon.in.evil.example/orders','amazon'),false);
  assert.equal(retailerUrl('http://www.amazon.in/orders','amazon'),false);
  assert.throws(()=>parseOrderEvidence({url:'https://evil.example/orders',text:''},'amazon'));
});

test('six-month Amazon history crosses year boundaries without relying on a three-month default',()=>{
  assert.deepEqual(historyUrls('amazon','2026-08-31','2027-02-28'),[
    'https://www.amazon.in/gp/your-account/order-history?orderFilter=year-2027',
    'https://www.amazon.in/gp/your-account/order-history?orderFilter=year-2026',
  ]);
});

test('Flipkart, Myntra and Ajio order snapshots normalize to verified history',()=>{
  const fixtures={
    flipkart:{url:'https://www.flipkart.com/order_details?order_id=OD1234567890123',
      text:'Order placed: 17 October 2026\nOrder Total: ₹2,399.75\nDelivered',
      product:{name:'Blue linen shirt',url:'https://www.flipkart.com/linen-shirt/p/itm12345',text:'Size: L\nColor: Blue',price:'₹2,399.75'}},
    myntra:{url:'https://www.myntra.com/my/orders/MYN123456789',
      text:'Order placed: 17 October 2026\nTotal paid: ₹1,599.00\nDelivered',
      product:{name:'Olive cotton shirt',url:'https://www.myntra.com/olive-shirt/abc123/buy',text:'Size: M\nColor: Olive',price:'₹1,599.00'}},
    ajio:{url:'https://www.ajio.com/my-account/orders?orderCode=AJIO123456',
      text:'Order placed: 17 October 2026\nGrand total: ₹999.00\nShipped',
      product:{name:'Black casual shirt',url:'https://www.ajio.com/black-shirt/p/123456789',text:'Size: S\nColour: Black',price:'₹999.00'}},
  };
  for(const [provider,fixture] of Object.entries(fixtures)){
    assert.equal(historyUrls(provider,'2026-04-17','2026-10-17')[0],RETAILERS[provider].orders);
    const order=parseOrderEvidence({...fixture,products:[fixture.product]},provider);
    assert.equal(order.error,undefined,provider);
    assert.equal(order.order_date,'2026-10-17',provider);
    assert.equal(order.items.length,1,provider);
    assert.equal(order.items[0].size,provider==='myntra'?'M':provider==='ajio'?'S':'L',provider);
    assert.equal(order.items[0].color,provider==='myntra'?'Olive':provider==='ajio'?'Black':'Blue',provider);
    assert.equal(order.currency,'INR',provider);
  }
});
