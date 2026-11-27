const { chromium } = require('playwright');
const fs = require('fs'), path = require('path');
const W = process.argv[2], OUT = process.argv[3], SHOT = process.argv[4] === 'shot';
const mock = JSON.parse(fs.readFileSync(path.join(W, 'mock.json'), 'utf8'));
const mime = { '.js': 'application/javascript', '.css': 'text/css', '.html': 'text/html; charset=utf-8', '.png': 'image/png', '.webp': 'image/webp', '.json': 'application/json' };
(async () => {
  const b = await chromium.launch();
  const opts = { viewport: { width: 1920, height: 1080 } };
  if (!SHOT) opts.recordVideo = { dir: OUT, size: { width: 1920, height: 1080 } };
  const ctx = await b.newContext(opts);
  await ctx.route('http://demo.local/**', async (route) => {
    const u = new URL(route.request().url());
    const p = u.pathname;
    if (p === '/' ) return route.fulfill({ path: path.join(W, 'app/web/index.html'), contentType: mime['.html'] });
    if (p === '/composite.html') return route.fulfill({ path: path.join(W, 'composite.html'), contentType: mime['.html'] });
    if (p.startsWith('/static/')) { const f = path.join(W, 'app/web', p.slice(8)); return route.fulfill({ path: f, contentType: mime[path.extname(f)] || 'application/octet-stream' }); }
    if (p === '/api/config') return route.fulfill({ json: mock.config });
    if (p === '/api/chat') { await new Promise(r => setTimeout(r, SHOT ? 3000 : 68200)); return route.fulfill({ json: mock.chat }); }
    if (p === '/api/doc') { const id = u.searchParams.get('id'); return route.fulfill({ json: mock.docs[id] || {} }); }
    return route.fulfill({ status: 404, body: '' });
  });
  await ctx.addInitScript(t => { window.__text = t; }, mock.text);
  const t0 = Date.now();
  const p = await ctx.newPage();
  await p.goto('http://demo.local/composite.html');
  if (SHOT) {
    for (const t of [4, 14, 40]) { await p.waitForTimeout(t === 4 ? 4000 : (t === 14 ? 10000 : 26000)); await p.screenshot({ path: `${OUT}/c${t}.png` }); }
  } else {
    await p.waitForFunction(() => window.__done, null, { timeout: 200000, polling: 500 });
    await p.waitForTimeout(800);
    const vp = await p.video().path();
    await ctx.close(); await b.close();
    console.log(JSON.stringify({ path: vp, t0 }));
    return;
  }
  await b.close();
})();
