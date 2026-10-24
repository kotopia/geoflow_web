/* Actual AdminKit asset checks; fixtures contain no production business data. */
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({channel: process.env.CHROME_CHANNEL || undefined, headless: true, args: ['--no-sandbox']});
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.addInitScript(() => {
    localStorage.setItem('adminkit_config_visited', 'true');
    localStorage.setItem('adminkit_config_sidebarLayout', 'default');
    window.layoutMismatches=[];
    function sample(){
      if(document.getElementById('sidebar')) {
        const expected=matchMedia('(max-width: 991.98px)').matches?'default':'compact';
        if(document.body.dataset.sidebarLayout!==expected)window.layoutMismatches.push(document.body.dataset.sidebarLayout);
      }
      requestAnimationFrame(sample);
    }
    requestAnimationFrame(sample);
  });
  let fixture = 'tenant';
  await page.route('**/*', route => {
    const u = new URL(route.request().url());
    if (u.hostname !== 'preview.local') return route.abort();
    if (u.pathname.includes('calendar_events')) return route.fulfill({json: []});
    let f = `artifacts/compact-layout/${fixture}.html`;
    if (u.pathname.startsWith('/static/')) {
      const rest = u.pathname.slice(8), app = rest.split('/')[0];
      f = path.join(app === 'control' ? 'control/static' : 'geoflow_ops/static', rest);
    }
    if (!fs.existsSync(f)) return route.fulfill({status: 404, body: ''});
    return route.fulfill({path: f, contentType: {'.css':'text/css','.js':'text/javascript','.html':'text/html','.png':'image/png','.woff2':'font/woff2'}[path.extname(f)]});
  });
  async function open(name, url='/') { fixture=name; await page.goto('http://preview.local'+url); await page.waitForTimeout(450); assert.deepEqual(await page.evaluate(()=>window.layoutMismatches),[]); }
  const width = selector => page.locator(selector).evaluate(el => el.getBoundingClientRect().width);
  const css = (selector, property) => page.locator(selector).first().evaluate((el,p)=>getComputedStyle(el)[p],property);
  await open('tenant');
  assert.equal(await width('#sidebar'),74);
  assert.equal(await css('body','fontSize'),'12px');
  assert.equal(await css('h1','fontSize'),'18px');
  assert.equal(await page.locator('#contract-menu a[href*="partner_list"]').count(),0);
  assert.equal(await page.locator('#company-menu a[href*="partner_list"]').count(),1);
  const company=page.locator('[data-bs-target="#company-menu"]');
  await page.locator('[data-bs-target="#bid-menu"]').click();
  await page.waitForURL('**/tenant/bid_notice_list/');
  await page.locator('[data-bs-target="#contract-menu"]').click();
  await page.waitForURL('**/tenant/contract_list/');
  await company.click();
  await page.waitForURL('**/tenant/myinfo_orgunit_list/');
  await company.hover();
  assert(await page.locator('#company-menu').isVisible());
  await page.screenshot({path:'artifacts/compact-layout/desktop.png',fullPage:true});
  await page.mouse.move(900,20);
  await company.focus();
  await page.keyboard.press('Tab');
  assert.equal(await page.locator(':focus').getAttribute('href'),'/tenant/myinfo_orgunit_list/');
  await page.keyboard.press('Tab');
  assert.equal(await page.locator(':focus').getAttribute('href'),'/tenant/partner_list/');
  await page.keyboard.press('Enter');
  await page.waitForURL('**/tenant/partner_list/');
  await page.waitForTimeout(450);
  assert.equal(await page.locator('#company-menu [aria-current="page"]').count(),1);
  await page.locator('.js-sidebar-toggle').click();
  await page.waitForTimeout(400);
  assert.equal(await css('#sidebar','marginLeft'),'-74px');
  await page.locator('.js-sidebar-toggle').click();
  await page.waitForTimeout(400);
  assert.equal(await css('#sidebar','marginLeft'),'0px');
  await page.setViewportSize({width:390,height:844});
  await open('tenant','/tenant/partner_list/');
  assert.equal(await width('#sidebar'),208);
  assert.equal(await width('#sidebar [data-simplebar]'),208);
  assert.equal(await css('#sidebar','marginLeft'),'-208px');
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth),390);
  await page.screenshot({path:'artifacts/compact-layout/mobile.png',fullPage:true});
  await page.locator('.js-sidebar-toggle').click();
  await page.waitForTimeout(400);
  assert.equal(await css('#sidebar','marginLeft'),'0px');
  assert(await page.locator('#company-menu a').first().isVisible());
  await company.click(); await page.waitForTimeout(400);
  assert(!(await page.locator('#company-menu').isVisible()));
  await company.click(); await page.waitForTimeout(400);
  assert(await page.locator('#company-menu').isVisible());
  await page.screenshot({path:'artifacts/compact-layout/mobile-menu.png',fullPage:true});
  await page.setViewportSize({width:1440,height:1000});
  await open('components');
  assert.equal(await css('.form-control','fontSize'),'12px');
  assert.equal(await css('.small small','fontSize'),'11px');
  assert.equal(await css('.badge','fontSize'),'11px');
  assert.equal(await css('.table:not(.table-sm) td','paddingTop'),'8px');
  assert.equal(await css('.table-sm td','paddingTop'),'4.8px');
  await page.screenshot({path:'artifacts/compact-layout/components.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});
  assert.equal(await css('.form-control','fontSize'),'16px');
  assert((await page.locator('.btn').first().boundingBox()).height>=40);
  await page.setViewportSize({width:1440,height:1000});
  await open('central');
  assert.equal(await width('#sidebar'),74);
  assert.equal(await page.locator('.js-stylesheet').count(),1);
  for (const link of await page.locator('.sidebar-nav > .sidebar-item > .sidebar-link').all()) {
    assert(await link.getAttribute('aria-label'));
    assert.equal(await link.locator('svg').count(),1);
  }
  await open('limited');
  for (const selector of ['#bid-menu','#finance-menu','#gis-menu','a[href*="employees_list"]','a[href*="settings_page"]']) {
    assert.equal(await page.locator(selector).count(),0);
  }
  assert.equal(await page.locator('#company-menu a[href*="partner_list"]').count(),1);
  await open('popup');
  assert.equal(await css('body','fontSize'),'12px');
  assert.equal(await css('.form-select','fontSize'),'12px');
  assert.deepEqual(errors,[]);
  console.log('PASS: compact sizes, menu relocation, keyboard/click, collapse, 390px touch targets, central icons, popup, no JS errors');
  await browser.close();
})().catch(e=>{console.error(e);process.exit(1);});
