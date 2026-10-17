import { chromium } from 'playwright';
import { isPublicHttpUrl } from './social_network.mjs';

const url = process.argv[2];
const productMode = process.argv.includes('--product');
const profileDir = process.argv[3] === '--product' ? null : process.argv[3];
if (!url) {
  console.log(JSON.stringify({ success: false, error: 'No URL provided' }));
  process.exit(0);
}

async function scrape() {
  let browser;
  try {
    const contextOptions = {
      viewport: { width: 1080, height: 1080 },
      serviceWorkers: 'block',
    };
    let context;
    if (profileDir) {
      context = await chromium.launchPersistentContext(profileDir,{channel:'chrome',headless:true,...contextOptions});
      browser = context;
    } else {
      try {
        browser = await chromium.launch({ channel: 'chrome', headless: true, chromiumSandbox: true });
      } catch {
        browser = await chromium.launch({ headless: true, chromiumSandbox: true });
      }
      context = await browser.newContext(contextOptions);
    }

    const page = await context.newPage();
    let blockedNavigation = false;
    // shortcut: DNS checks can race Chromium resolution; add IP pinning or an egress proxy before public deployment.
    await page.route('**/*', async (route) => {
      if (await isPublicHttpUrl(route.request().url())) return route.continue();
      if (route.request().isNavigationRequest()) blockedNavigation = true;
      return route.abort('blockedbyclient');
    });
    
    let pageTitle = '';
    let metaDescription = '';
    let ogImage = '';

    try {
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 15000 });
      // Wait a brief moment for images/hydration
      await page.waitForTimeout(2000);
      pageTitle = await page.title().catch(() => '');
      
      const meta = await page.evaluate(() => {
        const getMeta = (name) => {
          const el = document.querySelector(`meta[name="${name}"], meta[property="${name}"]`);
          return el ? el.getAttribute('content') || '' : '';
        };
        return {
          description: getMeta('description') || getMeta('og:description') || getMeta('twitter:description'),
          ogImage: getMeta('og:image') || getMeta('twitter:image'),
          ogTitle: getMeta('og:title') || getMeta('twitter:title'),
        };
      }).catch(() => ({ description: '', ogImage: '', ogTitle: '' }));

      metaDescription = meta.description || '';
      ogImage = meta.ogImage || '';
      if (!pageTitle && meta.ogTitle) pageTitle = meta.ogTitle;
    } catch (navErr) {
      // Continue even if navigation had partial timeouts, screenshot whatever was loaded
    }

    const screenshotBuffer = productMode ? null : await page.screenshot({ type: 'jpeg', quality: 75 }).catch(() => null);
    const html = productMode ? await page.locator('script[type="application/ld+json"]').evaluateAll(
      scripts => scripts.slice(0, 50).map(script => script.outerHTML).join('\n').slice(0, 2_000_000),
    ).catch(() => '') : '';
    const finalUrl = page.url();
    const pageText = (await page.locator('body').innerText().catch(()=>'')).slice(0,12000);
    const requiresLogin = /instagram\.com\/accounts\/login/i.test(finalUrl)
      || (/instagram\.com/i.test(finalUrl) && (/log in to (?:see|continue)|login to continue/i.test(pageText)
          || (!ogImage && /log in|sign up/i.test(pageText))));
    const blocked = /access denied|verify you are human|unusual traffic/i.test(pageText);

    await browser.close();

    if (requiresLogin) {
      console.log(JSON.stringify({success:false,requires_login:true}));
      return;
    }
    if ((!productMode && !screenshotBuffer) || blockedNavigation || finalUrl === 'about:blank' || blocked) {
      console.log(JSON.stringify({
        success: false,
        error: blockedNavigation ? 'Navigation to a non-public destination was blocked' : 'Could not capture screenshot',
        title: pageTitle,
        description: metaDescription,
      }));
      return;
    }

    if (productMode) {
      console.log(JSON.stringify({success: true, title: pageTitle, description: metaDescription, finalUrl, html}));
      return;
    }

    console.log(JSON.stringify({
      success: true,
      title: pageTitle,
      description: metaDescription,
      og_image: ogImage,
      screenshot_base64: screenshotBuffer.toString('base64'),
      mime_type: 'image/jpeg',
    }));
  } catch (err) {
    if (browser) await browser.close().catch(() => {});
    console.log(JSON.stringify({
      success: false,
      error: err.message || 'Scrape failed',
    }));
  }
}

scrape();
