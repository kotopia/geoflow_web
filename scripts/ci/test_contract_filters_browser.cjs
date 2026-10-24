const {chromium}=require('playwright');
const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:process.env.CHROME_CHANNEL||undefined,headless:true,args:['--no-sandbox']});
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
 await page.addInitScript(()=>localStorage.setItem('adminkit_config_visited','true'));
 let saved=[];
 await page.route('**/*',route=>{
  const u=new URL(route.request().url());if(u.hostname!=='preview.local')return route.abort();
  if(u.pathname==='/contracts/saved-filters/'){
   if(route.request().method()==='POST'){const body=route.request().postDataJSON();const record={id:'1',...body};saved=[record];return route.fulfill({json:record});}
   return route.fulfill({json:{filters:saved}});
  }
  let f='artifacts/contract-filters/contracts.html';
  if(u.pathname.startsWith('/static/')){const rest=u.pathname.slice(8);f=path.join(rest.startsWith('control/')?'control/static':'geoflow_ops/static',rest);}
  if(!fs.existsSync(f))return route.fulfill({status:404,body:''});
  return route.fulfill({path:f,contentType:{'.css':'text/css','.js':'text/javascript','.html':'text/html','.png':'image/png'}[path.extname(f)]});
 });
 async function openAdvanced(){
  if(await page.locator('#contract-base-tab').isVisible())await page.click('#contract-base-tab');
  await page.getByRole('button',{name:'계약 메뉴',exact:true}).click();
  await page.click('#contract-advanced-add');
 }
 const baseCount=()=>page.evaluate(()=>$('#datatables-contracts').DataTable().rows({search:'applied'}).count());
 const table=()=>page.locator('#contract-filter-1 table');
 async function filter(criteria,logic='AND',id=1){await page.evaluate(({criteria,logic,id})=>$('#contract-filter-'+id+' table').DataTable().searchBuilder.rebuild({criteria,logic}),{criteria,logic,id});}
 const term=(origData,data,type,condition,value)=>({origData,data,type,condition,value});
 await page.goto('http://preview.local/contracts/');await page.waitForSelector('#contractsCard:not([hidden])');
 assert.deepEqual(await page.evaluate(()=>{const row=$('#datatables-contracts').DataTable().rows().nodes().toArray().find(r=>r.querySelector('.gf-event-count'));return [row.querySelector('.gf-event-count').textContent,row.querySelector('.gf-event-suspension').textContent];}),['3','Ⅱ']);
 assert.equal(await baseCount(),11);assert.equal(await page.locator('#contract-column-search').isVisible(),false);
 await page.click('#contract-column-toggle');
 await page.getByLabel('계약명 검색',{exact:true}).fill('시험 계약 2');assert.equal(await baseCount(),2);
 await page.click('#contract-column-toggle');assert.equal(await baseCount(),2);
 await page.click('#contract-column-toggle');assert.equal(await page.getByLabel('계약명 검색',{exact:true}).inputValue(),'시험 계약 2');
 await page.getByLabel('계약명 검색',{exact:true}).fill('');
 await page.check('#showPreviousCompleted');assert.equal(await baseCount(),12);
 await page.uncheck('#showPreviousCompleted');assert.equal(await baseCount(),11);
 await page.screenshot({path:'artifacts/contract-filters/base-desktop.png',fullPage:true});
 await openAdvanced();await page.waitForSelector('#contract-filter-1 .dtsb-searchBuilder');
 assert.equal(await table().locator('tbody tr').count(),10);
 assert.match(await page.locator('#contract-filter-1 .filter-summary').textContent(),/선택 12건/);
 const conditions=[term('kind','계약종류','string','=','용역'.split()),term('amount','계약금액','num','>=',['10000000']),term('amount','계약금액','num','<=',['200000000'])];
 await filter(conditions);assert.match(await page.locator('#contract-filter-1 .filter-summary').textContent(),/선택 10건/);
 await table().locator('.filter-include').nth(0).uncheck();await table().locator('.filter-include').nth(1).uncheck();
 assert.match(await page.locator('#contract-filter-1 .filter-summary').textContent(),/선택 8건/);
 assert.match(await page.locator('#contract-filter-1 .filter-summary').textContent(),/360,000,000원/);
 await filter([...conditions,term('amount','계약금액','num','>=',['50000000'])]);
 assert.match(await page.locator('#contract-filter-1 .filter-summary').textContent(),/선택 4건/);
 await filter(conditions);assert.match(await page.locator('#contract-filter-1 .filter-summary').textContent(),/선택 8건/);
 await openAdvanced();assert.match(await page.locator('#contract-filter-2 .filter-summary').textContent(),/선택 12건/);
 await page.locator('#contract-filter-2').getByRole('button',{name:'조건 추가',exact:true}).click();
 await page.locator('#contract-filter-2 .dtsb-data').selectOption({label:'계약금액'});
 await page.locator('#contract-filter-2 .dtsb-condition').selectOption({label:'이상'});
 await page.locator('#contract-filter-2 input.dtsb-value').fill('100000000');
 await page.locator('#contract-filter-2 input.dtsb-value').press('Tab');
 await page.waitForFunction(()=>document.querySelector('#contract-filter-2 .filter-summary').textContent.includes('선택 2건'));
 await page.click('#contract-filter-1-tab');assert.match(await page.locator('#contract-filter-1 .filter-summary').textContent(),/선택 8건/);
 await page.locator('#contract-filter-1').getByLabel('필터 이름',{exact:true}).fill('최근 용역');
 await page.locator('#contract-filter-1').getByRole('button',{name:'필터조건 저장',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#contract-filter-1 [role=status]').textContent==='저장했습니다.');
 assert.equal(saved[0].definition.conditions.criteria.length,3);
 await page.waitForTimeout(200);
 await page.screenshot({path:'artifacts/contract-filters/desktop.png',fullPage:true});
 await page.reload();await openAdvanced();await page.waitForFunction(()=>document.querySelector('#contract-filter-1 select[aria-label="저장 필터"]').options.length===2);
 await page.locator('#contract-filter-1').getByLabel('저장 필터',{exact:true}).selectOption('1');
 await page.locator('#contract-filter-1').getByRole('button',{name:'불러오기',exact:true}).click();
 assert.match(await page.locator('#contract-filter-1 .filter-summary').textContent(),/선택 10건/);
 await filter([conditions[0],{logic:'OR',criteria:[term('client','거래처','string','contains',['충남']),term('client','거래처','string','contains',['대전'])]}]);
 assert.match(await page.locator('#contract-filter-1 .filter-summary').textContent(),/선택 10건/);
 await filter([term('start','시작일','date','between',['2023-01-01','2023-01-01'])]);
 assert.match(await page.locator('#contract-filter-1 .filter-summary').textContent(),/선택 12건/);
 await filter([term('events','표시 중인 이벤트','string','contains',['중지'])]);
 assert.match(await page.locator('#contract-filter-1 .filter-summary').textContent(),/선택 1건/);
 await page.setViewportSize({width:390,height:844});await page.waitForTimeout(200);await page.screenshot({path:'artifacts/contract-filters/mobile.png',fullPage:true});
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
 await page.click('#contract-base-tab');
 await page.getByRole('button',{name:'계약 메뉴',exact:true}).click();
 await page.screenshot({path:'artifacts/contract-filters/base-mobile.png',fullPage:true});
 assert.deepEqual(errors,[]);
 console.log('PASS column toggle, completion filter, 10/25/50, compound amount, AND/OR, date, event search, selection, tabs, save/reload, responsive and JS errors');
 await browser.close();
})().catch(e=>{console.error(e);process.exit(1);});
