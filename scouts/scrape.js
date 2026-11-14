// Puppeteer scraper that runs inside the Daytona sandbox (see scouts/daytona_fetch.py).
// Usage: node scrape.js <url> [item-url-regex]
// Prints one JSON line: {ok, url, title, text, images, items:[{url,title,text}]}
const puppeteer = require('puppeteer-core');

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const [url, itemPattern] = process.argv.slice(2);
  let browser;
  try {
    browser = await puppeteer.launch({
      executablePath: process.env.CHROME_PATH || '/usr/bin/chromium',
      headless: true,
      args: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu', '--lang=ja-JP'],
    });
    const page = await browser.newPage();
    await page.setUserAgent(
      'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) ' +
        'Chrome/124.0.0.0 Safari/537.36'
    );
    await page.setExtraHTTPHeaders({ 'Accept-Language': 'ja-JP,ja;q=0.9,en;q=0.8' });
    await page.setViewport({ width: 1366, height: 900 });
    await page.goto(url, { waitUntil: 'networkidle2', timeout: 45000 });
    await sleep(1500);
    await page.evaluate(() => window.scrollBy(0, 2500));
    await sleep(1000);

    const data = await page.evaluate((pat) => {
      const re = pat ? new RegExp(pat) : null;
      const images = [...document.images]
        .map((i) => i.currentSrc || i.src)
        .filter((s) => s && s.startsWith('http'))
        .slice(0, 30);
      const items = [];
      if (re) {
        const seen = new Set();
        for (const a of document.querySelectorAll('a[href]')) {
          if (!re.test(a.href) || seen.has(a.href)) continue;
          seen.add(a.href);
          // Walk up until we reach the card that holds a price.
          let el = a, card = null;
          for (let i = 0; i < 8 && el; i++) {
            el = el.parentElement;
            if (!el) break;
            const t = el.innerText || '';
            if (/[¥￥円$]/.test(t)) { card = el; break; }
            if (t.length > 1500) break;
          }
          const img = a.querySelector('img');
          items.push({
            url: a.href,
            title: ((a.innerText || '').trim() || a.getAttribute('title') || (img && img.alt) || '').slice(0, 200),
            text: ((card && card.innerText) || '').slice(0, 800),
          });
          if (items.length >= 150) break;
        }
      }
      return { title: document.title, text: document.body.innerText.slice(0, 20000), images, items };
    }, itemPattern || '');

    console.log(JSON.stringify({ ok: true, url, ...data }));
  } catch (e) {
    console.log(JSON.stringify({ ok: false, url, error: String(e) }));
  } finally {
    if (browser) await browser.close();
  }
})();
