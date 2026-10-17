import { parseFlipkartOrderPage, parseOrderEvidence } from './retailer_extract.mjs';

let input = '';
for await (const chunk of process.stdin) input += chunk;
try {
  const { provider, pages } = JSON.parse(input);
  if (!Array.isArray(pages) || !['amazon', 'flipkart', 'myntra', 'ajio'].includes(provider)) throw new Error('invalid_batch');
  const parsed = provider === 'flipkart'
    ? pages.map(parseFlipkartOrderPage)
    : pages.map((page) => {
      if (!page || !Array.isArray(page.orders)) return { error: 'history_page_unreadable', orders: [], errors: ['history_page_unreadable'] };
      const orders = [], errors = [];
      for (const snapshot of page.orders) {
        try {
          const order = parseOrderEvidence(snapshot, provider);
          if (order.error) errors.push(order.error);
          else orders.push(order);
        } catch { errors.push('order_unreadable'); }
      }
      return { orders, orderCount: page.orders.length, moreOrder: null, errors };
    });
  process.stdout.write(JSON.stringify(parsed));
} catch {
  process.stderr.write('retailer_page_parse_failed');
  process.exitCode = 1;
}
