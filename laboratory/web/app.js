'use strict';

const $ = (selector, context = document) => context.querySelector(selector);
const $$ = (selector, context = document) => [...context.querySelectorAll(selector)];
const classicView = globalThis.location?.pathname === '/classic';
document.body?.classList?.toggle('frontier-live', !classicView);
if(classicView)$$('[data-frontier-only]').forEach(element=>{element.hidden=true;});
let runSelection = 0;
let lastFrontierPoll = 0;
const state = {csrf: '', bootstrap: null, sources: [], runs: [], knowledge: [], selected: new Set(), sourceId: null, runId: null, pendingPlan: null, view: classicView?'inbox':globalThis.location&&new URL(location.href).searchParams.get('mode')==='evidence'?'observatory':'reactor', saveRunId: null, pollBusy: false, memoryData:null, memoryPreview:null, memoryOptions:null, memoryRebuilding:false, memoryBlocked:false, memoryEdit:null, studySchema:null,tasks:[],taskDraft:null,autoTaskQuestion:'',lessons:[],lessonSchema:null,lessonDraft:null,lessonEvidenceRun:null};
const activeStatuses = new Set(['running', 'queued']);
const statusNames = {planned: 'Ждёт вашего апрува', queued: 'В очереди', running: 'Исследуется', completed: 'Готово', failed: 'Не завершено', outcome_unknown: 'Исход уточняется', unknown: 'Исход уточняется', cancelled: 'Остановлено', canceled: 'Остановлено', interrupted: 'Прервано'};
let toastTimer;
const presentationCache = new Map();
const agentTraceCache = new Map();
let reviewSchemaPromise = null;
let storyboardTimer = null;
let storyboardReset = null;
let publicationData = null;
let publicationDirty = false;
let publicationSaving = false;
let publicationSlotId = 0;
let publicationRequest = 0;
let publicationChannelSaving = false;
const reducedMotion = globalThis.matchMedia?.('(prefers-reduced-motion: reduce)');
reducedMotion?.addEventListener?.('change',()=>{if(reducedMotion.matches)stopStoryboard();});

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined && text !== null) element.textContent = String(text);
  return element;
}
function append(parent, ...children) { for (const child of children.flat()) if (child) parent.append(child); return parent; }
function button(text, callback, className = 'button secondary') { const element = node('button', className, text); element.type = 'button'; element.addEventListener('click', callback); return element; }
function tags(value) { return (Array.isArray(value) ? value : String(value || '').split(',')).map(x => String(x).trim()).filter(Boolean); }
function renderTags(value) { return append(node('div', 'tags'), tags(value).map(tag => node('span', 'tag', tag))); }
function date(value) { if (!value) return ''; const parsed = new Date(value); return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString('ru-RU', {day:'numeric', month:'short', hour:'2-digit', minute:'2-digit'}); }
function providerName(id) { return state.bootstrap?.providers?.find(p => p.id === id)?.name || ({codex:'Codex', claude:'Claude Code'}[id]) || id || 'Исполнитель'; }
function safeUrl(value) { try { const parsed = new URL(value); return ['https:', 'http:'].includes(parsed.protocol) ? parsed.href : null; } catch { return null; } }
function link(value, label) { const href = safeUrl(value); if (!href) return null; const element = node('a', 'source-link', label || value); element.href = href; element.target = '_blank'; element.rel = 'noopener noreferrer'; return element; }
function notify(message, error = false) { const toast = $('#toast'); toast.textContent = message; toast.className = 'toast' + (error ? ' error' : ''); toast.hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => {toast.hidden = true;}, error ? 7500 : 4500); }
function empty(symbol, title, text, action) { return append(node('div', 'empty-state'), node('span', 'empty-symbol', symbol), node('h2', '', title), node('p', '', text), action); }
function notice(text, className = '') { return node('div', 'notice ' + className, text); }
function statusBadge(status) { return node('span', 'status-badge ' + status, statusNames[status] || status || 'Неизвестно'); }
function reportDisplayText(output) {return typeof output === 'string' ? output.replace(/<lab_(memory_review|presentation)>[\s\S]*?<\/lab_\1>/gi,'').replace(/<lab_(?:memory_review|presentation)>[\s\S]*$/gi,'').trim() : JSON.stringify(output,null,2);}
function errorMessage(error) { return error?.message || 'Не удалось выполнить действие. Попробуйте ещё раз.'; }
function showError(error) { notify(errorMessage(error), true); }
function commandId() { return globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`; }
function reviewedProtocol(plan) { return ['three-pass-v1','three-pass-v2','three-pass-v3','three-pass-v4','editor-resume-v1'].includes(plan?.research_protocol?.version) ? plan.research_protocol : null; }
const agentRoleNames = {researcher:'Исследователь и прикладной аналитик',critic:'Критик',reviewer:'Рецензент и редактор'};
function researchWebPermission(plan) {
  if(!plan.web_search)return 'Веб-поиск отключён; только переданные материалы';
  const protocol=reviewedProtocol(plan);if(!protocol)return 'Веб-поиск включён';
  const roles=Array.isArray(protocol.web_search_roles)?protocol.web_search_roles:[];
  return roles.length?'Веб-поиск разрешён ролям: '+roles.map(role=>agentRoleNames[role] || role).join(', ')+'. У остальных ролей отключён.':'Веб-разрешения ролей не зафиксированы; проверьте точный протокол.';
}
function literalText(value, fallback='Неизвестно') { return value === undefined || value === null || value === '' ? fallback : typeof value === 'object' ? JSON.stringify(value,null,2) : String(value); }
function updateResearchMode(prefix, requestedTimeout) {
  const reviewed=$('#'+prefix+'-mode').value==='reviewed',input=$('#'+prefix+'-timeout');
  const maximum=state.bootstrap?.settings?.source_grounding?360:240;
  input.min=reviewed?'200':'60';input.max=reviewed?String(maximum):'600';
  let value=Number(requestedTimeout ?? input.value);
  if(!Number.isInteger(value)||value<Number(input.min)||value>Number(input.max))value=reviewed?240:180;
  input.value=String(value);
  $('#'+prefix+'-mode-hint').textContent=reviewed?`Три отдельных прохода: исследователь и прикладной аналитик → критик → рецензент и редактор. Всего 200–${maximum} секунд; резервируются 3 вызова CLI из лимита за 24 часа.`:'Один ответ выбранного исполнителя. Всего 60–600 секунд; резервируется 1 вызов CLI из лимита за 24 часа.';
}

async function api(path, body) {
  const options = {headers: {'Accept':'application/json'}, cache:'no-store'};
  if (body !== undefined) { options.method = 'POST'; options.headers['Content-Type'] = 'application/json'; options.headers['X-Lab-Token'] = state.csrf; options.body = JSON.stringify(body); }
  let response;
  try { response = await fetch(path, options); } catch { throw new Error('Нет связи с лабораторией. Проверьте, что окно локального сервера открыто.'); }
  const contentType = response.headers.get('Content-Type') || '';
  const data = contentType.includes('json') ? await response.json() : {error: await response.text()};
  if (!response.ok) throw new Error(data.error || `Ошибка ${response.status}`);
  return data;
}
async function busy(element, work) { const disabled = element.disabled; element.disabled = true; try { return await work(); } catch (error) { showError(error); } finally { element.disabled = disabled; } }

function switchView(view) {
  if (view !== 'runs') stopStoryboard();
  state.view = view;
  if (['reactor','observatory'].includes(view)) globalThis.FrontierLive?.enter(view).catch(showError);
  else globalThis.FrontierLive?.leave();
  $$('.view').forEach(element => {element.hidden = element.id !== 'view-' + view;});
  $$('.nav-button').forEach(element => {const active = element.dataset.view === view; element.classList.toggle('active', active); if (active) element.setAttribute('aria-current', 'page'); else element.removeAttribute('aria-current');});
  if (view === 'research') globalThis.LabResearch?.mountWorkspace($('#research-workspace'),api);
  if (view === 'runs') refreshRuns().catch(showError);
  if (view === 'knowledge') refreshKnowledge().catch(showError);
  if (view === 'tasks') refreshTasks().catch(showError);
  if (view === 'settings') Promise.all([refreshBootstrap(true),refreshMemory(true),refreshPublication()]).catch(showError);
}

const publicationWeekdays = ['Понедельник','Вторник','Среда','Четверг','Пятница','Суббота','Воскресенье'];
const publicationStatusNames = {awaiting_owner:'Ждёт вашего апрува',queued:'В очереди',publishing:'Отправляется',published:'Опубликован',publication_uncertain:'Исход отправки нужно проверить',blocked:'Выпуск остановлен',cancelled:'Отменён',waiting_configuration:'Ждёт настройки канала и расписания'};
function publicationDate(value) {
  if(!value)return 'Время пока не назначено';
  const parsed=new Date(value);
  return Number.isNaN(parsed.getTime())?'Время пока не назначено':parsed.toLocaleString('ru-RU',{timeZone:'Europe/Moscow',day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'})+' МСК';
}
function markPublicationDirty(){publicationDirty=true;$('#publication-edit-state').textContent='Есть несохранённые изменения.';}
function addPublicationSlot(slot={}) {
  const rows=$('#publication-slots');if(rows.children.length>=7)return;
  const row=node('div','publication-slot'),identity=++publicationSlotId;
  const dayLabel=node('label','','День недели'),day=node('select');day.id='publication-day-'+identity;dayLabel.htmlFor=day.id;day.required=true;
  const placeholder=node('option','','Выберите день');placeholder.value='';day.append(placeholder);
  publicationWeekdays.forEach((title,index)=>{const option=node('option','',title);option.value=String(index);day.append(option);});
  day.value=Number.isInteger(slot.weekday)?String(slot.weekday):'';day.dataset.publicationField='weekday';dayLabel.append(day);
  const timeLabel=node('label','','Время МСК'),time=node('input');time.id='publication-time-'+identity;timeLabel.htmlFor=time.id;time.type='time';time.required=true;time.value=typeof slot.time==='string'?slot.time:'';time.dataset.publicationField='time';timeLabel.append(time);
  const remove=button('Удалить',()=>{row.remove();markPublicationDirty();$('#publication-add-slot').disabled=false;},'text-button');remove.setAttribute('aria-label','Удалить время выпуска');
  day.addEventListener('change',markPublicationDirty);time.addEventListener('input',markPublicationDirty);
  append(row,dayLabel,timeLabel,remove);rows.append(row);$('#publication-add-slot').disabled=rows.children.length>=7;
}
function renderPublication(data) {
  publicationData=data;
  globalThis.FrontierLive?.publication(data);
  const status=$('#publication-status');status.replaceChildren();
  append(status,node('strong','',data.channel_configured?'Канал: '+(data.channel_title||'подключён'):'Канал не подключён'));
  if(!data.channel_configured)status.append(node('p','small','Публикация в канал заблокирована. Сохранить расписание и поставить готовые выпуски в очередь можно; отправок в канал не будет.'));
  const slots=Array.isArray(data.slots)?data.slots:[];
  if(!slots.length)status.append(node('p','small','Расписание не задано.'));
  else status.append(node('p','small','Сохранённое расписание: '+slots.map(slot=>(publicationWeekdays[slot.weekday]||'День')+' '+slot.time+' МСК').join('; ')+'.'));
  if(!data.enabled)status.append(node('p','small','Автоматический выпуск выключен.'));
  if(data.blocked_reason)status.append(node('p','field-hint',data.blocked_reason));
  if(data.next_slot)status.append(node('p','small','Ближайший слот: '+publicationDate(data.next_slot)));
  if(!publicationDirty&&!publicationSaving){
    $('#publication-enabled').checked=Boolean(data.enabled);$('#publication-slots').replaceChildren();
    slots.slice(0,7).forEach(slot=>addPublicationSlot(slot));$('#publication-edit-state').textContent='';
  }
  $('#publication-enabled').disabled=false;
  $('#publication-add-slot').disabled=$('#publication-slots').children.length>=7;
  $('#publication-form button[type=submit]').disabled=publicationSaving;
  $('#publication-channel-form button[type=submit]').disabled=publicationChannelSaving;
  const queue=$('#publication-queue');queue.replaceChildren();
  const items=Array.isArray(data.items)?data.items:[];
  if(!items.length){queue.append(node('p','small muted','Очередь пуста. Просмотрите готовый комплект в Telegram и нажмите «В очередь».'));return;}
  for(const item of items){
    const entry=node('article','publication-entry');
    append(entry,node('h4','',item.title||'Готовый выпуск'),node('p','small',publicationStatusNames[item.status]||'Состояние уточняется'));
    if(item.approved_at)entry.append(node('p','field-hint','Одобрено: '+publicationDate(item.approved_at)));
    if(item.status==='queued')entry.append(node('p','field-hint',item.due_at?'Выпуск: '+publicationDate(item.due_at):'Ждёт канала и настроенного расписания.'));
    const blockers=Array.isArray(item.blockers)?item.blockers:[];
    if(blockers.length)entry.append(node('p','field-hint',blockers.filter(value=>typeof value==='string').join(' · ')));
    if(item.id&&['awaiting_owner','queued','blocked'].includes(item.status))entry.append(button('Убрать из очереди',event=>busy(event.currentTarget,async()=>{
      await api('/api/publication/'+encodeURIComponent(item.id)+'/cancel',{});
      await refreshPublication();notify('Выпуск убран из очереди. Исследование и база знаний сохранены.');
    }),'text-button'));
    queue.append(entry);
  }
}
async function refreshPublication(){
  const request=++publicationRequest;
  try{const data=await api('/api/publication');if(request===publicationRequest)renderPublication(data);}
  catch(error){if(request===publicationRequest)$('#publication-status').replaceChildren(notice('Не удалось загрузить публикацию. '+errorMessage(error)));}
}

function updateCounts(bootstrap) {
  const counts = bootstrap.counts || {};
  $('#count-sources').textContent = counts.sources ?? state.sources.length;
  $('#count-runs').textContent = counts.runs ?? state.runs.length;
  $('#count-knowledge').textContent = counts.knowledge ?? state.knowledge.length;
  $('#version').textContent = bootstrap.version ? 'Локальная версия ' + bootstrap.version : 'Локальная версия';
}
function fillSettings(bootstrap) {
  const settings = bootstrap.settings || {};
  const values = {provider:settings.provider || 'codex', model:settings.model || '', timeout:settings.timeout_seconds || 180, daily:settings.daily_run_limit || 3};
  for (const prefix of ['setting', 'research']) {
    $('#' + prefix + '-provider').value = values.provider;
    $('#' + prefix + '-model').value = values.model;
    $('#' + prefix + '-mode').value = settings.research_mode === 'reviewed' ? 'reviewed' : 'single';
    updateResearchMode(prefix,values.timeout);
    $('#' + prefix + '-web').checked = Boolean(settings.web_search);
  }
  $('#setting-daily').value = values.daily;
  renderProviders(bootstrap.providers || []);
}
function renderProviders(providers) {
  const target = $('#provider-status'); target.replaceChildren();
  for (const provider of providers) append(target, append(node('div','provider-line'), node('span','',provider.name || provider.id), node('span',provider.installed ? 'provider-installed' : 'provider-missing',provider.installed ? 'CLI найден' : 'CLI не установлен')));
  if (!providers.length) target.append(notice('Исполнители пока не обнаружены. Установите Codex CLI или Claude Code и войдите в аккаунт.'));
}
function renderTelegram(telegram = {}) {
  const box = $('#telegram-status'); box.replaceChildren();
  const connected = Boolean(telegram.owner_id);
  const title = connected ? 'Бот привязан к вашему аккаунту' : telegram.configured ? 'Ожидает привязки владельца' : 'Бот пока не подключён';
  append(box,node('strong','',title));
  if (telegram.username) box.append(link('https://t.me/' + String(telegram.username).replace(/^@/,''), '@' + String(telegram.username).replace(/^@/,'')));
  if (telegram.status) box.append(node('p','small',telegram.status));
  if (connected) box.append(node('p','small','Пересылайте выбранные материалы из «Избранного». Бот покажет план с памятью и уроками; запуск — после вашего апрува кнопкой. Выводы придут сюда же, полный отчёт сохранится в базе знаний. Лаборатория должна быть запущена на компьютере.'));
  const pairing = telegram.pairing_code;
  $('#telegram-pairing').hidden = !pairing || connected;
  $('#pairing-command').textContent = pairing ? '/start ' + pairing : '';
  $('#telegram-disconnect').hidden = !telegram.configured;
}
async function refreshBootstrap(fill = false) {
  const previous = state.bootstrap;
  const bootstrap = await api('/api/bootstrap');
  state.bootstrap = bootstrap; state.csrf = bootstrap.csrf || state.csrf;
  updateCounts(bootstrap); renderTelegram(bootstrap.telegram); renderProviders(bootstrap.providers || []);
  renderOperations(bootstrap.operations);
  if (fill || !previous) fillSettings(bootstrap);
  $('#connection-error').hidden = true;
  return bootstrap;
}
function renderOperations(data) {
  const host=$('#operations-status'); if(!host)return;
  host.replaceChildren();
  if(!data){host.append(node('p','small muted','Состояние обслуживания пока неизвестно.'));return;}
  const backup=data.backup||{},latest=backup.latest,drill=data.restore_drill||{},supervisor=data.supervisor||{},startup=data.startup||{},controls=data.quality_controls||{};
  const rows=[['Автовосстановление',supervisor.fresh&&supervisor.status==='healthy'?'Сервис под наблюдением': 'Наблюдение не подтверждено'],
    ['После входа в Windows',startup.configured?'Автозапуск настроен':'Автозапуск не подтверждён'],
    ['Полная копия',latest?date(latest.created_at)+(backup.due?' · нужна новая':''):'Копии ещё нет'],
    ['Восстановление',drill.status==='passed'?'Проверено в отдельной папке': 'Проверка ещё не завершена'],
    ['Контрольные примеры',Number.isInteger(controls.case_count)?`${controls.matched_case_count}/${controls.case_count} заданных проверок`: 'Ещё не проверены']];
  for(const [label,value] of rows){const item=node('div','operation-tile');append(item,node('span','small muted',label),node('strong','',value));host.append(item);}
  if(backup.error||data.maintenance?.status==='error')host.append(node('p','notice error','Обслуживание требует внимания. История и очередь сохранены; исследования не повторялись.'));
}
async function refreshSources() {
  const query = $('#source-search').value.trim();
  const result = await api('/api/sources?q=' + encodeURIComponent(query));
  state.sources = result.items || []; renderSources(); renderSourceDetail();
}
function renderSources() {
  const list = $('#source-list'); list.replaceChildren();
  $('#source-list-count').textContent = String(state.sources.length);
  if (!state.sources.length) { list.append(empty('↙', $('#source-search').value ? 'Ничего не найдено' : 'Входящие пока пусты', $('#source-search').value ? 'Попробуйте другой запрос.' : 'Сохраните первую статью, сообщение или ссылку.')); updateSelection(); return; }
  for (const source of state.sources) {
    const row = node('div','source-row' + (source.id === state.sourceId ? ' active' : ''));
    const check = document.createElement('input'); check.type = 'checkbox'; check.checked = state.selected.has(source.id); check.setAttribute('aria-label','Выбрать: ' + (source.title || 'Материал'));
    check.addEventListener('change', () => {if (check.checked) {state.selected.add(source.id); state.sourceId = source.id;} else state.selected.delete(source.id); renderSources(); renderSourceDetail();});
    const content = button('', () => {state.sourceId = source.id; state.selected = new Set([source.id]); renderSources(); renderSourceDetail();}, 'source-open');
    const origin = source.origins?.[0];
    append(content,node('div','item-title',source.title || 'Материал без названия'), node('p','source-preview',source.text || source.url || ''), append(node('div','item-meta'), node('span','',date(source.created_at)), node('span','',String(origin?.kind || '').startsWith('telegram') ? 'Telegram' : source.url ? 'Ссылка' : 'Текст')));
    if (tags(source.tags).length) content.append(renderTags(tags(source.tags).slice(0,3)));
    append(row,check,content); list.append(row);
  }
  updateSelection();
}
function renderSourceDetail() {
  const source = state.sources.find(item => item.id === state.sourceId);
  const target = $('#source-detail');
  if (!source) {
    target.replaceChildren(empty('↙','Всё интересное — в одном месте','Добавьте текст или ссылку, импортируйте JSON из «Избранного» либо подключите Telegram-бота в настройках.',button('Добавить материал',openSourceDialog)));
    updateSelection(); return;
  }
  target.replaceChildren(node('span','source-label','Исходный материал'), node('h2','',source.title || 'Материал без названия'));
  if (source.url) { const sourceLink = link(source.url); if (sourceLink) target.append(sourceLink); }
  if (source.text) target.append(node('pre','source-body',source.text));
  else target.append(notice('Сохранена ссылка. Её содержимое ещё не прочитано. Для изучения страницы включите веб-поиск либо добавьте текст материала.'));
  if (tags(source.tags).length) target.append(renderTags(source.tags));
  const origins = source.origins || (source.origin ? [source.origin] : []);
  let originText = 'Сохранено ' + date(source.created_at);
  if (origins.length) originText += ' · Источников происхождения: ' + origins.length;
  target.append(node('div','source-origin',originText));
  updateSelection();
}
function updateSelection() {
  const count = state.selected.size;
  $('#selection-summary').textContent = count ? `Выбрано материалов: ${count}` : 'Выберите материал слева';
  $('#prepare-button').disabled = !count;
}
function openSourceDialog() { $('#source-form').reset(); $('#source-dialog').showModal(); $('#source-title').focus(); }

async function refreshRuns() { const result = await api('/api/runs');lastFrontierPoll=Date.now(); state.runs = result.items || []; renderRuns(); if(state.runId&&!state.runs.some(r=>r.id===state.runId))state.runId=null; if (state.runId) await selectRun(state.runId, false); else if(['reactor','observatory'].includes(state.view)) await globalThis.FrontierLive?.enter(state.view); }
function boundedRunTitle(value) {
  const title=String(value || 'Исследование').replace(/\s+/g,' ').trim();
  return title.length<=180?title:title.slice(0,179).replace(/[\uD800-\uDBFF]$/,'')+'…';
}
function renderRuns() {
  const target = $('#run-list'); target.replaceChildren(); $('#run-list-count').textContent = state.runs.length;
  if (!state.runs.length) { target.append(empty('◎','Пока нет запусков','Первое исследование начинается с вашего вопроса.')); return; }
  for (const run of state.runs) {
    const plan = run.plan || {};
    const row = button('',() => selectRun(run.id).catch(showError),'run-row' + (run.id === state.runId ? ' active' : ''));
    const question=plan.question || run.question || 'Исследование';
    const itemTitle=node('div','item-title',boundedRunTitle(question));itemTitle.title=question;
    append(row,statusBadge(run.status),itemTitle,append(node('div','item-meta'),node('span','',providerName(plan.provider || run.provider)),node('span','',date(run.created_at)))); target.append(row);
  }
}
async function selectRun(id, highlight = true) {
  const request=++runSelection;state.runId=id;globalThis.FrontierLive?.loading(id);
  try{const run=await api('/api/runs/'+encodeURIComponent(id));if(request!==runSelection||state.runId!==id)return;
    if(state.view==='runs')renderRunDetail(run);if(highlight)renderRuns();
    await globalThis.FrontierLive?.selected(run);
  }catch(error){if(request===runSelection)globalThis.FrontierLive?.failed(id,error);throw error;}
}
function renderRunDetail(run) {
  const target = $('#run-detail'), plan = run.plan || {};
  const fingerprint = JSON.stringify([run.id,run.status,run.plan_hash,run.output,run.error,run.finished_at,run.usage,run.agent_pipeline,run.agent_review]);
  if (target.dataset.fingerprint === fingerprint) return;
  stopStoryboard();
  target.dataset.fingerprint = fingerprint;
  target.replaceChildren();
  const originalQuestion = plan.question || run.question || 'Исследование';
  const title = run.status === 'completed' ? boundedRunTitle(plan.study_context?.task?.title || plan.sources?.[0]?.title || originalQuestion) : originalQuestion;
  append(target,append(node('div','report-heading'),append(node('div'),statusBadge(run.status),node('h2','',title))),node('p','report-meta',[providerName(plan.provider || run.provider),plan.model || 'Модель по умолчанию',date(run.created_at)].filter(Boolean).join(' · ')));
  if (title!==originalQuestion) {
    const questionDetails=node('details','report-question');
    append(questionDetails,node('summary','','Вопрос исследования'),node('p','memory-literal',originalQuestion));target.append(questionDetails);
  }
  if (activeStatuses.has(run.status)) target.append(notice('Исследование выполняется. Отчёт появится здесь автоматически. Повторный запуск не нужен.','running'));
  if (run.status === 'outcome_unknown' || run.status === 'unknown' || run.status === 'interrupted') target.append(notice('Внешний запуск был прерван или не подтвердил результат. Расход мог произойти. Автоматического повтора не будет.','error'));
  if (run.error) target.append(notice(run.error,'error'));
  if (reviewedProtocol(plan)) target.append(renderAgentPipeline(run));
  if (run.agent_review && !(run.status === 'completed' && run.output)) target.append(renderAgentReview(run.agent_review));
  if (run.status === 'completed' && run.output) {
    const presentationHost = node('section','result-presentation');
    presentationHost.setAttribute('aria-label','Краткий разбор и материалы для публикации');
    presentationHost.append(node('p','loading-message','Собираем краткий разбор из готового отчёта…'));
    target.append(presentationHost);
    loadPresentation(run,presentationHost);
  }
  if (['completed','failed','cancelled','outcome_unknown'].includes(run.status)) {
    const reviewHost=node('section','research-review');reviewHost.setAttribute('aria-label','Решения, расходы, доказательства и качество');
    target.append(reviewHost);loadResearchReview(run,reviewHost);
  }
  if (run.output) {
    const fullReport = node('details','report-full');
    append(fullReport,node('summary','','Полный отчёт и доказательства'),notice('Анализ модели по сохранённым материалам' + (plan.web_search ? ' с разрешённым веб-поиском.' : '. Веб-поиск был отключён.') + ' Это не воспроизведённый эксперимент.'),node('pre','report-text',reportDisplayText(run.output)));
    if (run.status !== 'completed') fullReport.open = true;
    target.append(fullReport);
  }
  if (typeof run.output === 'string' && reportDisplayText(run.output) !== run.output.trim()) {
    const rawAnswer=node('details');append(rawAnswer,node('summary','','Исходный ответ со служебными блоками'),node('pre','technical-data',run.output));target.append(rawAnswer);
  }
  if (run.status === 'completed' && !run.output) target.append(notice('Исполнитель завершил запуск без текстового отчёта. Посмотрите сведения о запуске.'));
  const links = run.links || [];
  if (links.length) {
    const list = node('ul','report-links');
    for (const item of links) { const sourceLink = link(typeof item === 'string' ? item : item.url, typeof item === 'string' ? item : item.title || item.url); if (sourceLink) list.append(append(node('li'),sourceLink)); }
    if (list.childElementCount) {const sources=node('details','report-source-details');append(sources,node('summary','','Ссылки из ответа модели · ' + list.childElementCount),node('p','small muted','Наличие ссылки не подтверждает её прочтение или достоверность вывода.'),list);target.append(sources);}
  }
  const details = node('details'); append(details,node('summary','','План и сведения о запуске'),node('pre','technical-data',JSON.stringify({plan,usage:run.usage || {},id:run.id,plan_hash:run.plan_hash,status:run.status},null,2))); target.append(details);
  target.append(contextTrace(run));
  const actions = node('div','report-actions');
  if (['failed','cancelled','outcome_unknown'].includes(run.status) && !plan.continuation && ['three-pass-v2','three-pass-v3','three-pass-v4'].includes(plan.research_protocol?.version) && (run.agent_pipeline?.phases || []).filter(row=>row.index<2 && row.status==='completed' && row.dispatched===true).length===2) actions.append(button('Продолжить с редактора',event=>busy(event.currentTarget,async()=>{const next=await api('/api/runs/'+encodeURIComponent(run.id)+'/continue',{});await refreshRuns();await openPlanApproval(next);notify('Checkpoint готов. Новый вызов — только после апрува.');}),'button primary'));
  if (run.status === 'completed' && run.output) actions.append(button('Сохранить в базу знаний',() => openSaveDialog(run),'button primary'));
  if (run.status === 'completed' && run.output) actions.append(button('Создать урок из отчёта',event => busy(event.currentTarget,() => openLessonEditor(null,{run}))));
  if (run.output) actions.append(button('Скачать отчёт ↓',() => downloadText('# ' + originalQuestion + '\n\n' + reportDisplayText(run.output), 'research-' + run.id + '.md','text/markdown;charset=utf-8')));
  if (activeStatuses.has(run.status)) actions.append(button('Остановить',async event => {await busy(event.currentTarget, async () => {await api('/api/runs/' + encodeURIComponent(run.id) + '/cancel',{}); await refreshRuns(); notify('Запрошена остановка. Уже начатый внешний вызов мог использовать лимит.');});},'button danger'));
  if (run.status === 'planned') {
    actions.append(button('Открыть подтверждение',event => busy(event.currentTarget,() => openPlanApproval(run)),'button primary'));
    actions.append(button('План в Telegram',event => busy(event.currentTarget,() => sendTelegramPlan(run))));
  }
  target.append(actions);
}

function stopStoryboard() { if (storyboardTimer !== null) clearInterval(storyboardTimer); storyboardTimer = null; if(storyboardReset)storyboardReset(); }
function presentationText(value) {
  if (typeof value === 'string') return value;
  if (!value || typeof value !== 'object') return '';
  const label=value.name || value.label || value.title || '';
  const text=value.text || value.description || value.definition || value.value || value.detail || '';
  return [label,text].filter((item,index,array)=>typeof item==='string' && item && array.indexOf(item)===index).join(': ');
}
function presentationList(value) {return (Array.isArray(value)?value:typeof value==='string'?[value]:[]).map(presentationText).filter(Boolean).slice(0,8);}
function artifactLink(runId, file, text) {
  const anchor=node('a','text-button result-export',text);
  anchor.href='/api/runs/'+encodeURIComponent(runId)+'/'+file;
  anchor.download=file.replace(/\./g,'-'+runId+'.');
  return anchor;
}
async function sendTelegramPlan(run) {
  await api('/api/telegram/plans',{run_id:run.id});
  notify('План передан боту. Проверьте память и уроки перед апрувом в Telegram.');
}
async function loadPresentation(run, host, reload=false) {
  const cacheKey=run.id+':'+run.finished_at+':'+run.output.length;
  try {
    if (reload) presentationCache.delete(cacheKey);
    let pending=presentationCache.get(cacheKey);
    if (!pending) {pending=api('/api/runs/'+encodeURIComponent(run.id)+'/presentation');presentationCache.set(cacheKey,pending);}
    const data=await pending;
    if (!host.isConnected) return;
    renderPresentation(run,data,host);
  } catch(error) {
    presentationCache.delete(cacheKey);
    if (!host.isConnected) return;
    host.replaceChildren(notice('Краткий разбор пока недоступен. Полный отчёт сохранён ниже.'),button('Загрузить разбор',event=>busy(event.currentTarget,()=>loadPresentation(run,host,true)),'text-button'));
  }
}
function renderPresentation(run,data,host) {
  host.replaceChildren();
  if (!data || typeof data !== 'object') {host.append(notice('Полный отчёт доступен ниже. Краткая версия пока не подготовлена.'));return;}
  const headline=node('div','result-overview');
  const story=Array.isArray(data.story)?data.story:[];
  append(headline,node('span','eyebrow','ЗАДАЧА → МЕХАНИЗМ → ДОКАЗАТЕЛЬСТВА → ПРИМЕНЕНИЕ'),node('h2','result-title',presentationText(data.title) || 'Что мы выяснили'));
  if (!story.length) append(headline,node('p','result-verdict',presentationText(data.verdict) || presentationText(data.summary) || 'Вывод требует прочтения полного отчёта.'));
  if (!story.length && data.summary && data.summary!==data.verdict) headline.append(node('p','result-summary',presentationText(data.summary)));
  const evidence=node('div','result-evidence');
  evidence.append(node('span','result-evidence-label','Анализ источников · без воспроизведения эксперимента'));
  if (data.provenance?.notice) evidence.append(node('p','field-hint',data.provenance.notice));
  if (data.provenance?.mode==='legacy_extractive') evidence.append(node('p','field-hint','Краткая версия извлечена из ранее сохранённого отчёта; нового исследования не было.'));
  append(headline,evidence);host.append(headline);
  globalThis.LabResearch?.mountRun(host,run,data,api);
  if (data.applied_analysis?.rows) host.append(renderAppliedAnalysis(data.applied_analysis));
  if (data.agent_review || run.agent_review) host.append(renderAgentReview(data.agent_review || run.agent_review));
  if(data.publication_checks&&typeof data.publication_checks==='object'){
    const checks=data.publication_checks,ready=checks.status==='ready',box=node('section','publication-checks '+(ready?'ready':'incomplete'));
    const checkLabel=checks.automatic===false?'Проверка редакторского комплекта':'Автоматическая проверка комплекта';
    box.dataset.publicationStatus=ready?'ready':'incomplete';append(box,node('h3','',checkLabel+(ready?': готов':': есть пробелы')),node('p','',checks.notice||'Проверены структура и наличие оснований; научная достоверность и переносимость требуют проверки.'));
    if(checks.numeric_note)box.append(node('p','',checks.numeric_note));const issues=presentationList(checks.issues);if(issues.length){const list=node('ul');issues.forEach(text=>list.append(node('li','',text)));box.append(list);}host.append(box);
  }
  if (story.length) {
    host.append(renderInfographicCover(run,data));
    const narrative=node('div','research-story');
    for(const [index,part] of story.entries()) {
      const section=node('section','story-section story-section-'+String(part.id||index).replace(/[^a-z0-9_-]/gi,''));
      section.dataset.storyId=String(part.id||index);
      append(section,node('span','story-order',String(index+1).padStart(2,'0')),node('h3','',part.title || 'Разбор'));
      if(part.text)section.append(node('p','',presentationText(part.text)));
      const items=presentationList(part.items);if(items.length){const list=node('ul');items.forEach(text=>list.append(node('li','',text)));section.append(list);}
      if(part.id==='mechanism'){const technical=node('details','mechanism-details');append(technical,node('summary','','Техническая схема и анимация по шагам'),renderMechanism(run,data.visual,data.provenance?.editorial_version||data.provenance?.review_version));technical.addEventListener('toggle',()=>{if(!technical.open)stopStoryboard();});section.append(technical);}
      if(part.id==='findings'&&Array.isArray(data.comparisons)&&data.comparisons.length)section.append(renderComparisons(run,data.comparisons));
      narrative.append(section);
    }
    host.append(narrative);
  } else host.append(renderMechanism(run,data.visual,data.provenance?.editorial_version||data.provenance?.review_version));
  const grid=node('div','result-facts');
  const cards=[['Где применять','applicability','application'],['Плюсы','pros','advantages'],['Минусы и риски','cons','limitations'],['Что измерять','metrics','metrics'],['Инфраструктура','infrastructure','infrastructure'],['Сложность настройки','setup','setup']];
  for (const [label,key,kind] of cards) {
    const card=node('section','result-fact result-fact-'+kind);card.append(node('h3','',label));
    const items=presentationList(data[key]);
    if (items.length) {const list=node('ul');items.forEach(text=>list.append(node('li','',text)));card.append(list);}
    else card.append(node('p','result-unknown','Не установлено в этом разборе.'));
    grid.append(card);
  }
  if(!story.length)host.append(grid);
  const next=node('section','result-next');append(next,node('span','section-number','→'),append(node('div'),node('h3','','Следующий самый дешёвый шаг'),node('p','',presentationText(data.next_step) || 'Уточнить задачу, baseline и условия будущей проверки.')));host.append(next);
  const exports=node('div','result-export-row');
  exports.append(artifactLink(run.id,'card.svg','Карточка SVG ↓'));
  if (data.visual?.png_available) exports.append(artifactLink(run.id,'card.png','Карточка PNG ↓'));
  if (data.visual?.video_available) exports.append(artifactLink(run.id,'animation.mp4','Анимация MP4 · 1080 px ↓'));
  else if (data.visual?.animation_available) exports.append(artifactLink(run.id,'animation.gif','Анимация GIF ↓'));
  host.append(exports);
  const post=node('details','result-post');
  append(post,node('summary','','Готовый пост для Telegram-канала'));
  const postId='post-draft-'+run.id;
  const label=node('label','','Пост: разбор технологии и применимость');label.htmlFor=postId;
  const area=node('textarea','result-post-text');area.id=postId;area.rows=12;area.value=typeof data.post_text==='string'?data.post_text:'';area.spellcheck=false;
  append(post,label,node('p','field-hint','Текст подготовлен по правилам публикации. Апрув исследования не публикует пост. После просмотра точного комплекта в Telegram — кнопка «В очередь».'),area);
  if(data.publication_rules){
    const rules=node('details','publication-rules');append(rules,node('summary','','Правила этого формата'),node('p','small muted',(data.publication_rules.sections||[]).join(' → ')),node('p','small muted','До '+String(data.publication_rules.maximum_utf16||3500)+' знаков UTF-16. Сохраняем авторство, условия чисел, ограничения и источники. Служебные сообщения в пост не входят.'));post.append(rules);
  }
  const postActions=node('div','result-post-actions');
  postActions.append(button('Скопировать пост',async event=>busy(event.currentTarget,async()=>{try{await navigator.clipboard.writeText(area.value);notify('Готовый пост скопирован.');}catch{area.focus();area.select();notify('Текст выделен. Скопируйте его сочетанием Ctrl+C.');}}),'button primary'));
  postActions.append(button('Скачать текст ↓',()=>downloadText(area.value,'telegram-post-'+run.id+'.txt','text/plain;charset=utf-8')));
  append(post,postActions,node('p','field-hint','Карточку или анимацию можно приложить к посту. Источники и границы выводов оставьте в публикации.'));
  host.append(post);
  const telegram=node('div','result-telegram');
  telegram.append(button('Отправить результат мне в Telegram',event=>busy(event.currentTarget,async()=>{await api('/api/telegram/results',{run_id:run.id});notify('Результат передан боту для доставки.');})));
  telegram.append(node('span','field-hint','Готовый пост, инфографика и анимация — в ваш личный чат с ботом. Кнопка «В очередь» отдельно одобряет публикационный комплект. Полный отчёт доступен в базе знаний.'));
  host.append(telegram);
  const quality=node('details','result-quality');quality.append(node('summary','','Проверки качества и пробелы в доказательствах'));
  let qualityLoaded=false;
  quality.addEventListener('toggle',async()=>{if(!quality.open||qualityLoaded)return;qualityLoaded=true;const box=node('div','quality-findings');quality.append(box);try{const audit=await api('/api/runs/'+encodeURIComponent(run.id)+'/quality');box.append(node('p','field-hint','Это проверка происхождения данных и логики отчёта; независимая научная достоверность не подтверждена.'));for(const finding of audit.findings||[]){const row=node('div','quality-finding');append(row,node('strong','',finding.status==='pass'?'✓':finding.status==='not_applicable'?'—':'!'),node('span','',finding.detail||finding.id));box.append(row);}}catch(error){qualityLoaded=false;box.append(node('p','notice error',errorMessage(error)));}});
  host.append(quality);
}
function renderAgentPipeline(run) {
  const pipeline=run.agent_pipeline || {},protocol=reviewedProtocol(run.plan),section=node('section','agent-pipeline');
  const resume=Boolean(run.plan?.continuation);
  append(section,node('h3','',resume?'Продолжение с редактора':'Три прохода исследования'),node('p','small',resume?'Два исходных этапа переиспользованы. Здесь учитывается только один новый вызов редактора; старый неизвестный расход сохраняется отдельно.':'Исследователь и прикладной аналитик → критик → рецензент и редактор. Все проходы используют выбранного исполнителя и учитываются отдельно в лимите CLI.'));
  if(resume)append(section,node('pre','technical-data',JSON.stringify(pipeline.reused_phases || [],null,2)));
  const reserved=pipeline.reserved_calls ?? protocol?.max_calls,dispatched=pipeline.dispatched_calls;
  append(section,node('p','agent-budget',`Вызовы CLI: резерв ${literalText(reserved)}, отправлено ${literalText(dispatched,'пока неизвестно')}${pipeline.uncertain_calls ? ', исход отправки уточняется: '+pipeline.uncertain_calls : ''}. Общий предел: ${literalText(pipeline.total_timeout_seconds ?? protocol?.total_timeout_seconds ?? run.plan?.timeout_seconds)} сек.${typeof pipeline.elapsed_seconds==='number' ? ' Прошло: '+pipeline.elapsed_seconds.toFixed(1)+' сек.' : ''}`));
  const phases=Array.isArray(pipeline.phases)?pipeline.phases:[];
  if(phases.length){const list=node('ol','agent-phase-list');for(const phase of phases){const item=node('li');append(item,node('strong','',agentRoleNames[phase.role] || phase.role || 'Проход'),node('span','',` · ${literalText(phase.status)}${typeof phase.elapsed_seconds==='number'?' · '+phase.elapsed_seconds.toFixed(1)+' сек.':''} · CLI ${phase.dispatched===true?'отправлен':phase.dispatched===false?'не отправлен':'уточняется'}`));if(phase.usage&&Object.keys(phase.usage).length)append(item,node('pre','agent-usage',JSON.stringify(phase.usage,null,2)));list.append(item);}section.append(list);}
  section.append(node('p','field-hint','Резерв — верхняя граница вызовов, а не точная стоимость. Пропущенная фаза не означает нулевой расход уже отправленного вызова. Токены и стоимость показаны только при наличии данных CLI.'));
  const journal=node('details','agent-journal'),body=node('div','agent-journal-body');append(journal,node('summary','','Журнал отдельных проходов: запросы, ответы и расход'),body);
  const cacheKey=run.id+':'+run.status+':'+(run.finished_at||'')+':'+JSON.stringify(pipeline);
  let loaded=false;
  const load=async(refresh=false)=>{body.replaceChildren(node('p','small muted','Загружаем сохранённый журнал…'));try{if(refresh)agentTraceCache.delete(cacheKey);let request=agentTraceCache.get(cacheKey);if(!request){request=api('/api/runs/'+encodeURIComponent(run.id)+'/agents');agentTraceCache.set(cacheKey,request);}const data=await request;if(!journal.isConnected)return;body.replaceChildren();const records=Array.isArray(data.phases)?data.phases:[];if(!records.length)body.append(node('p','small muted','Отдельных проходов пока нет.'));for(const phase of records){const entry=node('details','agent-journal-phase');append(entry,node('summary','',`${phase.index ?? ''} · ${agentRoleNames[phase.role] || phase.role || 'Проход'} · ${literalText(phase.status)}`),node('h4','','Запрос'),node('pre','technical-data',literalText(phase.prompt,'Не сохранён')),node('h4','','Ответ'),node('pre','technical-data',literalText(phase.output,'Ответа нет')));const metadata={...phase};delete metadata.prompt;delete metadata.output;append(entry,node('h4','','Расход, контрольные суммы и контекст'),node('pre','technical-data',JSON.stringify(metadata,null,2)));body.append(entry);}if(activeStatuses.has(run.status))body.append(button('Обновить журнал',event=>busy(event.currentTarget,()=>load(true)),'text-button'));loaded=true;}catch(error){agentTraceCache.delete(cacheKey);loaded=false;body.replaceChildren(notice('Не удалось загрузить журнал. '+errorMessage(error)),button('Повторить загрузку',()=>load(),'text-button'));}};
  journal.addEventListener('toggle',()=>{if(journal.open&&!loaded)load();});section.append(journal);return section;
}
const comparisonBasisNames={unknown:'Неизвестно',hypothesis:'Гипотеза',author_claim:'Заявление автора',external_measurement:'Внешнее измерение',estimate:'Оценка'};
function appliedValue(value,unit,label) {
  const field=value&&typeof value==='object'?value:{},cell=node('td');
  cell.dataset.label=label;
  append(cell,node('strong','',literalText(field.label)),node('p','',typeof field.value==='number'&&Number.isFinite(field.value)?String(field.value)+(unit?' '+unit:''):'Неизвестно'),node('p','field-hint',comparisonBasisNames[field.basis] || literalText(field.basis)));
  if(Array.isArray(field.evidence_ids)&&field.evidence_ids.length)cell.append(node('p','field-hint','Основания: '+field.evidence_ids.join(', ')));return cell;
}
function renderAppliedAnalysis(analysis) {
  const section=node('section','applied-analysis');append(section,node('h3','','Прикладное сравнение по метрикам'),node('p','field-hint','Числа относятся к указанным источникам и условиям. «Неизвестно» сохраняет пробел в доказательствах; собственного бенчмарка не было.'));
  const rows=Array.isArray(analysis.rows)?analysis.rows:[];
  if(rows.length){const table=node('table','applied-table'),head=node('thead'),heading=node('tr');for(const text of ['Метрика','Baseline','Кандидат','Условия и сопоставимость']){const cell=node('th','',text);cell.scope='col';heading.append(cell);}head.append(heading);table.append(head);const body=node('tbody');for(const row of rows){const tr=node('tr'),metric=node('th');metric.scope='row';append(metric,node('strong','',literalText(row.metric)),node('p','',literalText(row.definition)),node('p','field-hint','Единица: '+literalText(row.unit)+' · '+({maximize:'больше — лучше',minimize:'меньше — лучше',descriptive:'описательный критерий'}[row.direction] || literalText(row.direction))));const conditions=node('td');conditions.dataset.label='Условия и сопоставимость';append(conditions,node('p','',literalText(row.conditions)),node('strong','',({comparable:'Сопоставимы',not_comparable:'Несопоставимы',unknown:'Сопоставимость неизвестна'}[row.comparability] || 'Сопоставимость неизвестна')),node('p','',literalText(row.comparability_reason)));append(tr,metric,appliedValue(row.baseline,row.unit,'Baseline'),appliedValue(row.candidate,row.unit,'Кандидат'),conditions);body.append(tr);}table.append(body);section.append(append(node('div','applied-table-scroll'),table));}else section.append(node('p','small muted','Строки с метриками не подготовлены.'));
  if(Array.isArray(analysis.unknowns)&&analysis.unknowns.length){append(section,node('h4','','Что осталось неизвестным'));const list=node('ul');analysis.unknowns.forEach(value=>list.append(node('li','',literalText(value))));section.append(list);}
  if(Array.isArray(analysis.analogues)&&analysis.analogues.length){append(section,node('h4','','Связь с выбранными прошлыми выводами'));for(const analogue of analysis.analogues){const item=node('article','applied-analogue');append(item,node('strong','',`${literalText(analogue.memory_id)} · v${literalText(analogue.memory_version)}`),node('p','',({supports:'Поддерживает',contradicts:'Противоречит',extends:'Дополняет',context:'Контекст'}[analogue.relation] || literalText(analogue.relation))+': '+literalText(analogue.relevance)),node('p','field-hint','Отличия условий: '+literalText(analogue.conditions_difference)));section.append(item);}}
  return section;
}
function renderAgentReview(review) {
  const section=node('details','agent-review');append(section,node('summary','','Замечания критика и решения рецензента · '+(review.status==='ready'?'проверка пройдена':'есть незакрытые вопросы')),node('p','field-hint','Это отдельные модельные проходы выбранного исполнителя. Проверка не заменяет воспроизведение результатов.'));
  if(review.notice)section.append(node('p','field-hint',literalText(review.notice)));
  if(Array.isArray(review.applied_analysis?.rows))section.append(node('p','small','Метрик в итоговом сравнении: '+review.applied_analysis.rows.length+'. Неизвестные значения и несопоставимые условия остаются в таблице.'));
  const issues=Array.isArray(review.critic?.issues)?review.critic.issues:[],dispositions=Array.isArray(review.dispositions)?review.dispositions:[];
  if(!issues.length)section.append(node('p','small','Критик не сохранил отдельных замечаний.'));
  for(const issue of issues){const item=node('article','agent-review-issue'),decision=dispositions.find(value=>value.issue_id===issue.id);append(item,node('h4','',({blocker:'Блокирующее',major:'Существенное',minor:'Замечание'}[issue.severity] || 'Замечание')+' · '+literalText(issue.target)),node('p','',literalText(issue.problem)),node('p','small','Нужно изменить: '+literalText(issue.required_change)),node('p','field-hint','Основания: '+(Array.isArray(issue.evidence_ids)&&issue.evidence_ids.length?issue.evidence_ids.join(', '):'не указаны')),node('p','',({fixed:'Исправлено',retained_with_limit:'Сохранено с оговоркой',unresolved:'Не устранено'}[decision?.status] || 'Решение отсутствует')+': '+literalText(decision?.reason)));if(decision?.resolution_excerpt)append(item,node('blockquote','memory-literal',literalText(decision.resolution_excerpt)));if(Array.isArray(decision?.resolution_evidence_ids)&&decision.resolution_evidence_ids.length)item.append(node('p','field-hint','Основания исправления: '+decision.resolution_evidence_ids.join(', ')));section.append(item);}
  if(Array.isArray(review.issues)&&review.issues.length){const list=node('ul','agent-review-blockers');review.issues.forEach(value=>list.append(node('li','',literalText(value))));section.append(list);}
  const exact=node('details');append(exact,node('summary','','Полный сохранённый результат проверки и покрытие метрик'),node('pre','technical-data',JSON.stringify(review,null,2)));section.append(exact);return section;
}
function renderApprovalComparison(plan) {
  const context=plan.comparison_context;if(!context||typeof context!=='object')return null;
  const section=node('section','approval-comparison');append(section,node('h3','','Что сравнить и какую память проверить'),node('p','field-hint','Это точный выбранный контекст сравнения для всех проходов. Прошлый вывод — основание для проверки применимости, а не новое внешнее доказательство.'));
  const metrics=Array.isArray(context.metric_checklist)?context.metric_checklist:[],analogues=Array.isArray(context.analogues)?context.analogues:[];
  append(section,node('h4','','Метрики для проверки'));if(!metrics.length)section.append(node('p','small','Метрики не заданы; пробелы должны быть отмечены в отчёте.'));else{const list=node('ul','approval-metric-list');for(const metric of metrics)list.append(append(node('li'),node('strong','',literalText(metric.name)),node('p','',literalText(metric.definition)),node('p','field-hint',`Единица: ${literalText(metric.unit)} · цель: ${literalText(metric.target)} · ожидание: ${literalText(metric.expected)}${metric.primary?' · основная':''}`)));section.append(list);}
  append(section,node('h4','','Выбранные аналоги из памяти'));if(!analogues.length)section.append(node('p','small','Прошлые выводы для сравнения не выбраны.'));for(const analogue of analogues){const item=node('article','applied-analogue');append(item,node('strong','',`${literalText(analogue.title)} · v${literalText(analogue.memory_version)}`),node('p','field-hint','ID: '+literalText(analogue.memory_id)+' · '+literalText(analogue.effective_status)),node('p','memory-literal',literalText(analogue.claim)),node('pre','technical-data',literalText(analogue.study_scope,'Условия не зафиксированы')));section.append(item);}
  const exact=node('details');append(exact,node('summary','','Полный снимок сравнения, условий и источников метрик'),node('pre','technical-data',JSON.stringify(context,null,2)));section.append(exact);return section;
}
function renderInfographicCover(run,data){
  const section=node('section','infographic-cover'),profile=data.visual_profile&&typeof data.visual_profile==='object'?data.visual_profile:null;
  append(section,node('div','eyebrow','ИНФОГРАФИКА'),node('h3','',presentationText(profile?.label)||'Сравнение · применение · границы'));
  if(profile){section.dataset.visualProfile=String(profile.mode||'');if(profile.reason)section.append(node('p','field-hint visual-selection','Почему этот формат: '+presentationText(profile.reason)));}
  const figure=node('figure','infographic-figure'),open=node('a','infographic-full'),picture=node('img','infographic-image'),version=data.provenance?.editorial_version||data.provenance?.review_version||run.finished_at||'';
  const base='/api/runs/'+encodeURIComponent(run.id)+'/',suffix=version?'?v='+encodeURIComponent(version):'';let kind=data.visual?.png_available?'png':'svg';
  const full=node('a','text-button','Открыть в полном размере ↗'),download=node('a','text-button','Скачать инфографику ↓');
  const setSource=()=>{const path=base+'card.'+kind;picture.src=path+suffix;open.href=path+suffix;full.href=path+suffix;download.href=path+suffix;download.download='research-'+run.id+'.'+kind;};
  open.target='_blank';open.rel='noopener';open.setAttribute('aria-label','Открыть инфографику в полном размере');full.target='_blank';full.rel='noopener';
  picture.loading='lazy';picture.decoding='async';picture.alt='Инфографика: '+(presentationText(data.title)||'сравнение, применение и ограничения технологии')+'. Текстовый разбор и доказательства — ниже.';
  picture.addEventListener('error',()=>{if(kind==='png'){kind='svg';setSource();}else{figure.classList.add('infographic-unavailable');picture.alt='Изображение временно недоступно. Текстовый разбор и ссылки сохранены ниже.';}});
  setSource();open.append(picture);append(figure,open,node('figcaption','field-hint','Собрано автоматически из разбора. Данные, условия и неизвестное отмечены на карточке. Изображение не заменяет проверку доказательств и применимости.'));section.append(figure);
  append(section,append(node('div','infographic-actions'),full,download));
  if(data.motion_story?.version==='dataflow-v1'&&data.visual?.video_available){
    const motion=node('figure','motion-preview'),video=node('video');video.controls=true;video.loop=true;video.muted=true;video.playsInline=true;video.preload='metadata';
    video.src=base+'animation.mp4'+suffix;video.setAttribute('aria-label','Движение данных и работа компонентов: '+presentationText(data.title));
    append(motion,video,node('figcaption','field-hint','Условное движение данных: порядок и связи, без измерения скорости. '+presentationText(data.motion_story.baseline?.note||'')));section.append(motion);
  }
  return section;
}
function renderComparisons(run,comparisons){
  const section=node('section','metric-comparisons');append(section,node('h4','','Сравнение по зафиксированным данным'),node('p','field-hint','Данные из журнала; условия и источник указаны ниже. График не является новым измерением. У каждой метрики своя шкала от нуля. Сравнивайте столбцы только внутри одной пары и при указанных условиях.'));
  for(const item of comparisons.slice(0,3)){
    if(!item||!Number.isFinite(item.baseline_value)||!Number.isFinite(item.result_value)||item.baseline_value<0||item.result_value<0)continue;
    const figure=node('figure','metric-comparison');figure.dataset.comparisonLabel=item.label||'';
    const caption=node('figcaption','metric-caption',item.label+(item.unit?' · '+item.unit:''));figure.append(caption);
    const maximum=Math.max(item.baseline_value,item.result_value),chart=node('div','metric-chart');chart.setAttribute('role','img');chart.setAttribute('aria-label',`${item.label}: ${item.baseline_label} — ${item.baseline_value} ${item.unit||''}; ${item.result_label} — ${item.result_value} ${item.unit||''}. Шкала от 0 до ${maximum}.`);
    for(const [kind,label,value] of [['baseline',item.baseline_label,item.baseline_value],['result',item.result_label,item.result_value]]){
      const row=node('div','metric-chart-row '+kind),track=node('div','metric-track'),bar=node('span','metric-bar');bar.style.width=(maximum?100*value/maximum:0)+'%';track.append(bar);track.setAttribute('aria-hidden','true');
      append(row,node('span','metric-label',label),node('strong','metric-value',String(value)+(item.unit?' '+item.unit:'')),track);chart.append(row);
    }
    append(figure,chart,node('p','metric-scale','0 → '+maximum+(item.unit?' '+item.unit:'')),node('p','metric-conditions',item.conditions||'Условия не указаны.'));
    if(item.evidence_ids?.length){const refs=node('div','metric-evidence');refs.append(node('span','','Основания: '));for(const id of item.evidence_ids){const ref=node('a','',id);ref.href='#review-evidence-'+run.id+'-'+id;ref.addEventListener('click',event=>{const proof=document.getElementById('review-evidence-'+run.id+'-'+id);if(!proof)return;event.preventDefault();for(let parent=proof.parentElement;parent;parent=parent.parentElement)if(parent.tagName==='DETAILS')parent.open=true;proof.scrollIntoView({block:'center'});});refs.append(ref);}figure.append(refs);}
    section.append(figure);
  }
  return section;
}
const reviewCriteria={task:'Вопрос и задача',mechanism:'Механизм и baseline',evidence:'Доказательства и условия',applicability:'Применимость и затраты',communication:'Понятность и следующий шаг'};
function reviewIds(value){return String(value||'').split(/[\s,]+/).map(value=>value.trim()).filter(Boolean);}
function reviewInput(parent,label,value,change,options={}){
  const field=node('label','review-field',label),input=node(options.rows?'textarea':'input');
  if(options.rows)input.rows=options.rows;else input.type=options.type||'text';
  input.value=value??'';input.maxLength=options.maxLength||6000;
  if(options.type==='number'){input.min='0';input.step='any';}
  if(options.name)input.dataset.reviewField=options.name;
  input.addEventListener('input',()=>change(input.value));field.append(input);parent.append(field);return input;
}
function reviewSelect(parent,label,value,values,change,name){
  const field=node('label','review-field',label),select=node('select');
  for(const [id,text] of values){const option=node('option','',text);option.value=id;select.append(option);}
  select.value=value??'';if(name)select.dataset.reviewField=name;select.addEventListener('change',()=>change(select.value));field.append(select);parent.append(field);return select;
}
function tokenValue(value){return typeof value==='number'?value.toLocaleString('ru-RU'):'неизвестно';}
function renderReviewCost(cost,label){
  const card=node('article','review-cost');append(card,node('h4','',label));
  const fields=[['Статус',statusNames[cost.status]||cost.status||'неизвестно'],['Время',typeof cost.elapsed_seconds==='number'?cost.elapsed_seconds+' с':'неизвестно'],['Запуски CLI',typeof cost.cli_invocations==='number'?String(cost.cli_invocations):'неизвестно'],['Входные токены',tokenValue(cost.usage?.input_tokens)],['Из них кеш',tokenValue(cost.usage?.cached_input_tokens)],['Выходные токены',tokenValue(cost.usage?.output_tokens)],['Денежный платёж',typeof cost.money_amount==='number'?cost.money_amount+' '+(cost.currency||''):'неизвестен']];
  const list=node('dl','review-cost-fields');for(const [term,value] of fields)append(list,node('dt','',term),node('dd','',value));card.append(list);return card;
}
async function loadResearchReview(run,host){
  try{
    reviewSchemaPromise=reviewSchemaPromise||api('/api/review/schema');
    const [schema,data]=await Promise.all([reviewSchemaPromise,api('/api/runs/'+encodeURIComponent(run.id)+'/review')]);
    if(!host.isConnected)return;renderResearchReview(run,schema,data,host);
  }catch(error){if(host.isConnected)host.replaceChildren(notice('Журнал ещё не загружен. Отчёт остаётся доступным.'),button('Загрузить журнал',()=>loadResearchReview(run,host),'text-button'));}
}
function renderResearchReview(run,schema,data,outer){
  outer.replaceChildren();
  const host=node('details','review-disclosure');
  host.append(node('summary','','Журнал исследования: решения, расходы, доказательства и качество'));
  outer.append(host);
  const current=data.current,body=current?.body||schema.template||{};
  append(host,node('div','eyebrow','ПРОВЕРКА РЕШЕНИЯ'),node('h2','','Решения, расходы и доказательства'),node('p','field-hint','Журнал и оценка редактируются отдельно от исходного отчёта. Сохранение не вызывает модель.'));
  const decisions=node('div','review-decisions');
  if(!body.decisions?.length)decisions.append(node('p','field-hint','Решение исследователя ещё не зафиксировано. Укажите объект проверки, основание и границы вывода.'));
  for(const decision of body.decisions||[]){
    const item=node('article','review-decision');append(item,node('h3','',decision.target),node('p','decision-action',decision.action),node('p','',decision.reason));
    if(decision.conditions)append(item,node('h4','','Границы и условия пересмотра'),node('p','',decision.conditions));
    if(decision.next_step)append(item,node('h4','','Следующий шаг'),node('p','',decision.next_step));
    if(decision.evidence_ids?.length)item.append(node('p','field-hint','Основания: '+decision.evidence_ids.join(', ')));decisions.append(item);
  }host.append(decisions);
  const costs=node('details','review-cost-section');costs.open=true;costs.append(node('summary','','Фактические расходы'));
  const costGrid=node('div','review-cost-grid');if(data.costs?.primary)costGrid.append(renderReviewCost(data.costs.primary,'Основное исследование'));
  for(const [index,value] of (data.costs?.related||[]).entries())costGrid.append(renderReviewCost(value,'Связанный проход '+(index+1)));
  append(costs,costGrid,node('p','field-hint',data.costs?.notice||'Токены и длительность берутся из сохранённых записей. Денежный платёж не вычисляется из токенов.'));
  const manual=data.costs?.manual||body.costs||{};
  if(manual.human_minutes!==null&&manual.human_minutes!==undefined)costs.append(node('p','field-hint','Ручная работа: '+manual.human_minutes+' мин. (оценка владельца)'));
  if(manual.money_amount!==null&&manual.money_amount!==undefined)costs.append(node('p','field-hint','Введённая сумма: '+manual.money_amount+' '+(manual.currency||'')+' (не счёт провайдера)'));
  if(manual.notes)costs.append(node('p','field-hint',manual.notes));host.append(costs);
  const evidence=node('details','review-evidence-section');evidence.append(node('summary','','Реестр доказательств · '+(body.evidence?.length||0)));
  const basisLabels={saved_report:'Утверждение из сохранённого отчёта',local_record:'Проверенная локальная запись',editor_assessment:'Редакторская оценка',missing:'Данных нет'};
  for(const item of body.evidence||[]){
    const card=node('article','review-evidence-item');card.id='review-evidence-'+run.id+'-'+item.id;append(card,node('h4','',item.id+' · '+item.claim),node('p','field-hint',basisLabels[item.basis]||item.basis),node('p','',item.locator));
    if(item.excerpt)card.append(node('blockquote','',item.excerpt));if(item.limitations)card.append(notice(item.limitations));
    const sourceLink=link(item.source_url,'Открыть источник ↗');if(sourceLink)card.append(sourceLink);evidence.append(card);
  }if(!body.evidence?.length)evidence.append(node('p','field-hint','Основания пока не записаны. Наличие URL само по себе не подтверждает вывод.'));host.append(evidence);
  const quality=node('section','review-quality');
  const criteria=schema.criteria||Object.entries(reviewCriteria).map(([id,label])=>({id,label}));
  const scored=criteria.map(item=>body.rubric?.[item.id]?.score).filter(value=>Number.isInteger(value));
  const total=scored.length===criteria.length?scored.reduce((a,b)=>a+b,0):null;
  append(quality,node('h3','','Рубрика качества исследования'),node('p','review-quality-total',total===null?'Оценка не завершена':total+' / 10 · редакторская оценка'),node('p','field-hint','0 — не раскрыто; 1 — частично; 2 — раскрыто с основанием. Балл оценивает подготовку разбора, а не истинность технологии или вероятность успеха.'));
  const rubricGrid=node('div','review-rubric-grid');
  for(const criterion of criteria){const rating=body.rubric?.[criterion.id]||{};const card=node('article','review-rubric-item');append(card,node('h4','',criterion.label),node('span','rubric-score',rating.score===null||rating.score===undefined?'Не оценено':String(rating.score)+' / 2'),node('p','',rating.note||'Основание оценки не задано.'));rubricGrid.append(card);}quality.append(rubricGrid);host.append(quality);
  const editor=node('details','review-editor');append(editor,node('summary','','Зафиксировать или уточнить разбор'),buildReviewEditor(run,schema,data));host.append(editor);
  const history=node('details','review-history');history.append(node('summary','','История журнала · '+(data.history?.length||0)));
  for(const version of data.history||[]){const item=node('details','review-version');append(item,node('summary','','Версия '+version.version+' · '+date(version.created_at)));for(const decision of version.body?.decisions||[])append(item,node('h4','',decision.target),node('p','',decision.action+' — '+decision.reason));item.append(node('p','field-hint','Записей доказательств: '+(version.body?.evidence?.length||0)));history.append(item);}host.append(history);
}
function buildReviewEditor(run,schema,data){
  const body=JSON.parse(JSON.stringify(data.current?.body||schema.template||{}));
  body.decisions=body.decisions||[];body.evidence=body.evidence||[];body.costs=body.costs||{related_run_ids:[],human_minutes:null,money_amount:null,currency:'',notes:''};body.rubric=body.rubric||{};body.editorial=body.editorial||{};
  for(const key of ['lab_target','lab_decision','lab_reason','lab_conditions'])delete body.editorial[key];
  const form=node('form','review-form');form.noValidate=true;
  form.append(node('p','field-hint','Зафиксируйте исследовательский выбор: какое утверждение проверяем, с каким baseline сравниваем, что включаем или исключаем и почему. Исходный ответ модели сохраняется.'));
  const decisions=node('div','review-decision-editors');
  const nextId=(prefix,items)=>{let id=1;while(items.some(item=>item.id===prefix+id))id++;return prefix+id;};
  const renderDecisions=()=>{decisions.replaceChildren();for(const [index,item] of body.decisions.entries()){
    const card=node('fieldset','review-record-editor');card.append(node('legend','','Решение '+(index+1)+' · '+item.id));
    for(const [key,label,rows] of [['target','Объект проверки',2],['action','Решение исследователя',2],['reason','Основание',3],['conditions','Границы и условия пересмотра',2],['next_step','Следующая проверка',2]])reviewInput(card,label,item[key],value=>item[key]=value,{rows,name:'decision-'+key});
    reviewInput(card,'ID оснований через запятую',item.evidence_ids?.join(', '),value=>item.evidence_ids=reviewIds(value),{name:'decision-evidence-ids'});
    card.append(button('Удалить эту запись из новой версии',()=>{body.decisions.splice(index,1);renderDecisions();},'text-button'));decisions.append(card);
  }};
  append(form,node('h3','','Решения'),decisions,button('+ Добавить решение',()=>{body.decisions.push({id:nextId('d',body.decisions),target:'',action:'',reason:'',evidence_ids:[],conditions:'',next_step:''});renderDecisions();},'button secondary'));
  renderDecisions();
  const evidence=node('div','review-evidence-editors');
  const renderEvidence=()=>{evidence.replaceChildren();for(const [index,item] of body.evidence.entries()){
    const card=node('fieldset','review-record-editor');card.append(node('legend','','Основание '+item.id));
    reviewInput(card,'Какой вывод обосновывает?',item.claim,value=>item.claim=value,{rows:2,name:'evidence-claim'});
    reviewSelect(card,'Тип основания',item.basis,[['saved_report','Из сохранённого отчёта'],['local_record','Локальная запись исполнения'],['editor_assessment','Редакторская оценка'],['missing','Данных нет']],value=>item.basis=value,'evidence-basis');
    for(const [key,label,rows] of [['locator','Где именно проверить: раздел отчёта, страница, запись',2],['excerpt','Сохранённый фрагмент или наблюдение',3],['limitations','Что этим не доказано?',2]])reviewInput(card,label,item[key],value=>item[key]=value,{rows,name:'evidence-'+key});
    reviewInput(card,'Публичный URL источника',item.source_url,value=>item.source_url=value,{type:'url',name:'evidence-source-url'});
    card.append(button('Удалить из новой версии',()=>{body.evidence.splice(index,1);renderEvidence();},'text-button'));evidence.append(card);
  }};
  append(form,node('h3','','Доказательства'),evidence,button('+ Добавить основание',()=>{body.evidence.push({id:nextId('e',body.evidence),claim:'',basis:'saved_report',locator:'',source_url:'',excerpt:'',limitations:''});renderEvidence();},'button secondary'));renderEvidence();
  const costs=node('fieldset','review-record-editor');costs.append(node('legend','','Дополнительные расходы'));
  const relatedLabel=node('label','review-field','Связанные проходы (например, ошибочный запуск)'),related=node('select');related.multiple=true;related.size=4;related.dataset.reviewField='related-runs';
  for(const item of state.runs.filter(item=>item.id!==run.id&&!activeStatuses.has(item.status)&&item.status!=='planned')){const option=node('option','',boundedRunTitle(item.plan?.sources?.[0]?.title||item.plan?.question||item.id)+' · '+date(item.created_at));option.value=item.id;option.selected=body.costs.related_run_ids?.includes(item.id);related.append(option);}
  related.addEventListener('change',()=>body.costs.related_run_ids=[...related.selectedOptions].map(item=>item.value));relatedLabel.append(related);costs.append(relatedLabel);
  reviewInput(costs,'Время ручной работы, минут (пусто — неизвестно)',body.costs.human_minutes,value=>body.costs.human_minutes=value===''?null:Number(value),{type:'number',name:'human-minutes'});
  reviewInput(costs,'Сумма по доступным данным (пусто — неизвестно)',body.costs.money_amount,value=>body.costs.money_amount=value===''?null:Number(value),{type:'number',name:'money-amount'});
  reviewInput(costs,'Валюта',body.costs.currency,value=>body.costs.currency=value,{maxLength:20,name:'currency'});
  reviewInput(costs,'Основание и ограничения оценки расходов',body.costs.notes,value=>body.costs.notes=value,{rows:3,name:'cost-notes'});form.append(costs);
  const rubric=node('div','review-rubric-editors');
  for(const criterion of schema.criteria||Object.entries(reviewCriteria).map(([id,label])=>({id,label}))){
    const rating=body.rubric[criterion.id]||{score:null,note:'',evidence_ids:[]};body.rubric[criterion.id]=rating;
    const item=node('fieldset','review-record-editor');item.append(node('legend','',criterion.label));if(criterion.description)item.append(node('p','field-hint',criterion.description));
    reviewSelect(item,'Оценка',rating.score===null?'':String(rating.score),[['','Не оценено'],['0','0 — не раскрыто'],['1','1 — частично'],['2','2 — раскрыто с основанием']],value=>rating.score=value===''?null:Number(value),'score-'+criterion.id);
    reviewInput(item,'Почему такая оценка?',rating.note,value=>rating.note=value,{rows:2,name:'note-'+criterion.id});reviewInput(item,'ID оснований через запятую',rating.evidence_ids?.join(', '),value=>rating.evidence_ids=reviewIds(value),{name:'refs-'+criterion.id});rubric.append(item);
  }append(form,node('h3','','Качество разбора'),node('p','field-hint','Для любой оценки укажите причину. Для 2 баллов нужен ID основания. Неполная рубрика не получает итогового балла.'),rubric);
  const editorial=node('details','review-editorial');editorial.append(node('summary','','Редакторская версия для читателя и канала'));
  const texts={title:'Заголовок',problem:'Какая проблема решается?',audience:'Кому это нужно?',use_case:'Конкретный сценарий применения',public_takeaway:'Практический вывод для читателя',next_step:'Следующая проверка для своей задачи'};
  for(const [key,label] of Object.entries(texts))reviewInput(editorial,label,body.editorial[key],value=>body.editorial[key]=value,{rows:2,maxLength:schema.editorial_fields?.text?.[key]||4000,name:'editorial-'+key});
  for(const [key,label] of [['mechanism','Механизм: ровно три шага, каждый с новой строки'],['findings','Что показали авторы, с условиями: по строке на пункт'],['limitations','Ограничения и риски'],['resources','Настройка и инфраструктура']])reviewInput(editorial,label,(body.editorial[key]||[]).join('\n'),value=>body.editorial[key]=value.split('\n').map(item=>item.trim()).filter(Boolean),{rows:4,name:'editorial-'+key});
  const comparisons=node('div','review-comparison-editors'),comparisonSpec=schema.editorial_fields?.comparisons||{},comparisonLimit=Math.min(3,comparisonSpec.items||3);
  const addComparison=button('+ Добавить сравнение метрики',()=>{body.editorial.comparisons=body.editorial.comparisons||[];if(body.editorial.comparisons.length>=comparisonLimit)return;body.editorial.comparisons.push({label:'',unit:'',baseline_label:'',baseline_value:null,result_label:'',result_value:null,conditions:'',evidence_ids:[]});renderComparisonEditors();},'button secondary');
  const renderComparisonEditors=()=>{comparisons.replaceChildren();for(const [index,item] of (body.editorial.comparisons||[]).entries()){
    const card=node('fieldset','review-record-editor');card.append(node('legend','','Сравнение метрики '+(index+1)));
    for(const [key,label,maxLength] of [['label','Метрика',180],['unit','Единица измерения',60],['baseline_label','Название baseline',120],['result_label','Название сравниваемого метода',120]])reviewInput(card,label,item[key],value=>item[key]=value,{maxLength:comparisonSpec.text?.[key]||maxLength,name:'comparison-'+key});
    for(const [key,label] of [['baseline_value','Значение baseline'],['result_value','Значение метода']])reviewInput(card,label,item[key],value=>item[key]=value===''?null:Number(value),{type:'number',name:'comparison-'+key});
    reviewInput(card,'Одинаковые условия и границы сравнения',item.conditions,value=>item.conditions=value,{rows:3,maxLength:comparisonSpec.text?.conditions||1600,name:'comparison-conditions'});reviewInput(card,'ID оснований с этими числами',item.evidence_ids?.join(', '),value=>item.evidence_ids=reviewIds(value),{name:'comparison-evidence-ids'});
    card.append(button('Удалить сравнение из новой версии',()=>{body.editorial.comparisons.splice(index,1);renderComparisonEditors();},'text-button'));comparisons.append(card);
  }addComparison.disabled=(body.editorial.comparisons||[]).length>=comparisonLimit;};
  append(editorial,node('h4','','Сравнение чисел из источника'),node('p','field-hint','До трёх пар: одна метрика, одна единица, сопоставимые условия и ID основания. Числа не извлекаются и не придумываются автоматически. Нулевое значение допустимо.'),comparisons,addComparison);renderComparisonEditors();
  reviewSelect(editorial,'Тип визуального объяснения',body.editorial.visual_kind||'',[['','По имеющемуся описанию'],['generic','Общая схема'],['replay_tree','Replay по дереву записанных попыток']],value=>body.editorial.visual_kind=value,'editorial-visual-kind');form.append(editorial);
  const status=node('p','review-save-status');status.setAttribute('role','status');
  const save=node('button','button primary','Сохранить новую версию разбора');save.type='submit';
  form.addEventListener('submit',async event=>{event.preventDefault();await busy(save,async()=>{
    await api('/api/runs/'+encodeURIComponent(run.id)+'/review',{expected_version:data.current?.version||0,body});
    presentationCache.clear();globalThis.FrontierLive?.invalidate();delete $('#run-detail').dataset.fingerprint;await selectRun(run.id,false);notify('Новая версия журнала и редакторской подачи сохранена. Модель не запускалась.');
  });});append(form,node('p','field-hint','Изменения сохраняются новой версией. Старые решения, расходы и исходный отчёт остаются в истории.'),save,status);return form;
}
function svgNode(tag,attributes={},text) {
  const element=document.createElementNS('http://www.w3.org/2000/svg',tag);
  for(const [key,value] of Object.entries(attributes))element.setAttribute(key,String(value));
  if(text!==undefined)element.textContent=String(text);return element;
}
function renderMechanism(run,visual,version) {
  const graph=visual?.graph,scenes=Array.isArray(visual?.scenes)?visual.scenes:[];
  if(!graph || !Array.isArray(graph.nodes) || !Array.isArray(graph.edges) || !scenes.length){
    const figure=node('figure','mechanism-figure');
    const image=node('img','mechanism-image');image.src='/api/runs/'+encodeURIComponent(run.id)+'/card.svg'+(version?'?v='+encodeURIComponent(version):'');image.alt='Визуальное объяснение: '+(run.plan?.sources?.[0]?.title||'механизм технологии');image.loading='lazy';
    append(figure,image,node('figcaption','field-hint',visual?.caption||'Схема механизма по сохранённому отчёту.'));return append(node('div','mechanism-block'),figure,renderStoryboard(visual));
  }
  const process=visual.kind==='process_flow',section=node('section','mechanism-block replay-mechanism'+(process?' process-mechanism':''));
  append(section,node('h4','',process?'Механизм: от входа к результату':'Сравните два маршрута по одной сохранённой истории'),node('p','field-hint',process?'Три шага из сохранённого описания. Маркер проходит по стрелкам в порядке объяснения; это не запись выполненного запуска.':'Слева — фиксированный выбор. Справа — проверка другой стратегии по уже записанным исходам. Пунктир означает, что исход ещё неизвестен.'));
  const viewport=node('div','replay-viewport');viewport.tabIndex=0;viewport.setAttribute('role','region');viewport.setAttribute('aria-label',process?'Последовательность: вход, три шага механизма и результат':'Дерево записанных попыток: фиксированная стратегия и replay');
  const width=Number.isFinite(graph.width)?Math.min(2000,Math.max(500,graph.width)):1280,height=Number.isFinite(graph.height)?Math.min(1400,Math.max(250,graph.height)):560;
  const graphYs=graph.nodes.filter(item=>Number.isFinite(item?.y)).map(item=>item.y);
  const graphTop=graphYs.length?Math.max(0,Math.min(...graphYs)-70):0;
  const svg=svgNode('svg',{viewBox:'0 '+graphTop+' '+width+' '+(height-graphTop),role:'img','aria-label':process?'Механизм из трёх текстовых шагов отчёта':'Два дерева одних и тех же записанных попыток'});
  if(process){const defs=svgNode('defs'),arrow=svgNode('marker',{id:'process-arrow-'+run.id,markerWidth:12,markerHeight:12,refX:32,refY:6,orient:'auto',markerUnits:'userSpaceOnUse'});arrow.append(svgNode('path',{d:'M0 0 L12 6 L0 12 Z',fill:'#8fbac6'}));defs.append(arrow);svg.append(defs);}
  if(!process)svg.append(svgNode('text',{x:width*.25,y:graphTop+29,'text-anchor':'middle',class:'replay-panel-title'},'Фиксированный маршрут'),svgNode('text',{x:width*.75,y:graphTop+29,'text-anchor':'middle',class:'replay-panel-title'},'Другой маршрут по той же истории'));
  const nodes=new Map(),edges=new Map(),nodeViews=new Map();
  const usable=graph.nodes.filter(item=>item && typeof item.id==='string' && Number.isFinite(item.x) && Number.isFinite(item.y)).slice(0,50);
  usable.forEach(item=>nodes.set(item.id,item));
  for(const item of graph.edges.slice(0,70)){
    const from=nodes.get(item.from),to=nodes.get(item.to);if(!from||!to)continue;
    const line=svgNode('line',{x1:from.x,y1:from.y,x2:to.x,y2:to.y,class:'replay-edge'+(item.dashed?' unavailable':''),'data-edge-id':item.id});svg.append(line);edges.set(item.id,{item,line,from,to});
    if(process)line.setAttribute('marker-end','url(#process-arrow-'+run.id+')');
  }
  for(const item of usable){
    const group=svgNode('g',{class:'replay-node '+(item.kind==='unknown'?'unknown':item.kind==='new'?'new-outcome':'recorded'),'data-node-id':item.id});
    group.append(svgNode('circle',{cx:item.x,cy:item.y,r:19}),svgNode('title',{},String(item.detail||item.label||item.id)));
    const label=String(item.label||item.id),lineChars=process?Math.max(12,Math.min(42,Number(item.line_chars)||36)):12;const words=label.split(/\s+/);let lines=[''];
    for(const word of words){const chunks=word.match(new RegExp('.{1,'+lineChars+'}','gu'))||[];for(const chunk of chunks){const last=lines.length-1;if((lines[last]+' '+chunk).trim().length>lineChars&&lines[last])lines.push(chunk);else lines[last]=(lines[last]+' '+chunk).trim();}}
    if(lines.length>3){lines=lines.slice(0,3);lines[2]=lines[2].slice(0,lineChars-1)+'…';}
    lines.forEach((line,index)=>group.append(svgNode('text',{x:process&&Number.isFinite(item.label_x)?item.label_x:item.x,y:(process&&Number.isFinite(item.label_y)?item.label_y:item.y+39)+index*(process?37:30),'text-anchor':process?'start':'middle'},line)));
    svg.append(group);nodeViews.set(item.id,group);
  }
  const marker=svgNode('circle',{r:9,class:'replay-traveller',visibility:'hidden'});svg.append(marker);viewport.append(svg);section.append(viewport);if(!process)section.append(node('p','field-hint replay-scroll-hint','↔ Сдвигайте схему в стороны: справа — replay по той же истории.'));
  const legend=node('div','replay-legend');if(process)append(legend,node('span','recorded','● Шаг описания'),node('span','','→ Порядок, без оценки скорости'));else append(legend,node('span','recorded','● Сохранённый исход'),node('span','unknown','┄ Неизвестное продолжение'),node('span','new-outcome','● Новый онлайн-исход'));section.append(legend);
  const title=node('h4','replay-scene-title'),explanation=node('p','replay-scene-text');
  const live=node('div','replay-scene');live.setAttribute('aria-live','polite');append(live,title,explanation);section.append(live);
  let active=0,playing=false,progress=0;
  const setScene=index=>{
    active=index;progress=0;const scene=scenes[index];
    title.textContent=String(index+1)+' / '+scenes.length+' · '+(scene.title||'Шаг механизма');explanation.textContent=scene.explanation||'';
    const activeEdges=new Set(scene.active_edges||[]),activeNodes=new Set(scene.active_nodes||[]);
    edges.forEach((value,id)=>{value.line.classList.toggle('active',activeEdges.has(id));value.line.setAttribute('visibility',Number(value.item.reveal_scene||0)>active?'hidden':'visible');});
    nodeViews.forEach((group,id)=>{group.classList.toggle('active',activeNodes.has(id));group.setAttribute('visibility',Number(nodes.get(id)?.reveal_scene||0)>active?'hidden':'visible');});
    sceneButtons.forEach((control,index)=>control.setAttribute('aria-pressed',String(index===active)));
    marker.setAttribute('visibility','hidden');section.dataset.scene=String(index);
  };
  const play=button(process?'▶ Показать движение по шагам':'▶ Показать движение по ветвям',()=>{
    if(playing){stopStoryboard();return;}
    if(reducedMotion?.matches){setScene((active+1)%scenes.length);return;}
    stopStoryboard();playing=true;play.textContent='Ⅱ Пауза';play.setAttribute('aria-pressed','true');
    storyboardTimer=setInterval(()=>{
      if(!section.isConnected||state.view!=='runs'){stopStoryboard();return;}
      progress+=.018;
      const route=(scenes[active].active_edges||[]).map(id=>edges.get(id)).filter(item=>item&&!item.item.dashed);
      if(route.length){const position=Math.min(.999,progress)*route.length,segment=route[Math.min(route.length-1,Math.floor(position))],fraction=position-Math.floor(position);marker.setAttribute('cx',segment.from.x+(segment.to.x-segment.from.x)*fraction);marker.setAttribute('cy',segment.from.y+(segment.to.y-segment.from.y)*fraction);marker.setAttribute('visibility','visible');}
      if(progress>=1)setScene((active+1)%scenes.length);
    },50);
  },'button secondary replay-play');play.setAttribute('aria-pressed','false');
  storyboardReset=()=>{playing=false;play.textContent=reducedMotion?.matches?'Следующий этап →':process?'▶ Показать движение по шагам':'▶ Показать движение по ветвям';play.setAttribute('aria-pressed','false');marker.setAttribute('visibility','hidden');};
  const sceneButtons=[];const chooser=node('div','replay-scenes');
  scenes.slice(0,8).forEach((scene,index)=>{const control=button(String(index+1),()=>{stopStoryboard();setScene(index);},'replay-scene-button');control.setAttribute('aria-label',scene.title||'Этап '+(index+1));sceneButtons.push(control);chooser.append(control);});
  append(section,append(node('div','storyboard-controls'),play,button('Сначала',()=>{stopStoryboard();setScene(0);},'text-button'),chooser),node('p','field-hint',visual.caption||'Объясняющая схема. Размеры дерева и движение не являются измерением производительности.'));
  if(reducedMotion?.matches)append(section,node('p','field-hint','Уменьшение движения включено: переходите по этапам вручную.'));
  setScene(0);return section;
}
function renderStoryboard(visual) {
  const source=visual && typeof visual==='object'?visual:{};
  const provided=Array.isArray(source.steps)?source.steps:[];
  const steps=provided.map((step,index)=>({label:typeof step==='string'?'Шаг '+(index+1):step?.label || 'Шаг '+(index+1),text:typeof step==='string'?step:presentationText(step?.text || step?.description)})).filter(step=>step.text).slice(0,5);
  const section=node('section','result-storyboard');
  append(section,node('div','eyebrow','КАК ЭТО РАБОТАЕТ'),node('h3','','Идея по шагам'));
  if (!steps.length) {section.append(node('p','field-hint','Механизм не описан в краткой версии. Его можно проверить в полном отчёте.'));return section;}
  const path=node('ol','storyboard-path');
  const selectors=[];
  let active=0,playing=false;
  const progress=node('p','storyboard-progress','');
  const animate=button('▶ Показать по шагам',()=>{if(playing){pause();return;}if(reducedMotion?.matches){setStep((active+1)%steps.length);return;}stopStoryboard();playing=true;animate.textContent='Ⅱ Пауза';animate.setAttribute('aria-pressed','true');storyboardTimer=setInterval(()=>{if(!section.isConnected || state.view!=='runs'){pause();return;}setStep((active+1)%steps.length);},3000);},'button secondary storyboard-play');
  const setStep=index=>{active=index;selectors.forEach((selector,itemIndex)=>{selector.classList.toggle('active',itemIndex===index);selector.setAttribute('aria-pressed',String(itemIndex===index));});progress.textContent='Шаг '+(index+1)+' из '+steps.length+' · '+steps[index].label;};
  const reset=()=>{playing=false;animate.textContent=reducedMotion?.matches?'Следующий шаг →':'▶ Показать по шагам';animate.setAttribute('aria-pressed','false');};
  storyboardReset=reset;
  const pause=()=>{stopStoryboard();};
  for (const [index,step] of steps.entries()) {
    const selector=button('',()=>{pause();setStep(index);},'storyboard-step');
    append(selector,node('span','storyboard-number',String(index+1).padStart(2,'0')),node('strong','',step.label),node('span','storyboard-description',step.text));
    const item=node('li');item.append(selector);path.append(item);selectors.push(selector);
  }
  animate.setAttribute('aria-label','Показать механизм по шагам');animate.setAttribute('aria-pressed','false');
  append(section,path,append(node('div','storyboard-controls'),animate,progress),node('p','field-hint storyboard-caption',source.caption || 'Схема объясняет идею. Переходы не изображают измеренную скорость или эффективность.'));
  if(reducedMotion?.matches) {animate.textContent='Следующий шаг →';section.append(node('p','field-hint','Учитываем настройку уменьшения движения: шаги переключаются вручную.'));}
  setStep(0);return section;
}
function showApproval(run) {
  state.pendingPlan = run;
  const plan = run.plan || {}, target = $('#approval-summary'); target.replaceChildren();
  target.append(node('p','approval-question',plan.question || run.question || $('#research-question').value));
  const grid = node('dl','approval-grid');
  const protocol=reviewedProtocol(plan);
  const items = [['Исполнитель',providerName(plan.provider || $('#research-provider').value)],['Модель',plan.model || 'По умолчанию у исполнителя'],['Интернет',researchWebPermission(plan)],['Общее время',String(protocol?.total_timeout_seconds || plan.timeout_seconds || 180) + ' сек.'],['Вызовы CLI / резерв лимита',protocol ? `${protocol.max_calls} / ${protocol.max_calls} за 24 часа` : '1 / 1 за 24 часа']];
  for (const [label,value] of items) grid.append(append(node('div'),node('dt','',label),node('dd','',value)));
  target.append(grid);
  const sourceIds = plan.source_ids || (plan.sources || []).map(item => item.id || item.source_id);
  const materials = node('ul','approval-materials');
  for (const id of sourceIds) {
    const source = state.sources.find(item => item.id === id);
    const snapshot = (plan.sources || []).find(item => item.id === id || item.source_id === id);
    materials.append(node('li','',source?.title || snapshot?.title || id));
  }
  append(target,node('h3','','Материалы для исполнителя'),materials,notice((plan.continuation?'Два сохранённых этапа, один новый редактор; резервируется 1 вызов CLI. Прошлый расход не обнуляется.':protocol?'Запланированы три отдельных прохода и максимум '+protocol.max_calls+' вызова CLI. Резервируются '+protocol.max_calls+' единицы лимита за 24 часа.':'Выполнится один запуск CLI; резервируется 1 единица лимита за 24 часа.')+' Расходуется лимит аккаунта, через который выполнен вход в ' + providerName(plan.provider || $('#research-provider').value) + '. Параллельно — одно исследование. После таймаута автоматического повтора нет.'));
  if(protocol){const roles=node('ol','approval-roles');for(const [index,role] of (protocol.roles || []).entries())roles.append(node('li','',`${agentRoleNames[role] || role}${protocol.phase_timeouts?.[index] ? ' · до '+protocol.phase_timeouts[index]+' сек.' : ''}`));const hint=plan.continuation?'Только редактор по сохранённым ответам. Указанный бюджет включает 20 секунд завершения процесса; веб выключен.':protocol.version==='three-pass-v4'?'Критик работает независимо. Редактору достаётся фактический остаток общего времени; его предел — потолок, а не дополнительное время. В общий бюджет включены 20 секунд завершения.':protocol.version==='three-pass-v1'?'Каждый следующий проход получает сохранённый результат предыдущего. При ошибке цепочка останавливается; запас общего времени включает завершение процессов.':'Критик изучает источники без ответа исследователя. Редактор получает оба ответа. При ошибке цепочка останавливается; общий бюджет включает завершение процессов.';append(target,node('h3','','Отдельные проходы'),roles,node('p','field-hint',hint),append(node('details'),node('summary','','Точный протокол'),node('pre','technical-data',JSON.stringify(protocol,null,2))));}
  const validationContract=protocol?.validation_contract;
  if(validationContract){const baseline=validationContract.baseline||{},metrics=validationContract.measurable_metrics||[],conditions=validationContract.conditions||{};const passport=node('section','approval-validation-contract');append(passport,node('h3','','Паспорт прикладной проверки'),node('p','field-hint','Этот апрув разрешает разбор источников. Реальный benchmark или эксперимент требует отдельного плана, бюджета и апрува.'),node('p','','Задача: '+(validationContract.task||'Не задана')),node('p','','Baseline: '+(baseline.name||'Не выбран')+' · версия '+(baseline.version||'Не закреплена')),node('p','','Метрики: '+(metrics.map(m=>(m.name||'Метрика')+' ['+(m.unit||'нет единицы')+']').join('; ')||'Не заданы')),node('p','','Проверочный набор: '+(conditions.dataset||'Не выбран')),node('p','','Методика: '+(conditions.evaluation||'Не выбрана')),node('p','','Опровергающая проверка: '+(validationContract.minimal_falsifying_check||'Не определена')),node('p','','Критерий: '+(validationContract.acceptance_criteria||'Не задан')),node('p','field-hint','Исполнитель ищет первичное сравнение на похожей задаче; внешний результат и выполненный здесь тест различаются. Иллюстративная симуляция не подтверждает производительность.'));target.append(passport);}
  if (!plan.web_search) target.append(node('p','field-hint','Без веб-поиска модель анализирует переданный текст. Ссылки сами по себе не подтверждают прочтение первоисточника.'));
  if(plan.continuation){append(target,node('h3','','Сохранённые задача, память и уроки'),node('p','field-hint','Исходные версии зафиксированы. Повторных запусков исследователя и критика нет.'),node('pre','technical-data',JSON.stringify({study_context:plan.study_context,memory:plan.memory,continuation:plan.continuation},null,2)));}
  else{renderApprovalContext(run,target);renderApprovalMemory(run, target);}
  target.append(...[renderApprovalComparison(plan)].filter(Boolean));
  target.append(contextTrace(run));
  target.append(node('p','plan-hash','Версия плана: ' + (run.plan_hash || '—')));
  target.append(button('Продолжить апрув в Telegram',event=>busy(event.currentTarget,()=>sendTelegramPlan(run)),'button secondary'));
  $('#approval-consent').checked = false;
  state.memoryBlocked = false;
  updateApprovalLaunch();
  if (!$('#approval-dialog').open) $('#approval-dialog').showModal();
}

async function refreshKnowledge() { const [result,reviews] = await Promise.all([api('/api/knowledge?q=' + encodeURIComponent($('#knowledge-search').value.trim())),api('/api/memory/reviews'),refreshTasks(),refreshLessons()]); state.knowledge = result.items || []; renderKnowledge(); renderMemoryReviews(reviews.items || []);renderLessons(); }
function renderKnowledge() {
  const target = $('#knowledge-list'); target.replaceChildren();
  if (!state.knowledge.length) { target.append(empty('◇',$('#knowledge-search').value ? 'По этому запросу ничего нет' : 'Собирайте знания, а не открытые вкладки',$('#knowledge-search').value ? 'Попробуйте другую тему или тег.' : 'После исследования сохраните полезный вывод. Он останется связан с исходником и полным отчётом.',button('К исследованиям',() => switchView('runs')))); return; }
  for (const item of state.knowledge) {
    const memory = item.memory;
    const card = node('article','panel knowledge-card');
    append(card,append(node('div','memory-card-heading'),node('div','source-label','Сохранённое знание'),memory ? memoryBadge(memory) : null),node('h2','',memory?.title || item.title || 'Исследование'),renderTags(memory?.tags || item.tags));
    if (memory?.claim || item.decision) card.append(node('p','decision',memory?.claim || item.decision));
    if (memory?.notes) card.append(node('p','memory-notes',memory.notes));
    if (memory?.study_scope) card.append(studyScopeSummary(memory.study_scope));
    if (memory) card.append(node('p','small muted',`Версия ${memory.version} · Проверить ${reviewDate(memory.review_at) || 'позже'}`));
    if (item.output) card.append(node('p','report-snippet',reportDisplayText(item.output)));
    if (memory) {
      const memoryActions = node('div','memory-card-actions');
      append(memoryActions,button('Исправить вывод',event => busy(event.currentTarget,() => openMemoryEdit(item.id)),'text-button'),button('История версий',event => busy(event.currentTarget,() => openMemoryHistory(item.id)),'text-button'),button('Проверить актуальность',event => busy(event.currentTarget,() => prepareFreshnessRun(item.id)),'text-button'),button('Создать урок',event => busy(event.currentTarget,() => openLessonEditor(null,{knowledge:item})),'text-button'));
      card.append(memoryActions);
    }
    append(card,append(node('div','card-bottom'),node('span','small muted',date(item.created_at)),button('Полный отчёт ↗',() => {state.runId = item.run_id; switchView('runs');},'text-button')));
    target.append(card);
  }
}
function contextTrace(run){
  const section=node('details','context-trace');section.dataset.runId=run.id;
  const content=node('div','context-trace-content');append(section,node('summary','','Точный контекст для исполнителя: текст, настройки и SHA-256'),content);
  let loading=false,loaded=false;
  const load=async()=>{
    if(loading || loaded)return;loading=true;content.replaceChildren(node('p','field-hint','Загружаем сохранённый контекст…'));
    try{
      const trace=await api('/api/runs/'+encodeURIComponent(run.id)+'/context');
      if(!section.isConnected)return;
      content.replaceChildren();
      if(trace.status==='legacy_unavailable')content.append(notice('Для этого старого запуска точный переданный контекст не записывался. Исторический текст восстановить достоверно нельзя.'));
      else{
        append(content,node('p','trace-status',trace.status==='captured'?'Записан перед отправкой исполнителю.':'Подготовлен к отправке; запуск ещё не выполнен.'),node('p','field-hint','Это точный текст и настройки, которые приложение передаёт исполнителю. Внутренние инструкции CLI и провайдера, а также будущие результаты веб-поиска приложению полностью не видны.'),node('p','context-prompt-hash','SHA-256 текста: '+(trace.prompt_sha256 || '—')));
        const prompt=node('pre','technical-data context-prompt',trace.prompt ?? '');prompt.tabIndex=0;prompt.setAttribute('aria-label','Точный текст для исполнителя');
        append(content,prompt,button('Скачать точный текст ↓',()=>downloadText(trace.prompt || '','context-'+run.id+'.txt','text/plain;charset=utf-8'),'text-button'));
        const manifest=node('details','context-manifest');append(manifest,node('summary','','Состав контекста и настройки инструментов'),node('pre','technical-data',JSON.stringify(trace.manifest || {},null,2)));content.append(manifest);
      }
      loaded=true;
    }catch(error){content.replaceChildren(notice(errorMessage(error),'error'),button('Повторить загрузку',()=>load(),'text-button'));}
    finally{loading=false;}
  };
  section.addEventListener('toggle',()=>{if(section.open)load();});return section;
}
const lessonLabels={title:'Название урока',problem:'Какую проблему решает',rule:'Правило для следующего исследования',evidence_note:'Что именно подтверждает основание',applies_when:'Когда применять',not_applicable_when:'Когда не применять',limitations:'Ограничения и неопределённость'};
function lessonBody(item){return item.body || item;}
function lessonBadge(item){return node('span','status-badge '+(item.stale && item.status==='active'?'stale':item.status),item.status==='draft'?'Черновик':item.status==='retired'?'Выведен из использования':item.stale?'Пора проверить':'Активный урок');}
function lessonDescription(item){
  const body=lessonBody(item),target=node('div','lesson-description');
  append(target,append(node('div','memory-card-heading'),node('h3','',body.title || 'Урок'),lessonBadge(item)),node('p','field-hint',`Версия ${item.version} · Проверить ${reviewDate(body.review_at) || 'дата не задана'}`));
  const fields=node('dl','study-description');
  for(const key of ['problem','rule','evidence_note','applies_when','not_applicable_when','limitations'])append(fields,node('dt','',lessonLabels[key]),node('dd',key==='rule'?'memory-literal lesson-rule':'memory-literal',body[key] || 'Не указано'));
  append(fields,node('dt','','Тип основания'),node('dd','',({hypothesis:'Гипотеза',source_analysis:'Анализ источников',external_measurement:'Внешнее измерение'}[body.evidence_level]) || body.evidence_level || 'Не указано'));
  if(body.task_id)append(fields,node('dt','','Привязка к задаче'),node('dd','',state.tasks.find(task=>task.id===body.task_id)?.body?.title || body.task_id));
  target.append(fields);
  const evidence=node('div','memory-evidence');
  if(body.evidence_run_id)evidence.append(button('Открыть исследование-основание ↗',()=>{$('#lesson-history-dialog').close();$('#approval-dialog').close();state.runId=body.evidence_run_id;switchView('runs');},'text-button'));
  if(body.evidence_source_ids?.length)evidence.append(node('p','field-hint','Материалы: '+body.evidence_source_ids.map(id=>state.sources.find(source=>source.id===id)?.title || id).join('; ')));
  for(const url of body.evidence_urls || []){const source=link(url);if(source)evidence.append(source);}
  if(evidence.childElementCount)target.append(evidence);return target;
}
async function lessonSchema(){if(!state.lessonSchema)state.lessonSchema=await api('/api/lessons/schema');return state.lessonSchema;}
async function refreshLessons(){const result=await api('/api/lessons');state.lessons=result.items || [];renderLessons();}
function renderLessons(){
  const target=$('#lesson-list'),query=$('#lesson-search').value.trim().toLocaleLowerCase('ru');target.replaceChildren();
  const items=state.lessons.filter(item=>!query || JSON.stringify(item.body).toLocaleLowerCase('ru').includes(query));
  if(!items.length){target.append(empty('◇',query?'Уроки не найдены':'Вывод можно превратить в правило',query?'Попробуйте другое слово.':'Создайте урок из сохранённого вывода или завершённого отчёта. Укажите, когда он полезен и где его применять нельзя.'));return;}
  for(const item of items){const card=node('article','panel knowledge-card lesson-card');card.dataset.lessonId=item.id;append(card,lessonDescription(item),append(node('div','memory-card-actions'),button('Редактировать урок',event=>busy(event.currentTarget,()=>openLessonEditor(item.id)),'text-button'),button('История урока',event=>busy(event.currentTarget,()=>openLessonHistory(item.id)),'text-button')));target.append(card);}
}
async function lessonRun(id){state.lessonEvidenceRun=id ? await api('/api/runs/'+encodeURIComponent(id)) : null;renderLessonSources();}
function renderLessonSources(){
  const target=$('#lesson-source-options');if(!target)return;target.replaceChildren();
  const sources=state.lessonEvidenceRun?.plan?.sources || [],body=state.lessonDraft.body;
  if(!sources.length){target.append(node('p','field-hint','Выберите завершённое исследование, чтобы отметить его материалы.'));return;}
  for(const source of sources){const check=document.createElement('input');check.type='checkbox';check.value=source.id;check.className='lesson-source';check.checked=body.evidence_source_ids.includes(source.id);check.addEventListener('change',()=>{body.evidence_source_ids=$$('.lesson-source:checked').map(input=>input.value);});append(target,append(node('label','checkbox-label'),check,node('span','',source.title || source.id)));}
}
function renderLessonEditor(){
  const body=state.lessonDraft.body,target=$('#lesson-editor-fields');target.replaceChildren();
  for(const [key,label] of Object.entries(lessonLabels))editorField(target,body,key,label,{rows:key==='title'?0:2,required:key==='title',maxLength:state.lessonSchema.limits?.fields?.[key] || 1000,placeholder:key==='applies_when'?'Конкретная задача, тип данных и условия, при которых полезно правило':key==='not_applicable_when'?'Границы переноса: другая задача, данные или неподтверждённые условия':''});
  const scope=document.createElement('select');scope.id='lesson-task';fillTaskOptions(scope,body.task_id || '');scope.firstChild.textContent='Без привязки к одной задаче — условия заданы выше';scope.addEventListener('change',()=>{body.task_id=scope.value;});append(target,append(node('label','task-field','Для сохранённой задачи'),scope));
  const evidence=node('section','lesson-evidence-editor');append(evidence,node('h3','','Основание урока'),node('p','field-hint','Анализ источников — вывод из материалов. Внешнее измерение — результат из указанного внешнего источника; лаборатория здесь его не воспроизводит.'));
  editorField(evidence,body,'evidence_level','Тип основания',{choices:state.lessonSchema.evidence_levels});
  const runSelect=document.createElement('select');runSelect.id='lesson-evidence-run';const none=node('option','','Выберите завершённое исследование');none.value='';runSelect.append(none);
  for(const run of state.runs.filter(item=>item.status==='completed')){const option=node('option','',run.plan?.question || run.question || run.id);option.value=run.id;runSelect.append(option);}runSelect.value=body.evidence_run_id || '';
  runSelect.addEventListener('change',()=>{body.evidence_run_id=runSelect.value;body.evidence_source_ids=[];lessonRun(runSelect.value).catch(showError);});append(evidence,append(node('label','task-field','Завершённое исследование'),runSelect));
  const sources=node('div','lesson-source-options');sources.id='lesson-source-options';evidence.append(sources);
  const urls=document.createElement('textarea');urls.id='lesson-evidence-urls';urls.rows=3;urls.maxLength=30000;urls.placeholder='https://…\nОдна публичная ссылка в строке';urls.value=(body.evidence_urls || []).join('\n');urls.addEventListener('input',()=>{body.evidence_urls=urls.value.split(/\r?\n/).map(value=>value.trim()).filter(Boolean);});append(evidence,append(node('label','task-field','Публичные ссылки на основание'),urls));target.append(evidence);
  if(body.knowledge_id)target.append(node('p','field-hint','Урок связан с сохранённым выводом. Исходный вывод сохраняется отдельно.'));
  $('#lesson-status').value=state.lessonDraft.status;$('#lesson-review').value=body.review_at || '';$('#lesson-edit-version').textContent=state.lessonDraft.id?`Редактируется версия ${state.lessonDraft.version}. Каждое сохранение добавит версию в историю.`:'Сохранение урока не запускает модель.';$('#lesson-edit-error').hidden=true;renderLessonSources();
}
async function openLessonEditor(id=null,seed={}){
  await Promise.all([lessonSchema(),refreshTasks()]);const runs=await api('/api/runs');state.runs=runs.items || [];
  const lesson=id ? await api('/api/lessons/'+encodeURIComponent(id)) : null,current=lesson?.current || lesson;
  state.lessonDraft=current ? {id:current.id,version:current.version,status:current.status,body:clone(current.body)} : {id:null,version:0,status:'draft',body:clone(state.lessonSchema.template)};
  const body=state.lessonDraft.body;let run=seed.run;
  if(seed.knowledge){const item=seed.knowledge;body.knowledge_id=item.id;body.title=item.memory?.title || item.title || '';body.rule=item.memory?.claim || item.decision || '';run=await api('/api/runs/'+encodeURIComponent(item.run_id));}
  if(run){body.evidence_run_id=run.id;body.evidence_source_ids=(run.plan?.sources || []).map(item=>item.id).slice(0,6);body.evidence_level='source_analysis';body.title ||= (run.plan?.question || 'Урок из исследования').slice(0,200);body.problem=run.plan?.question || '';body.task_id=run.plan?.study_context?.task_id || '';body.evidence_urls=(run.links || []).map(item=>typeof item==='string'?item:item.url).filter(value=>safeUrl(value)).slice(0,10);}
  state.lessonEvidenceRun=body.evidence_run_id ? run || await api('/api/runs/'+encodeURIComponent(body.evidence_run_id)) : null;
  $('#lesson-dialog-title').textContent=id?'Уточнить урок':'Новый урок';renderLessonEditor();if(!$('#lesson-dialog').open)$('#lesson-dialog').showModal();
}
async function openLessonHistory(id){const data=await api('/api/lessons/'+encodeURIComponent(id)),target=$('#lesson-history-content');target.replaceChildren();for(const item of data.history || data.versions || [data.current || data]){const card=node('article','memory-version');append(card,node('p','field-hint',date(item.created_at)),lessonDescription(item));target.append(card);}$('#lesson-history-dialog').showModal();}
const taskFieldLabels={title:'Название задачи',business_goal:'Бизнес-цель и ожидаемая польза',beneficiary:'Для кого решаем задачу',task_type:'Тип задачи',research_question:'Вопрос к исследованию',inputs:'Входные данные',expected_output:'Ожидаемый результат',constraints:'Ограничения',dataset:'Датасет и происхождение данных',evaluation:'Протокол оценки и сравнения',success_criteria:'Критерии успешного решения'};
const baselineLabels={name:'Текущий подход / baseline',version:'Версия',description:'Как работает сейчас',limitations:'Ограничения текущего подхода'};
const candidateLabels={name:'Кандидат / технология',version:'Версия',description:'Что предлагается',applicability:'Применимость к задаче',advantages:'Преимущества для задачи',limitations:'Ограничения и риски',evidence_level:'Основание',evidence_url:'Ссылка на основание'};
const metricLabels={name:'Метрика',definition:'Определение и способ расчёта',unit:'Единица',direction:'Направление',target:'Цель / порог приёмки',expected:'Ожидание по кандидату',evidence_level:'Основание ожидания',evidence_url:'Источник ожидания'};
const hostedLabels={availability:'Возможность своего развёртывания',model:'Модель и вариант',license:'Лицензия и ограничения',runtime:'Среда выполнения',cpu:'CPU',ram:'RAM',gpu:'GPU',vram:'VRAM',disk:'Диск',context:'Контекст',concurrency:'Параллельность',dependencies:'Зависимости',operations:'Эксплуатация и сопровождение',cost:'Стоимость и способ расчёта',candidate_profiles:'Требования по отдельным кандидатам',evidence_level:'Основание требований',evidence_url:'Источник требований'};
const directionOptions=[{id:'descriptive',label:'Описательная / без направления'},{id:'maximize',label:'Больше — лучше'},{id:'minimize',label:'Меньше — лучше'}];
const availabilityOptions=[{id:'unknown',label:'Неизвестно'},{id:'available',label:'Доступно'},{id:'unavailable',label:'Недоступно'},{id:'not_applicable',label:'Не применимо'}];
function clone(value){return JSON.parse(JSON.stringify(value));}
function knownText(value){return value === undefined || value === null || value === '' || value === 'unknown' ? 'Неизвестно' : String(value);}
function evidenceName(value){return state.studySchema?.evidence_levels?.find(item=>item.id===value)?.label || ({unknown:'Неизвестно',hypothesis:'Гипотеза',author_claim:'Заявление автора',external_measurement:'Внешнее измерение',estimate:'Оценка'}[value]) || value;}
function taskTypeName(value){return state.studySchema?.task_types?.find(item=>item.id===value)?.label || value || 'Свободное изучение';}
async function studySchema(){if(!state.studySchema)state.studySchema=await api('/api/study/schema');return state.studySchema;}
function taskCurrent(value){return value.current || value.task || value;}
async function refreshTasks(){await studySchema();const result=await api('/api/tasks');state.tasks=result.items || [];$('#count-tasks').textContent=state.tasks.length;renderTaskSelect();renderTasks();return state.tasks;}
function fillTaskOptions(select,selected='',includeArchived=false){select.replaceChildren();const exploration=node('option','','Свободное изучение материала');exploration.value='';select.append(exploration);for(const task of state.tasks){if(task.status==='archived' && !includeArchived && task.id!==selected)continue;const option=node('option','',`${task.body?.title || 'Задача'} · v${task.version}${task.status==='archived' ? ' · архив' : ''}`);option.value=task.id;option.disabled=task.status==='archived' && task.id!==selected;select.append(option);}select.value=selected;if(selected && select.value!==selected){const unavailable=node('option','','Выбранная задача недоступна — обновите контекст');unavailable.value=selected;select.append(unavailable);select.value=selected;}}
function renderTaskSelect(){const select=$('#research-task'),selected=select.value;fillTaskOptions(select,selected);renderTaskSummary();}
function renderTaskSummary(){const task=state.tasks.find(item=>item.id===$('#research-task').value);const target=$('#research-task-summary');target.replaceChildren();if(!task){target.textContent='Можно исследовать материал без привязки к бизнес-задаче.';return;}const body=task.body || {},primary=(body.metrics || []).find(item=>item.primary);append(target,node('p','',body.business_goal || 'Бизнес-цель пока не описана.'),node('p','',`Текущий подход: ${knownText(body.baseline?.name)}${primary ? ' · Основная метрика: '+primary.name : ''}`));}
function chooseTask(id){$('#research-task').value=id;renderTaskSummary();const task=state.tasks.find(item=>item.id===id),question=$('#research-question');if(task?.body?.research_question && (!question.value.trim() || question.value===state.autoTaskQuestion)){question.value=task.body.research_question;state.autoTaskQuestion=question.value;}}
function renderTasks(){const target=$('#task-list');target.replaceChildren();if(!state.tasks.length){target.append(empty('▤','Сохраните первую задачу','Опишите, для чего вам технология, с чем её сравнить и какой результат будет полезен.',button('Описать задачу',()=>openTaskEditor().catch(showError))));return;}for(const task of state.tasks){const body=task.body || {},card=node('article','panel knowledge-card task-card'),primary=(body.metrics || []).find(item=>item.primary);append(card,append(node('div','memory-card-heading'),node('span','source-label',taskTypeName(body.task_type)),node('span','status-badge '+(task.status==='archived'?'retired':'active'),task.status==='archived'?'Архив':'Активная задача')),node('h2','',body.title || 'Исследовательская задача'),node('p','decision',knownText(body.business_goal)),node('p','small muted','Baseline: '+knownText(body.baseline?.name)),node('p','small muted',primary ? `Основная метрика: ${primary.name} · цель ${knownText(primary.target)}` : 'Метрики пока не определены'),node('p','field-hint',`Версия ${task.version} · Кандидатов: ${body.candidates?.length || 0} · Анализ источников`));const actions=node('div','memory-card-actions');if(task.status!=='archived')actions.append(button('Использовать в исследовании',()=>{chooseTask(task.id);switchView('inbox');notify('Контекст выбран. Добавьте материал или задайте вопрос.');},'button secondary'));append(actions,button('Редактировать',event=>busy(event.currentTarget,()=>openTaskEditor(task.id)),'text-button'),button('История',event=>busy(event.currentTarget,()=>openTaskHistory(task.id)),'text-button'));card.append(actions);target.append(card);}}
function editorField(parent,obj,key,label,options={}){const wrapper=node('label','task-field',label);const choices=options.choices;const input=document.createElement(choices?'select':options.rows?'textarea':'input');input.dataset.field=key;if(choices){for(const choice of choices){const option=node('option','',choice.label || choice.id);option.value=choice.id;input.append(option);}}else{if(!options.rows)input.type=options.url?'url':'text';const body=state.taskDraft?.body,limits=state.studySchema?.limits || {};const fieldLimit=obj===body?limits.top?.[key]:obj===body?.baseline?limits.baseline?.[key]:obj===body?.self_hosted?limits.self_hosted?.[key]:body?.candidates?.includes(obj)?limits.candidate?.[key]:body?.metrics?.includes(obj)?limits.metric?.[key]:null;input.maxLength=options.maxLength || fieldLimit || (options.url?3000:2000);if(options.rows)input.rows=options.rows;input.placeholder=options.placeholder || 'Неизвестно / пока не определено';}input.value=String(obj[key] ?? '');if(options.required)input.required=true;input.addEventListener(choices?'change':'input',()=>{obj[key]=input.value;});wrapper.append(input);parent.append(wrapper);return input;}
function editorSection(title,description,open=false){const section=node('details','task-editor-section');section.open=open;append(section,node('summary','',title));const content=node('div','task-editor-section-body');if(description)content.append(node('p','field-hint',description));section.append(content);return {section,content};}
function editorEvidence(parent,obj,label='Основание'){editorField(parent,obj,'evidence_level',label,{choices:state.studySchema.evidence_levels});editorField(parent,obj,'evidence_url','Ссылка на первоисточник / внешнее измерение',{url:true});}
function renderCandidateEditors(target){target.replaceChildren();const draft=state.taskDraft.body;for(const [index,candidate] of draft.candidates.entries()){const group=editorSection(`Кандидат ${index+1}: ${candidate.name || 'новая технология'}`,'Сравнивайте применимость к вашей задаче. Указывайте происхождение преимуществ и ограничений.',true);group.section.dataset.candidate=index;for(const key of ['name','version','description','applicability','advantages','limitations'])editorField(group.content,candidate,key,candidateLabels[key],{rows:['description','applicability','advantages','limitations'].includes(key)?2:0});editorEvidence(group.content,candidate);group.content.append(button('Удалить кандидата',()=>{draft.candidates.splice(index,1);renderCandidateEditors(target);},'text-button danger-text'));target.append(group.section);}target.append(button('+ Добавить кандидата',()=>{if(draft.candidates.length>=5){notify('В одной задаче до 5 кандидатов.',true);return;}draft.candidates.push({name:'',version:'',description:'',applicability:'',advantages:'',limitations:'',evidence_level:'unknown',evidence_url:''});renderCandidateEditors(target);},'button secondary'));}
function renderMetricEditors(target){target.replaceChildren();const draft=state.taskDraft.body;for(const [index,metric] of draft.metrics.entries()){const group=editorSection(`Метрика ${index+1}: ${metric.name || 'критерий оценки'}`,'Цель — условие приёмки. Ожидание — гипотеза или число из указанного источника; оно не считается измерением лаборатории.',true);group.section.dataset.metric=index;for(const key of ['name','definition','unit'])editorField(group.content,metric,key,metricLabels[key],{rows:key==='definition'?2:0});editorField(group.content,metric,'direction',metricLabels.direction,{choices:directionOptions});const primary=node('label','checkbox-label');const radio=document.createElement('input');radio.type='radio';radio.name='task-primary-metric';radio.checked=Boolean(metric.primary);radio.dataset.primary=index;radio.addEventListener('change',()=>{draft.metrics.forEach((item,i)=>{item.primary=i===index;});});append(primary,radio,node('span','','Основная метрика задачи'));group.content.append(primary);editorField(group.content,metric,'target',metricLabels.target);editorField(group.content,metric,'expected',metricLabels.expected);editorEvidence(group.content,metric,'Основание ожидания');group.content.append(button('Удалить метрику',()=>{const wasPrimary=metric.primary;draft.metrics.splice(index,1);if(wasPrimary && draft.metrics.length)draft.metrics[0].primary=true;renderMetricEditors(target);},'text-button danger-text'));target.append(group.section);}target.append(button('+ Добавить метрику',()=>{if(draft.metrics.length>=8){notify('В одной задаче до 8 метрик.',true);return;}draft.metrics.push({name:'',definition:'',unit:'',direction:'descriptive',primary:draft.metrics.length===0,target:'',expected:'',evidence_level:'unknown',evidence_url:''});renderMetricEditors(target);},'button secondary'));}
function renderTaskEditor(){const draft=state.taskDraft.body,target=$('#task-editor-fields');target.replaceChildren();const main=editorSection('1 · Задача и польза','Область лаборатории — ИИ и непосредственно связанные передовые технологии.',true);for(const key of ['title','business_goal','beneficiary'])editorField(main.content,draft,key,taskFieldLabels[key],{rows:key==='business_goal'?3:0,required:key==='title',maxLength:key==='title'?200:2000});editorField(main.content,draft,'task_type',taskFieldLabels.task_type,{choices:state.studySchema.task_types});for(const key of ['research_question','inputs','expected_output','constraints'])editorField(main.content,draft,key,taskFieldLabels[key],{rows:2});target.append(main.section);const baseline=editorSection('2 · Текущий подход / baseline','Что используется сейчас и с чем потребуется сравнение.',true);draft.baseline ||= {};for(const key of Object.keys(baselineLabels))editorField(baseline.content,draft.baseline,key,baselineLabels[key],{rows:['description','limitations'].includes(key)?2:0});target.append(baseline.section);const candidates=editorSection('3 · Кандидаты и применимость','До 5 альтернатив: применимость, плюсы, минусы и происхождение утверждений.',true),candidateList=node('div','task-repeat-list');candidates.content.append(candidateList);draft.candidates ||= [];renderCandidateEditors(candidateList);target.append(candidates.section);const metrics=editorSection('4 · Метрики, цели и ожидания','До 8 метрик. Среди заданных метрик должна быть ровно одна основная.',true),metricList=node('div','task-repeat-list');metrics.content.append(metricList);draft.metrics ||= [];renderMetricEditors(metricList);target.append(metrics.section);const protocol=editorSection('5 · Датасет и протокол','План проверки фиксируется здесь. Текущий режим выполняет только анализ источников.');for(const key of ['dataset','evaluation','success_criteria'])editorField(protocol.content,draft,key,taskFieldLabels[key],{rows:3});target.append(protocol.section);const hosted=editorSection('6 · Собственное развёртывание','Параметры зависят от модели, квантизации, контекста и нагрузки. Неизвестные требования не подменяются числами.');draft.self_hosted ||= {};editorField(hosted.content,draft.self_hosted,'availability',hostedLabels.availability,{choices:availabilityOptions});for(const key of Object.keys(hostedLabels).filter(key=>!['availability','evidence_level','evidence_url'].includes(key)))editorField(hosted.content,draft.self_hosted,key,hostedLabels[key],{rows:['dependencies','operations','candidate_profiles','cost'].includes(key)?2:0});editorEvidence(hosted.content,draft.self_hosted,'Основание требований');target.append(hosted.section);$('#task-status').value=state.taskDraft.status;$('#task-edit-version').textContent=state.taskDraft.id ? `Редактируется версия ${state.taskDraft.version}. Предыдущая версия сохранится в истории.` : 'Новая задача; облачные вызовы при сохранении не выполняются.';}
async function openTaskEditor(id=null){await studySchema();let task;if(id)task=taskCurrent(await api('/api/tasks/'+encodeURIComponent(id)));state.taskDraft=task ? {id:task.id,version:task.version,status:task.status,body:clone(task.body)} : {id:null,version:0,status:'active',body:clone(state.studySchema.template)};$('#task-dialog-title').textContent=id?'Уточнить задачу':'Новая задача';renderTaskEditor();$('#task-dialog').showModal();}
function taskDescription(body){const out=node('div','frozen-study-body');const overview=node('dl','study-description');for(const key of ['title','business_goal','beneficiary','task_type','research_question','inputs','expected_output','constraints']){append(overview,node('dt','',taskFieldLabels[key]),node('dd','memory-literal',key==='task_type'?taskTypeName(body[key]):knownText(body[key])));}out.append(overview);const block=(title,labels,values)=>{const section=node('section','study-read-section');section.append(node('h4','',title));const description=node('dl','study-description');for(const [key,label] of Object.entries(labels)){let value=values?.[key];if(key==='evidence_level')value=evidenceName(value);else if(key==='direction')value=directionOptions.find(item=>item.id===value)?.label || value;else if(key==='availability')value=availabilityOptions.find(item=>item.id===value)?.label || value;append(description,node('dt','',label),node('dd','memory-literal',knownText(value)));if(key==='evidence_url' && safeUrl(values?.[key]))description.lastChild.replaceChildren(link(values[key],values[key]));}section.append(description);out.append(section);};block('Текущий подход / baseline',baselineLabels,body.baseline || {});if(body.candidates?.length)body.candidates.forEach((candidate,index)=>block(`Кандидат ${index+1} · ${candidate.name || 'Без названия'}`,candidateLabels,candidate));else out.append(notice('Кандидаты пока не определены.'));if(body.metrics?.length)body.metrics.forEach((metric,index)=>block(`Метрика ${index+1}${metric.primary ? ' · ОСНОВНАЯ' : ''}`,metricLabels,metric));else out.append(notice('Метрики пока не определены.'));block('Датасет, протокол и успех',{dataset:taskFieldLabels.dataset,evaluation:taskFieldLabels.evaluation,success_criteria:taskFieldLabels.success_criteria},body);block('Собственное развёртывание',hostedLabels,body.self_hosted || {});return out;}
function studyScopeSummary(scope){const block=node('div','study-scope');append(block,node('strong','','Условия исходного вывода'),node('p','',scope.task_id ? `${scope.title || 'Задача'} · версия ${scope.task_version}` : 'Свободное изучение материала'));if(scope.business_goal)block.append(node('p','',scope.business_goal));const baseline=typeof scope.baseline==='object' ? scope.baseline?.name : scope.baseline;if(baseline)block.append(node('p','','Baseline: '+baseline));if(scope.dataset)block.append(node('p','','Данные: '+scope.dataset));if(scope.conditions)block.append(node('p','','Условия: '+(typeof scope.conditions==='string'?scope.conditions:JSON.stringify(scope.conditions))));block.append(node('small','','Анализ источников; результаты бенчмарка не измерялись.'));return block;}
async function openTaskHistory(id){const result=await api('/api/tasks/'+encodeURIComponent(id)),history=result.history || result.versions || [taskCurrent(result)],target=$('#task-history-content');target.replaceChildren();for(const task of history){const item=node('details','task-editor-section');append(item,node('summary','',`Версия ${task.version} · ${task.body?.title || 'Задача'} · ${task.status==='archived'?'архив':'активная'}`),node('p','field-hint',date(task.created_at)),taskDescription(task.body || {}));target.append(item);}$('#task-history-dialog').showModal();}
function renderApprovalContext(run,target){const context=run.plan?.study_context,section=node('section','approval-context');section.id='approval-context';append(section,node('h3','','Задача и условия этого исследования'),notice('Режим: анализ источников. Метрики и протокол задают контекст оценки; лабораторный бенчмарк в этом запуске не выполняется.'));const select=document.createElement('select');select.id='approval-task';select.className='context-option';fillTaskOptions(select,context?.task_id || '');select.addEventListener('change',()=>rebuildPlanContext(select.value || null,true).catch(showError));append(section,append(node('label','','Сохранённая задача'),select));if(context){append(section,node('p','field-hint',context.task_id ? `Зафиксирована версия задачи ${context.task_version}.` : 'Свободное изучение материала без сохранённой бизнес-задачи.'),taskDescription(context.task || {}));for(const text of context.notices || [])section.append(notice(text));const raw=node('details');append(raw,node('summary','','Полный снимок задачи и контрольная сумма'),node('pre','technical-data',JSON.stringify(context,null,2)));section.append(raw);}else section.append(notice('В этом старом плане контекст задачи не задан. Его можно добавить обновлением плана.'));const error=node('div','notice error');error.id='approval-context-error';error.hidden=true;section.append(error);section.append(button('Обновить задачу и память',()=>rebuildPlanContext($('#approval-task').value || null).catch(showError),'button secondary context-rebuild'));target.append(section);}
async function rebuildPlanContext(taskId,explicitSelection=false){if(state.memoryRebuilding || !state.pendingPlan)return;state.memoryRebuilding=true;state.memoryBlocked=true;$('#approval-consent').checked=false;updateApprovalLaunch();$$('.memory-option,.memory-rebuild,.context-option,.context-rebuild').forEach(element=>{element.disabled=true;});try{await refreshTasks();const values={...planValues(state.pendingPlan),task_id:taskId};if(taskId || explicitSelection)delete values.study_task;state.memoryPreview=await api('/api/memory/preview',values);const contextBody={memory_options:state.memoryOptions || {enabled:true,include_profile:true,include_corrections:true}};if(taskId || explicitSelection)contextBody.task_id=taskId;const run=await api('/api/plans/'+encodeURIComponent(state.pendingPlan.id)+'/context',contextBody);state.memoryOptions=run.plan?.memory_options || state.memoryOptions;showApproval(run);notify('Контекст и память обновлены. Проверьте новую версию плана и дайте апрув.');}catch(error){const box=$('#approval-context-error');if(box){box.textContent=errorMessage(error);box.hidden=false;}throw error;}finally{state.memoryRebuilding=false;$$('.memory-option,.memory-rebuild,.context-option,.context-rebuild').forEach(element=>{element.disabled=element.dataset.forced==='true';});updateApprovalLaunch();}}

const memoryStateNames = {active:'Используется',stale:'Пора перепроверить',disputed:'Есть противоречие',retired:'Выведено из использования'};
function memoryBadge(memory) {
  const status = memory.effective_status || (memory.status === 'retired' ? 'retired' : memory.stale ? 'stale' : 'active');
  return node('span','status-badge ' + status,memoryStateNames[status] || status);
}
function memoryId(item) { return item.knowledge_id || item.id; }
function reviewDate(value) {if(!value)return '';const parsed=new Date(value);return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleDateString('ru-RU',{day:'numeric',month:'short',year:'numeric'});}
function researchValues() { return {source_ids:[...state.selected],question:$('#research-question').value.trim(),provider:$('#research-provider').value,model:$('#research-model').value.trim(),web_search:$('#research-web').checked,research_mode:$('#research-mode').value,timeout_seconds:Number($('#research-timeout').value),task_id:$('#research-task').value || null}; }
function planValues(run) { const plan = run.plan || {}; return {source_ids:(plan.sources || []).map(item => item.id),question:plan.question,provider:plan.provider,model:plan.model,web_search:plan.web_search,research_mode:reviewedProtocol(plan)?'reviewed':'single',timeout_seconds:plan.timeout_seconds,task_id:plan.study_context?.task_id || null,...(!plan.study_context?.task_id && plan.study_context?.task ? {study_task:plan.study_context.task} : {})}; }
async function prepareResearch(values) {
  state.memoryPreview = await api('/api/memory/preview',values);
  state.memoryOptions = {enabled:true,selected_ids:state.memoryPreview.suggested_ids || [],lesson_ids:state.memoryPreview.suggested_lesson_ids || [],include_profile:true,include_corrections:true};
  const run = await api('/api/plans',{...values,memory_options:state.memoryOptions});
  showApproval(run);
}
async function openPlanApproval(run) {
  state.memoryPreview = run.plan?.continuation ? null : await api('/api/memory/preview',planValues(run));
  const memory = run.plan?.memory;
  state.memoryOptions = {enabled:memory?.enabled !== false,selected_ids:(memory?.items || []).map(memoryId),lesson_ids:(memory?.lessons || []).map(item=>item.id),include_profile:memory ? Boolean(memory.profile) : true,include_corrections:memory ? Boolean(memory.corrections?.length) : true,...(run.plan?.memory_options || {})};
  showApproval(run);
}
function checkbox(text,checked,callback,id) {
  const input = document.createElement('input'); input.type = 'checkbox'; input.checked = checked; input.className = 'memory-option'; if (id) input.id = id;
  input.addEventListener('change',callback);
  return append(node('label','checkbox-label'),input,node('span','',text));
}
function readMemoryOptions() {
  return {...state.memoryOptions,enabled:$('#approval-memory-enabled').checked,include_profile:$('#approval-memory-profile').checked,include_corrections:$('#approval-memory-corrections').checked,selected_ids:$$('.memory-select:checked').map(element => element.value),lesson_ids:$$('.lesson-select:checked').map(element => element.value)};
}
function updateApprovalLaunch() { $('#approve-launch').disabled = !$('#approval-consent').checked || state.memoryRebuilding || state.memoryBlocked; $('#approval-consent').disabled = state.memoryRebuilding || state.memoryBlocked; }
function renderApprovalMemory(run,target) {
  globalThis.LabResearch?.mountPlan(target,run);
  const memory = run.plan?.memory;
  const block = node('section','approval-memory'); block.id = 'approval-memory';
  append(block,node('h3','','Память этого исследования'),node('p','field-hint','Ниже показан сохранённый снимок, который получит исполнитель. Изменение состава обновляет план и сбрасывает апрув.'));
  const options = state.memoryOptions || {enabled:memory?.enabled !== false,selected_ids:(memory?.items || []).map(memoryId),lesson_ids:(memory?.lessons || []).map(item=>item.id),include_profile:Boolean(memory?.profile),include_corrections:true};
  state.memoryOptions = options;
  const controls = node('div','memory-controls');
  const changed = () => rebuildPlanMemory(readMemoryOptions()).catch(showError);
  append(controls,checkbox('Учитывать память в этом исследовании',options.enabled,changed,'approval-memory-enabled'),checkbox('Учитывать исследовательский профиль',options.include_profile,changed,'approval-memory-profile'),checkbox('Учитывать мои поправки',options.include_corrections,changed,'approval-memory-corrections'));
  block.append(controls);
  const available = new Map();
  for (const item of state.memoryPreview?.candidates || []) available.set(memoryId(item),item);
  for (const item of memory?.items || []) if (!available.has(memoryId(item))) available.set(memoryId(item),item);
  if (available.size) {
    const selection = node('details','memory-selection');
    append(selection,node('summary','',`Состав памяти: ${memory?.items?.length || 0} из ${available.size} знаний`));
    const optionsList = node('div','memory-option-list');
    for (const [id,item] of available) {
      const row = node('label','memory-select-row');
      const check = document.createElement('input'); check.type = 'checkbox'; check.value = id; check.className = 'memory-select memory-option'; check.checked = memory?.enabled === false ? (options.selected_ids || []).includes(id) : (memory?.items || []).some(value => memoryId(value) === id); check.addEventListener('change',changed);
      if (id === options.refresh_id) {check.checked=true;check.disabled=true;check.dataset.forced='true';}
      append(row,check,append(node('span'),node('strong','',item.title || 'Сохранённое знание'),node('small','',`Версия ${item.version} · ${item.reason || 'Связано с темой исследования'}`)));
      optionsList.append(row);
    }
    selection.append(optionsList); block.append(selection);
  }
  const lessonCandidates=new Map();
  for(const item of state.memoryPreview?.lesson_candidates || [])lessonCandidates.set(item.id,item);
  for(const item of memory?.lessons || [])if(!lessonCandidates.has(item.id))lessonCandidates.set(item.id,item);
  if(lessonCandidates.size){
    const selection=node('details','lesson-selection memory-selection');
    append(selection,node('summary','',`Уроки с условиями применения: ${memory?.lessons?.length || 0} из ${lessonCandidates.size} · до 3`));
    const list=node('div','memory-option-list');
    for(const [id,item] of lessonCandidates){
      const body=item.body || item,row=node('label','memory-select-row'),check=document.createElement('input');
      check.type='checkbox';check.value=id;check.className='lesson-select memory-option';check.checked=memory?.enabled===false ? (options.lesson_ids || []).includes(id) : (memory?.lessons || []).some(value=>value.id===id);
      check.addEventListener('change',()=>{if($$('.lesson-select:checked').length>3){check.checked=false;notify('В одно исследование можно включить до 3 уроков.',true);return;}changed();});
      append(row,check,append(node('span'),node('strong','',body.title || 'Урок'),node('small','',`Версия ${item.version} · ${item.reason || body.applies_when || 'Условия указаны в уроке'}`)));
      list.append(row);
    }
    append(selection,list,node('p','field-hint','Активные уроки предложены по задаче и теме. Перед выбором проверьте условия применения; для другой задачи появится предупреждение. Снятие выбора исключает урок из передаваемого снимка.'));block.append(selection);
  }
  if (!memory || !memory.enabled) block.append(notice('В этот план память не включена.'));
  else {
    if (memory.profile) {
      const profile = memory.profile;
      append(block,node('h4','',`Ваш профиль · версия ${profile.version}`),node('pre','frozen-memory-text',`Интересы: ${profile.interests || '—'}\n\nЦели: ${profile.goals || '—'}\n\nПредпочтения: ${profile.preferences || '—'}`));
    }
    if (memory.corrections?.length) {
      block.append(node('h4','','Ваши поправки'));
      for (const correction of memory.corrections) append(block,append(node('div','frozen-memory-item'),node('p','small muted',`Поправка · версия ${correction.version}`),node('p','memory-literal',correction.text)));
    }
    if (!memory.items?.length) block.append(node('p','field-hint','Подходящих сохранённых выводов пока нет. Профиль и включённые поправки показаны выше.'));
    for (const item of memory.items || []) {
      const entry = node('article','frozen-memory-item');
      append(entry,append(node('div','memory-card-heading'),node('h4','',item.title || 'Сохранённый вывод'),memoryBadge(item)),node('p','small muted',`Версия ${item.version} · Проверить ${reviewDate(item.review_at) || 'позже'}`),node('p','memory-literal',item.claim));
      if (item.notes) append(entry,node('p','memory-notes',item.notes));
      if (item.study_scope) entry.append(studyScopeSummary(item.study_scope));
      if (item.reason) entry.append(node('p','field-hint','Почему включено: ' + item.reason));
      block.append(entry);
    }
    if(memory.lessons?.length)block.append(node('h4','','Уроки и границы их применения'));
    for(const lesson of memory.lessons || []){
      const entry=node('article','frozen-memory-item frozen-lesson');
      entry.dataset.lessonId=lesson.id;append(entry,lessonDescription(lesson));block.append(entry);
    }
    for (const text of memory.notices || []) block.append(notice(text));
    const exact = node('details'); append(exact,node('summary','','Полный снимок памяти и контрольная сумма'),node('pre','technical-data',JSON.stringify(memory,null,2))); block.append(exact);
  }
  const error = node('div','notice error'); error.id = 'approval-memory-error'; error.hidden = true; block.append(error);
  block.append(button('Обновить память и версию плана',() => rebuildPlanMemory(readMemoryOptions(),true).catch(showError),'button secondary memory-rebuild'));
  target.append(block);
}
async function rebuildPlanMemory(options,refreshPreview=false) {
  if (state.memoryRebuilding || !state.pendingPlan) return;
  state.memoryRebuilding = true; state.memoryBlocked = true; $('#approval-consent').checked = false; updateApprovalLaunch();
  $$('.memory-option, .memory-rebuild, .context-option, .context-rebuild').forEach(element => {element.disabled=true;});
  try {
    if (refreshPreview) state.memoryPreview = await api('/api/memory/preview',planValues(state.pendingPlan));
    const run = await api('/api/plans/' + encodeURIComponent(state.pendingPlan.id) + '/memory',{memory_options:options});
    state.memoryOptions = options; showApproval(run); notify('Память обновлена. Проверьте новый снимок и подтвердите план.');
  } catch(error) {
    const box = $('#approval-memory-error'); if (box) {box.textContent=errorMessage(error);box.hidden=false;}
    throw error;
  } finally {
    state.memoryRebuilding = false;
    $$('.memory-option, .memory-rebuild, .context-option, .context-rebuild').forEach(element => {element.disabled=element.dataset.forced === 'true';});
    updateApprovalLaunch();
  }
}
async function refreshMemory(fill = false) {
  const fields=$$('#memory-profile-form input, #memory-profile-form textarea, #memory-profile-form button');
  if(fill)fields.forEach(element=>{element.disabled=true;});
  try {
    const result = await api('/api/memory'); state.memoryData = result;
    if (fill) {
      const profile = result.profile || {};
      $('#memory-interests').value = profile.interests || ''; $('#memory-goals').value = profile.goals || ''; $('#memory-preferences').value = profile.preferences || ''; $('#memory-review-days').value = profile.review_days || 30;
      $('#memory-profile-version').textContent = `Версия профиля: ${profile.version || 0}. Область: только ИИ и связанные передовые технологии.`;
    }
    renderCorrections(result.corrections || []); return result;
  } finally {if(fill)fields.forEach(element=>{element.disabled=false;});}
}
function renderCorrections(corrections) {
  const target = $('#memory-correction-list'); target.replaceChildren();
  if (!corrections.length) {target.append(node('p','field-hint','Здесь появятся ваши постоянные правила и поправки.'));return;}
  for (const correction of corrections) {
    const card = node('article','correction-item' + (correction.active ? '' : ' inactive'));
    append(card,node('p','memory-literal',correction.text),node('p','field-hint',`Версия ${correction.version} · ${correction.active ? 'Учитывается' : 'Отключена'}${correction.knowledge_id ? ' · Для отдельного знания' : ''}`),button(correction.active ? 'Отключить' : 'Включить',event => busy(event.currentTarget,async () => {await api('/api/memory/corrections',{id:correction.id,expected_version:correction.version,text:correction.text,knowledge_id:correction.knowledge_id || '',active:!correction.active});await refreshMemory(false);notify('Состояние поправки сохранено новой версией.');}),'text-button'));
    target.append(card);
  }
}
function renderMemoryReviews(reviews) {
  const pending = reviews.filter(review => review.status === 'pending');
  $('#memory-reviews-panel').hidden = !pending.length; $('#memory-review-count').textContent = pending.length;
  const list = $('#memory-review-list'); list.replaceChildren();
  for (const review of pending) {
    const card = node('article','memory-review-card');
    const label = review.relation === 'contradicts' ? 'Возможное противоречие' : review.relation === 'supports' ? 'Возможное подтверждение' : 'Предлагаемое уточнение';
    append(card,append(node('div','memory-card-heading'),node('h3','',review.old_title || 'Сохранённый вывод'),node('span','status-badge disputed',label)),node('p','field-hint','Предложение модели, а не проверенный факт. Основание: исследование ' + review.run_id),node('h4','',`Предыдущая формулировка · версия ${review.memory_version}`),node('p','memory-literal',review.old_claim),node('h4','','Новая формулировка из исследования'),node('p','memory-literal',review.updated_claim || review.new_claim || 'Новая формулировка не предложена.'),node('p','memory-notes',review.rationale || 'Причина не указана.'));
    const evidence = node('div','memory-evidence');
    for (const url of review.evidence_urls || []) {const evidenceLink=link(url);if(evidenceLink)evidence.append(evidenceLink);}
    if (evidence.childElementCount) card.append(evidence);
    if(review.relation === 'supports')card.append(node('p','field-hint','При подтверждении актуальности обновятся дата проверки и источники; предыдущая версия сохранится.'));
    const actions = node('div','memory-card-actions');
    append(actions,button('Открыть исследование',() => {state.runId=review.run_id;switchView('runs');},'text-button'),button('История знания',event => busy(event.currentTarget,() => openMemoryHistory(review.knowledge_id)),'text-button'),button(review.relation === 'supports' ? 'Подтвердить актуальность' : 'Принять новую версию',event => busy(event.currentTarget,() => resolveReview(review,'accept')),'button secondary'),button('Отклонить предложение',event => busy(event.currentTarget,() => resolveReview(review,'dismiss')),'text-button'));
    card.append(actions);list.append(card);
  }
}
async function resolveReview(review,action) {await api('/api/memory/reviews/' + encodeURIComponent(review.id) + '/resolve',{action,expected_version:review.version});await refreshKnowledge();notify(action === 'accept' ? 'Решение сохранено. История знания обновлена.' : 'Предложение отклонено. Прежний вывод сохранён.');}
async function openMemoryEdit(id) {
  const data = await api('/api/memory/' + encodeURIComponent(id)), memory=data.current;
  state.memoryEdit = {id,version:memory.version};
  $('#memory-edit-name').value=memory.title || '';$('#memory-edit-claim').value=memory.claim || '';$('#memory-edit-notes').value=memory.notes || '';$('#memory-edit-tags').value=tags(memory.tags).join(', ');$('#memory-edit-status').value=memory.status || 'active';
  $('#memory-edit-review').value=String(memory.review_at || '').slice(0,10);
  $('#memory-edit-dialog').showModal();
}
async function openMemoryHistory(id) {
  const data = await api('/api/memory/' + encodeURIComponent(id));
  const target=$('#memory-history-content');target.replaceChildren();
  for (const memory of data.versions || []) {
    const card=node('article','memory-version');
    append(card,append(node('div','memory-card-heading'),node('h3','',`Версия ${memory.version} · ${memory.title || ''}`),memoryBadge(memory)),node('p','field-hint',date(memory.created_at)),node('p','memory-literal',memory.claim));
    if(memory.notes)card.append(node('p','memory-notes',memory.notes));
    if(memory.evidence_run_id)card.append(button('Исходное исследование ↗',() => {$('#memory-history-dialog').close();state.runId=memory.evidence_run_id;switchView('runs');},'text-button'));
    target.append(card);
  }
  for (const correction of data.corrections || []) append(target,append(node('article','correction-item'),node('h4','',`Поправка · версия ${correction.version}${correction.active ? '' : ' · отключена'}`),node('p','memory-literal',correction.text)));
  if ((data.reviews || []).length) {
    target.append(node('h3','','История предложений модели'));
    for (const review of data.reviews) append(target,append(node('article','memory-version'),node('p','small muted',`${review.status} · ${date(review.created_at)}`),node('p','memory-literal',review.rationale || ''),node('p','memory-literal',review.updated_claim || review.new_claim || '')));
  }
  $('#memory-history-dialog').showModal();
}
async function prepareFreshnessRun(id) {
  const run=await api('/api/memory/' + encodeURIComponent(id) + '/refresh-plan',{});
  await openPlanApproval(run);
  state.memoryOptions.refresh_id=id;
  showApproval(run);
  notify('Подготовлен план проверки актуальности. Запуск начнётся после вашего апрува.');
}
function openSaveDialog(run) { state.saveRunId = run.id; $('#finding-title').value = (run.plan?.question || run.question || 'Исследование').slice(0,300); $('#finding-decision').value = ''; $('#finding-tags').value = ''; $('#save-dialog').showModal(); }
function downloadText(text, filename, type = 'application/json;charset=utf-8') { const url = URL.createObjectURL(new Blob([text],{type})); const anchor = document.createElement('a'); anchor.href = url; anchor.download = filename; document.body.append(anchor); anchor.click(); anchor.remove(); setTimeout(() => URL.revokeObjectURL(url),1000); }
async function exportBackup() { const backup = await api('/api/export'); downloadText(JSON.stringify(backup,null,2),'constellation-backup-' + new Date().toISOString().slice(0,10) + '.json'); notify('Резервная копия скачана.'); }
async function readJsonFile(input, maxMB = 20) { const file = input.files?.[0]; if (!file) return null; if (file.size > maxMB * 1024 * 1024) throw new Error(`Файл больше ${maxMB} МБ. Выберите меньший фрагмент или используйте локальное резервирование папки данных.`); try { return JSON.parse(await file.text()); } catch { throw new Error('Не удалось прочитать JSON. Выберите исходный JSON-экспорт, не HTML и не ZIP.'); } }
function debounce(callback, ms = 300) { let timeout; return () => {clearTimeout(timeout); timeout = setTimeout(() => callback().catch(showError),ms);}; }

$$('[data-view]').forEach(element => element.addEventListener('click',() => switchView(element.dataset.view)));
$$('[data-go]').forEach(element => element.addEventListener('click',() => switchView(element.dataset.go)));
$$('[data-close]').forEach(element => element.addEventListener('click',() => $('#' + element.dataset.close).close()));
$('#add-source-button').addEventListener('click',openSourceDialog);
$('#empty-add-source').addEventListener('click',openSourceDialog);
$('#new-task-button').addEventListener('click',event=>busy(event.currentTarget,()=>openTaskEditor()));
$('#new-lesson-button').addEventListener('click',event=>busy(event.currentTarget,()=>openLessonEditor()));
$('#lesson-search').addEventListener('input',renderLessons);
$('#lesson-form').addEventListener('submit',event=>{
  event.preventDefault();busy($('button[type=submit]',event.currentTarget),async()=>{
    if(!state.lessonDraft)return;const draft=state.lessonDraft;draft.body.review_at=$('#lesson-review').value;
    const payload={expected_version:draft.version,status:$('#lesson-status').value,body:draft.body};if(draft.id)payload.id=draft.id;
    try{await api('/api/lessons',payload);$('#lesson-dialog').close();await refreshLessons();notify('Версия урока сохранена. Состав уже подготовленных планов не меняется.');}
    catch(error){const box=$('#lesson-edit-error');box.replaceChildren(node('p','',errorMessage(error)));if(draft.id)box.append(button('Загрузить актуальную версию урока',()=>openLessonEditor(draft.id).catch(showError),'text-button'));box.hidden=false;}
  });
});
$('#research-new-task').addEventListener('click',event=>busy(event.currentTarget,()=>openTaskEditor()));
$('#research-task').addEventListener('change',event=>chooseTask(event.target.value));
for(const prefix of ['research','setting'])$('#'+prefix+'-mode').addEventListener('change',()=>updateResearchMode(prefix));
$('#task-form').addEventListener('submit',event=>{event.preventDefault();busy($('button[type=submit]',event.currentTarget),async()=>{if(!state.taskDraft)return;const body={expected_version:state.taskDraft.version,status:$('#task-status').value,body:state.taskDraft.body};if(state.taskDraft.id)body.id=state.taskDraft.id;const saved=taskCurrent(await api('/api/tasks',body));$('#task-dialog').close();await refreshTasks();if(saved.status!=='archived')chooseTask(saved.id);notify('Задача сохранена. Исследование начнётся только после отдельного апрува.');});});
$('#source-search').addEventListener('input',debounce(refreshSources));
$('#knowledge-search').addEventListener('input',debounce(refreshKnowledge));
$('#refresh-button').addEventListener('click',event => busy(event.currentTarget, async () => {globalThis.FrontierLive?.invalidate();await refreshBootstrap(); await refreshSources(); await refreshTasks(); if (['runs','reactor','observatory'].includes(state.view)) await refreshRuns(); if (state.view === 'knowledge') await refreshKnowledge(); notify('Данные обновлены.');}));
$('#source-form').addEventListener('submit',event => {event.preventDefault(); const submit = $('button[type=submit]',event.currentTarget); busy(submit,async () => {const text = $('#source-text').value.trim(), url = $('#source-url').value.trim(); if (!text && !url) throw new Error('Добавьте текст или ссылку.'); const result = await api('/api/sources',{title:$('#source-title').value.trim(),text,url,tags:tags($('#source-tags').value)}); const source = result.source || result; if (source.id) {state.sourceId = source.id; state.selected = new Set([source.id]);} $('#source-dialog').close(); $('#source-search').value = ''; await refreshSources(); await refreshBootstrap(); notify('Материал сохранён. Теперь можно задать вопрос.');});});
$('#telegram-import').addEventListener('change',async event => {const input = event.target; try {const data = await readJsonFile(input); if (!data) return; const result = await api('/api/import/telegram',{export:data}); $('#source-search').value = ''; await refreshSources(); await refreshBootstrap(); notify(`Импортировано: ${result.imported || 0}. Дубликатов: ${result.duplicates || 0}. Пропущено: ${result.skipped || 0}.`);} catch(error) {showError(error);} finally {input.value = '';}});
$('#research-form').addEventListener('submit',event => {event.preventDefault(); busy($('#prepare-button'),async () => {if (!state.selected.size) throw new Error('Выберите хотя бы один материал.'); await prepareResearch(researchValues()); await refreshBootstrap();});});
$('#approval-consent').addEventListener('change',updateApprovalLaunch);
$('#approve-launch').addEventListener('click',async () => {
  if (!state.pendingPlan || !$('#approval-consent').checked || state.memoryRebuilding || state.memoryBlocked) return;
  $('#approve-launch').disabled=true;
  try {
    const plan=state.pendingPlan;
    const run=await api('/api/runs/' + encodeURIComponent(plan.id) + '/start',{plan_hash:plan.plan_hash,consent:true,command_id:plan.command_id || (plan.command_id=commandId())});
    $('#approval-dialog').close();state.runId=run.id || plan.id;switchView('runs');await refreshBootstrap();notify('Исследование запущено.');
  } catch(error) {
    state.memoryBlocked=true;$('#approval-consent').checked=false;
    const box=$('#approval-context-error') || $('#approval-memory-error');if(box){box.textContent=errorMessage(error) + ' Если задача или память изменились, обновите контекст и проверьте новую версию плана.';box.hidden=false;}
    showError(error);
  } finally {updateApprovalLaunch();}
});
$('#save-form').addEventListener('submit',event => {event.preventDefault(); busy($('button[type=submit]',event.currentTarget),async () => {await api('/api/runs/' + encodeURIComponent(state.saveRunId) + '/save',{title:$('#finding-title').value.trim(),decision:$('#finding-decision').value.trim(),tags:tags($('#finding-tags').value)}); $('#save-dialog').close(); await refreshBootstrap(); await refreshKnowledge(); notify('Вывод сохранён в базе знаний.');});});
$('#settings-form').addEventListener('submit',event => {event.preventDefault(); busy($('button[type=submit]',event.currentTarget),async () => {await api('/api/settings',{provider:$('#setting-provider').value,model:$('#setting-model').value.trim(),web_search:$('#setting-web').checked,research_mode:$('#setting-mode').value,timeout_seconds:Number($('#setting-timeout').value),daily_run_limit:Number($('#setting-daily').value)}); await refreshBootstrap(true); notify('Настройки сохранены.');});});
$('#memory-profile-form').addEventListener('submit',event => {event.preventDefault();busy($('button[type=submit]',event.currentTarget),async () => {await api('/api/memory/profile',{expected_version:state.memoryData?.profile?.version || 0,interests:$('#memory-interests').value.trim(),goals:$('#memory-goals').value.trim(),preferences:$('#memory-preferences').value.trim(),review_days:Number($('#memory-review-days').value)});await refreshMemory(true);notify('Профиль сохранён. Для существующего плана потребуется обновить память.');});});
$('#memory-correction-form').addEventListener('submit',event => {event.preventDefault();busy($('button[type=submit]',event.currentTarget),async () => {await api('/api/memory/corrections',{expected_version:0,text:$('#memory-correction-text').value.trim(),knowledge_id:'',active:true});$('#memory-correction-text').value='';await refreshMemory(false);notify('Поправка сохранена для следующих исследований.');});});
$('#memory-edit-form').addEventListener('submit',event => {event.preventDefault();busy($('button[type=submit]',event.currentTarget),async () => {
  if(!state.memoryEdit)return;
  const value=$('#memory-edit-review').value;
  const body={expected_version:state.memoryEdit.version,title:$('#memory-edit-name').value.trim(),claim:$('#memory-edit-claim').value.trim(),notes:$('#memory-edit-notes').value.trim(),tags:tags($('#memory-edit-tags').value),status:$('#memory-edit-status').value};
  if(value)body.review_at=value;
  await api('/api/memory/' + encodeURIComponent(state.memoryEdit.id) + '/revise',body);$('#memory-edit-dialog').close();await refreshKnowledge();notify('Новая версия знания сохранена. Предыдущая осталась в истории.');
});});
$('#publication-channel-form').addEventListener('submit',event=>{
  event.preventDefault();busy($('button[type=submit]',event.currentTarget),async()=>{
    const input=$('#publication-channel'),value=input.value.trim(),feedback=$('#publication-channel-feedback');
    let channel;
    if(/^@[A-Za-z0-9_]{5,32}$/.test(value))channel=value;
    else if(/^-[1-9][0-9]*$/.test(value)&&Number.isSafeInteger(Number(value)))channel=Number(value);
    else{feedback.textContent='Укажите @username канала или отрицательный числовой ID. Ссылки и названия без @ не подходят.';throw new Error(feedback.textContent);}
    publicationChannelSaving=true;++publicationRequest;input.disabled=true;feedback.textContent='Проверяем канал и права бота…';
    try{
      const saved=await api('/api/publication/channel',{channel});
      ++publicationRequest;renderPublication(saved);
      feedback.textContent='Канал подключён. Готовые выпуски требуют вашего апрува для этого канала; расписание сохранено без изменений.';
      notify('Канал проверен и подключён. Публикация не запускалась.');
    }catch(error){feedback.textContent=errorMessage(error);throw error;}
    finally{publicationChannelSaving=false;input.disabled=false;$('#publication-channel-form button[type=submit]').disabled=false;}
  });
});
$('#publication-enabled').addEventListener('change',markPublicationDirty);
$('#publication-add-slot').addEventListener('click',()=>{addPublicationSlot();markPublicationDirty();});
$('#publication-refresh').addEventListener('click',event=>busy(event.currentTarget,refreshPublication));
$('#operations-refresh').addEventListener('click',event=>busy(event.currentTarget,async()=>renderOperations(await api('/api/operations'))));
$('#operations-backup').addEventListener('click',event=>busy(event.currentTarget,async()=>{renderOperations(await api('/api/operations/backup',{}));notify('Полная копия создана; проверка восстановления завершена.');}));
$('#publication-form').addEventListener('submit',event=>{
  event.preventDefault();busy($('button[type=submit]',event.currentTarget),async()=>{
    const slots=$$('.publication-slot').map(row=>({weekday:Number($('[data-publication-field="weekday"]',row).value),time:$('[data-publication-field="time"]',row).value}));
    if(new Set(slots.map(slot=>slot.weekday+':'+slot.time)).size!==slots.length)throw new Error('Укажите каждое время выпуска только один раз.');
    const enabled=$('#publication-enabled').checked;
    const controls=$$('input,select,button',event.currentTarget),disabled=controls.map(control=>control.disabled);
    publicationSaving=true;++publicationRequest;controls.forEach(control=>{control.disabled=true;});
    try{
      const saved=await api('/api/publication/settings',{enabled,slots});
      publicationDirty=false;publicationSaving=false;++publicationRequest;renderPublication(saved);
      notify(saved.channel_configured?'Расписание сохранено. Публикуются только одобренные выпуски.':'Расписание сохранено. Канал не подключён, отправок в канал не будет.');
    }finally{
      publicationSaving=false;controls.forEach((control,index)=>{if(control.isConnected)control.disabled=disabled[index];});
      $('#publication-add-slot').disabled=$('#publication-slots').children.length>=7;
    }
  });
});
$('#telegram-form').addEventListener('submit',event => {event.preventDefault(); busy($('button[type=submit]',event.currentTarget),async () => {const token = $('#telegram-token').value.trim(); if (!token) throw new Error('Введите токен Telegram-бота.'); try {const result = await api('/api/telegram/config',{token}); renderTelegram(result.telegram || result); await refreshBootstrap(); notify('Настройка сохранена. Отправьте боту команду привязки.');} finally {$('#telegram-token').value = '';}});});
$('#telegram-disconnect').addEventListener('click',event => busy(event.currentTarget,async () => {if (!confirm('Отключить Telegram-бота? Уже сохранённые материалы останутся в лаборатории.')) return; await api('/api/telegram/disconnect',{}); await refreshBootstrap(); notify('Бот отключён.');}));
$('#copy-pairing').addEventListener('click',async () => {try {await navigator.clipboard.writeText($('#pairing-command').textContent); notify('Команда скопирована.');} catch {notify('Выделите команду и скопируйте её вручную.');}});
$('#export-button').addEventListener('click',event => busy(event.currentTarget,exportBackup));
$('#settings-export-button').addEventListener('click',event => busy(event.currentTarget,exportBackup));
$('#restore-input').addEventListener('change',async event => {const input = event.target; try {const backup = await readJsonFile(input, 100); if (!backup) return; const counts = state.bootstrap?.counts || {}; if (Object.values(counts).some(value => Number(value) > 0)) throw new Error('Восстановление доступно только в пустую базу. Текущие записи сохранены.'); if (!confirm('Восстановить материалы и отчёты из выбранной копии в пустую базу?')) return; await api('/api/restore',{backup,confirm:true}); await refreshBootstrap(); await refreshSources(); await refreshKnowledge(); notify('Резервная копия восстановлена.');} catch(error) {showError(error);} finally {input.value = '';}});

async function initialLoad() {
  $('#source-list').replaceChildren(node('div','loading-message','Открываем вашу лабораторию…'));
  try {await refreshBootstrap(true); await refreshSources(); await refreshRuns(); await refreshMemory(true); await refreshTasks();} catch(error) {const banner = $('#connection-error'); banner.textContent = errorMessage(error); banner.hidden = false; $('#source-list').replaceChildren(empty('↙','Не удалось загрузить материалы','Проверьте сервер и нажмите «Обновить».'));}
}
setInterval(async () => {
  if (document.hidden || state.pollBusy || !state.bootstrap) return;
  state.pollBusy = true;
  try {
    const oldCount = state.bootstrap.counts?.sources;
    const oldRuns = state.bootstrap.counts?.runs;
    const bootstrap = await refreshBootstrap();
    if (oldCount !== bootstrap.counts?.sources) await refreshSources();
    if (state.runs.some(run => activeStatuses.has(run.status)) || oldRuns!==bootstrap.counts?.runs ||
        (['reactor','observatory'].includes(state.view)&&Date.now()-lastFrontierPoll>=15000)) await refreshRuns();
    if (state.view==='settings'&&!publicationSaving) await refreshPublication();
  } catch(error) {const banner = $('#connection-error'); banner.textContent = errorMessage(error); banner.hidden = false;}
  finally {state.pollBusy = false;}
},3000);
globalThis.FrontierLive?.configure({getState:()=>state,api,switchView,selectRun,showError,openPlanApproval,refreshPublication});
switchView(state.view);
initialLoad();
