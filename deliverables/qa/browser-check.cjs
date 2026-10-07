const fs=require('fs');
const path=require('path');
const {pathToFileURL}=require('url');
const playwright = require('playwright');
const {chromium}=playwright;
const root=path.resolve(__dirname,'..');
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.PLAYWRIGHT_CHANNEL ? {channel:process.env.PLAYWRIGHT_CHANNEL} : {})});
 const results=[];
 for(const [num,name] of [['01','01-observatory.html'],['02','02-atelier.html'],['03','03-constellation.html']]){
  const context=await browser.newContext({viewport:{width:1440,height:1000},deviceScaleFactor:1,locale:'ru-RU',reducedMotion:'reduce'});
  const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(pathToFileURL(path.join(root,'ui',name)).href);
  await page.waitForTimeout(200);
  await page.screenshot({path:path.join(__dirname,num+'-desktop.png'),fullPage:false});
  const controls=await page.locator('button,select,input').evaluateAll(es=>es.map(e=>({tag:e.tagName,id:e.id,text:e.textContent.trim().slice(0,100),label:e.getAttribute('aria-label'),data:{...e.dataset}})));
  const desktop=await page.evaluate(()=>({width:innerWidth,body:document.documentElement.scrollWidth,visibleDemo:[...document.querySelectorAll('*')].some(e=>e.textContent.length<100 && /синтетическ|Демо/i.test(e.textContent) && e.getBoundingClientRect().height>0 && e.getBoundingClientRect().top<innerHeight)}));
  await page.setViewportSize({width:390,height:844});
  await page.screenshot({path:path.join(__dirname,num+'-mobile.png'),fullPage:true});
  const mobile=await page.evaluate(()=>({width:innerWidth,body:document.documentElement.scrollWidth,visibleDemo:[...document.querySelectorAll('*')].some(e=>e.textContent.length<100 && /синтетическ|Демо/i.test(e.textContent) && e.getBoundingClientRect().height>0 && e.getBoundingClientRect().top<innerHeight)}));
  results.push({name,errors,desktop,mobile,controls});
  await context.close();
 }
 await browser.close();
 fs.writeFileSync(path.join(__dirname,'browser-discovery.json'),JSON.stringify(results,null,2));
 console.log(JSON.stringify(results.map(({name,errors,desktop,mobile})=>({name,errors,desktop,mobile})),null,2));
})().catch(e=>{console.error(e);process.exitCode=1});
