/* TEST_ONLY browser acceptance. Fresh browser/context, local fake runner, no user data. */
const assert = require('assert/strict');
const fs = require('fs');
const path = require('path');
const {spawn} = require('child_process');
const {createHash} = require('crypto');
const {chromium} = require('playwright');
const origin = 'http://127.0.0.1:8796';
const out = path.resolve(__dirname, 'qa-output');
fs.mkdirSync(out, {recursive:true});
const dataRoot = fs.mkdtempSync(path.join(out, 'TEST_ONLY-data-'));
const downloads = fs.mkdtempSync(path.join(out, 'TEST_ONLY-downloads-'));
const python = process.env.LAB_TEST_PYTHON || 'python';
const root = path.resolve(__dirname, '..');
const results = [], screenshots = [], errors = [], externalRequests = [];
let serverOutput = '', browser, context, page, server, expectedStaleError = false, studyTaskId, lessonId;
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function check(name, action) { await action(); results.push({name,status:'pass'}); }
async function stats() { const response = await fetch(origin + '/__test__/stats'); assert(response.ok); return response.json(); }
async function post(pathname,body) {const bootstrap=await (await fetch(origin+'/api/bootstrap')).json();const response=await fetch(origin+pathname,{method:'POST',headers:{'Content-Type':'application/json','X-Lab-Token':bootstrap.csrf},body:JSON.stringify(body)});const value=await response.json();assert(response.ok,JSON.stringify(value));return value;}
async function current(pathname){const value=await (await fetch(origin+pathname)).json();return value.current || value;}
async function ready() { for (let i=0;i<60;i++) { if (server.exitCode !== null) throw new Error('Test server exited: ' + serverOutput); try {const response = await fetch(origin + '/api/health'); if(response.ok) return;} catch {} await sleep(100); } throw new Error('Test server did not start: ' + serverOutput); }
async function shot(name,fullPage=true) { const file = name + '.png'; await page.screenshot({path:path.join(out,file),fullPage}); screenshots.push(file); }
async function noOverflow() { const dimensions = await page.evaluate(() => ({viewport:innerWidth,document:document.documentElement.scrollWidth,body:document.body.scrollWidth,view:[...document.querySelectorAll('.view')].find(x=>!x.hidden)?.id,offenders:[...document.querySelectorAll('body *')].filter(x=>{const r=x.getBoundingClientRect();return r.width && r.right>innerWidth+1;}).slice(0,12).map(x=>({tag:x.tagName,id:x.id,className:x.className,right:Math.round(x.getBoundingClientRect().right)}))})); assert(dimensions.document <= dimensions.viewport + 1,JSON.stringify(dimensions)); assert(dimensions.body <= dimensions.viewport + 1,JSON.stringify(dimensions)); }
async function nav(view) { await page.locator(`.nav-button[data-view="${view}"]`).click(); await page.locator('#view-' + view).waitFor({state:'visible'}); }

(async () => {
  server = spawn(python,['-B',path.join(__dirname,'ui_server.py'),'--data-dir',dataRoot],{cwd:root,windowsHide:true,env:{...process.env,PYTHONPATH:root,PYTHONUTF8:'1'}});
  server.stdout.on('data',chunk => {serverOutput += chunk.toString();});
  server.stderr.on('data',chunk => {serverOutput += chunk.toString();});
  await ready();
  browser = await chromium.launch({headless:true,channel:'chrome',downloadsPath:downloads});
  context = await browser.newContext({locale:'ru-RU',timezoneId:'Europe/Moscow',viewport:{width:1440,height:1050},acceptDownloads:true,reducedMotion:'reduce',serviceWorkers:'block'});
  await context.route('**/*',route => {if (route.request().url().startsWith(origin + '/')) return route.continue(); externalRequests.push(route.request().url()); return route.abort();});
  page = await context.newPage(); page.setDefaultTimeout(8000);
  page.on('pageerror',error => errors.push(error.message));
  page.on('console',message => {if(message.type()==='error' && !message.text().includes('favicon.ico') && !(expectedStaleError && message.text().includes('400'))) errors.push(message.text());});
  await page.goto(origin,{waitUntil:'networkidle'});
  await check('Empty inbox and real zero counters',async () => {await page.getByText('Входящие пока пусты',{exact:true}).waitFor(); assert.equal(await page.locator('#count-sources').textContent(),'0'); assert.equal((await stats()).dispatches,0); await noOverflow();});
  await check('Reusable task editor saves business baseline candidates metrics and deployment unknowns without dispatch',async()=>{
    await nav('tasks');await page.locator('#new-task-button').click();await page.locator('#task-dialog').waitFor({state:'visible'});
    await page.locator('#task-editor-fields [data-field="title"]').fill('TEST_ONLY: применимость памяти ИИ');
    await page.locator('#task-editor-fields [data-field="business_goal"]').fill('TEST_ONLY: уменьшить пропуски в поиске знаний <script>window.__taskExecuted=true</script>');
    await page.locator('#task-editor-fields [data-field="beneficiary"]').fill('TEST_ONLY: владелец лаборатории');
    await page.locator('#task-editor-fields [data-field="task_type"]').selectOption('retrieval');
    await page.locator('#task-editor-fields [data-field="research_question"]').fill('TEST_ONLY: применима ли память к поиску ИИ-исследований?');
    await page.locator('#task-editor-fields [data-field="inputs"]').fill('TEST_ONLY: короткие заметки и статьи об ИИ');
    await page.locator('#task-editor-fields [data-field="expected_output"]').fill('TEST_ONLY: ранжированные ссылки с доказательствами');
    await page.locator('#task-editor-fields [data-field="constraints"]').fill('TEST_ONLY: без локального GPU и без запуска бенчмарка');
    const baseline=page.locator('#task-editor-fields > details').nth(1);
    await baseline.locator('[data-field="name"]').fill('TEST_ONLY baseline: ручной поиск по заметкам');
    await baseline.locator('[data-field="description"]').fill('TEST_ONLY: текущий ручной процесс');
    await page.getByRole('button',{name:'+ Добавить кандидата',exact:true}).click();
    const candidate=page.locator('[data-candidate="0"]');
    await candidate.locator('[data-field="name"]').fill('TEST_ONLY Harness 2');
    await candidate.locator('[data-field="applicability"]').fill('TEST_ONLY: гипотеза для поиска связанных ИИ-работ');
    await candidate.locator('[data-field="advantages"]').fill('TEST_ONLY: возможная связь заметок');
    await candidate.locator('[data-field="limitations"]').fill('TEST_ONLY: качество не измерено');
    await candidate.locator('[data-field="evidence_level"]').selectOption('hypothesis');
    await page.getByRole('button',{name:'+ Добавить метрику',exact:true}).click();
    const metric=page.locator('[data-metric="0"]');
    await metric.locator('[data-field="name"]').fill('TEST_ONLY Recall');
    await metric.locator('[data-field="definition"]').fill('TEST_ONLY: доля найденных релевантных источников в размеченном наборе');
    await metric.locator('[data-field="unit"]').fill('%');
    await metric.locator('[data-field="direction"]').selectOption('maximize');
    await metric.locator('[data-field="target"]').fill('TEST_ONLY: целевой порог 95%');
    await metric.locator('[data-field="expected"]').fill('Неизвестно; требуется проверка');
    assert.equal(await metric.locator('[data-primary="0"]').isChecked(),true);
    await page.locator('#task-editor-fields > details > summary').filter({hasText:'5 · Датасет'}).click();
    await page.locator('[data-field="dataset"]').fill('TEST_ONLY: закрытый набор пока не сформирован');
    await page.locator('[data-field="evaluation"]').fill('TEST_ONLY: одинаковые запросы и baseline, без исполнения сейчас');
    await page.locator('[data-field="success_criteria"]').fill('TEST_ONLY: измерить Recall отдельно после согласования');
    await page.locator('#task-editor-fields > details > summary').filter({hasText:'6 · Собственное'}).click();
    await page.locator('[data-field="candidate_profiles"]').fill('TEST_ONLY: требования по вариантам ещё неизвестны');
    await page.locator('#task-form button[type="submit"]').click();await page.locator('#task-dialog').waitFor({state:'hidden'});
    await page.locator('.task-card').filter({hasText:'TEST_ONLY: применимость памяти ИИ'}).waitFor();
    const tasks=(await (await fetch(origin+'/api/tasks')).json()).items;studyTaskId=tasks[0].id;
    assert.equal(tasks[0].body.metrics[0].primary,true);assert.equal(tasks[0].body.self_hosted.availability,'unknown');assert.equal((await stats()).dispatches,0);assert.equal(await page.evaluate(()=>window.__taskExecuted),undefined);
    await shot('desktop-task-catalog');await page.locator('.task-card').getByRole('button',{name:'Использовать в исследовании',exact:true}).click();await page.locator('#view-inbox').waitFor({state:'visible'});assert.equal(await page.locator('#research-task').inputValue(),studyTaskId);
  });
  await check('Material creation preserves Cyrillic and literal untrusted HTML',async () => {
    await page.locator('#add-source-button').click(); await page.locator('#source-title').fill('TEST_ONLY: ИИ и память');
    await page.locator('#source-text').fill('Кириллица: исследование памяти ИИ. <script>window.__sourceExecuted = true</script>');
    await page.locator('#source-tags').fill('память, test_only'); await page.locator('#source-form button[type="submit"]').click();
    await page.locator('#source-dialog').waitFor({state:'hidden'}); await page.locator('.source-body').filter({hasText:'<script>'}).waitFor();
    assert.equal(await page.evaluate(() => window.__sourceExecuted),undefined); assert.equal((await stats()).dispatches,0); await shot('desktop-inbox');
  });
  const telegram = {name:'Saved Messages',type:'saved_messages',id:123,messages:[{id:1,type:'message',date:'2026-10-20T12:00:00',text:['TEST_ONLY Telegram ИИ: ',{type:'bold',text:'новая память'},' https://example.org/paper']}]};
  const exportFile = path.join(out,'TEST_ONLY-telegram.json'); fs.writeFileSync(exportFile,JSON.stringify(telegram),'utf8');
  await check('Telegram JSON import and repeated import deduplicate without dispatch',async () => {
    await page.locator('#telegram-import').setInputFiles(exportFile); await page.waitForFunction(() => document.querySelector('#count-sources').textContent === '2');
    await page.locator('#telegram-import').setInputFiles(exportFile); await page.waitForFunction(() => document.querySelector('#toast').textContent.includes('Дубликатов: 1'));
    assert.equal((await stats()).counts.sources,2); assert.equal((await stats()).dispatches,0);
  });
  await check('Research profile and correction persist without provider dispatch',async () => {
    await nav('settings');await page.locator('#memory-interests').fill('TEST_ONLY: память агентов и оценка ИИ');
    await page.locator('#memory-goals').fill('TEST_ONLY: выбирать проверяемые методы для лаборатории');
    await page.locator('#memory-preferences').fill('TEST_ONLY: сначала первоисточники и ограничения');
    await page.locator('#memory-profile-form button[type="submit"]').click();
    await page.waitForFunction(() => document.querySelector('#toast').textContent.includes('Профиль сохранён'));
    await page.locator('#memory-correction-text').fill('TEST_ONLY: не считать заявление автора измерением лаборатории <script>window.__correctionExecuted=true</script>');
    await page.locator('#memory-correction-form button[type="submit"]').click();
    await page.locator('.correction-item').filter({hasText:'не считать заявление автора'}).waitFor();
    assert.equal((await stats()).dispatches,0);assert.equal(await page.evaluate(()=>window.__correctionExecuted),undefined);await nav('inbox');
  });
  await check('Immutable plan requires a checked human approval before dispatch',async () => {
    await page.locator('.source-open').filter({hasText:'TEST_ONLY: ИИ и память'}).click();
    await page.locator('#research-question').fill('TEST_ONLY: какие доказательства для памяти ИИ?');
    await page.locator('#prepare-button').click(); await page.locator('#approval-dialog').waitFor({state:'visible'});
    assert.equal(await page.locator('#approve-launch').isDisabled(),true); assert.equal((await stats()).dispatches,0);
    assert.match(await page.locator('#approval-summary').innerText(),/TEST_ONLY: ИИ и память/);
    assert.match(await page.locator('#approval-memory').innerText(),/TEST_ONLY: память агентов и оценка ИИ/);
    assert.match(await page.locator('#approval-memory').innerText(),/не считать заявление автора/);
    assert.match(await page.locator('#approval-context').innerText(),/TEST_ONLY baseline: ручной поиск по заметкам/);
    assert.match(await page.locator('#approval-context').innerText(),/TEST_ONLY Harness 2/);
    assert.match(await page.locator('#approval-context').innerText(),/целевой порог 95%/);
    assert.match(await page.locator('#approval-context').innerText(),/Неизвестно; требуется проверка/);
    assert.equal(await page.evaluate(()=>window.__taskExecuted),undefined);
    const firstHash=await page.locator('.plan-hash').textContent();
    const task=await (await fetch(origin+'/api/tasks/'+studyTaskId)).json();
    await post('/api/tasks',{id:studyTaskId,expected_version:task.version,status:'active',body:{...task.body,business_goal:'TEST_ONLY: уточнённая бизнес-цель задачи v2'}});
    expectedStaleError=true;await page.locator('#approval-consent').check();await page.locator('#approve-launch').click();await page.locator('#approval-context-error').waitFor({state:'visible'});expectedStaleError=false;
    assert.equal((await stats()).dispatches,0);assert.equal(await page.locator('#approve-launch').isDisabled(),true);
    await page.locator('.context-rebuild').click();await page.waitForFunction(old=>document.querySelector('.plan-hash').textContent!==old,firstHash);
    assert.equal(await page.locator('#approval-consent').isChecked(),false);assert.match(await page.locator('#approval-context').innerText(),/уточнённая бизнес-цель задачи v2/);await shot('desktop-study-approval');
    await page.locator('#approval-consent').check(); await page.locator('#approve-launch').click();
    await page.locator('#approval-dialog').waitFor({state:'hidden'});
    for(let i=0;i<30 && (await stats()).dispatches===0;i++)await sleep(100);
    assert.equal((await stats()).dispatches,1);
    assert.match((await stats()).last_prompt,/TEST_ONLY: сначала первоисточники и ограничения/);
    assert.match((await stats()).last_prompt,/уточнённая бизнес-цель задачи v2/);assert.match((await stats()).last_prompt,/TEST_ONLY baseline: ручной поиск/);assert.match((await stats()).last_prompt,/TEST_ONLY Harness 2/);assert.match((await stats()).last_prompt,/целевой порог 95%/);assert.match((await stats()).last_prompt,/требования по вариантам ещё неизвестны/);
    await fetch(origin + '/__test__/release',{method:'POST'});
    await page.locator('#run-detail .report-text').filter({hasText:'TEST_ONLY — Синтетический отчёт'}).waitFor({state:'attached',timeout:12000});
    assert.equal(await page.evaluate(() => window.__reportExecuted),undefined); await shot('desktop-report');
  });
  await check('Completed report saves to knowledge and survives search and reload',async () => {
    await page.locator('#run-detail').getByRole('button',{name:'Сохранить в базу знаний',exact:true}).click();
    await page.locator('#finding-title').fill('TEST_ONLY память ИИ — сохранённый вывод');
    await page.locator('#finding-decision').fill('TEST_ONLY: сохранить как непроверенную гипотезу для будущего эксперимента.');
    await page.locator('#finding-tags').fill('память, проверка');
    await page.locator('#save-form button[type="submit"]').click(); await page.locator('#save-dialog').waitFor({state:'hidden'});
    await nav('knowledge'); await page.locator('#knowledge-search').fill('ПАМЯТЬ');
    await page.locator('.knowledge-card').filter({hasText:'TEST_ONLY память ИИ'}).waitFor();
    assert.equal((await stats()).counts.knowledge,1); await shot('desktop-knowledge');
    await page.reload({waitUntil:'networkidle'}); await nav('knowledge'); await page.locator('.knowledge-card').filter({hasText:'TEST_ONLY память ИИ'}).waitFor();
    assert.equal((await stats()).dispatches,1);
  });
  await check('Captured context exposes the exact dispatched prompt and hash without executing its text',async()=>{
    await nav('runs');await page.locator('.run-row').first().click();await page.locator('#run-detail .context-trace > summary').click();
    const prompt=await page.locator('#run-detail .context-prompt').textContent();
    assert.equal(prompt,(await stats()).last_prompt);
    assert.match(await page.locator('#run-detail .context-prompt-hash').textContent(),new RegExp(createHash('sha256').update(prompt,'utf8').digest('hex')));
    assert.match(await page.locator('#run-detail .trace-status').textContent(),/перед отправкой/);
    assert.match(await page.locator('#run-detail .context-trace').innerText(),/Внутренние инструкции CLI/);
    assert.equal(await page.evaluate(()=>window.__sourceExecuted),undefined);await shot('desktop-exact-context');await nav('knowledge');
  });
  await check('Backup download contains stored sources, run and knowledge without secrets',async () => {
    const pending = page.waitForEvent('download'); await page.locator('#export-button').click(); const download = await pending;
    assert.equal(await download.failure(),null); const filename = await download.path(); const backup = JSON.parse(fs.readFileSync(filename,'utf8'));
    assert.equal(backup.format,'ai-rd-laboratory-backup');assert(backup.schema_version>=3);assert.equal(backup.tables.study_task_revisions.length,2); assert.equal(backup.tables.sources.length,2); assert.equal(backup.tables.runs.length,1); assert.equal(backup.tables.knowledge.length,1); assert(!('settings' in backup.tables));
  });
  await check('Saved task history and knowledge retain their original study conditions',async()=>{
    assert.match(await page.locator('.knowledge-card .study-scope').innerText(),/уточнённая бизнес-цель задачи v2/);
    await nav('tasks');await page.locator('.task-card').getByRole('button',{name:'История',exact:true}).click();await page.locator('#task-history-dialog').waitFor({state:'visible'});
    assert.match(await page.locator('#task-history-content').innerText(),/Версия 2/);assert.match(await page.locator('#task-history-content').innerText(),/Версия 1/);
    await page.locator('[data-close="task-history-dialog"]').click();await nav('knowledge');assert.equal((await stats()).dispatches,1);
  });
  await check('Knowledge correction creates an immutable visible version history',async () => {
    await page.locator('.knowledge-card').getByRole('button',{name:'Исправить вывод',exact:true}).click();
    await page.locator('#memory-edit-claim').fill('TEST_ONLY: память ИИ требует независимой проверки <script>window.__memoryExecuted=true</script>');
    await page.locator('#memory-edit-notes').fill('TEST_ONLY: поправка владельца, прежний вывод сохранён');
    await page.locator('#memory-edit-form button[type="submit"]').click();await page.locator('#memory-edit-dialog').waitFor({state:'hidden'});
    await page.locator('.knowledge-card .decision').filter({hasText:'память ИИ требует независимой проверки'}).waitFor();
    assert.equal(await page.evaluate(()=>window.__memoryExecuted),undefined);
    await page.locator('.knowledge-card').getByRole('button',{name:'История версий',exact:true}).click();
    await page.locator('#memory-history-dialog').waitFor({state:'visible'});
    assert((await page.locator('#memory-history-content').innerText()).includes('сохранить как непроверенную гипотезу'));
    assert((await page.locator('#memory-history-content').innerText()).includes('память ИИ требует независимой проверки'));
    await page.locator('[data-close="memory-history-dialog"]').click();assert.equal((await stats()).dispatches,1);
  });
  await check('A finding becomes a scoped lesson with explicit evidence, draft activation and safe version history',async()=>{
    await page.locator('.knowledge-card').getByRole('button',{name:'Создать урок',exact:true}).click();await page.locator('#lesson-dialog').waitFor({state:'visible'});
    await page.locator('#lesson-editor-fields [data-field="title"]').fill('TEST_ONLY: урок о проверке памяти');
    await page.locator('#lesson-editor-fields [data-field="rule"]').fill('TEST_ONLY: сверяй память с первоисточниками <script>window.__lessonExecuted=true</script>');
    await page.locator('#lesson-editor-fields [data-field="evidence_note"]').fill('TEST_ONLY: основание — синтетический отчёт; это проверка интерфейса, не эксперимент.');
    await page.locator('#lesson-editor-fields [data-field="applies_when"]').fill('TEST_ONLY: анализ источников о памяти ИИ для выбранной задачи поиска');
    await page.locator('#lesson-editor-fields [data-field="not_applicable_when"]').fill('TEST_ONLY: не переносить на другую задачу или измерения качества');
    await page.locator('#lesson-editor-fields [data-field="limitations"]').fill('TEST_ONLY: нет независимых измерений, требуется проверка');
    assert.equal(await page.locator('.lesson-source:checked').count(),1);assert.equal(await page.locator('#lesson-task').inputValue(),studyTaskId);
    await page.locator('#lesson-review').fill('2030-01-01');await page.locator('#lesson-form button[type="submit"]').click();await page.locator('#lesson-dialog').waitFor({state:'hidden'});
    let lessons=(await (await fetch(origin+'/api/lessons')).json()).items;lessonId=lessons[0].id;assert.equal(lessons[0].status,'draft');assert.equal((await stats()).dispatches,1);
    const card=page.locator('.lesson-card').filter({hasText:'TEST_ONLY: урок о проверке памяти'});
    await card.getByRole('button',{name:'Редактировать урок',exact:true}).click();await page.locator('#lesson-status').selectOption('active');await page.locator('#lesson-form button[type="submit"]').click();await page.locator('#lesson-dialog').waitFor({state:'hidden'});
    await card.locator('.status-badge').filter({hasText:'Активный урок'}).waitFor();assert.equal(await page.evaluate(()=>window.__lessonExecuted),undefined);
    await card.getByRole('button',{name:'История урока',exact:true}).click();await page.locator('#lesson-history-dialog').waitFor({state:'visible'});const history=await page.locator('#lesson-history-content').innerText();assert.match(history,/Версия 2/);assert.match(history,/Версия 1/);assert.match(history,/не переносить на другую задачу/);await page.locator('[data-close="lesson-history-dialog"]').click();
    const lesson=await current('/api/lessons/'+lessonId);
    const task=await current('/api/tasks/'+studyTaskId);
    const otherTask=await post('/api/tasks',{expected_version:0,status:'active',body:{...task.body,title:'TEST_ONLY: другая задача для проверки границ'}});
    await post('/api/lessons',{expected_version:0,status:'active',body:{...lesson.body,title:'TEST_ONLY: правило другой задачи',task_id:(otherTask.current || otherTask).id}});
    await post('/api/lessons',{expected_version:0,status:'draft',body:{...lesson.body,title:'TEST_ONLY: неактивный черновик'}});
    await post('/api/lessons',{expected_version:0,status:'retired',body:{...lesson.body,title:'TEST_ONLY: выведенное правило'}});
    await nav('knowledge');await shot('desktop-lessons');
  });
  await check('A stale lesson edit cannot overwrite a newer revision',async()=>{
    const card=page.locator('.lesson-card').filter({hasText:'TEST_ONLY: урок о проверке памяти'});await card.getByRole('button',{name:'Редактировать урок',exact:true}).click();
    const lesson=await current('/api/lessons/'+lessonId);
    await post('/api/lessons',{id:lessonId,expected_version:lesson.version,status:'active',body:{...lesson.body,limitations:'TEST_ONLY: уточнённые ограничения версии 3'}});
    await page.locator('#lesson-editor-fields [data-field="title"]').fill('TEST_ONLY: устаревшая попытка');expectedStaleError=true;
    await page.locator('#lesson-form button[type="submit"]').click();await page.locator('#lesson-edit-error').waitFor({state:'visible'});expectedStaleError=false;
    assert.equal((await current('/api/lessons/'+lessonId)).body.title,'TEST_ONLY: урок о проверке памяти');
    await page.getByRole('button',{name:'Загрузить актуальную версию урока',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#lesson-editor-fields [data-field="limitations"]').value.includes('версии 3'));await page.locator('[data-close="lesson-dialog"]').first().click();assert.equal((await stats()).dispatches,1);
  });
  await check('New research shows exact remembered claim; exclusion rebuilds plan and resets consent',async () => {
    await nav('inbox');await page.locator('.source-open').filter({hasText:'TEST_ONLY: ИИ и память'}).click();
    await page.locator('#research-task').selectOption(studyTaskId);
    await page.locator('#research-question').fill('TEST_ONLY: что изменилось в доказательствах памяти ИИ?');
    await page.locator('#prepare-button').click();await page.locator('#approval-dialog').waitFor({state:'visible'});
    await page.locator('#approval-memory .memory-literal').filter({hasText:'память ИИ требует независимой проверки'}).waitFor();
    await page.locator('#approval-memory .frozen-lesson').filter({hasText:'TEST_ONLY: урок о проверке памяти'}).waitFor();
    assert.equal(await page.locator('.lesson-select').count(),2);assert.equal(await page.locator('.lesson-select:checked').count(),1);assert.equal(await page.locator('.frozen-lesson').count(),1);assert.match(await page.locator('.frozen-lesson').innerText(),/уточнённые ограничения версии 3/);assert(!((await page.locator('#approval-memory').innerText()).includes('выведенное правило')));assert(!((await page.locator('#approval-memory').innerText()).includes('неактивный черновик')));
    const hash=await page.locator('.plan-hash').textContent();await page.locator('#approval-consent').check();
    await page.locator('.memory-selection:not(.lesson-selection) summary').click();await page.locator('.memory-select').first().uncheck();
    await page.waitForFunction(old=>document.querySelector('.plan-hash').textContent!==old,hash);
    assert.equal(await page.locator('#approval-consent').isChecked(),false);assert.equal(await page.locator('#approve-launch').isDisabled(),true);
    assert.equal(await page.locator('#approval-memory .memory-literal').filter({hasText:'память ИИ требует независимой проверки'}).count(),0);
    assert.equal((await stats()).dispatches,1);
    await page.locator('.memory-selection:not(.lesson-selection) summary').click();await page.locator('.memory-select').first().check();
    await page.locator('#approval-memory .memory-literal').filter({hasText:'память ИИ требует независимой проверки'}).waitFor();await shot('desktop-memory-approval');
  });
  await check('Lesson exclusion freezes a new prompt hash, resets consent and preserves scope on reselection',async()=>{
    await page.locator('#approval-dialog .context-trace > summary').click();await page.locator('#approval-dialog .context-prompt').waitFor();const oldPrompt=await page.locator('#approval-dialog .context-prompt').textContent();assert.match(oldPrompt,/сверяй память с первоисточниками/);assert.match(oldPrompt,/не переносить на другую задачу/);
    const oldHash=await page.locator('.plan-hash').textContent();await page.locator('#approval-consent').check();await page.locator('.lesson-selection > summary').click();await page.locator('.lesson-select:checked').uncheck();
    await page.waitForFunction(old=>document.querySelector('.plan-hash').textContent!==old,oldHash);assert.equal(await page.locator('#approval-consent').isChecked(),false);assert.equal(await page.locator('.frozen-lesson').count(),0);
    await page.locator('#approval-dialog .context-trace > summary').click();const prompt=await page.locator('#approval-dialog .context-prompt').textContent();assert(!prompt.includes('сверяй память с первоисточниками'));assert.match(await page.locator('#approval-dialog .context-prompt-hash').textContent(),new RegExp(createHash('sha256').update(prompt,'utf8').digest('hex')));
    await page.locator('.lesson-selection > summary').click();await page.locator('.lesson-select[value="'+lessonId+'"]').check();await page.locator('.frozen-lesson').waitFor();assert.equal(await page.locator('#approval-consent').isChecked(),false);assert.equal((await stats()).dispatches,1);await page.locator('.frozen-lesson').scrollIntoViewIfNeeded();await shot('desktop-lesson-approval',false);
  });
  await check('Changed lesson blocks stale launch until the new scoped version is reviewed',async()=>{
    const lesson=await current('/api/lessons/'+lessonId);
    await post('/api/lessons',{id:lessonId,expected_version:lesson.version,status:'active',body:{...lesson.body,limitations:'TEST_ONLY: границы версии 4 — применять только к анализу источников'}});
    expectedStaleError=true;await page.locator('#approval-consent').check();await page.locator('#approve-launch').click();await page.locator('#approval-context-error').waitFor({state:'visible'});expectedStaleError=false;
    assert.equal((await stats()).dispatches,1);assert.equal(await page.locator('#approve-launch').isDisabled(),true);
    await page.locator('.memory-rebuild').click();await page.locator('.frozen-lesson').filter({hasText:'границы версии 4'}).waitFor();assert.equal(await page.locator('#approval-consent').isChecked(),false);
  });
  await check('Changed profile blocks stale approval; refresh freezes new profile before launch',async () => {
    const memory=await (await fetch(origin+'/api/memory')).json();
    await post('/api/memory/profile',{expected_version:memory.profile.version,interests:memory.profile.interests,goals:memory.profile.goals,preferences:'TEST_ONLY: обновлённая поправка профиля',review_days:30});
    expectedStaleError=true;await page.locator('#approval-consent').check();await page.locator('#approve-launch').click();
    await page.locator('#approval-context-error').waitFor({state:'visible'});assert.equal((await stats()).dispatches,1);
    expectedStaleError=false;
    assert.equal(await page.locator('#approve-launch').isDisabled(),true);
    await page.locator('.memory-rebuild').click();await page.locator('.frozen-memory-text').filter({hasText:'обновлённая поправка профиля'}).waitFor();
    assert.equal(await page.locator('#approval-consent').isChecked(),false);
    await page.locator('#approval-consent').check();await page.locator('#approve-launch').click();await page.locator('#approval-dialog').waitFor({state:'hidden'});
    await page.locator('#run-detail .report-text').filter({hasText:'TEST_ONLY — Синтетический отчёт'}).waitFor({state:'attached',timeout:12000});
    assert.equal((await stats()).dispatches,2);assert.match((await stats()).last_prompt,/обновлённая поправка профиля/);assert.match((await stats()).last_prompt,/память ИИ требует независимой проверки/);
  });
  await check('Review suggestions show old/new evidence; dismissal and acceptance preserve version history',async () => {
    await nav('knowledge');await page.locator('#memory-reviews-panel').waitFor({state:'visible'});
    await page.waitForFunction(()=>document.querySelectorAll('.memory-review-card').length===2);
    const contradiction=page.locator('.memory-review-card').filter({hasText:'Возможное противоречие'});
    assert.match(await contradiction.innerText(),/память ИИ требует независимой проверки/);
    assert.match(await contradiction.innerText(),/уточнённая память ИИ после решения владельца/);
    assert.equal(await contradiction.locator('a[href="https://example.org/test-only"]').count(),1);
    await shot('desktop-memory-reviews');
    await page.locator('.memory-review-card').filter({hasText:'Возможное подтверждение'}).getByRole('button',{name:'Отклонить предложение',exact:true}).click();
    await page.waitForFunction(()=>document.querySelectorAll('.memory-review-card').length===1);
    await page.locator('.memory-review-card').getByRole('button',{name:'Принять новую версию',exact:true}).click();
    await page.locator('#memory-reviews-panel').waitFor({state:'hidden'});
    await page.locator('.knowledge-card .decision').filter({hasText:'уточнённая память ИИ после решения владельца'}).waitFor();
    await page.locator('.knowledge-card').getByRole('button',{name:'История версий',exact:true}).click();
    await page.locator('#memory-history-dialog').waitFor({state:'visible'});
    const history=await page.locator('#memory-history-content').innerText();
    assert.match(history,/Версия 3/);assert.match(history,/Версия 2/);assert.match(history,/Версия 1/);assert.match(history,/dismissed/);assert.match(history,/accepted/);
    await page.locator('[data-close="memory-history-dialog"]').click();assert.equal((await stats()).dispatches,2);
  });
  await check('Retiring a lesson in the editor removes future use while preserving the dispatched version',async()=>{
    await nav('knowledge');const card=page.locator('.lesson-card').filter({hasText:'TEST_ONLY: урок о проверке памяти'});await card.getByRole('button',{name:'Редактировать урок',exact:true}).click();await page.locator('#lesson-dialog').waitFor({state:'visible'});await page.locator('#lesson-status').selectOption('retired');await page.locator('#lesson-form button[type="submit"]').click();await page.locator('#lesson-dialog').waitFor({state:'hidden'});
    assert.equal((await current('/api/lessons/'+lessonId)).status,'retired');
    const runs=(await (await fetch(origin+'/api/runs')).json()).items,dispatched=runs.find(run=>run.status==='completed' && run.plan.memory?.lessons?.some(item=>item.id===lessonId));assert(dispatched);assert.equal(dispatched.plan.memory.lessons.find(item=>item.id===lessonId).version,4);
    const preview=await post('/api/memory/preview',{source_ids:dispatched.plan.sources.map(item=>item.id),question:dispatched.plan.question,task_id:studyTaskId});assert(!preview.lesson_candidates.some(item=>item.id===lessonId));assert(!preview.suggested_lesson_ids.includes(lessonId));
    await card.getByRole('button',{name:'История урока',exact:true}).click();await page.locator('#lesson-history-dialog').waitFor({state:'visible'});const history=await page.locator('#lesson-history-content').innerText();assert.match(history,/Версия 5/);assert.match(history,/Версия 4/);assert.match(history,/Версия 1/);await page.locator('[data-close="lesson-history-dialog"]').click();assert.equal((await stats()).dispatches,2);
  });
  await check('All five views fit desktop and 390px mobile without document overflow',async () => {
    for(const width of [1440,390]) { await page.setViewportSize({width,height:width===1440?1050:844}); for(const view of ['inbox','runs','tasks','knowledge','settings']) {await nav(view); await noOverflow();} if(width===390){await nav('tasks');await shot('mobile-tasks');await nav('inbox');await shot('mobile-inbox');await nav('knowledge');await shot('mobile-knowledge');await page.locator('.lesson-card').filter({hasText:'TEST_ONLY: урок о проверке памяти'}).getByRole('button',{name:'Редактировать урок',exact:true}).click();await page.locator('#lesson-dialog').waitFor({state:'visible'});await noOverflow();await shot('mobile-lesson-editor',false);await page.locator('[data-close="lesson-dialog"]').first().click();} }
  });
  await check('A legacy report states that the historical transmitted context is unavailable',async()=>{
    const fixture=await (await fetch(origin+'/__test__/legacy',{method:'POST'})).json();await nav('runs');await page.locator('.run-row').filter({hasText:'TEST_ONLY: старый отчёт без записи контекста'}).click();await page.locator('#run-detail .context-trace > summary').click();
    await page.locator('#run-detail .context-trace').getByText(/точный переданный контекст не записывался/).waitFor();assert.equal(await page.locator('#run-detail .context-prompt').count(),0);assert.equal((await (await fetch(origin+'/api/runs/'+fixture.id+'/context')).json()).status,'legacy_unavailable');await shot('mobile-legacy-context');
  });
  await check('No JavaScript errors, external requests, or unintended model dispatches',async () => {assert.deepEqual(errors,[]);assert.deepEqual(externalRequests,[]);assert.equal((await stats()).dispatches,2);});
})().catch(error => {results.push({name:'Browser acceptance',status:'fail',error:error.stack});process.exitCode=1;}).finally(async () => {
  if(context)await context.close(); if(browser)await browser.close();
  if(server && server.exitCode===null) {try {await fetch(origin + '/__test__/shutdown',{method:'POST'});}catch{} await Promise.race([new Promise(resolve=>server.once('exit',resolve)),sleep(3000)]);if(server.exitCode===null)server.kill();}
  const report={testOnly:true,provider:'deterministic fake runner',freshBrowser:true,userProfile:false,realTelegram:false,realModels:false,results,screenshots,errors,externalRequests};
  fs.writeFileSync(path.join(out,'ui-results.json'),JSON.stringify(report,null,2),'utf8');
  fs.writeFileSync(path.join(out,'server-output.txt'),serverOutput,'utf8');
  console.log(JSON.stringify({passed:results.filter(x=>x.status==='pass').length,failed:results.filter(x=>x.status==='fail').length,report:path.join(out,'ui-results.json'),errors,externalRequests},null,2));
});
