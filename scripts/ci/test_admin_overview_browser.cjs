const {chromium}=require('playwright'); const fs=require('fs');const path=require('path');
(async()=>{ const browser=await chromium.launch({channel:process.env.CHROME_CHANNEL || undefined,headless:true,args:['--no-sandbox']});const page=await browser.newPage({viewport:{width:1440,height:1100}});let failures=[];page.on('pageerror',e=>failures.push(e.message));
await page.route('**/*',async route=>{const u=new URL(route.request().url());if(u.hostname!=='preview.local')return route.abort();let f='artifacts/admin-overview/index.html';
if(u.pathname.includes('/calendar_events/')) return route.fulfill({json:[{id:'fixture1',title:'검증 일정',start:'2026-10-19',url:'/project/fixture',extendedProps:{scope_name:'검증용 프로젝트 1',kind:'현장 작업',stage:'execution',event_type:'work_report',assignee:'검증 담당자',history:false}}]});
if(u.pathname.startsWith('/static/')){let rest=u.pathname.slice(8);let app=rest.split('/')[0];f=path.join(process.cwd(),app==='control'?'control/static':'geoflow_ops/static',rest);}
if(!fs.existsSync(f))return route.fulfill({status:404,body:''});let ext=path.extname(f);return route.fulfill({path:f,contentType:({'.css':'text/css','.js':'text/javascript','.html':'text/html','.png':'image/png','.woff2':'font/woff2'})[ext]});});
await page.goto('http://preview.local/');await page.waitForSelector('.fc-daygrid-day');await page.waitForTimeout(500);await page.screenshot({path:'artifacts/admin-overview/desktop.png',fullPage:true});
if(!(await page.locator('#calendar-details').innerText()).includes('검증용 프로젝트 1')) throw Error('initial date not selected');
await page.locator('[data-date="2026-10-20"]').first().click();if(!(await page.locator('#selected-date').innerText()).includes('2026-10-20'))throw Error('date selection failed');
await page.locator('[data-date="2026-10-19"]').first().click();
await page.setViewportSize({width:390,height:844});await page.screenshot({path:'artifacts/admin-overview/mobile.png',fullPage:true});if(failures.length) throw Error(failures.join('; '));
if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('mobile horizontal overflow');
console.log(JSON.stringify({pageErrors:failures,viewport:await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth})),calendarSelection:'pass'}));await browser.close();})();
