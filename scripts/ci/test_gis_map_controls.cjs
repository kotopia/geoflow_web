/* Browser integration with real Leaflet, isolated API fixtures and no live keys. */
const {chromium} = require('playwright');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const root = process.cwd();
const assets = process.env.GEOFLOW_MAP_TEST_ASSETS || '/tmp/geoflow-map-assets';
const read = p => fs.readFileSync(p, 'utf8');
const js = p => `<script>${read(p)}</script>`;
const config = {tiles: Object.fromEntries(['Base','Satellite','Hybrid','Cadastral'].map(s=>[s,`/tiles/${s}/{z}/{y}/{x}`])),options_url:'/options',overlay_url:'/overlay'};
const point = {type:'Feature',geometry:{type:'Point',coordinates:[127,36]},properties:{번호:'TEST-001'}};
const json = (id,value) => `<script id="${id}" type="application/json">${JSON.stringify(value)}</script>`;
(async()=>{
 const browser = await chromium.launch({headless:true, ...(process.env.CHROMIUM_PATH ? {executablePath:process.env.CHROMIUM_PATH} : {})});
 try {
  const page=await browser.newPage({viewport:{width:1280,height:900}}); const errors=[]; page.on('pageerror',e=>errors.push(e.message));
  let map, overlayCount=0, tileStyles=new Set();
  await page.route('https://map.test/**',async route=>{
    const u=new URL(route.request().url());
    if(u.pathname==='/options')return route.fulfill({json:{ok:true,datasets:[{id:'dataset',name:'기준점 시험자료',versions:[{id:'version',label:'시험 버전'}]}]}});
    if(u.pathname==='/overlay'){
      const data=route.request().postDataJSON();
      if(data.action==='inspect') { await new Promise(resolve=>setTimeout(resolve,150)); return route.fulfill({json:{ok:true,layers:[{name:'points',kind:'vector',crs:'EPSG:4326',fields:['번호']}]}}); }
      overlayCount++;return route.fulfill({json:{ok:true,type:'FeatureCollection',features:[point],written:false}});
    }
    if(u.pathname.startsWith('/tiles/')){tileStyles.add(u.pathname.split('/')[2]);return route.fulfill({contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=','base64')});}
    if(u.pathname==='/'){return route.fulfill({contentType:'text/html',body:map});}
    return route.fulfill({body:'project detail'});
  });
  const head=`<meta charset="utf-8"><style>${read(assets+'/leaflet.css')}${read(root+'/geoflow_ops/static/geoflow_ops/css/gis-project-map.css')}</style>`;
  const libs=js(assets+'/leaflet.js')+js(assets+'/cluster.js')+js(root+'/geoflow_ops/static/geoflow_ops/js/gis-map-references.js');
  map=`<!doctype html>${head}<input name="csrfmiddlewaretoken" value="test-token" type="hidden"><div id="gisDashboardMap"></div>${json('gis-vworld-config',config)}${json('gis-project-locations',[{...point,properties:{code:'26001',name:'시험 사업',url:'/projects/one/'}}])}${libs}<script>window.testMaps=[];L.Map.addInitHook(function(){window.testMaps.push(this)});</script>${js(root+'/geoflow_ops/static/geoflow_ops/js/gis-dashboard-map.js')}`;
  await page.goto('https://map.test/'); await page.getByRole('combobox',{name:'배경지도'}).waitFor();
  await page.getByRole('combobox',{name:'배경지도'}).selectOption('SatelliteHybrid');
  await page.waitForFunction(()=>Object.values(window.testMaps[0]._layers).filter(l=>l._url&&l._url.includes('/tiles/')).length===2);
  await page.getByLabel('지적편집도',{exact:true}).check();
  await page.waitForFunction(()=>Object.values(window.testMaps[0]._layers).some(l=>l._url&&l._url.includes('/Cadastral/')));
  await page.getByRole('combobox',{name:'배경지도'}).selectOption('Base');
  assert(await page.getByLabel('지적편집도',{exact:true}).isChecked());
  await page.evaluate(()=>window.testMaps[0].setView([36,127],17,{animate:false}));
  await page.locator('summary').click(); await page.getByLabel('기준점 시험자료',{exact:true}).check();
  await page.evaluate(()=>window.testMaps[0].panBy([10,10],{animate:false}));
  await page.waitForFunction(()=>document.body.textContent.includes('1개 · 시험 버전'));
  await page.getByText('TEST-001',{exact:true}).count();
  const initial=overlayCount;
  await page.getByLabel('기준점 시험자료',{exact:true}).uncheck();
  await page.evaluate(()=>window.testMaps[0].panBy([30,30],{animate:false}));
  await page.waitForTimeout(500); assert.equal(overlayCount,initial);
  await page.setViewportSize({width:390,height:800});
  assert(await page.locator('.gf-reference-control').evaluate(e=>e.getBoundingClientRect().width<230));
  await page.setViewportSize({width:1280,height:900});
  await page.evaluate(()=>{const map=window.testMaps[0]; map.setView([36,127],15,{animate:false});});
  await page.locator('.leaflet-marker-icon').first().click();
  await page.waitForURL('https://map.test/projects/one/');
  assert.deepEqual(errors,[]); assert(tileStyles.has('Satellite')&&tileStyles.has('Hybrid')&&tileStyles.has('Cadastral'));
  console.log('Browser map controls passed: basemap switching, persistent cadastral overlay, file overlay, off cleanup, responsive width, direct project navigation');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
