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
  page.on('pageerror', e => console.log('PAGEERROR:', e.message));
  await login(page);
  await page.goto(BASE + '/config/integrations/dashboard', { waitUntil: 'networkidle' });
  await page.waitForTimeout(2500);
  await mc(page, page.locator('ha-button:has-text("Add integration")').first(), 'add-int');
  await page.waitForTimeout(1500);
  await page.locator('ha-dialog input').first().fill('print timelapse');
  await page.waitForTimeout(1500);
  await page.locator('ha-dialog :text-is("Print Timelapse Archive")').first().click();
  await page.waitForTimeout(3000);
  await mc(page, page.locator('ha-entity-picker').nth(0), 'cam-picker');
  await page.waitForTimeout(1500);
  await mc(page, page.locator('ha-combo-box-item:has-text("127_0_0_1")').first(), 'cam-item');
  await page.waitForTimeout(1000);
  await mc(page, page.locator('ha-entity-picker').nth(1), 'status-picker');
  await page.waitForTimeout(1500);
  await mc(page, page.locator('ha-combo-box-item:has-text("Printer status")').first(), 'status-item');
  await page.waitForTimeout(1000);
  await page.screenshot({ path: SHOTS + '/07-config-flow-filled.png' });
  await mc(page, page.locator('ha-dialog ha-button:has-text("Submit")').first(), 'submit');
  await page.waitForTimeout(6000);
  await page.screenshot({ path: SHOTS + '/08-config-flow-result.png' });
  const bodyText = await page.evaluate(() => document.body.innerText);
  console.log('flow success shown:', /success|created/i.test(bodyText));
  await browser.close();
  console.log('PHASE A DONE');
})().catch(e => { console.error('FAIL', e.message); process.exit(1); });
