import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import test from 'node:test';

test('Flipkart page bridge forwards only order fields needed by the importer', async () => {
  const posted = [];
  const payload = {
    SESSION: { secureToken: 'must-not-leave-the-tab' },
    RESPONSE: { customerDetails: { phone: 'must-not-leave-the-tab' }, multipleOrderDetailsView: {
      moreOrder: false,
      orders: [{
        orderMetaData: { orderId: 'OD12345678901234567890', orderDate: 1792195200000 },
        productDataBag: { LISTING: {
          productBasicData: { title: 'Blue linen shirt', url: '/shirt/p/itm12345', privateData: 'discard' },
          productAttribute: { storePath: '/shirt/p/itm12345', brand: 'Example', size: 'L', color: 'Blue', privateData: 'discard' },
        } },
        units: { UNIT: { metaData: { listingId: 'LISTING', quantity: 1, status: { key: 'Delivered', privateData: 'discard' } }, moneyDataBag: { amount: 1299 } } },
        orderMoneyDataBag: { amount: 1299 }, address: 'must-not-leave-the-tab',
      }],
    } },
  };
  const window = {
    fetch: async () => ({ ok: true, clone: () => ({ json: async () => payload }) }),
    postMessage: (message) => posted.push(message),
  };
  class XMLHttpRequest { open() {} send() {} }
  vm.runInNewContext(await readFile(new URL('../extension/flipkart_main.js', import.meta.url), 'utf8'), {
    window, location: { origin: 'https://www.flipkart.com', href: 'https://www.flipkart.com/account/orders' },
    URL, XMLHttpRequest,
  });
  await window.fetch('/api/1/self-serve/orders?view=all');
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(posted.length, 1);
  const forwarded = posted[0].payload;
  assert.equal(forwarded.RESPONSE.multipleOrderDetailsView.orders[0].orderMetaData.orderId, 'OD12345678901234567890');
  assert.equal(forwarded.RESPONSE.multipleOrderDetailsView.orders[0].productDataBag.LISTING.productBasicData.title, 'Blue linen shirt');
  assert.equal(JSON.stringify(forwarded).includes('must-not-leave-the-tab'), false);
  assert.equal(JSON.stringify(forwarded).includes('privateData'), false);
});
