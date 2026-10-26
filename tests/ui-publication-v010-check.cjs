/* TEST_ONLY: publication settings against an in-memory fake API. No server, providers or Telegram. */
const {chromium}=require('playwright'),fs=require('fs'),path=require('path'),assert=require('assert/strict');
const root=path.resolve(__dirname,'..'),out=path.join(__dirname,'qa-publication'),base='http://127.0.0.1:8811';
const errors=[],unexpected=[],posts=[],cancellations=[],channels=[],checks=[];let browser,failSave=false,failChannel=false;
let publication={enabled:false,timezone:'Europe/Moscow',slots:[],channel_configured:false,channel_title:null,items:[],next_slot:null,blocked_reason:'Канал не подключён; отправка заблокирована.'};
const boot={csrf:'TEST_ONLY_csrf',version:'TEST_ONLY',settings:{provider:'codex',model:'',timeout_seconds:180,daily_run_limit:3,web_search:false},providers:[],telegram:{configured:false},counts:{sources:0,runs:0,knowledge:0}};
async function check(name,work){await work();checks.push({name,status:'pass'});}
(async()=>{try{
 fs.mkdirSync(out,{recursive:true});browser=await chromium.launch({headless:true,channel:'chrome'});
 const context=await browser.newContext({viewport:{width:1400,height:1000},locale:'ru-RU',serviceWorkers:'block'});
 await context.route('**/*',async route=>{
   const req=route.request(),url=new URL(req.url());
   if(url.origin!==base){unexpected.push(req.url());return route.abort();}
   const p=url.pathname;
   if(req.method()==='POST'){
     if(p==='/api/publication/channel'){
       const body=req.postDataJSON();channels.push(body);
       if(failChannel){failChannel=false;return route.fulfill({status:400,contentType:'application/json',body:JSON.stringify({error:'TEST_ONLY: у бота нет права публикации'})});}
       publication={...publication,channel_configured:true,channel_title:'TEST_ONLY Frontier',blocked_reason:'Готовые выпуски требуют апрува для выбранного канала.'};
       return route.fulfill({contentType:'application/json',body:JSON.stringify(publication)});
     }
     if(p==='/api/publication/TEST_ONLY/cancel'){
       cancellations.push(req.postDataJSON());publication.items=publication.items.map(item=>item.id==='TEST_ONLY'?{...item,status:'cancelled'}:item);
       return route.fulfill({contentType:'application/json',body:JSON.stringify({status:'cancelled'})});
     }
     if(p!=='/api/publication/settings'){unexpected.push(req.method()+' '+p);return route.fulfill({status:400,contentType:'application/json',body:'{"error":"Unexpected mutation"}'});}
     const body=req.postDataJSON();posts.push(body);
     if(failSave){failSave=false;return route.fulfill({status:400,contentType:'application/json',body:JSON.stringify({error:'TEST_ONLY: сохранение отклонено'})});}
     publication={...publication,...body};return route.fulfill({contentType:'application/json',body:JSON.stringify(publication)});
   }
   const file=p==='/'?'index.html':p==='/assets/app.js'?'app.js':p==='/assets/style.css'?'style.css':null;
   if(file)return route.fulfill({contentType:file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html',body:fs.readFileSync(path.join(root,'laboratory/web',file))});
   let data=p==='/api/bootstrap'?boot:p==='/api/publication'?publication:p==='/api/memory'?{profile:{version:1,review_days:30},corrections:[]}:p==='/api/study/schema'?{task_types:[],evidence_levels:[],template:{}}:{items:[]};
   return route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
 });
 const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));page.setDefaultTimeout(9000);
 await page.goto(base,{waitUntil:'networkidle'});await page.locator('[data-view="settings"]').click();await page.locator('#publication-enabled').waitFor();
 await check('Empty settings explicitly block disconnected channel without preset schedule',async()=>{
   await page.waitForFunction(()=>!document.querySelector('#publication-enabled').disabled);
   assert.match(await page.locator('#publication-status').innerText(),/Канал не подключён/);
   assert.match(await page.locator('#publication-status').innerText(),/Расписание не задано/);
   assert.equal(await page.locator('.publication-slot').count(),0);assert.equal(await page.locator('#publication-enabled').isChecked(),false);
 });
 await check('Refreshing queue preserves unsaved schedule and no mutation occurs until save',async()=>{
   await page.locator('#publication-add-slot').click();await page.locator('[data-publication-field="weekday"]').selectOption('4');await page.locator('[data-publication-field="time"]').fill('12:15');await page.locator('#publication-enabled').check();
   publication.items=[{id:'TEST_ONLY',title:'<script>TEST_ONLY</script>',status:'queued',due_at:null,approved_at:'2026-10-21T12:00:00Z',blockers:['Канал не подключён']}];
   await page.locator('#publication-refresh').click();await page.locator('.publication-entry').waitFor();
   assert.equal(await page.locator('[data-publication-field="time"]').inputValue(),'12:15');assert.equal(await page.locator('[data-publication-field="weekday"]').inputValue(),'4');assert.equal(await page.locator('#publication-enabled').isChecked(),true);assert.equal(posts.length,0);
   assert.match(await page.locator('.publication-entry').innerText(),/<script>TEST_ONLY<\/script>/);assert.equal(await page.locator('.publication-entry script').count(),0);
 });
 await check('Save only updates schedule settings and still reports no channel sends',async()=>{
   await page.locator('#publication-form button[type="submit"]').click();await page.waitForFunction(()=>document.querySelector('#publication-edit-state').textContent==='');
   assert.deepEqual(posts,[{enabled:true,slots:[{weekday:4,time:'12:15'}]}]);assert.deepEqual(publication.slots,[{weekday:4,time:'12:15'}]);
   assert.match(await page.locator('#toast').innerText(),/Канал не подключён/);assert.match(await page.locator('#publication-status').innerText(),/отправок в канал не будет/);
 });
 await check('Failed save preserves edited fields and enables correction without an implicit retry',async()=>{
   await page.locator('[data-publication-field="time"]').fill('13:20');failSave=true;
   await page.locator('#publication-form button[type="submit"]').click();await page.waitForFunction(()=>document.querySelector('#toast').textContent.includes('сохранение отклонено'));
   assert.equal(await page.locator('[data-publication-field="time"]').inputValue(),'13:20');assert.equal(await page.locator('[data-publication-field="time"]').isDisabled(),false);assert.equal(posts.length,2);assert.equal(publication.slots[0].time,'12:15');
   await page.locator('#publication-refresh').click();assert.equal(await page.locator('[data-publication-field="time"]').inputValue(),'13:20');
 });
 await check('Mobile layout fits and an added empty slot does not imply a chosen time',async()=>{
   await page.locator('#publication-add-slot').click();assert.equal(await page.locator('[data-publication-field="weekday"]').nth(1).inputValue(),'');assert.equal(await page.locator('[data-publication-field="time"]').nth(1).inputValue(),'');
   await page.setViewportSize({width:390,height:844});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
   await page.locator('.publication-settings').screenshot({path:path.join(out,'TEST_ONLY-publication-mobile.png')});
 });
 await check('Removing a queued publication sends one cancel request and keeps saved research untouched',async()=>{
   const cancel=page.locator('.publication-entry button').filter({hasText:'Убрать из очереди'});
   assert.equal(await cancel.count(),1);await cancel.click();
   await page.waitForFunction(()=>document.querySelector('.publication-entry')?.textContent.includes('Отменён'));
   assert.deepEqual(cancellations,[{}]);assert.equal(await cancel.count(),0);
   await page.locator('#publication-refresh').click();assert.deepEqual(cancellations,[{}]);assert.equal(posts.length,2);
 });
 await check('Channel URLs and unsafe IDs are rejected locally without a connection request',async()=>{
   for(const value of ['https://t.me/VVFrontier','-9007199254740992']){
     await page.locator('#publication-channel').fill(value);await page.locator('#publication-channel-form button[type="submit"]').click();
     assert.equal(await page.locator('#publication-channel').inputValue(),value);assert.equal(channels.length,0);
     assert.match(await page.locator('#publication-channel-feedback').innerText(),/Укажите @username/);
   }
 });
 await check('Failed channel check preserves its input and never retries or changes schedule',async()=>{
   await page.locator('#publication-channel').fill('@VVFrontier');failChannel=true;
   await page.locator('#publication-channel-form button[type="submit"]').click();
   await page.waitForFunction(()=>document.querySelector('#publication-channel-feedback').textContent.includes('нет права публикации'));
   assert.equal(await page.locator('#publication-channel').inputValue(),'@VVFrontier');assert.equal(await page.locator('#publication-channel').isDisabled(),false);
   assert.deepEqual(channels,[{channel:'@VVFrontier'}]);assert.equal(publication.channel_configured,false);assert.equal(posts.length,2);
 });
 await check('Successful channel connection preserves unsaved slots and sends only the target',async()=>{
   await page.locator('#publication-channel-form button[type="submit"]').click();
   await page.waitForFunction(()=>document.querySelector('#publication-status').textContent.includes('TEST_ONLY Frontier'));
   assert.deepEqual(channels,[{channel:'@VVFrontier'},{channel:'@VVFrontier'}]);
   assert.equal(await page.locator('[data-publication-field="time"]').first().inputValue(),'13:20');assert.equal(await page.locator('.publication-slot').count(),2);
   assert.equal(publication.enabled,true);assert.deepEqual(publication.slots,[{weekday:4,time:'12:15'}]);assert.equal(posts.length,2);assert.deepEqual(cancellations,[{}]);
   assert.match(await page.locator('#publication-channel-feedback').innerText(),/требуют вашего апрува/);
 });
 await check('Strict negative channel ID is sent as a safe integer and mobile layout still fits',async()=>{
   await page.locator('#publication-channel').fill('-1001234567890');await page.locator('#publication-channel-form button[type="submit"]').click();
   await page.waitForFunction(()=>document.querySelector('#publication-channel-feedback').textContent.includes('Канал подключён'));
   assert.deepEqual(channels[2],{channel:-1001234567890});assert.equal(typeof channels[2].channel,'number');assert.equal(posts.length,2);
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
   await page.locator('.publication-settings').screenshot({path:path.join(out,'TEST_ONLY-channel-mobile.png')});
 });
 assert.deepEqual(errors,[]);assert.deepEqual(unexpected,[]);
 fs.writeFileSync(path.join(out,'ui-publication-v0101.json'),JSON.stringify({checks,errors,unexpected,provider_calls:0,telegram_calls:0,channel_sends:0},null,2));
 console.log(JSON.stringify({passed:checks.length,errors,unexpected,provider_calls:0,telegram_calls:0}));
}finally{if(browser)await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
