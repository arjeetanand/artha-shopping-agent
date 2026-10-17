import { chromium } from 'playwright';
import { isPublicHttpUrl } from './social_network.mjs';

const targetUrl = process.argv[2];
const profileDir = process.argv[3] && !process.argv[3].startsWith('--') ? process.argv[3] : null;
const maxPostsArg = process.argv.find((arg) => arg.startsWith('--max='));
const maxPosts = Math.min(5, Math.max(1, Number(maxPostsArg ? maxPostsArg.split('=')[1] : 5) || 5));

if (!targetUrl) {
  console.log(JSON.stringify({ success: false, error: 'No Instagram URL provided' }));
  process.exit(0);
}

async function scrapeInstagram() {
  let browser;
  let context;
  try {
    if (!(await isPublicHttpUrl(targetUrl))) {
      console.log(JSON.stringify({ success: false, error: 'Reference URLs must resolve to public addresses' }));
      return;
    }
    const contextOptions = {
      viewport: { width: 1080, height: 1080 },
      serviceWorkers: 'block',
      locale: 'en-IN',
      timezoneId: 'Asia/Kolkata',
    };
    if (profileDir) {
      try {
        context = await chromium.launchPersistentContext(profileDir, { channel: 'chrome', headless: true, ...contextOptions });
      } catch {
        context = await chromium.launchPersistentContext(profileDir, { headless: true, ...contextOptions });
      }
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
    await page.route('**/*', async (route) => {
      if (await isPublicHttpUrl(route.request().url())) return route.continue();
      if (route.request().isNavigationRequest()) blockedNavigation = true;
      return route.abort('blockedbyclient');
    });

    await page.goto(targetUrl, { waitUntil: 'domcontentloaded', timeout: 20000 }).catch(() => {});
    await page.waitForTimeout(2200);

    const finalUrl = page.url();
    const pageTitle = await page.title().catch(() => '');
    const bodyText = (await page.locator('body').innerText().catch(() => '')).slice(0, 16000);

    if (blockedNavigation || finalUrl === 'about:blank') {
      await browser.close();
      console.log(JSON.stringify({ success: false, error: 'Navigation to a non-public destination was blocked' }));
      return;
    }

    const isLoginWall = /instagram\.com\/accounts\/login/i.test(finalUrl)
      || (/log in to instagram|log in to continue|sign up to see photos/i.test(bodyText) && !/posts\b/i.test(bodyText));
    const isPrivate = /this account is private/i.test(bodyText);
    const isUnavailable = /sorry, this page isn't available|page not found/i.test(bodyText);

    if (isPrivate) {
      await browser.close();
      console.log(JSON.stringify({
        success: false,
        private_account: true,
        error: 'This Instagram profile is private and not accessible in the current session.',
      }));
      return;
    }

    if (isUnavailable) {
      await browser.close();
      console.log(JSON.stringify({
        success: false,
        not_found: true,
        error: 'This Instagram profile or post could not be found.',
      }));
      return;
    }

    const parsedTarget = new URL(targetUrl);
    const isSinglePost = /^\/(p|reel|tv)\/[^/]+/i.test(parsedTarget.pathname);

    let postLinks = [];
    if (isSinglePost) {
      postLinks = [targetUrl];
    } else {
      postLinks = await page.locator('a[href*="/p/"], a[href*="/reel/"]').evaluateAll((anchors) => {
        const seen = new Set();
        const urls = [];
        for (const a of anchors) {
          const href = a.href;
          if (!href || seen.has(href)) continue;
          seen.add(href);
          urls.push(href);
        }
        return urls;
      }).catch(() => []);
    }

    if (!postLinks.length) {
      if (isLoginWall) {
        await browser.close();
        console.log(JSON.stringify({
          success: false,
          requires_login: true,
          error: 'Instagram required login to view posts on this profile. Connect Instagram in Taste OS, paste a direct public post link, or upload a screenshot.',
        }));
        return;
      }
      await browser.close();
      console.log(JSON.stringify({
        success: false,
        error: 'No accessible posts were found on this Instagram page.',
      }));
      return;
    }

    const selectedUrls = postLinks.slice(0, maxPosts);
    const posts = [];

    for (const postUrl of selectedUrls) {
      try {
        if (!isSinglePost || postUrl !== targetUrl) {
          await page.goto(postUrl, { waitUntil: 'domcontentloaded', timeout: 15000 }).catch(() => {});
          await page.waitForTimeout(1500);
        }
        const currentUrl = page.url();
        const postText = (await page.locator('body').innerText().catch(() => '')).slice(0, 8000);
        if (/instagram\.com\/accounts\/login/i.test(currentUrl)) {
          continue;
        }
        const meta = await page.evaluate(() => {
          const getMeta = (name) => {
            const el = document.querySelector(`meta[name="${name}"], meta[property="${name}"]`);
            return el ? el.getAttribute('content') || '' : '';
          };
          return {
            title: document.title || getMeta('og:title') || '',
            description: getMeta('og:description') || getMeta('description') || '',
            ogImage: getMeta('og:image') || '',
          };
        }).catch(() => ({ title: '', description: '', ogImage: '' }));

        const articleLocator = page.locator('article').first();
        let screenshotBuffer = null;
        if (await articleLocator.count().catch(() => 0)) {
          screenshotBuffer = await articleLocator.screenshot({ type: 'jpeg', quality: 80 }).catch(() => null);
        }
        if (!screenshotBuffer) {
          screenshotBuffer = await page.screenshot({ type: 'jpeg', quality: 75 }).catch(() => null);
        }
        if (!screenshotBuffer) continue;

        const shortcodeMatch = postUrl.match(/\/(?:p|reel|tv)\/([A-Za-z0-9_-]+)/i);
        posts.push({
          post_url: postUrl,
          shortcode: shortcodeMatch ? shortcodeMatch[1] : '',
          caption: (meta.description || meta.title || postText.slice(0, 400)).trim(),
          og_image: meta.ogImage || '',
          captured_at: new Date().toISOString(),
          screenshot_base64: screenshotBuffer.toString('base64'),
          mime_type: 'image/jpeg',
        });
      } catch {
        // Skip individual unreadable post without fabricating a screenshot
      }
    }

    await browser.close();

    if (!posts.length) {
      console.log(JSON.stringify({
        success: false,
        requires_login: isLoginWall,
        error: isLoginWall
          ? 'Instagram required login before any post screenshots could be captured.'
          : 'Could not capture screenshots from the Instagram posts.',
      }));
      return;
    }

    console.log(JSON.stringify({
      success: true,
      profile_title: pageTitle,
      posts,
    }));
  } catch (err) {
    if (browser) await browser.close().catch(() => {});
    console.log(JSON.stringify({
      success: false,
      error: err.message || 'Instagram scrape failed',
    }));
  }
}

scrapeInstagram();
