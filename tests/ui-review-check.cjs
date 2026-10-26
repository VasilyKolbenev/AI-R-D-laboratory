/* TEST_ONLY: isolated reader-first story/review QA. No real model or Telegram. */
const assert=require('assert/strict'),fs=require('fs'),path=require('path');
const {spawn}=require('child_process');const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..'),out=path.join(__dirname,'qa-output'),base='http://127.0.0.1:8799';
fs.mkdirSync(out,{recursive:true});const data=fs.mkdtempSync(path.join(out,'TEST_ONLY-review-'));
let server,browser,page,serverOutput='';const checks=[],errors=[],requests=[];
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function stats(){return (await fetch(base+'/__test__/stats')).json();}
async function current(){const s=await stats();return (await fetch(base+'/api/runs/'+s.run_id+'/review')).json();}
async function check(name,fn){await fn();checks.push({name,status:'pass'});}
async function noOverflow(){const metrics=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));assert(metrics.scroll<=metrics.width+1,JSON.stringify(metrics));}
async function post(url,body){const b=await (await fetch(base+'/api/bootstrap')).json();const r=await fetch(base+url,{method:'POST',headers:{'Content-Type':'application/json','X-Lab-Token':b.csrf},body:JSON.stringify(body)});return {status:r.status,value:await r.json()};}
(async()=>{
  server=spawn(process.env.LAB_TEST_PYTHON||'python',['-B',path.join(__dirname,'ui_review_server.py'),'--data-dir',data],{cwd:root,windowsHide:true,env:{...process.env,PYTHONPATH:root,PYTHONUTF8:'1'}});
  server.stdout.on('data',data=>serverOutput+=data);server.stderr.on('data',data=>serverOutput+=data);
  for(let i=0;i<80;i++){try{if((await fetch(base+'/api/health')).ok)break;}catch{}if(server.exitCode!==null)throw Error(serverOutput);await sleep(100);}
  browser=await chromium.launch({headless:true,channel:'chrome'});
  const context=await browser.newContext({viewport:{width:1440,height:1100},locale:'ru-RU',timezoneId:'Europe/Moscow',reducedMotion:'reduce',serviceWorkers:'block'});
  await context.route('**/*',route=>{const url=route.request().url();if(url.startsWith(base+'/'))return route.continue();requests.push(url);return route.abort();});
  page=await context.newPage();page.setDefaultTimeout(9000);page.on('pageerror',error=>errors.push(error.message));
  await page.goto(base,{waitUntil:'networkidle'});await page.locator('[data-view="runs"]').click();await page.locator('.run-row').filter({hasText:'TEST_ONLY: как использовать'}).click();await page.locator('.research-story').waitFor();
  await check('Reader story follows problem audience mechanism evidence limits resources takeaway',async()=>{
    const ids=await page.locator('.story-section').evaluateAll(items=>items.map(item=>item.dataset.storyId));
    assert.deepEqual(ids,['problem','audience','mechanism','findings','limitations','resources','takeaway']);
    assert.equal(await page.getByText('Решение для нашей лаборатории',{exact:false}).count(),0);
    assert.match(await page.locator('.publication-checks h3').innerText(),/Проверка редакторского комплекта/);assert(!((await page.locator('.publication-checks h3').innerText()).includes('Автоматическая')));
    assert.equal(await page.locator('.report-full').evaluate(element=>element.open),false);
    assert.equal((await stats()).provider_dispatches,0);await noOverflow();
  });
  await check('Technical tree remains available behind the infographic with a dashed unknown branch',async()=>{
    await page.locator('.mechanism-details>summary').click();
    await page.locator('.replay-viewport svg').waitFor({state:'visible'});assert((await page.locator('.replay-node').count())>=10);assert((await page.locator('.replay-edge.unavailable').count())>=2);
    assert.equal(await page.locator('[data-node-id="replay_new"]').getAttribute('visibility'),'hidden');
    assert.match(await page.locator('.replay-scene-text').innerText(),/истори|ветв/i);
    const collisions=await page.locator('.replay-viewport svg').evaluate(svg=>{const labels=[...svg.querySelectorAll('text')].filter(el=>el.closest('g')?.getAttribute('visibility')!=='hidden').map(el=>({text:el.textContent,box:el.getBoundingClientRect(),group:el.closest('g')?.dataset.nodeId}));return labels.flatMap((a,i)=>labels.slice(i+1).filter(b=>a.box.left<b.box.right&&b.box.left<a.box.right&&a.box.top<b.box.bottom&&b.box.top<a.box.bottom).map(b=>[a.text,b.text,a.group,b.group,a.box.toJSON(),b.box.toJSON()]));});assert.deepEqual(collisions,[]);
  });
  await check('Source metric charts use separate zero-based scales and link exact evidence',async()=>{
    const charts=page.locator('.metric-comparison');assert.equal(await charts.count(),2);assert.match(await page.locator('.metric-comparisons').innerText(),/не является новым измерением/);
    assert.deepEqual(await charts.first().locator('.metric-bar').evaluateAll(items=>items.map(item=>item.style.width)),['100%','40%']);assert.deepEqual(await charts.nth(1).locator('.metric-bar').evaluateAll(items=>items.map(item=>item.style.width)),['0%','100%']);
    assert.match(await charts.first().getByRole('img').getAttribute('aria-label'),/baseline — 100 GPU-ч/);assert.match(await charts.first().locator('.metric-conditions').innerText(),/только для проверки интерфейса/);
    await charts.first().locator('.metric-evidence a').click();assert(await page.locator('.review-evidence-section').evaluate(el=>el.open));assert(await page.locator('.review-disclosure').evaluate(el=>el.open));await page.locator('.review-evidence-section>summary').click();await page.locator('.review-disclosure>summary').click();await noOverflow();
  });
  await check('Reduced motion uses manual semantic scenes and reveals new data only online',async()=>{
    await page.locator('.replay-scene-button').last().click();assert.equal(await page.locator('[data-node-id="replay_new"]').getAttribute('visibility'),'visible');
    assert.match(await page.locator('.replay-scene-text').innerText(),/онлайн|новых запусков/i);
    await page.locator('.replay-mechanism').getByRole('button',{name:'Сначала',exact:true}).click();
    assert.equal(await page.locator('[data-node-id="replay_new"]').getAttribute('visibility'),'hidden');
    await page.locator('.replay-play').click();assert.equal(await page.locator('.replay-play').getAttribute('aria-pressed'),'false');
    assert.equal(await page.locator('.replay-traveller').getAttribute('visibility'),'hidden');
  });
  await check('Playback moves along recorded edges and can be paused',async()=>{
    await page.emulateMedia({reducedMotion:'no-preference'});await page.locator('.replay-scene-button').nth(1).click();await page.locator('.replay-play').click();await sleep(170);
    assert.equal(await page.locator('.replay-traveller').getAttribute('visibility'),'visible');const first=await page.locator('.replay-traveller').getAttribute('cx');await sleep(170);assert.notEqual(await page.locator('.replay-traveller').getAttribute('cx'),first);
    await page.locator('.replay-play').click();assert.equal(await page.locator('.replay-play').getAttribute('aria-pressed'),'false');await page.emulateMedia({reducedMotion:'reduce'});
  });
  await page.locator('.review-disclosure>summary').click();
  await check('Costs distinguish actual records related failure and unknown money',async()=>{
    assert.equal(await page.locator('.review-cost').count(),2);const text=await page.locator('.review-cost-section').innerText();assert.match(text,/Основное исследование/);assert.match(text,/Связанный проход/);assert.match(text,/неизвестен/);assert.match(text,/1\s?000/);
    assert.equal((await current()).current.body.costs.human_minutes,null);
    assert.match(await page.locator('.review-quality-total').innerText(),/7 \/ 10/);assert.match(await page.locator('.review-quality').innerText(),/не истинность|а не истинность/);
  });
  await check('Evidence remains attributed rather than silently becoming verified truth',async()=>{
    await page.locator('.review-evidence-section>summary').click();assert.equal(await page.locator('.review-evidence-item').count(),2);assert.match(await page.locator('.review-evidence-section').innerText(),/не независимое воспроизведение/);
    const href=await page.locator('.review-evidence-item .source-link').first().getAttribute('href');assert.equal(href,'https://example.org/TEST_ONLY-source');
    assert.equal(await page.evaluate(()=>window.__reviewInjected),undefined);
  });
  await check('Owner saves a research decision as a new review version without a model',async()=>{
    await page.locator('.review-editor>summary').click();await page.getByRole('button',{name:'+ Добавить решение',exact:true}).click();
    const form=page.locator('.review-form');const decision=page.locator('.review-decision-editors fieldset').last();
    await decision.locator('[data-review-field="decision-target"]').fill('TEST_ONLY: проверка переносимости авторского эффекта');await decision.locator('[data-review-field="decision-action"]').fill('Сравнить только совпадающие условия');await decision.locator('[data-review-field="decision-reason"]').fill('Различия в baseline могут объяснить результат.');await decision.locator('[data-review-field="decision-evidence-ids"]').fill('e1');
    await form.locator('[data-review-field="cost-notes"]').fill('TEST_ONLY: новая заметка, расходы не переоценивались.');const saved=page.waitForResponse(r=>r.url().includes('/review')&&r.request().method()==='POST');await form.locator('button[type="submit"]').click();assert((await saved).ok());
    await page.waitForFunction(()=>document.querySelector('.review-history>summary')?.textContent.includes('· 2'));const result=await current();assert.equal(result.current.version,2);assert.equal(result.current.body.decisions.length,2);assert.equal(result.current.body.editorial.comparisons.length,2);assert.equal(result.current.body.editorial.comparisons[0].result_value,40);assert.equal(result.history.length,2);assert.equal((await stats()).provider_dispatches,0);
    await page.locator('.review-disclosure>summary').click();await page.locator('.review-history>summary').click();assert.match(await page.locator('.review-history').innerText(),/Версия 1/);assert.match(await page.locator('.review-history').innerText(),/Версия 2/);
  });
  await check('Stale versions and missing evidence are rejected without corrupting the journal',async()=>{
    const value=await current(),s=await stats();const stale=await post('/api/runs/'+s.run_id+'/review',{expected_version:1,body:value.current.body});assert.equal(stale.status,400);
    const bad=structuredClone(value.current.body);bad.decisions[0].evidence_ids=['missing'];assert.equal((await post('/api/runs/'+s.run_id+'/review',{expected_version:2,body:bad})).status,400);assert.equal((await current()).current.version,2);
    await page.locator('.review-disclosure').screenshot({path:path.join(out,'TEST_ONLY-review-v07-journal.png')});
  });
  await check('Editorial form regenerates the public story without lab adoption framing',async()=>{
    await page.locator('.review-editor>summary').click();await page.locator('.review-editorial>summary').click();await page.locator('[data-review-field="editorial-public_takeaway"]').fill('TEST_ONLY: проверить свою задачу и baseline до переноса чисел авторов.');
    const add=page.getByRole('button',{name:'+ Добавить сравнение метрики',exact:true});await add.click();assert(await add.isDisabled());await page.locator('.review-comparison-editors fieldset').last().getByRole('button',{name:'Удалить сравнение из новой версии',exact:true}).click();assert.equal(await page.locator('.review-comparison-editors fieldset').count(),2);assert(!(await add.isDisabled()));
    await page.locator('.review-comparison-editors fieldset').first().locator('[data-review-field="comparison-result_value"]').fill('45');
    const saved=page.waitForResponse(r=>r.url().includes('/review')&&r.request().method()==='POST');await page.locator('.review-form button[type="submit"]').click();assert((await saved).ok());await page.waitForFunction(()=>document.querySelector('.story-section-takeaway')?.textContent.includes('TEST_ONLY: проверить свою задачу'));assert.match(await page.locator('.story-section-takeaway').innerText(),/TEST_ONLY: проверить свою задачу/);
    assert.equal((await current()).current.version,3);assert.equal((await current()).current.body.editorial.comparisons[0].result_value,45);assert.deepEqual(await page.locator('.metric-comparison').first().locator('.metric-bar').evaluateAll(items=>items.map(item=>item.style.width)),['100%','45%']);await page.locator('.result-post>summary').click();const post=await page.locator('.result-post-text').inputValue();assert(post.indexOf('ПРОБЛЕМА')<post.indexOf('КАК РАБОТАЕТ'));assert.match(post,/Источники/);assert(!post.includes('нашей лаборатории'));
  });
  await check('Desktop and mobile preserve readable story and contain SVG scrolling',async()=>{
    await page.evaluate(()=>window.scrollTo(0,0));await noOverflow();await page.screenshot({path:path.join(out,'TEST_ONLY-review-v07-desktop.png'),fullPage:true});
    await page.locator('.metric-comparisons').screenshot({path:path.join(out,'TEST_ONLY-review-v07-metrics-desktop.png')});
    await page.setViewportSize({width:390,height:844});await noOverflow();await page.locator('.replay-viewport').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,'TEST_ONLY-review-v07-mobile.png'),fullPage:true});
    await page.locator('.metric-comparisons').screenshot({path:path.join(out,'TEST_ONLY-review-v07-metrics-mobile.png')});
    const graph=await page.locator('.replay-viewport').evaluate(el=>({client:el.clientWidth,scroll:el.scrollWidth}));assert(graph.scroll>graph.client);assert.equal((await stats()).provider_dispatches,0);assert.deepEqual(errors,[]);assert.deepEqual(requests,[]);
  });
})().catch(error=>{checks.push({name:'Reader/review UI acceptance',status:'fail',error:error.stack});process.exitCode=1;}).finally(async()=>{
  if(browser)await browser.close();if(server&&server.exitCode===null){try{await fetch(base+'/__test__/shutdown',{method:'POST'});}catch{}await Promise.race([new Promise(resolve=>server.once('exit',resolve)),sleep(3000)]);if(server.exitCode===null)server.kill();}
  const result={test_only:true,checks,provider_dispatches:0,real_telegram_calls:0,errors,external_requests:requests};fs.writeFileSync(path.join(out,'ui-review-v07.json'),JSON.stringify(result,null,2));fs.writeFileSync(path.join(out,'ui-review-server.txt'),serverOutput);console.log(JSON.stringify({passed:checks.filter(x=>x.status==='pass').length,failed:checks.filter(x=>x.status==='fail').length,errors},null,2));
});
