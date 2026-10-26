/* TEST_ONLY: fresh isolated browser, local fixture, no user data or paid calls. */
const assert=require('assert/strict');
const fs=require('fs');
const path=require('path');
const {spawn}=require('child_process');
const {chromium}=require('playwright');
const base='http://127.0.0.1:8798';
const root=path.resolve(__dirname,'..');
const out=path.join(__dirname,'qa-output');
fs.mkdirSync(out,{recursive:true});
const data=fs.mkdtempSync(path.join(out,'TEST_ONLY-results-data-'));
let server,browser,page,serverOutput='';
const checks=[],errors=[],blockedRequests=[];
let presentationRequests=0;
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function check(name,fn){await fn();checks.push({name,status:'pass'});}
async function stats(){return (await fetch(base+'/__test__/stats')).json();}
async function noOverflow(){assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);}
async function nav(view){await page.locator('.nav-button[data-view="'+view+'"]').click();}
async function openRun(id){await nav('runs');await page.locator('.run-row').filter({hasText:id==='plan'?'TEST_ONLY: новый план':'TEST_ONLY: где полезен'}).click();}
(async()=>{
  server=spawn(process.env.LAB_TEST_PYTHON||'python',['-B',path.join(__dirname,'ui_results_server.py'),'--data-dir',data],{cwd:root,windowsHide:true,env:{...process.env,PYTHONPATH:root,PYTHONUTF8:'1'}});
  server.stdout.on('data',chunk=>serverOutput+=chunk);
  server.stderr.on('data',chunk=>serverOutput+=chunk);
  for(let i=0;i<80;i++){try{if((await fetch(base+'/api/health')).ok)break;}catch{}if(server.exitCode!==null)throw Error(serverOutput);await sleep(100);}
  browser=await chromium.launch({headless:true,channel:'chrome'});
  const context=await browser.newContext({viewport:{width:1440,height:1100},locale:'ru-RU',timezoneId:'Europe/Moscow',reducedMotion:'reduce',serviceWorkers:'block'});
  await context.route('**/*',route=>{const url=route.request().url();if(url.startsWith(base+'/'))return route.continue();blockedRequests.push(url);return route.abort();});
  page=await context.newPage();page.setDefaultTimeout(8000);
  page.on('pageerror',error=>errors.push(error.message));
  page.on('request',request=>{if(request.url().endsWith('/presentation'))presentationRequests++;});
  await page.goto(base,{waitUntil:'networkidle'});
  await openRun('completed');
  await page.locator('.result-overview').waitFor();
  await check('Decision summary and six evidence cards replace the initial text wall',async()=>{
    assert.equal(await page.locator('.result-fact').count(),6);
    assert.equal(await page.locator('.report-full').evaluate(element=>element.open),false);
    assert.equal(await page.locator('.result-overview').innerText().then(text=>text.includes('Анализ источников')),true);
    assert.equal((await stats()).provider_dispatches,0);
    await noOverflow();
  });
  await check('Long research question remains complete behind a collapsed disclosure and in export',async()=>{
    const fixture=await stats();
    const saved=await (await fetch(base+'/api/runs/'+fixture.run_id)).json();
    assert(saved.plan.question.length>1400);
    assert((await page.locator('#run-detail>.report-heading h2').innerText()).length<=180);
    assert.equal(await page.locator('.report-question').evaluate(element=>element.open),false);
    assert.equal(await page.locator('.report-question .memory-literal').textContent(),saved.plan.question);
    assert((await page.locator('.run-row.active .item-title').innerText()).length<=180);
    assert.equal(await page.locator('.run-row.active .item-title').getAttribute('title'),saved.plan.question);
    await page.locator('.report-question>summary').click();
    assert((await page.locator('.report-question .memory-literal').innerText()).endsWith('TEST_ONLY_END_OF_FULL_QUESTION'));
    await page.locator('.report-question>summary').click();
    const download=page.waitForEvent('download');
    await page.getByRole('button',{name:'Скачать отчёт ↓',exact:true}).click();
    const file=await download;
    const content=fs.readFileSync(await file.path(),'utf8');
    assert(content.startsWith('# '+saved.plan.question+'\n\n'));
    assert.equal((await stats()).provider_dispatches,0);
  });
  await check('Legacy report, script text and protocol blocks render safely',async()=>{
    await page.locator('.report-full>summary').click();
    await page.locator('.report-text').waitFor({state:'visible'});
    assert.equal(await page.evaluate(()=>window.__resultExecuted),undefined);
    assert.equal(await page.locator('.report-text').innerText().then(text=>text.includes('lab_memory_review')),false);
    assert.equal(await page.locator('.result-presentation').innerText().then(text=>text.includes('ранее сохранённого отчёта')),true);
    await page.locator('.report-full>summary').click();
  });
  await check('Reduced motion uses manual explanation steps',async()=>{
    assert.equal(await page.locator('.storyboard-step').count(),3);
    await page.locator('.storyboard-play').click();
    assert.equal(await page.locator('.storyboard-step').nth(1).getAttribute('aria-pressed'),'true');
    assert.equal(await page.locator('.storyboard-play').getAttribute('aria-pressed'),'false');
  });
  await check('Refreshing an unchanged run preserves visual state and avoids regeneration',async()=>{
    const requests=presentationRequests;
    await page.locator('#refresh-button').click();
    await page.waitForFunction(()=>document.querySelector('#toast').textContent.includes('Данные обновлены'));
    assert.equal(await page.locator('.storyboard-step').nth(1).getAttribute('aria-pressed'),'true');
    assert.equal(presentationRequests,requests);
  });
  await check('Animation has explicit play and pause',async()=>{
    await page.emulateMedia({reducedMotion:'no-preference'});
    await page.locator('.storyboard-play').click();
    assert.equal(await page.locator('.storyboard-play').getAttribute('aria-pressed'),'true');
    await page.locator('.storyboard-play').click();
    assert.equal(await page.locator('.storyboard-play').getAttribute('aria-pressed'),'false');
  });
  await check('Channel draft is editable and local-only until explicitly sent',async()=>{
    await page.locator('.result-post>summary').click();
    assert((await page.locator('.result-post-text').inputValue()).length>30);
    await page.locator('.result-post-text').fill('TEST_ONLY: редактируемый черновик без публикации');
    assert.equal((await stats()).result_deliveries,0);
    assert.equal(await page.getByRole('button',{name:/опубликовать/i}).count(),0);
    assert.equal(await page.locator('.result-export-row a').count()>=1,true);
  });
  await check('Owner explicitly requests delivery through the CSRF protected endpoint',async()=>{
    await page.getByRole('button',{name:'Отправить результат мне в Telegram',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('#toast').textContent.includes('Результат передан'));
    assert.equal((await stats()).result_deliveries,1);
    assert.equal((await stats()).provider_dispatches,0);
  });
  await page.evaluate(()=>scrollTo(0,0));
  await page.screenshot({path:path.join(out,'TEST_ONLY-result-desktop.png'),fullPage:true});
  await check('Mobile reading has no horizontal overflow',async()=>{
    await page.setViewportSize({width:390,height:844});await noOverflow();
    await page.screenshot({path:path.join(out,'TEST_ONLY-result-mobile.png'),fullPage:true});
  });
  await check('A prepared plan can be delivered for approval without a provider dispatch',async()=>{
    await openRun('plan');await page.getByRole('button',{name:'План в Telegram',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('#toast').textContent.includes('План передан'));
    assert.equal((await stats()).plan_deliveries,1);
    assert.equal((await stats()).provider_dispatches,0);
  });
  assert.deepEqual(errors,[]);assert.deepEqual(blockedRequests,[]);
  console.log(JSON.stringify({test_only:true,checks,provider_dispatches:0,errors,blockedRequests},null,2));
  fs.writeFileSync(path.join(out,'ui-results-v06.json'),JSON.stringify({test_only:true,checks,provider_dispatches:0,errors,blockedRequests},null,2));
})().catch(error=>{console.error(error.stack);process.exitCode=1;}).finally(async()=>{
  if(browser)await browser.close();
  try{await fetch(base+'/__test__/shutdown',{method:'POST'});}catch{}
  if(server&&server.exitCode===null)await Promise.race([new Promise(resolve=>server.once('exit',resolve)),sleep(1500)]);
  if(server&&server.exitCode===null)server.kill();
});
