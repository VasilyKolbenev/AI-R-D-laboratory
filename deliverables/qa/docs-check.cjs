const fs=require('fs');
const path=require('path');
const {pathToFileURL}=require('url');
const playwright = require('playwright');
const {chromium}=playwright;
const root=path.resolve(__dirname,'..');
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.PLAYWRIGHT_CHANNEL ? {channel:process.env.PLAYWRIGHT_CHANNEL} : {})});
 const results=[];
 for(const [id,file] of [['gallery','index.html'],['architecture','docs/architecture.html'],['plan','docs/implementation-plan.html'],['catalog','docs/research-catalog.html'],['verification','qa/verification.html']]){
  const context=await browser.newContext({viewport:{width:1440,height:1000},deviceScaleFactor:1,locale:'ru-RU',reducedMotion:'reduce'});
  const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(pathToFileURL(path.join(root,file)).href);
  const desktop=await page.evaluate(()=>({viewport:innerWidth,width:document.documentElement.scrollWidth,images:[...document.querySelectorAll('img[src]')].map(e=>({src:e.getAttribute('src'),loaded:e.complete&&e.naturalWidth>0}))}));
  await page.screenshot({path:path.join(__dirname,id+'-desktop.png')});
  const extra={};
  if(id==='architecture'){
   await page.locator('#containers').scrollIntoViewIfNeeded();
   await page.screenshot({path:path.join(__dirname,'architecture-c2.png')});
   await page.locator('#containers [data-diagram]').click();
   extra.dialogOpens=await page.locator('dialog').evaluate(e=>e.open);
   await page.screenshot({path:path.join(__dirname,'architecture-c2-modal.png')});
   await page.locator('#diagramZoom').selectOption('200');
   extra.zoomWorks=await page.locator('.diagramViewport').evaluate(e=>e.scrollWidth>e.clientWidth*1.9);
   await page.keyboard.press('Escape');
   extra.escapeCloses=await page.locator('dialog').evaluate(e=>!e.open);
  }
  await page.setViewportSize({width:390,height:844});await page.evaluate(()=>scrollTo(0,0));
  const mobile=await page.evaluate(()=>({viewport:innerWidth,width:document.documentElement.scrollWidth}));
  await page.screenshot({path:path.join(__dirname,id+'-mobile.png')});
  results.push({file,errors,desktop,mobile,...extra});
  await context.close();
 }
 await browser.close();
 fs.writeFileSync(path.join(__dirname,'docs-results.json'),JSON.stringify(results,null,2));
 console.log(JSON.stringify(results,null,2));
 if(results.some(r=>r.errors.length||r.desktop.viewport!==r.desktop.width||r.mobile.viewport!==r.mobile.width||r.desktop.images.some(i=>!i.loaded)||r.dialogOpens===false||r.zoomWorks===false||r.escapeCloses===false))process.exitCode=1;
})().catch(e=>{console.error(e);process.exitCode=1});
