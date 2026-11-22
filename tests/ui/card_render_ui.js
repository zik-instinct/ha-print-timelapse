const { chromium } = require('playwright');
const BASE = 'http://127.0.0.1:8123';
const SHOTS = '/downloads/plugin-test-shots';
async function login(page) {
  await page.goto(BASE + '/', { waitUntil: 'networkidle' });
  const u = page.locator('input#username');
  if (await u.count()) {
    await u.fill(process.env.HA_TEST_USER || '');
    await page.locator('input#password').fill(process.env.HA_TEST_PASS || '');
    await page.locator('ha-button:has-text("Log in")').click();
    await page.waitForTimeout(5000);
  }
}
(async () => {
  const browser = await chromium.launch();
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
  page.on('pageerror', e => console.log('PAGEERROR:', e.message));
  await login(page);
  await page.goto(BASE + '/printer-corner', { waitUntil: 'networkidle' });
  await page.waitForTimeout(9000);
  const res = await page.evaluate(() => {
    const deep = (sel) => { const o=[]; const w=(nd)=>{ if(!nd.querySelectorAll)return; o.push(...nd.querySelectorAll(sel)); for(const e of nd.querySelectorAll('*')) if(e.shadowRoot) w(e.shadowRoot);}; w(document); return o; };
    const card = deep('print-timelapse-card')[0];
    return { defined: !!customElements.get('print-timelapse-card'), inDom: deep('print-timelapse-card').length,
             cardText: card ? card.innerText.slice(0, 200) : null };
  });
  console.log(JSON.stringify(res, null, 1));
  await page.screenshot({ path: SHOTS + '/14-dashboard-with-card.png' });
  // mobile too
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(2000);
  await page.screenshot({ path: SHOTS + '/15-dashboard-card-mobile.png' });
  await browser.close();
  console.log('PHASE C4 DONE');
})().catch(e => { console.error('FAIL', e.message); process.exit(1); });
