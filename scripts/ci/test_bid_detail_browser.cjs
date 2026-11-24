const {chromium}=require('playwright');
const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:process.env.CHROME_CHANNEL||undefined,headless:true});
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 const errors=[],posts=[];let source='g2b',failProgress=false;page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',route=>{
  const u=new URL(route.request().url());if(u.hostname!=='bid-preview.local')return route.abort();
  if(u.pathname==='/events/')return route.fulfill({json:[{id:'bid-calendar',title:'관심공고 제목',start:new Date().toISOString().slice(0,10)+'T11:00:00',extendedProps:{scope_type:'bid'}},{id:'project-calendar',title:'프로젝트 일정',start:new Date().toISOString().slice(0,10)+'T12:00:00',extendedProps:{scope_type:'project'}}]});
  if(route.request().method()==='POST'){
   posts.push(route.request().postData());const action=new URLSearchParams(posts.at(-1)).get('action');
   if(['submit','unsubmit'].includes(action)){
    if(failProgress)return route.fulfill({status:403,body:'Denied'});
    const done=action==='submit';return route.fulfill({contentType:'application/json',body:JSON.stringify({progress_badge:done?'투찰':'참가',timeline:[{key:'bid_close_at',action:done?'unsubmit':'submit',action_label:done?'취소':'완료',action_title:done?'투찰 완료 취소':'투찰 완료',completed_at:done?'2026-11-24T01:00:00Z':null,completed_label:done?'완료 기록 · 11.24 10:00':''}]})});
   }
   return route.fulfill({body:'saved',contentType:'text/html'});
  }
  let file=`artifacts/bid-detail/${source}${u.pathname==='/detail/'?'-detail':u.pathname==='/bulk/'?'-bulk':''}.html`;
  if(u.pathname==='/calendar/')file='artifacts/bid-detail/calendar.html';
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
   assert(await modal.locator('[data-bid-event=bid_close_at]').evaluate(e=>e.classList.contains('completed')));
   assert.equal(await modal.locator('textarea').inputValue(),'미저장 메모 유지');
   assert.equal(await page.locator('[data-bid-progress-cell]').innerText(),'투찰');
   assert.equal(await page.locator('.table-responsive > table > thead th').last().innerText(),'진행');
   await modal.getByRole('button',{name:'투찰 완료 취소',exact:true}).click();
   await modal.getByRole('button',{name:'투찰 완료',exact:true}).waitFor();
   assert.equal(await page.locator('[data-bid-progress-cell]').innerText(),'참가');
   assert.equal(await modal.locator('[data-bid-event=bid_close_at]').evaluate(e=>e.classList.contains('completed')),false);
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
 await page.setViewportSize({width:1440,height:1000});
 await page.goto('http://bid-preview.local/bulk/');
 assert.deepEqual(await page.locator('.nav-tabs .nav-link').allTextContents(),['맞춤공고','전체공고','서류함']);
 assert.equal(await page.locator('select[name=company]').count(),0);
 assert.equal(await page.locator('#bid-bulk').isVisible(),false);
 await page.locator('.bid-select').first().check();
 assert.equal(await page.locator('#bid-interest-action').innerText(),'선택 관심 해제');
 assert.equal(await page.locator('#bid-interest-action').getAttribute('value'),'unsave');
 assert.equal(await page.locator('#bid-interest-action').evaluate(e=>e.form.id),'bid-bulk-form');
 await page.locator('.bid-select').last().check();
 assert.equal(await page.locator('#bid-interest-action').innerText(),'선택 관심 등록');
 assert.equal(await page.locator('#bid-interest-action').getAttribute('value'),'save');
 assert.equal(await page.locator('.table-responsive tbody tr').first().locator('td').nth(3).innerText(),'250,000,000');
 assert.equal(await page.locator('.table-responsive tbody tr').last().locator('td').nth(3).innerText(),'0');
 assert.equal(await page.locator('.pagination [aria-current=page]').innerText(),'1');
 assert.equal(await page.getByRole('link',{name:'2 페이지',exact:true}).getAttribute('href'),'?page=2');
 await page.screenshot({path:'artifacts/bid-detail/list-selection.png'});
 await page.locator('#bid-interest-action').click();await page.waitForURL('**/action/');
 const bulkPost=new URLSearchParams(posts.at(-1));assert.equal(bulkPost.get('action'),'save');assert.equal(bulkPost.getAll('notice_ids').length,2);
 await page.goto('http://bid-preview.local/bids/?notice=00000000-0000-0000-0000-000000000001');
 await page.locator('#bid-detail-modal #bid-general').waitFor();
 assert(await page.locator('#bid-detail-modal').isVisible());
 await page.goto('http://bid-preview.local/calendar/');
 await page.getByText('관심공고 제목',{exact:true}).waitFor();
 const bidEvent=page.locator('.fc-event').filter({hasText:'관심공고 제목'});
 assert.equal(await bidEvent.innerText(),'관심공고 제목');
 await page.getByRole('button',{name:'목록',exact:true}).click();
 await page.locator('.fc-list-event').filter({hasText:'관심공고 제목'}).waitFor();
 assert.equal(await page.locator('.fc-list-event').filter({hasText:'관심공고 제목'}).locator('.fc-list-event-time').innerText(),'');
 assert.notEqual(await page.locator('.fc-list-event').filter({hasText:'프로젝트 일정'}).locator('.fc-list-event-time').innerText(),'');
 assert.deepEqual(errors,[]);await browser.close();console.log('PASS: bid modal, shared source tables, read-only history, memo submission and responsive layout');
})().catch(e=>{console.error(e);process.exit(1)});
