import { chromium } from 'playwright';
import { copyFile, mkdir } from 'node:fs/promises';
import { existsSync } from 'node:fs';

const demoUrl = process.env.DEMO_URL || 'http://127.0.0.1:5175/';
const outputDir = new URL('../demo/', import.meta.url).pathname;
const outputFile = new URL('../demo/INSPIRA-demo-flow.webm', import.meta.url).pathname;

await mkdir(outputDir, { recursive: true });

const browserCandidates = [
  process.env.CHROME_PATH,
  chromium.executablePath(),
  '/Users/arjeetanand/Library/Caches/ms-playwright/chromium-1228/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing',
  '/Users/arjeetanand/Library/Caches/ms-playwright/chromium-1208/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing',
].filter(Boolean);
const chromePath = browserCandidates.find((candidate) => existsSync(candidate));

if (!chromePath) {
  throw new Error('No local Chrome-for-Testing executable was found.');
}

const browser = await chromium.launch({
  headless: true,
  executablePath: chromePath,
});
const context = await browser.newContext({
  viewport: { width: 1600, height: 900 },
  recordVideo: {
    dir: outputDir,
    size: { width: 1600, height: 900 },
  },
});
const page = await context.newPage();
const video = page.video();

const pause = (milliseconds) => page.waitForTimeout(milliseconds);

await page.goto(demoUrl, { waitUntil: 'domcontentloaded' });
await pause(1800);

// 01 — Start with the inspiration-led shopping brief.
await page.getByRole('button', { name: '✦ Use a demo inspiration' }).click();
await pause(1800);

// 02 — Submit the brief and show the structured AI interpretation.
await page.getByRole('button', { name: 'Build my shortlist' }).click();
await pause(2200);

// 03 — Run search, hard-constraint checks, and ranking.
await page.getByRole('button', { name: 'Search valid options' }).click();
await pause(2800);

// 04 — Select the strongest valid set and review the approval gate.
await page.getByRole('button', { name: 'Select set' }).first().click();
await pause(2200);

// 05 — Explicit approval creates a simulated order only.
await page.getByRole('button', { name: 'Confirm simulated purchase' }).click();
await pause(2400);

// 06 — Open tracking and advance the demo status to show the notification loop.
await page.getByRole('button', { name: 'Open live tracking' }).click();
await pause(2200);
await page.getByRole('button', { name: 'Advance demo status' }).click();
await pause(2200);

await context.close();
const recordedPath = await video.path();
await copyFile(recordedPath, outputFile);
await browser.close();

console.log(JSON.stringify({ outputFile, recordedPath }));
