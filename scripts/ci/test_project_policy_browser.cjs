const {chromium}=require('playwright');
const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:process.env.CHROME_CHANNEL||undefined,headless:true,args:['--no-sandbox']});
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 let fixture='list'; const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',route=>{
  const u=new URL(route.request().url());if(u.hostname!=='preview.local')return route.abort();
  let f=`artifacts/project-policy/${fixture}.html`;
  if(u.pathname.startsWith('/static/')){
   const rest=u.pathname.slice(8);f=path.join(rest.startsWith('control/')?'control/static':'geoflow_ops/static',rest);
  }
  if(!fs.existsSync(f))return route.fulfill({status:404,body:''});
  return route.fulfill({path:f,contentType:{'.html':'text/html','.js':'text/javascript','.css':'text/css','.woff2':'font/woff2'}[path.extname(f)]});
 });
 await page.goto('http://preview.local/projects/');
 await page.waitForSelector('#projectsCard:not([hidden])');
 assert.deepEqual(await page.evaluate(()=>$('#datatables-projects').DataTable().order()),[[6,'desc']]);
 assert.equal(await page.locator('#datatables-projects tbody tr:first-child [data-col="name"]').innerText(),'독립 프로젝트 3');
 await page.locator('.gf-k-pause').click();
 assert.equal(await page.locator('#datatables-projects tbody tr').count(),1);
 assert.equal(await page.locator('#datatables-projects tbody [data-col="status"]').innerText(),'중지');
 await page.locator('.gf-k-complete').click();
 assert.equal(await page.locator('#datatables-projects tbody [data-col="name"]').innerText(),'독립 프로젝트 2');
 await page.screenshot({path:'artifacts/project-policy/list-desktop.png',fullPage:true});
 fixture='create';await page.goto('http://preview.local/projects/new/');
 await page.selectOption('#id_contract','single');
 assert(await page.locator('#id_name').evaluate(e=>e.readOnly));assert.equal(await page.inputValue('#id_name'),'단일 계약 원본');
 await page.selectOption('#id_contract','multiple');
 assert.equal(await page.locator('#id_name').evaluate(e=>e.readOnly),false);
 await page.fill('#id_name','독립 입력');assert.equal(await page.inputValue('#id_name'),'독립 입력');
 await page.screenshot({path:'artifacts/project-policy/create-desktop.png',fullPage:true});
 await page.setViewportSize({width:390,height:844});
 await page.screenshot({path:'artifacts/project-policy/create-mobile.png',fullPage:true});
 assert.deepEqual(errors,[]);await browser.close();console.log('Project list sorting/status and SINGLE/MULTIPLE name UI passed');
})().catch(e=>{console.error(e);process.exit(1)});
