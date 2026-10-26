/* TEST_ONLY automatic process UI. No real model, Telegram, or external requests. */
const assert=require('assert/strict'),fs=require('fs'),path=require('path');
const {spawn}=require('child_process'),{chromium}=require('playwright');
const root=path.resolve(__dirname,'..'),out=path.join(__dirname,'qa-auto'),base='http://127.0.0.1:8808';fs.mkdirSync(out,{recursive:true});
const data=fs.mkdtempSync(path.join(out,'TEST_ONLY-auto-')),checks=[],errors=[],external=[];let browser,server,serverOutput='';
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function check(name,fn){await fn();checks.push({name,status:'pass'});}
(async()=>{
  server=spawn(process.env.LAB_TEST_PYTHON||'python',['-B',path.join(__dirname,'ui_auto_server.py'),'--data-dir',data],{cwd:root,windowsHide:true,env:{...process.env,PYTHONPATH:root,PYTHONUTF8:'1'}});server.stdout.on('data',data=>serverOutput+=data);server.stderr.on('data',data=>serverOutput+=data);
  for(let i=0;i<80;i++){try{if((await fetch(base+'/api/health')).ok)break;}catch{}if(server.exitCode!==null)throw Error(serverOutput);await sleep(100);}
  browser=await chromium.launch({headless:true,channel:'chrome'});const context=await browser.newContext({viewport:{width:1440,height:1100},locale:'ru-RU',reducedMotion:'reduce',serviceWorkers:'block'});
  await context.route('**/*',route=>{const url=route.request().url();if(url.startsWith(base+'/'))return route.continue();external.push(url);return route.abort();});
  const page=await context.newPage();page.setDefaultTimeout(9000);page.on('pageerror',error=>errors.push(error.message));
  const stats=await (await fetch(base+'/__test__/stats')).json();await page.goto(base,{waitUntil:'networkidle'});await page.locator('[data-view="runs"]').click();
  for(const [index,title] of ['TEST_ONLY: поиск документов','TEST_ONLY: генерация изображений'].entries()){
    if(index===1)await page.route('**/api/runs/'+stats.run_ids[index]+'/card.png**',route=>route.abort());
    await page.locator('.run-row').filter({hasText:title}).click();await page.locator('.result-title').filter({hasText:title}).waitFor();await page.locator('.infographic-cover').waitFor();
    await check('Infographic topic '+index+' has visible cover before narrative and accessible full-size image',async()=>{
      assert.equal(await page.locator('.mechanism-details').evaluate(el=>el.open),false);assert.match(await page.locator('.infographic-cover h3').innerText(),/Сравнение · применение · границы/);await page.locator('.infographic-cover').scrollIntoViewIfNeeded();await page.waitForFunction(()=>{const image=document.querySelector('.infographic-image');return image?.complete&&image.naturalWidth>0;});
      const image=page.locator('.infographic-image');assert.equal(await image.getAttribute('loading'),'lazy');assert.match(await image.getAttribute('src'),index===0?/\/card\.png/:/\/card\.svg/);assert.equal(await page.locator('.infographic-full').getAttribute('href'),await image.getAttribute('src'));assert.match(await image.getAttribute('alt'),/Инфографика/);
      assert(await page.locator('.infographic-cover').evaluate(el=>Boolean(el.compareDocumentPosition(document.querySelector('.research-story'))&Node.DOCUMENT_POSITION_FOLLOWING)));await page.locator('.infographic-cover').screenshot({path:path.join(out,'TEST_ONLY-infographic-'+index+'-desktop.png')});
      await page.setViewportSize({width:390,height:844});const bounds=await image.boundingBox();assert(bounds.width<=390);assert(bounds.height<=951);assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await page.locator('.infographic-cover').screenshot({path:path.join(out,'TEST_ONLY-infographic-'+index+'-mobile.png')});await page.setViewportSize({width:1440,height:1100});
    });
    await page.locator('.mechanism-details>summary').click();await page.locator('.process-mechanism').waitFor();
    await check('Automatic topic '+index+' has a real process path and truthful package check',async()=>{
      assert.equal(await page.locator('.process-mechanism .replay-node').count(),5);assert.equal(await page.locator('.process-mechanism .replay-edge').count(),4);assert.equal(await page.locator('.replay-panel-title').count(),0);
      assert.match(await page.locator('.process-mechanism').innerText(),/не запись выполненного запуска/);assert(!((await page.locator('.process-mechanism').innerText()).includes('фиксированный выбор')));
      assert.equal(await page.locator('.publication-checks').getAttribute('data-publication-status'),index===0?'ready':'incomplete');assert.match(await page.locator('.publication-checks').innerText(),/научная достоверность.*не подтверждены/);
      if(index===1)assert.match(await page.locator('.publication-checks').innerText(),/источник.*фрагмент/);
      assert.equal(await page.locator('.metric-comparison').count(),0);assert(!((await page.locator('.result-evidence').innerText()).includes('Редакторская версия')));
      const presentation=await (await fetch(base+'/api/runs/'+stats.run_ids[index]+'/presentation')).json();assert.equal(presentation.visual.kind,'process_flow');assert.equal(presentation.visual_theme,'reader_infographic');assert.equal(presentation.provenance.mode,'model_structured');
    });
    await check('Process topic '+index+' marker travels the path and respects pause/reduced motion',async()=>{
      await page.emulateMedia({reducedMotion:'no-preference'});await page.locator('.replay-scene-button').nth(1).click();await page.locator('.replay-play').click();await sleep(160);const first=await page.locator('.replay-traveller').getAttribute('cy');await sleep(160);const second=await page.locator('.replay-traveller').getAttribute('cy');assert.notEqual(first,second);assert.equal(await page.locator('.replay-traveller').getAttribute('visibility'),'visible');await page.locator('.mechanism-details>summary').click();await page.waitForFunction(()=>document.querySelector('.replay-play')?.getAttribute('aria-pressed')==='false');await page.locator('.mechanism-details>summary').click();
      await page.emulateMedia({reducedMotion:'reduce'});await page.locator('.replay-play').click();assert.equal(await page.locator('.replay-play').getAttribute('aria-pressed'),'false');assert.equal(await page.locator('.replay-traveller').getAttribute('visibility'),'hidden');
    });
    await check('Process topic '+index+' is readable on desktop and mobile without graph scroll',async()=>{
      await page.locator('.process-mechanism').screenshot({path:path.join(out,'TEST_ONLY-process-'+index+'-desktop.png')});await page.setViewportSize({width:390,height:844});
      const metrics=await page.locator('.replay-viewport').evaluate(el=>({width:el.clientWidth,scroll:el.scrollWidth,doc:document.documentElement.scrollWidth,viewport:innerWidth}));assert(metrics.scroll<=metrics.width+1,JSON.stringify(metrics));assert(metrics.doc<=metrics.viewport+1,JSON.stringify(metrics));
      await page.locator('.process-mechanism').screenshot({path:path.join(out,'TEST_ONLY-process-'+index+'-mobile.png')});await page.setViewportSize({width:1440,height:1100});
    });
  }
  assert.equal((await (await fetch(base+'/__test__/stats')).json()).provider_dispatches,0);assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
})().catch(error=>{checks.push({name:'Automatic process UI acceptance',status:'fail',error:error.stack});process.exitCode=1;}).finally(async()=>{
  if(browser)await browser.close();if(server&&server.exitCode===null){try{await fetch(base+'/__test__/shutdown',{method:'POST'});}catch{}await Promise.race([new Promise(resolve=>server.once('exit',resolve)),sleep(3000)]);if(server.exitCode===null)server.kill();}
  fs.writeFileSync(path.join(out,'ui-auto-v08.json'),JSON.stringify({test_only:true,checks,provider_dispatches:0,real_telegram_calls:0,errors,external_requests:external},null,2));fs.writeFileSync(path.join(out,'ui-auto-server.txt'),serverOutput);console.log(JSON.stringify({passed:checks.filter(x=>x.status==='pass').length,failed:checks.filter(x=>x.status==='fail').length,errors},null,2));
});
