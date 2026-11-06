#!/usr/bin/env node
// Development-only renderer. Requires Playwright and a local Chrome installation.
// NODE_PATH may point at an existing Playwright installation. No network service is started.
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { pathToFileURL } = require('node:url');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '..');
(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1600, height: 720 }, deviceScaleFactor: 1 });
    await page.route(/^(https?|wss?):/, route => route.abort());
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(pathToFileURL(path.join(root, 'docs/images/cover.html')).href);
    await page.evaluate(() => document.fonts.ready);
    const cdp = await page.context().newCDPSession(page);
    await cdp.send('DOM.enable');
    await cdp.send('CSS.enable');
    const { root: dom } = await cdp.send('DOM.getDocument');
    const { nodeId } = await cdp.send('DOM.querySelector', { nodeId: dom.nodeId, selector: 'h1' });
    const { fonts } = await cdp.send('CSS.getPlatformFontsForNode', { nodeId });
    const renderedFonts = fonts.map(font => ({ family: font.familyName, glyphCount: font.glyphCount, custom: font.isCustomFont }));
    const cover = await page.evaluate(() => {
      const bounds = document.querySelector('.cover').getBoundingClientRect();
      const overflow = [...document.querySelectorAll('[data-qa-text]')].filter(el => {
        const r = el.getBoundingClientRect();
        return r.left < bounds.left || r.top < bounds.top || r.right > bounds.right || r.bottom > bounds.bottom || el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1;
      }).map(el => el.textContent.trim());
      return { imagesLoaded: [...document.images].every(img => img.complete && img.naturalWidth > 0), width: bounds.width, height: bounds.height, horizontalOverflow: document.documentElement.scrollWidth > innerWidth, textOverflow: overflow, localChineseFont: document.fonts.check('24px "PingFang SC"') };
    });
    cover.renderedFonts = renderedFonts;
    if (!cover.imagesLoaded || cover.horizontalOverflow || cover.textOverflow.length || errors.length) throw Error('Cover overflow or JavaScript error: ' + JSON.stringify({cover, errors}));
    await page.screenshot({ path: path.join(root, 'docs/images/cover.png') });
    await page.setViewportSize({ width: 512, height: 512 });
    const icon = fs.readFileSync(path.join(root, 'skills/lan-file-share-assistant/assets/icon.svg'), 'utf8');
    await page.setContent('<html><body style="margin:0;background:transparent">' + icon + '</body></html>');
    await page.locator('svg').screenshot({ path: path.join(root, 'skills/lan-file-share-assistant/assets/icon-512.png'), omitBackground: true });
    await page.setViewportSize({ width: 1600, height: 440 });
    await page.goto(pathToFileURL(path.join(root, 'docs/images/workflow.svg')).href);
    await page.evaluate(() => document.fonts.ready);
    const workflow = await page.evaluate(() => {
      const svg = document.documentElement;
      const overlaps = [];
      const items = [...svg.querySelectorAll('text')].map(el => ({ text: el.textContent, ...(() => { const b = el.getBBox(); return { x: b.x, y: b.y, width: b.width, height: b.height }; })() }));
      for (const item of items) if (item.x < 0 || item.y < 0 || item.x + item.width > 1600 || item.y + item.height > 440) overlaps.push(item.text);
      for (let i = 0; i < 7; i++) {
        const title = items[2 + i * 3 + 1];
        const subtitle = items[2 + i * 3 + 2];
        const right = 76 + i * 207 + 188 - 12;
        if (title.x + title.width > right || subtitle.x + subtitle.width > right) overlaps.push('card-' + (i + 1));
      }
      return { width: 1600, height: 440, steps: 7, textOverflow: overlaps };
    });
    if (workflow.textOverflow.length) throw Error('Workflow text overflow: ' + workflow.textOverflow.join(', '));
    const workflowPreview = path.join(os.tmpdir(), 'lan-file-share-workflow-preview.png');
    await page.screenshot({ path: workflowPreview });
    await page.goto('about:blank');
    await page.setViewportSize({ width: 32, height: 32 });
    await page.setContent('<html><body style="margin:0;background:transparent">' + icon.replace('width="512" height="512"', 'width="32" height="32"') + '</body></html>');
    const smallIconPreview = path.join(os.tmpdir(), 'lan-file-share-icon-32-preview.png');
    await page.screenshot({ path: smallIconPreview, omitBackground: true });
    console.log(JSON.stringify({ cover, icon: { width: 512, height: 512 }, workflow, workflowPreview, smallIconPreview, javascriptErrors: errors.length }, null, 2));
  } finally { await browser.close(); }
})().catch(error => { console.error(error.message); process.exit(1); });
