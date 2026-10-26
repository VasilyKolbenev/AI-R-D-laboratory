/* TEST_ONLY: isolated browser rendering with intercepted, read-only fixtures.
 * No local server, live records, provider calls, Telegram, or mutations. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..'),out=path.join(__dirname,'qa-reviewed'),base='http://127.0.0.1:8813';
const requests=[],unexpected=[],errors=[],checks=[];
let browser,page;
const protocol={version:'three-pass-v1',roles:['researcher','critic','reviewer'],web_search_roles:['researcher','critic'],max_calls:3,total_timeout_seconds:240,phase_timeouts:[100,60,60]};
const analogue={id:'TEST_ONLY_memory',version:7,title:'TEST_ONLY прежний вывод о памяти агентов',claim:'TEST_ONLY: результат зависит от состава данных; эффект переноса неизвестен.',effective_status:'active',study_scope:{title:'TEST_ONLY обработка документов',dataset:'TEST_ONLY архив A',conditions:'TEST_ONLY другая модель и нагрузка'}};
const metric={id:'metric_1',name:'TEST_ONLY задержка p95',definition:'TEST_ONLY время ответа при фиксированной нагрузке',unit:'ms',direction:'minimize',target:'120',expected:'unknown',evidence_level:'unknown',evidence_url:'',primary:true};
const comparison={version:'applied-context-v1',metric_checklist:[metric],baseline:{name:'TEST_ONLY текущий поиск',version:'v1'},conditions:{dataset:'TEST_ONLY архив B',evaluation:'unknown'},analogues:[{memory_id:analogue.id,memory_version:analogue.version,title:analogue.title,claim:analogue.claim,study_scope:analogue.study_scope,effective_status:'active',trust:'previous_claim_not_new_external_evidence'}],notices:['TEST_ONLY: память не является новым внешним измерением.']};
const plan={question:'TEST_ONLY: сравнить технологию с baseline по p95 и условиям применения',provider:'codex',model:'',web_search:true,timeout_seconds:240,research_mode:'reviewed',research_protocol:protocol,comparison_context:comparison,sources:[{id:'TEST_ONLY_source',title:'TEST_ONLY материал о памяти агентов',text:'TEST_ONLY исходный текст'}],memory:{enabled:true,profile:null,corrections:[],items:[analogue],lessons:[],notices:[]},memory_options:{enabled:true,selected_ids:[analogue.id],lesson_ids:[],include_profile:false,include_corrections:false}};
const rows=[{id:'metric_1',metric:metric.name,definition:metric.definition,unit:'ms',direction:'minimize',baseline:{label:'TEST_ONLY текущий поиск',value:120,basis:'author_claim',evidence_ids:['e1']},candidate:{label:'TEST_ONLY технология',value:null,basis:'unknown',evidence_ids:[]},conditions:'TEST_ONLY: иные данные и оборудование; p95 кандидата не раскрыт.',comparability:'not_comparable',comparability_reason:'TEST_ONLY: одинаковые условия не подтверждены.'}];
const applied={version:'applied-comparison-v1',rows,unknowns:['TEST_ONLY: фактический p95 кандидата неизвестен.'],analogues:[{memory_id:analogue.id,memory_version:7,relation:'context',relevance:'TEST_ONLY общая задача памяти',conditions_difference:'TEST_ONLY другой архив и модель'}]};
const review={status:'incomplete',notice:'TEST_ONLY: модельная редакционная проверка, без научного доказательства.',issues:['TEST_ONLY: критическое замечание осталось открытым.'],critic:{version:'critic-review-v1',issues:[{id:'i1',severity:'blocker',target:'report',problem:'TEST_ONLY: сравнение без общей конфигурации не подтверждает ускорение.',evidence_ids:['e1'],required_change:'TEST_ONLY: убрать обещание ускорения.'}]},dispositions:[{issue_id:'i1',status:'unresolved',reason:'TEST_ONLY: внешних измерений нет.'}],applied_analysis:applied};
const phases=protocol.roles.map((role,index)=>({index,role,status:'completed',dispatched:true,elapsed_seconds:10+index,usage:{input_tokens:100+index,output_tokens:50+index},prompt:'TEST_ONLY точный запрос '+role,output:'TEST_ONLY сохранённый ответ '+role}));
const runs=[{id:'TEST_ONLY_plan',status:'planned',plan,plan_hash:'TEST_ONLY_frozen_plan',created_at:'2026-10-23T09:00:00Z',output:''},{id:'TEST_ONLY_result',status:'completed',plan,plan_hash:'TEST_ONLY_frozen_result',created_at:'2026-10-23T09:00:00Z',finished_at:'2026-10-23T09:03:00Z',output:'TEST_ONLY полный сохранённый отчёт.',agent_pipeline:{version:protocol.version,reserved_calls:3,dispatched_calls:3,total_timeout_seconds:240,elapsed_seconds:33,phases},agent_review:review}];
const boot={csrf:'TEST_ONLY_csrf',version:'TEST_ONLY',settings:{provider:'codex',model:'',timeout_seconds:240,daily_run_limit:3,research_mode:'reviewed',web_search:false},providers:[],telegram:{configured:false},counts:{sources:0,runs:2,knowledge:0}};
const svg='<svg xmlns="http://www.w3.org/2000/svg" width="960" height="500" viewBox="0 0 960 500"><rect width="960" height="500" fill="#152c39"/><text x="45" y="85" fill="#d8e9e3" font-size="32">TEST_ONLY reviewed research</text></svg>';
function resultPresentation(){return {title:'TEST_ONLY прикладное сравнение',story:[{id:'takeaway',title:'TEST_ONLY вывод',text:'TEST_ONLY: данных для обещания ускорения недостаточно.'}],applied_analysis:applied,agent_review:review,publication_checks:{status:'incomplete',issues:review.issues},next_step:'TEST_ONLY: уточнить общую конфигурацию.',post_text:'TEST_ONLY: текст публикации без служебного журнала.',visual:{png_available:false},provenance:{editorial_version:1}};}
async function routeRequest(route){
  const request=route.request(),url=new URL(request.url()),p=url.pathname;requests.push({method:request.method(),path:p});
  if(url.origin!==base||request.method()!=='GET'){unexpected.push(request.method()+' '+request.url());return route.abort();}
  const file=p==='/'?'index.html':p==='/assets/app.js'?'app.js':p==='/assets/style.css'?'style.css':null;
  if(file)return route.fulfill({contentType:file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html',body:fs.readFileSync(path.join(root,'laboratory/web',file))});
  if(p==='/favicon.ico')return route.fulfill({status:204,body:''});
  let data;
  if(p==='/api/bootstrap')data=boot;
  else if(p==='/api/sources'||p==='/api/tasks')data={items:[]};
  else if(p==='/api/runs')data={items:runs};
  else if(p==='/api/memory')data={profile:{version:1,review_days:30},corrections:[]};
  else if(p==='/api/study/schema')data={task_types:[],evidence_levels:[],template:{}};
  else if(p==='/api/review/schema')data={criteria:[],template:{}};
  else{const match=p.match(/^\/api\/runs\/(TEST_ONLY_(?:plan|result))(?:\/(presentation|review|agents|card\.svg))?$/),run=match&&runs.find(item=>item.id===match[1]);
    if(run){if(!match[2])data=run;else if(match[2]==='presentation')data=resultPresentation();else if(match[2]==='review')data={current:null,history:[],costs:{}};else if(match[2]==='agents')data={run_id:run.id,status:run.status,version:protocol.version,reserved_calls:3,dispatched_calls:3,phases,review};else if(match[2]==='card.svg')return route.fulfill({contentType:'image/svg+xml',body:svg});}}
  if(data!==undefined)return route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
  unexpected.push(request.method()+' '+request.url());return route.fulfill({status:400,contentType:'application/json',body:'{"error":"TEST_ONLY unexpected request"}'});
}
async function check(name,work){await work();checks.push({name,status:'pass'});}
async function fits(selector){assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true,'page overflow');assert.equal(await page.locator(selector).evaluate(element=>{const r=element.getBoundingClientRect();return r.width>0&&r.left>=-1&&r.right<=innerWidth+1;}),true,selector+' outside viewport');}
(async()=>{try{
  fs.mkdirSync(out,{recursive:true});browser=await chromium.launch({headless:true,channel:'chrome'});
  const context=await browser.newContext({viewport:{width:1440,height:1100},locale:'ru-RU',timezoneId:'Europe/Moscow',reducedMotion:'reduce',serviceWorkers:'block'});await context.route('**/*',routeRequest);
  page=await context.newPage();page.setDefaultTimeout(9000);page.on('pageerror',error=>errors.push(error.message));page.on('console',message=>{if(message.type()==='error')errors.push(message.text());});
  await page.goto(base,{waitUntil:'networkidle'});await page.locator('.nav-button[data-view="runs"]').click();
  await check('Desktop and mobile approval show 3 calls, total/role deadlines, web permissions and exact selected analogue',async()=>{
    // Render the immutable read-only fixture directly. All POST routes stay blocked.
    await page.evaluate(run=>showApproval(run),runs[0]);
    const summary=page.locator('#approval-summary');for(const text of ['3 / 3 за 24 часа','240 сек.','до 100 сек.','Критик','Рецензент и редактор','TEST_ONLY_memory','v7',analogue.claim])assert.ok((await summary.textContent()).includes(text),text);
    await fits('#approval-dialog');await page.screenshot({path:path.join(out,'TEST_ONLY-reviewed-approval-desktop.png'),fullPage:true});
    await page.setViewportSize({width:390,height:844});await fits('#approval-dialog');await page.screenshot({path:path.join(out,'TEST_ONLY-reviewed-approval-mobile.png'),fullPage:true});await page.locator('.approval-comparison').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,'TEST_ONLY-reviewed-approval-memory-mobile.png'),fullPage:true});
    await page.locator('#approval-dialog [data-close]').first().click();
  });
  await check('Results preserve unknown values, incompatible conditions and visible critic disposition on desktop and mobile',async()=>{
    await page.locator('.run-row').filter({has:page.locator('.status-badge.completed')}).click();
    await page.locator('.applied-table').waitFor();
    const table=await page.locator('.applied-table').innerText();for(const text of ['Неизвестно','Несопоставимы','120 ms','TEST_ONLY: одинаковые условия не подтверждены.'])assert.ok(table.includes(text),text);
    await page.locator('.agent-review>summary').click();assert.ok((await page.locator('.agent-review').innerText()).includes('Не устранено: TEST_ONLY: внешних измерений нет.'));
    await fits('.applied-table-scroll');await fits('.applied-table tbody td:last-child');await page.locator('.applied-analysis').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,'TEST_ONLY-reviewed-result-mobile.png'),fullPage:true});await page.locator('.applied-analysis').screenshot({path:path.join(out,'TEST_ONLY-reviewed-comparison-mobile.png')});
    await page.setViewportSize({width:1440,height:1100});await fits('.applied-table-scroll');await page.screenshot({path:path.join(out,'TEST_ONLY-reviewed-result-desktop.png'),fullPage:true});
  });
  await check('Only opening the selected phase journal fetches it once; prompt and output remain inspectable',async()=>{
    assert.equal(requests.filter(item=>item.path.endsWith('/agents')).length,0);
    await page.locator('.agent-journal>summary').click();await page.locator('.agent-journal-phase').first().waitFor();assert.equal(requests.filter(item=>item.path.endsWith('/agents')).length,1);
    await page.locator('.agent-journal-phase>summary').first().click();assert.ok((await page.locator('.agent-journal').innerText()).includes('TEST_ONLY точный запрос researcher'));
    await page.locator('.agent-journal').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,'TEST_ONLY-reviewed-journal-desktop.png'),fullPage:true});
    await page.locator('.agent-journal>summary').click();await page.locator('.agent-journal>summary').click();assert.equal(requests.filter(item=>item.path.endsWith('/agents')).length,1);
  });
  await check('No mutations, external traffic, live entries, providers, Telegram or browser errors',async()=>{assert.deepEqual(unexpected,[]);assert.deepEqual(errors,[]);assert.equal(requests.some(item=>item.method!=='GET'||/telegram|provider|\/start|\/save|\/cancel/.test(item.path)),false);});
  const report={test_only:true,fixture:'In-memory routes only; no server or live state. Approval renderer receives frozen fixture directly; all non-GET routes blocked.',checks,errors,unexpected,requests:requests.length,mutations:0,provider_calls:0,telegram_calls:0};fs.writeFileSync(path.join(out,'TEST_ONLY-ui-reviewed-v0130.json'),JSON.stringify(report,null,2));const failure=path.join(out,'TEST_ONLY-ui-reviewed-v0130-failure.json');if(fs.existsSync(failure))fs.unlinkSync(failure);console.log(JSON.stringify(report,null,2));
}finally{if(browser)await browser.close();}})().catch(error=>{fs.mkdirSync(out,{recursive:true});fs.writeFileSync(path.join(out,'TEST_ONLY-ui-reviewed-v0130-failure.json'),JSON.stringify({test_only:true,checks,errors,unexpected,error:error.stack},null,2));console.error(error.stack);process.exitCode=1;});
