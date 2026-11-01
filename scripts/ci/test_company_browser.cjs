const assert = require('node:assert/strict');
const {chromium} = require('playwright');
(async () => {
  const browser = await chromium.launch({headless:true});
  const page = await browser.newPage({viewport:{width:1440,height:1100}});
  const errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  // Third party font/data-table CSS is unnecessary to verify our local assets.
  await page.route('https://fonts.googleapis.com/**',route=>route.abort());
  await page.route('https://cdn.jsdelivr.net/**',route=>route.abort());
  await page.goto('http://127.0.0.1:8765/index.html');
  await page.waitForFunction(()=>window.Chart && Object.values(Chart.instances).find(chart=>chart.canvas.id === 'company-headcount-chart'));
  const points=await page.evaluate(()=>Object.values(Chart.instances).find(chart=>chart.canvas.id === 'company-headcount-chart').data.datasets[0].data);
  assert.equal(points[2],null,'missing historical data stays a gap');
  assert.equal(await page.locator('form[method=post]').count(),0,'overview is read-only');
  await page.screenshot({path:'/tmp/company-preview/desktop.png',fullPage:true});
  for(const width of [390,768,1440]) {
    await page.setViewportSize({width,height:900});
    assert.equal(await page.evaluate(()=>document.body.scrollWidth <= innerWidth),true,`overview overflows at ${width}`);
  }
  await page.setViewportSize({width:390,height:844});
  await page.screenshot({path:'/tmp/company-preview/mobile.png',fullPage:true});
  for(const section of ['basic','documents','performance','organization','references','detail','basic-edit']) {
    await page.goto(`http://127.0.0.1:8765/${section}.html`);
    assert.equal(await page.evaluate(()=>document.body.scrollWidth <= innerWidth),true,`${section} overflows on mobile`);
  }
  await page.goto('http://127.0.0.1:8765/edit.html');
  assert.equal(await page.evaluate(()=>document.body.scrollWidth <= innerWidth),true,'editor overflows on mobile');
  await page.locator('[name=name]').fill('새 등록');
  await page.locator('[name=occurred_on]').fill('2026-01-01');
  await page.locator('[name=kind]').selectOption('registration');
  // Verify failed upload preserves input and restores the save button.
  await page.evaluate(()=>{ window.uploadSingleFile=()=>Promise.reject(new Error('synthetic upload failure')); });
  await page.locator('#evidence-files').setInputFiles({name:'test.pdf',mimeType:'application/pdf',buffer:Buffer.from('synthetic')});
  await page.locator('#evidence-files').setInputFiles({name:'second.pdf',mimeType:'application/pdf',buffer:Buffer.from('second synthetic')});
  assert.equal(await page.locator('#evidence-queue .company-file').count(),2,'repeated file selection accumulates');
  await page.getByRole('button',{name:'＋ 대상 품목 추가'}).click();
  await page.locator('[data-item-field=name]').fill('테스트 품목');
  await page.locator('#company-fact-form button[type=submit]').click();
  await page.waitForFunction(()=>document.getElementById('company-save-status').textContent.includes('synthetic upload failure'));
  assert.equal(await page.locator('[name=name]').inputValue(),'새 등록');
  assert.equal(await page.locator('#company-fact-form button[type=submit]').isEnabled(),true);
  assert.equal(await page.locator('#evidence-queue .company-file').count(),2,'upload failure retains queue');
  await page.locator('#evidence-queue button').first().click();
  assert.equal(await page.locator('#evidence-queue .company-file').count(),1);
  await page.screenshot({path:'/tmp/company-preview/editor.png',fullPage:true});
  assert.deepEqual(errors,[],'unexpected browser errors');
  await browser.close();
  console.log('PASS: AdminKit charts, null gaps, responsive layout, editor and upload failure recovery');
})().catch(error=>{console.error(error);process.exitCode=1;});
