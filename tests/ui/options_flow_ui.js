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
    await page.waitForTimeout(4000);
  }
}
async function mc(page, loc, name) {
  const box = await loc.boundingBox();
  if (!box) throw new Error('no box for ' + name);
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
}
(async () => {
  const browser = await chromium.launch();
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
  await login(page);
  await page.goto(BASE + '/config/integrations/integration/print_timelapse', { waitUntil: 'networkidle' });
  await page.waitForTimeout(3000);
  // gear icon: x>1100, y<340, smallest x (gear is left of the dots)
  const icons = page.locator('ha-icon-button');
  const n = await icons.count();
  let gear = null, gearX = 1e9;
  for (let i = 0; i < n; i++) {
    const b = await icons.nth(i).boundingBox();
    if (b && b.y < 340 && b.x > 1100 && b.x < gearX) { gear = icons.nth(i); gearX = b.x; }
  }
  if (!gear) throw new Error('gear not found');
  await mc(page, gear, 'gear');
  await page.waitForTimeout(3500);
  await page.screenshot({ path: SHOTS + '/11-options-dialog.png' });
  const bt = await page.evaluate(() => document.body.innerText.slice(0, 3000));
  console.log('dialog text has interval field:', /interval/i.test(bt));
  const sub = page.locator('ha-dialog ha-button:has-text("Submit")').first();
  if (await sub.count()) {
    await mc(page, sub, 'opt-submit');
    await page.waitForTimeout(4000);
    await page.screenshot({ path: SHOTS + '/12-options-result.png' });
    const bt2 = await page.evaluate(() => document.body.innerText);
    console.log('options success:', /success|saved|reload/i.test(bt2));
  } else console.log('no submit in dialog');
  await browser.close();
  console.log('PHASE B3 DONE');
})().catch(e => { console.error('FAIL', e.message); process.exit(1); });
