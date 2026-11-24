const {chromium}=require('playwright');
const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:process.env.CHROME_CHANNEL||undefined,headless:true});
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 const errors=[],posts=[];let source='g2b',failProgress=false;page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',route=>{
  const u=new URL(route.request().url());if(u.hostname!=='bid-preview.local')return route.abort();
  if(route.request().method()==='POST'){
   posts.push(route.request().postData());const action=new URLSearchParams(posts.at(-1)).get('action');
   if(['submit','unsubmit'].includes(action)){
    if(failProgress)return route.fulfill({status:403,body:'Denied'});
    const done=action==='submit';return route.fulfill({contentType:'application/json',body:JSON.stringify({progress_badge:done?'투찰':'참가',timeline:[{key:'bid_close_at',action:done?'unsubmit':'submit',action_label:done?'취소':'완료',action_title:done?'투찰 완료 취소':'투찰 완료',completed_label:done?'완료 기록 · 11.24 10:00':''}]})});
   }
   return route.fulfill({body:'saved',contentType:'text/html'});
  }
  let file=`artifacts/bid-detail/${source}${u.pathname==='/detail/'?'-detail':''}.html`;
  if(u.pathname.startsWith('/static/'))file=path.join('control/static',u.pathname.slice(8));
  if(!fs.existsSync(file))return route.fulfill({status:404,body:''});
  return route.fulfill({path:file,contentType:{'.html':'text/html','.css':'text/css','.js':'text/javascript'}[path.extname(file)]});
 });
 for(source of ['g2b','kepco','history']){
  await page.setViewportSize({width:1440,height:1000});
  await page.goto('http://bid-preview.local/bids/');
  await page.locator('.bid-title').click();
  const modal=page.locator('#bid-detail-modal');await modal.locator('#bid-general').waitFor();
  await page.waitForFunction(()=>getComputedStyle(document.querySelector('#bid-detail-modal')).opacity==='1');
  await page.evaluate(()=>document.fonts.ready);
  assert.equal(await modal.locator('#bid-general table').count(),1);
  assert.equal(await modal.locator('.bid-progress li').count(),5);
  assert.equal(await modal.getByRole('button',{name:'개찰 결과 보기'}).isEnabled(),false);
  assert.equal(await modal.getByRole('button',{name:'기록 저장'}).count(),source==='history'?0:1);
  assert.equal(await modal.getByRole('button',{name:'투찰 완료',exact:true}).count(),source==='history'?0:1);
  if(source!=='history'){
   assert.equal(await modal.locator('[aria-label="업무 진행"]').innerText(),'참가');
   assert.equal(await modal.getByRole('button',{name:'참가등록 완료 취소',exact:true}).count(),1);
  }
  if(source==='kepco')assert((await modal.innerText()).includes('한국전력'));
  assert((await modal.innerText()).includes('미연동'));
  await page.screenshot({path:`artifacts/bid-detail/${source}-desktop.png`});
  await modal.locator('[data-bid-section][href="#bid-files"]').click();
  assert.equal(await page.evaluate(()=>document.activeElement.id),'bid-files');
  assert.equal(await modal.getByRole('link',{name:'예시공고문.pdf 다운로드'}).getAttribute('href'),source==='kepco'?'https://srm.kepco.net/example.pdf':'https://www.g2b.go.kr/example.pdf');
  for(const width of [768,390]){
   await page.setViewportSize({width,height:844});
   assert(await modal.locator('.modal-body').evaluate(e=>e.scrollWidth<=e.clientWidth+1),`modal overflow: ${source} ${width}`);
  }
  await modal.locator('.modal-body').evaluate(e=>{e.scrollTop=0});
  await page.screenshot({path:`artifacts/bid-detail/${source}-mobile.png`});
  if(source!=='history'){
   await modal.locator('textarea').fill('미저장 메모 유지');
   const before=page.url();
   await modal.getByRole('button',{name:'투찰 완료',exact:true}).click();
   await modal.getByRole('button',{name:'투찰 완료 취소',exact:true}).waitFor();
   assert.equal(page.url(),before);assert(await modal.isVisible());
   assert.equal(await modal.locator('textarea').inputValue(),'미저장 메모 유지');
   assert.equal(await page.locator('[data-bid-progress-cell]').innerText(),'투찰');
   assert.equal(await page.locator('.table-responsive > table > thead th').last().innerText(),'진행');
   await modal.getByRole('button',{name:'투찰 완료 취소',exact:true}).click();
   await modal.getByRole('button',{name:'투찰 완료',exact:true}).waitFor();
   assert.equal(await page.locator('[data-bid-progress-cell]').innerText(),'참가');
   failProgress=true;
   await modal.getByRole('button',{name:'투찰 완료',exact:true}).click();
   await modal.getByRole('alert').waitFor();
   assert.equal(await page.locator('[data-bid-progress-cell]').innerText(),'참가');
   assert(await modal.isVisible());assert.equal(await modal.locator('textarea').inputValue(),'미저장 메모 유지');
   failProgress=false;
  }
  if(source==='history')assert.equal(await modal.locator('form').count(),0);
  else {
   await modal.locator('[data-bid-section][href="#bid-memo"]').click();
   await modal.locator('textarea').fill('검토 메모 & 원문 확인');
   await modal.getByRole('button',{name:'기록 저장'}).click();await page.waitForURL('**/action/');
   assert.equal(new URLSearchParams(posts.at(-1)).get('memo'),'검토 메모 & 원문 확인');
  }
 }
 source='g2b';
 await page.goto('http://bid-preview.local/bids/?notice=00000000-0000-0000-0000-000000000001');
 await page.locator('#bid-detail-modal #bid-general').waitFor();
 assert(await page.locator('#bid-detail-modal').isVisible());
 assert.deepEqual(errors,[]);await browser.close();console.log('PASS: bid modal, shared source tables, read-only history, memo submission and responsive layout');
})().catch(e=>{console.error(e);process.exit(1)});
