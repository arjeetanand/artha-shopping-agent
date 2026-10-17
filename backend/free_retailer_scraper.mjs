import { chromium } from 'playwright';
import { isPublicHttpUrl } from './social_network.mjs';

const mode = process.argv[2] || 'search';
const target = process.argv[3] || '';
const maxResults = Math.min(10, Math.max(1, Number(process.argv[4] || 6) || 6));

if (!target) {
  console.log(JSON.stringify({ success: false, error: 'Missing query or URL' }));
  process.exit(0);
}

const BOT_PATTERN = /enter the characters you see below|validatecaptcha|api-services-support@amazon|recaptcha|access denied|unusual traffic|automated access/i;

function cleanQuery(raw) {
  return String(raw || '')
    .replace(/\bsite:[^\s]+/gi, '')
    .replace(/\bOR\b/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

async function scrapeSearch(page, query) {
  const cleaned = cleanQuery(query);
  if (!cleaned) return { results: [], diagnostics: [] };

  const results = [];
  const diagnostics = [];
  const retrievedAt = new Date().toISOString();

  // 1. Amazon India (amazon.in)
  const amazonSearchUrl = `https://www.amazon.in/s?k=${encodeURIComponent(cleaned)}`;
  try {
    await page.goto(amazonSearchUrl, { waitUntil: 'domcontentloaded', timeout: 15000 });
    await page.waitForTimeout(1200);
    const bodyText = (await page.locator('body').innerText().catch(() => '')).slice(0, 6000);
    if (BOT_PATTERN.test(bodyText)) {
      diagnostics.push({ retailer: 'Amazon India', status: 'bot_challenge', detail: 'Amazon India returned an automated-access check' });
    } else {
      const items = await page.locator('[data-component-type="s-search-result"]').evaluateAll((nodes, ts) => {
        const out = [];
        for (const node of nodes.slice(0, 8)) {
          const asin = node.getAttribute('data-asin') || '';
          const linkEl = node.querySelector('h2 a[href], a.a-link-normal[href*="/dp/"]');
          const titleEl = node.querySelector('h2 span') || linkEl;
          const priceEl = node.querySelector('.a-price .a-offscreen');
          const imgEl = node.querySelector('img.s-image');
          const ratingEl = node.querySelector('span.a-icon-alt');
          const deliveryEl = node.querySelector('[data-cy="delivery-recipe"]');
          const title = (titleEl?.textContent || '').replace(/\s+/g, ' ').trim();
          let href = linkEl?.href || (asin ? `https://www.amazon.in/dp/${asin}` : '');
          if (href && href.includes('/sspa/click')) {
            try {
              const u = new URL(href);
              const embedded = u.searchParams.get('url');
              if (embedded) href = new URL(embedded, 'https://www.amazon.in').href;
            } catch {}
          }
          if (!title || !href || !/amazon\.in/i.test(href)) continue;
          const priceText = (priceEl?.textContent || '').trim();
          const deliveryText = (deliveryEl?.textContent || '').replace(/\s+/g, ' ').trim();
          const ratingText = (ratingEl?.textContent || '').trim();
          out.push({
            title,
            url: href.split('?')[0],
            image: imgEl?.src || '',
            price_text: priceText,
            rating_text: ratingText,
            delivery_text: deliveryText,
            seller: 'Amazon India',
            retrieved_at: ts,
            snippet: [priceText ? `Price ${priceText}` : '', deliveryText, ratingText].filter(Boolean).join(' · '),
          });
        }
        return out;
      }, retrievedAt).catch(() => []);
      results.push(...items.slice(0, Math.ceil(maxResults / 2)));
      diagnostics.push({
        retailer: 'Amazon India',
        status: items.length ? 'ok' : 'empty_or_layout_changed',
        count: items.length,
        retrieved_at: retrievedAt,
      });
    }
  } catch (err) {
    diagnostics.push({ retailer: 'Amazon India', status: 'unavailable', detail: err.message || 'Navigation failed' });
  }

  // Polite rate limit pause before second retailer
  await page.waitForTimeout(400);

  // 2. Flipkart (flipkart.com)
  const flipkartSearchUrl = `https://www.flipkart.com/search?q=${encodeURIComponent(cleaned)}`;
  try {
    await page.goto(flipkartSearchUrl, { waitUntil: 'domcontentloaded', timeout: 15000 });
    await page.waitForTimeout(1200);
    const bodyText = (await page.locator('body').innerText().catch(() => '')).slice(0, 6000);
    if (BOT_PATTERN.test(bodyText)) {
      diagnostics.push({ retailer: 'Flipkart', status: 'bot_challenge', detail: 'Flipkart returned an access challenge' });
    } else {
      const items = await page.locator('[data-id], a[href*="/p/itm"]').evaluateAll((nodes, ts) => {
        const seen = new Set();
        const out = [];
        for (const node of nodes.slice(0, 24)) {
          const anchor = node.tagName === 'A' && node.href?.includes('/p/itm') ? node : node.querySelector('a[href*="/p/itm"]');
          if (!anchor || !anchor.href) continue;
          const cleanUrl = anchor.href.split('?')[0];
          if (seen.has(cleanUrl)) continue;
          seen.add(cleanUrl);
          const container = node.closest('[data-id]') || anchor.parentElement?.parentElement || node;
          const text = (container?.innerText || '').replace(/\s+/g, ' ').trim();
          const img = container?.querySelector('img')?.src || '';
          const titleAttr = anchor.getAttribute('title') || container?.querySelector('a[title]')?.getAttribute('title') || '';
          const lines = (container?.innerText || '').split('\n').map((l) => l.trim()).filter(Boolean);
          const title = titleAttr || lines.find((l) => l.length > 8 && !/^₹|^\d+% off|sponsored|bestseller/i.test(l)) || '';
          const priceMatch = text.match(/₹[\d,]+/);
          if (!title) continue;
          out.push({
            title,
            url: cleanUrl,
            image: img,
            price_text: priceMatch ? priceMatch[0] : '',
            seller: 'Flipkart',
            retrieved_at: ts,
            snippet: [priceMatch ? `Price ${priceMatch[0]}` : '', lines.slice(0, 3).join(' · ')].filter(Boolean).join(' · '),
          });
          if (out.length >= 6) break;
        }
        return out;
      }, retrievedAt).catch(() => []);
      results.push(...items.slice(0, Math.ceil(maxResults / 2)));
      diagnostics.push({
        retailer: 'Flipkart',
        status: items.length ? 'ok' : 'empty_or_layout_changed',
        count: items.length,
        retrieved_at: retrievedAt,
      });
    }
  } catch (err) {
    diagnostics.push({ retailer: 'Flipkart', status: 'unavailable', detail: err.message || 'Navigation failed' });
  }

  return { results: results.slice(0, maxResults), diagnostics, retrieved_at: retrievedAt };
}

async function scrapeProductPage(page, url) {
  if (!(await isPublicHttpUrl(url))) {
    return { success: false, error: 'Non-public product URL blocked' };
  }
  const retrievedAt = new Date().toISOString();
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 18000 });
  await page.waitForTimeout(1200);
  const finalUrl = page.url();
  const bodyText = (await page.locator('body').innerText().catch(() => '')).slice(0, 12000);
  if (BOT_PATTERN.test(bodyText)) {
    return { success: false, bot_challenge: true, error: 'Retailer returned a bot challenge on the product page' };
  }

  const extracted = await page.evaluate((ts) => {
    const scripts = [...document.querySelectorAll('script[type="application/ld+json"]')].slice(0, 30).map((s) => s.outerHTML).join('\n');
    const title = (
      document.querySelector('#productTitle, h1 span, h1')?.textContent ||
      document.title ||
      ''
    ).replace(/\s+/g, ' ').trim();
    const priceEl = document.querySelector(
      '#corePriceDisplay_desktop_feature_div .a-price .a-offscreen, #corePrice_feature_div .a-offscreen, .a-price .a-offscreen, [class*="Nx9bqj"], [class*="_30jeq3"]'
    );
    const priceText = (priceEl?.textContent || '').trim();
    const imgEl = document.querySelector('#landingImage, #imgTagWrapperId img, img[class*="DByuf4"], img[class*="_396cs4"]');
    const image = imgEl?.src || document.querySelector('meta[property="og:image"]')?.getAttribute('content') || '';
    const availEl = document.querySelector('#availability, [id*="availability"]');
    const availabilityText = (availEl?.textContent || '').replace(/\s+/g, ' ').trim();

    // Extract verifiable size options when present on the page
    const sizeNodes = [
      ...document.querySelectorAll('#variation_size_name li, select#native_dropdown_selected_size_name option, [id*="size"] li a, ul[class*="size"] li'),
    ];
    const sizes = [];
    const variants = [];
    const seenSizes = new Set();
    for (const node of sizeNodes) {
      const label = (node.textContent || node.getAttribute('title') || '').replace(/Click to select/i, '').replace(/\s+/g, ' ').trim();
      if (!label || /^select$/i.test(label) || label.length > 16 || seenSizes.has(label.toUpperCase())) continue;
      seenSizes.add(label.toUpperCase());
      const cls = `${node.className || ''} ${node.parentElement?.className || ''}`;
      const unavailable = /unavailable|out-of-stock|disabled/i.test(cls);
      if (!unavailable) sizes.push(label.toUpperCase());
      variants.push({ size: label.toUpperCase(), available: !unavailable });
    }

    return {
      title,
      priceText,
      image,
      availabilityText,
      sizes,
      variants,
      html: scripts,
      retrieved_at: ts,
    };
  }, retrievedAt);

  return {
    success: true,
    finalUrl,
    pageTitle: extracted.title,
    html: extracted.html,
    retrieved_at: retrievedAt,
    generatedJson: {
      data: {
        name: extracted.title,
        pageType: 'productDetail',
        price: extracted.priceText,
        currency: 'INR',
        image: extracted.image,
        sizes: extracted.sizes,
        variants: extracted.variants,
        stock: /out of stock|currently unavailable/i.test(extracted.availabilityText) ? 0 : (/in stock/i.test(extracted.availabilityText) ? 5 : null),
        retrieved_at: retrievedAt,
      },
    },
  };
}

async function main() {
  let browser;
  try {
    try {
      browser = await chromium.launch({ channel: 'chrome', headless: true, chromiumSandbox: true });
    } catch {
      browser = await chromium.launch({ headless: true, chromiumSandbox: true });
    }
    const context = await browser.newContext({
      viewport: { width: 1280, height: 900 },
      locale: 'en-IN',
      timezoneId: 'Asia/Kolkata',
      serviceWorkers: 'block',
    });
    const page = await context.newPage();
    await page.route('**/*', async (route) => {
      if (await isPublicHttpUrl(route.request().url())) return route.continue();
      return route.abort('blockedbyclient');
    });

    if (mode === 'product') {
      const data = await scrapeProductPage(page, target);
      await browser.close();
      console.log(JSON.stringify(data));
      return;
    }

    const data = await scrapeSearch(page, target);
    await browser.close();
    console.log(JSON.stringify({ success: true, ...data }));
  } catch (err) {
    if (browser) await browser.close().catch(() => {});
    console.log(JSON.stringify({ success: false, error: err.message || 'Retailer scrape failed' }));
  }
}

main();
