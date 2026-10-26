(function () {
  'use strict';

  const list = value => Array.isArray(value) ? value : [];
  const object = value => value && typeof value === 'object' && !Array.isArray(value) ? value : {};
  const text = value => typeof value === 'string' ? value.trim() : typeof value === 'number' && Number.isFinite(value) ? String(value) : '';
  const unknown = 'Не зафиксировано';
  const gateNames = {task:'Задача',baseline:'Baseline',metrics:'Метрики',conditions:'Условия',evidence:'Основания',execution:'Выполнение',reproducibility:'Воспроизводимость'};
  const statusNames = {recorded:'Зафиксировано',partial:'Частично',missing:'Не хватает данных',not_executed:'Не выполнено'};
  const basisNames = {author_claim:'Заявление авторов',external_measurement:'Внешнее измерение',hypothesis:'Гипотеза',estimate:'Оценка',unknown:'Основание не указано',stored_source_analysis:'Анализ источников'};
  const memoryStatuses = {active:'активна',archived:'в архиве',superseded:'заменена',needs_review:'нужен пересмотр',retired:'исключена из активной памяти',stale:'нужен пересмотр'};
  const relationNames = {context:'Контекст',supports:'Поддерживает прежний вывод',contradicts:'Противоречит прежнему выводу',updates:'Уточняет прежний вывод',confirms:'Поддерживает прежний вывод',different_conditions:'Условия различаются'};
  const dimensionNames = {definition:'Определение метрики',unit:'Единица',direction:'Направление',model_version:'Модель / версия',dataset:'Данные',evaluation:'Метод оценки',hardware:'Оборудование',load:'Нагрузка',conditions:'Прочие условия'};

  function el(tag, value, className) {
    const node = document.createElement(tag);
    if (value !== undefined && value !== null) node.textContent = String(value);
    if (className) node.className = className;
    return node;
  }
  function add(parent, ...children) { for (const child of children.flat()) if (child) parent.append(child); return parent; }
  function button(label, action, className = 'fl-button') { const node = el('button', label, className); node.type = 'button'; node.addEventListener('click', action); return node; }
  function badge(label, state = '') { const node = el('span', label, 'fl-badge'); if (state) node.dataset.state = state; return node; }
  function paragraph(value, className = '') { return el('p', text(value) || unknown, className); }
  function block(title, ...children) { return add(el('section', undefined, 'fl-detail-block'), el('h4', title), ...children); }
  function disclosure(title, ...children) { return add(el('details', undefined, 'fl-disclosure'), el('summary', title), ...children); }
  function dl(rows) { const node = el('dl', undefined, 'fl-facts'); for (const [label, value] of rows) add(node, el('dt', label), el('dd', text(value) || unknown)); return node; }
  function safeUrl(value) {
    try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password ? url.href : null; } catch (_) { return null; }
  }
  function sourceLink(url, label) {
    const href = safeUrl(url);
    if (!href) return null;
    const node = el('a', label || new URL(href).hostname, 'fl-link');
    node.href = href; node.target = '_blank'; node.rel = 'noopener noreferrer'; return node;
  }
  function plain(value) { return text(value).replace(/<lab_[\s\S]*$/i, '').replace(/^#{1,6}\s*/gm, '').replace(/\*\*/g, '').trim(); }
  function excerpt(value, limit = 240) { const valueText = plain(value).replace(/\s+/g, ' '); return valueText.length > limit ? valueText.slice(0, limit - 1).trimEnd() + '…' : valueText; }
  function taskFor(run) { return object(run?.plan?.study_context?.task || run?.plan?.task_snapshot?.task || run?.plan?.task_snapshot); }
  function baselineFor(task) { const baseline = object(task.baseline); return typeof task.baseline === 'string' ? task.baseline : [baseline.name,baseline.version,baseline.description].map(text).filter(Boolean).join(' · '); }
  function titleFor(run, p) { return text(p?.title) || text(taskFor(run).title) || text(run?.plan?.sources?.[0]?.title) || excerpt(run?.plan?.question, 100) || 'Исследование ' + (text(run?.id).slice(0, 8) || 'без ID'); }
  function recordBody(item) { return object(item?.body || item); }
  function recordIds(item) { const body = recordBody(item); return [...new Set([item?.id,item?.knowledge_id,body.id,body.knowledge_id].map(text).filter(Boolean))]; }
  function versionOf(item) { return item?.version ?? recordBody(item).version; }
  function recordTitle(item, report) {
    if (text(report?.p?.title)) return text(report.p.title);
    const first = plain(item.output).split(/\r?\n/).find(line => line.trim());
    if (first && !/^(?:\d+[.)]?\s*)?(?:рабочая проблема|рабочая задача|краткий вывод|что |кому |сценарий)/i.test(first)) return first;
    return text(item.title) || text(item.memory?.title) || first || 'Сохранённая запись';
  }
  function table(headings, className = '') {
    const node = el('table', undefined, 'fl-table ' + className), head = el('thead'), row = el('tr'), body = el('tbody');
    for (const title of headings) { const th = el('th', title); th.scope = 'col'; row.append(th); }
    add(node, add(head, row), body); return {node, body};
  }
  function tableWrap(node, label) { const wrap = el('div', undefined, 'fl-table-scroll'); wrap.tabIndex = 0; wrap.setAttribute('role', 'region'); wrap.setAttribute('aria-label', label); wrap.append(node); return wrap; }
  function empty(title, detail) { return add(el('div', undefined, 'fl-empty'), el('span', '∅', 'fl-empty-symbol'), el('h3', title), detail ? paragraph(detail, 'fl-muted') : null); }

  function normalizedReports(options) {
    const found = new Map();
    for (const input of list(options.reports)) {
      const report = {run:object(input.run),p:object(input.p || input.presentation),research:object(input.research)};
      if (text(report.run.id)) found.set(report.run.id, report);
    }
    if (text(options.selectedRun?.id)) {
      const previous = found.get(options.selectedRun.id) || {};
      found.set(options.selectedRun.id, {run:options.selectedRun,p:options.selectedPresentation || previous.p || {},research:options.selectedResearch || previous.research || {}});
    }
    return [...found.values()];
  }

  function mount(host, options = {}) {
    if (!host || typeof host.replaceChildren !== 'function') throw new TypeError('FrontierLibrary.mount: нужен DOM-контейнер.');
    const mode = ['knowledge','compare','validation'].includes(options.mode) ? options.mode : 'knowledge';
    const root = el('section', undefined, 'fl-library fl-' + mode);
    const reports = normalizedReports(options), reportMap = new Map(reports.map(report => [report.run.id, report]));
    const cleanups = [];
    const titles = {knowledge:['01 / АРХИВ','База знаний'],compare:['02 / УСЛОВИЯ','Сравнить исследования'],validation:['03 / ОСНОВАНИЯ','Проверка']};
    const head = el('header', undefined, 'fl-view-head');
    add(head, add(el('div'), el('span', titles[mode][0], 'fl-eyebrow'), el('h2', titles[mode][1])));
    root.append(head); host.replaceChildren(root);
    const context = {options,root,head,reports,reportMap,cleanups};
    if (mode === 'knowledge') renderKnowledge(context);
    if (mode === 'compare') renderCompare(context);
    if (mode === 'validation') renderValidation(context);
    if (mode === 'knowledge' || mode === 'compare') renderLocalBenchmarks(context);
    let destroyed = false;
    return {destroy() { if (destroyed) return; destroyed = true; for (const cleanup of cleanups) cleanup(); if (root.parentNode === host) root.remove(); }};
  }

  function renderLocalBenchmarks({options,root}) {
    const rows=list(options.workspace?.lexical_benchmarks).filter(row=>row.completed===true&&row.origin==='executed_local_lexical');
    if(!rows.length)return;
    const section=add(el('section',undefined,'fl-detail-block'),el('h3','Измеренные CPU-проверки'),paragraph('Отдельные прикладные кейсы. Их результат не переносится автоматически на выбранные статьи.','fl-note'));
    const records=table(['Задача / данные','Запросов','TF-IDF · nDCG@10','BM25 · nDCG@10','Критерий','Результаты']);
    function metric(value){return typeof value==='number'&&Number.isFinite(value)?(value*100).toLocaleString('ru-RU',{maximumFractionDigits:2})+' %':'Не измерено';}
    for(const row of rows){const tr=el('tr'),metrics=object(row.metrics),counts=object(row.counts);
      add(tr,el('td','Поиск документов · '+text(row.payload?.manifest?.dataset||'SciFact')),el('td',typeof counts.queries==='number'?counts.queries:'Не зафиксировано'),el('td',metric(metrics.tfidf?.ndcg_at_10)),el('td',metric(metrics.bm25?.ndcg_at_10)),el('td',row.passed===true?'Выполнен':row.passed===false?'Не выполнен':'Не оценён'));
      const cell=el('td');if(typeof options.onOpenBenchmark==='function')cell.append(button('Открыть замер →',()=>options.onOpenBenchmark(row.plan_id||row.id)));else cell.append(paragraph('Смотрите раздел «Эксперименты».'));tr.append(cell);records.body.append(tr);
    }
    section.append(tableWrap(records.node,'Результаты локальных CPU-проверок'));root.append(section);
  }

  function renderKnowledge({options,root,head,reportMap}) {
    const items = list(options.knowledge), memory = object(options.selectedRun?.plan?.memory), snapshots = new Map();
    for (const [key,label] of [['items','Вывод'],['lessons','Урок'],['corrections','Поправка']]) {
      for (const item of list(memory[key])) for (const id of recordIds(item)) {
        const current = snapshots.get(id) || []; current.push({item,label}); snapshots.set(id,current);
      }
    }
    const analogues = list(options.selectedPresentation?.applied_analysis?.analogues);
    const idsFor = item => [...new Set([text(item.id),...recordIds(item.memory)].filter(Boolean))];
    const snapshotFor = item => idsFor(item).flatMap(id => snapshots.get(id) || []);
    let selected = items[0] || null, filter = 'all', query = '';
    const count = el('p', undefined, 'fl-count'); count.setAttribute('aria-live','polite'); head.append(count);
    const toolbar = el('div', undefined, 'fl-toolbar'), searchLabel = el('label', undefined, 'fl-search');
    const input = el('input'); input.type = 'search'; input.placeholder = 'Название, задача, тег…'; input.setAttribute('aria-label','Найти знание');
    add(searchLabel, el('span','Поиск','fl-control-label'), input);
    const switches = el('div', undefined, 'fl-switches'); switches.setAttribute('role','group'); switches.setAttribute('aria-label','Область базы знаний');
    const allButton = button('Все записи', () => setFilter('all'), 'fl-switch');
    const selectedButton = button('В памяти исследования', () => setFilter('selected'), 'fl-switch');
    add(switches, allButton, selectedButton); add(toolbar, searchLabel, switches); root.append(toolbar);
    const grid = el('div', undefined, 'fl-knowledge-grid'), main = el('div', undefined, 'fl-knowledge-main');
    const detail = el('aside', undefined, 'fl-detail'); detail.setAttribute('aria-label','Карточка знания');
    const result = table(['Знание','Задача / область','Основание','Версия / пересмотр','Связь с текущей памятью'],'fl-knowledge-table');
    const noResults = empty('Ничего не найдено','Измените запрос или выберите все записи.');
    add(main, tableWrap(result.node,'База знаний'), noResults); add(grid,main,detail); root.append(grid);
    function setFilter(value) { filter=value; refresh(); }
    function relationship(item) {
      const matches=snapshotFor(item);
      if (!matches.length) return 'Не включено в снимок';
      const versions=[...new Set(matches.map(match => versionOf(match.item)).filter(value => value !== undefined && value !== null))];
      return 'В снимке' + (versions.length ? ' · ' + versions.map(value=>'v'+value).join(', ') : ' · версия не указана');
    }
    function refresh() {
      allButton.setAttribute('aria-pressed',String(filter==='all')); selectedButton.setAttribute('aria-pressed',String(filter==='selected'));
      const visible=items.filter(item => (filter!=='selected'||snapshotFor(item).length) && (!query||[recordTitle(item,reportMap.get(item.run_id)),...list(item.tags),...list(item.memory?.tags),item.memory?.study_scope?.title,item.memory?.study_scope?.business_goal,item.memory?.claim].map(text).join(' ').toLocaleLowerCase('ru').includes(query)));
      count.textContent=visible.length+' из '+items.length+' записей'; result.body.replaceChildren(); noResults.hidden=Boolean(visible.length); result.node.parentNode.hidden=!visible.length;
      if (!visible.includes(selected)) selected=visible[0]||null;
      for (const item of visible) {
        const body=object(item.memory), report=reportMap.get(item.run_id), tr=el('tr'); tr.dataset.selected=String(item===selected); tr.dataset.knowledgeId=text(item.id);
        const titleButton=button(recordTitle(item,report),()=>{selected=item;refresh();},'fl-record-button'); titleButton.setAttribute('aria-pressed',String(item===selected));
        const knowledgeCell=add(el('td'),titleButton,el('span',text(item.created_at)?.split('T')[0]||'Дата не указана','fl-cell-note'));
        const scope=el('td'), tags=el('div',undefined,'fl-tags'); for(const tag of list(item.tags).length?item.tags:list(body.tags)) tags.append(el('span',text(tag),'fl-tag'));
        add(scope,el('span',text(body.study_scope?.title)||unknown),tags);
        const version=el('td'); add(version,el('strong',body.version!==undefined?'v'+body.version:'Версия не указана'),el('span',body.review_at?'Пересмотр: '+text(body.review_at):'Дата пересмотра не указана','fl-cell-note'));
        if(body.effective_status||body.status) version.append(el('span','Статус записи: '+(memoryStatuses[body.effective_status||body.status]||'не размечен'),'fl-cell-note'));
        add(tr,knowledgeCell,scope,el('td',basisNames[body.evidence_level]||text(body.evidence_level)||'Анализ источников'),version,el('td',relationship(item),snapshotFor(item).length?'fl-in-snapshot':'fl-muted')); result.body.append(tr);
      }
      renderDetail(selected);
    }
    function renderDetail(item) {
      detail.replaceChildren();
      if(!item){detail.append(empty('Выберите запись'));return;}
      const body=object(item.memory),report=reportMap.get(item.run_id),scope=object(body.study_scope),ids=idsFor(item),matches=snapshotFor(item);
      add(detail,el('span','КАРТОЧКА ЗНАНИЯ','fl-eyebrow'),el('h3',recordTitle(item,report)),badge(basisNames[body.evidence_level]||text(body.evidence_level)||'Анализ источников'));
      const claim=plain(body.claim||item.output), paragraphs=claim.split(/\n\s*\n/).map(value=>value.trim()).filter(Boolean);
      detail.append(block('Утверждение',paragraph(excerpt(paragraphs.find(value=>value.length>80)||claim,400))));
      detail.append(disclosure('Область и условия',dl([['Задача',scope.business_goal||scope.title],['Baseline',baselineFor(scope)],['Условия',scope.conditions],['Данные',scope.dataset]])));
      detail.append(disclosure('Версия записи',dl([['ID',item.id],['Версия',body.version!==undefined?'v'+body.version:''],['Пересмотр',body.review_at],['Статус записи',memoryStatuses[body.effective_status||body.status]||'не размечен']])));
      const relation=block('Связь с выбранным исследованием',paragraph(relationship(item)));
      for(const match of matches){const snapshotVersion=versionOf(match.item);if(snapshotVersion!==undefined&&body.version!==undefined&&snapshotVersion!==body.version) relation.append(paragraph('В плане сохранена v'+snapshotVersion+'; в базе открыта v'+body.version+'. Старый отчёт использовал свою версию.','fl-note'));}
      for(const analogue of analogues.filter(row=>ids.includes(text(row.memory_id)))){
        const entry=add(el('div',undefined,'fl-analogue'),badge(relationNames[analogue.relation]||text(analogue.relation)||'Связь из отчёта'),paragraph(analogue.relevance),dl([['Версия в отчёте',analogue.memory_version!==undefined?'v'+analogue.memory_version:''],['Различие условий',analogue.conditions_difference]])); relation.append(entry);
      }
      detail.append(relation);
      const urls=new Set();
      const sourceIds=new Set([...list(item.source_ids),...list(body.source_ids)]);
      for(const source of list(options.workspace?.sources)) {const data=object(source.payload||source);if([source.id,data.source_id,data.asset_id,data.document_id].some(id=>id&&sourceIds.has(id))&&safeUrl(data.url)) urls.add(safeUrl(data.url));}
      for(const source of list(report?.p?.sources)) {const url=typeof source==='string'?source:source.url;if(safeUrl(url)) urls.add(safeUrl(url));}
      for(const raw of text(item.output).match(/https?:\/\/[^\s<>"'\]]+/g)||[]){const url=safeUrl(raw.replace(/[).,;]+$/g,''));if(url)urls.add(url);}
      const sources=block('Сохранённые ссылки'); for(const url of urls) sources.append(sourceLink(url)); if(!urls.size)sources.append(paragraph('URL не сохранены в доступной записи.','fl-muted')); detail.append(sources);
      detail.append(disclosure('Полный сохранённый текст',el('div',plain(item.output||body.claim),'fl-full-text')));
      if(typeof options.onSelectRun==='function'&&text(item.run_id)) detail.append(button('Открыть исследование ↗',()=>options.onSelectRun(item.run_id),'fl-button fl-button-paper'));
      detail.append(paragraph('Версия и статус взяты из записи. Сохранённый анализ не означает воспроизведение результата.','fl-note'));
    }
    input.addEventListener('input',()=>{query=input.value.trim().toLocaleLowerCase('ru');refresh();}); refresh();
  }

  function measurementRows(options,reports) {
    const inputs=[...list(options.workspace?.measurements)];
    for(const report of reports) inputs.push(...list(report.research?.measurements),...list(report.research?.measurement_assets));
    const entries=new Map(),conflicts=new Set();
    for(const input of inputs){
      const payload=object(input.payload||input),id=text(input.asset_id||input.id||payload.asset_id);
      if(!text(payload.run_id))continue;
      const key=id||[payload.run_id,payload.row_id,payload.side,payload.output_sha256].map(text).join('|');
      if(!id&&!text(payload.row_id))continue;
      const entry={...payload,asset_id:id};
      if(entries.has(key)&&canonical(entries.get(key))!==canonical(entry)){conflicts.add(key);continue;}
      entries.set(key,entry);
    }
    return [...entries].filter(([key])=>!conflicts.has(key)).map(([,row])=>row);
  }
  function canonical(value) {if(Array.isArray(value))return '['+value.map(canonical).join(',')+']';if(value&&typeof value==='object')return '{'+Object.keys(value).sort().map(key=>JSON.stringify(key)+':'+canonical(value[key])).join(',')+'}';return JSON.stringify(value);}
  function knownDimension(value) { return Boolean(text(value))&&!/^(?:unknown|not_reported|неизвест|не указан|не зафиксирован|null$|n\/a$|none$|—$|-$)/i.test(text(value)); }
  function sourceFor(row) {
    const urls=list(row.source_urls).map(safeUrl).filter(Boolean),ids=list(row.evidence_ids).map(text).filter(Boolean);
    if(urls.length!==1||!ids.length||new Set(ids).size!==ids.length)return null;
    const documents=list(row.source_documents).filter(document=>safeUrl(document.url)===urls[0]&&/^[a-f0-9]{64}$/.test(text(document.asset_id))&&/^[a-f0-9]{64}$/.test(text(document.sha256)));
    return documents.length===1?urls[0]:null;
  }
  function comparable(left,right) {
    if(!left||!right||left.run_id===right.run_id)return false;
    if([left,right].some(row=>row.version!=='measurement-v1'||row.origin!=='stored_source_analysis'||row.comparability!=='comparable'||!['author_claim','external_measurement'].includes(row.basis)||typeof row.value!=='number'||!Number.isFinite(row.value)||row.value<0||!sourceFor(row)))return false;
    return ['metric',...Object.keys(dimensionNames)].every(key=>knownDimension(left[key])&&knownDimension(right[key])&&left[key]===right[key]);
  }
  function reportedRows(report,registry) {
    const recorded=registry.filter(row=>row.run_id===report?.run?.id);
    if(recorded.length)return recorded;
    const rows=[];
    for(const row of list(report?.p?.applied_analysis?.rows))for(const side of ['baseline','candidate']){
      const item=object(row[side]);rows.push({...row,...object(row.measurement_context),run_id:report.run.id,side,label:item.label,value:item.value,basis:item.basis,source_urls:[],origin:'stored_source_analysis',display_only:true});
    }
    return rows;
  }
  function numeric(value) {return typeof value==='number'&&Number.isFinite(value)?new Intl.NumberFormat('ru-RU',{maximumSignificantDigits:8}).format(value):'Неизвестно';}

  function renderCompare({options,root,head,reports}) {
    head.append(el('p',reports.length+' доступных отчётов','fl-count'));
    if(reports.length<2){root.append(empty('Нужны два сохранённых отчёта','Сравнение появится после загрузки второго доступного исследования.'));return;}
    const registry=measurementRows(options,reports);
    let leftId=reports.some(row=>row.run.id===options.selectedRun?.id)?options.selectedRun.id:reports[0].run.id;
    let rightId=reports.find(row=>row.run.id!==leftId).run.id;
    const controls=el('div',undefined,'fl-compare-controls'),body=el('div',undefined,'fl-compare-body');
    function selector(label,side){const node=el('label',undefined,'fl-compare-select');const select=el('select');for(const report of reports){const option=el('option',titleFor(report.run,report.p));option.value=report.run.id;select.append(option);}select.value=side==='left'?leftId:rightId;select.addEventListener('change',()=>{if(side==='left')leftId=select.value;else rightId=select.value;refresh();});add(node,el('span',label,'fl-control-label'),select);return node;}
    add(controls,selector('Исследование A','left'),el('span','↔','fl-compare-arrow'),selector('Исследование B','right')); add(root,controls,body);
    function refresh(){
      const left=reports.find(row=>row.run.id===leftId),right=reports.find(row=>row.run.id===rightId);body.replaceChildren();
      if(leftId===rightId){body.append(empty('Выбрано одно исследование','Выберите другой отчёт во втором списке.'));return;}
      const passports=el('div',undefined,'fl-passports');
      for(const [report,letter]of [[left,'A'],[right,'B']]){
        const task=taskFor(report.run),rows=reportedRows(report,registry),single=key=>{const values=[...new Set(rows.map(row=>text(row[key])).filter(knownDimension))];return values.length?values.join(' / '):'';};
        const card=add(el('article',undefined,'fl-passport'),el('span','ИССЛЕДОВАНИЕ '+letter,'fl-eyebrow'),el('h3',titleFor(report.run,report.p)),badge('Сохранённый разбор источников'));
        card.append(dl([['Задача / сценарий',report.p.use_case||task.business_goal||task.title],['Baseline',baselineFor(task)],['Модель / версия',single('model_version')],['Данные',single('dataset')||task.dataset],['Метод оценки',single('evaluation')||task.evaluation],['Оборудование',single('hardware')||task.hardware],['Нагрузка',single('load')||task.load]]));
        card.append(disclosure('Вывод и следующий шаг',paragraph(report.p.public_takeaway||report.p.verdict),block('Следующий шаг',paragraph(report.p.next_step))));
        if(typeof options.onSelectRun==='function')card.append(button('Открыть исследование '+letter+' ↗',()=>options.onSelectRun(report.run.id),'fl-text-button'));passports.append(card);
      }
      body.append(passports);
      const leftRows=reportedRows(left,registry),rightRows=reportedRows(right,registry),pairs=[];
      for(const a of registry.filter(row=>row.run_id===leftId))for(const b of registry.filter(row=>row.run_id===rightId))if(comparable(a,b))pairs.push([a,b]);
      const measurements=el('section',undefined,'fl-comparison-section');measurements.append(add(el('div',undefined,'fl-section-head'),el('h3','Численные результаты'),badge(pairs.length?pairs.length+' сопоставимых пар':'Нет сопоставимых замеров',pairs.length?'recorded':'missing')));
      if(pairs.length){for(const [a,b]of pairs)measurements.append(pairChart(a,b));}
      else measurements.append(paragraph('Числа сравнимы только при одинаковых определении, единице, модели, данных, оценке, оборудовании и нагрузке.','fl-muted'));
      const reported=[...leftRows,...rightRows];
      if(reported.length){const numericTable=table(['Отчёт / вариант','Метрика','Значение','Единица','Основание'],'fl-numeric-table');for(const row of reported){const tr=el('tr');add(tr,el('td',(row.run_id===leftId?'A':'B')+' · '+(text(row.label)||row.side||unknown)),el('td',text(row.metric)||unknown),el('td',numeric(row.value),'fl-number'),el('td',text(row.unit)||unknown),add(el('td'),el('span',basisNames[row.basis]||text(row.basis)||unknown),sourceFor(row)?sourceLink(sourceFor(row),'Источник ↗'):el('span','Привязка источника неполна','fl-cell-note')));numericTable.body.append(tr);}measurements.append(disclosure('Все записанные значения · '+reported.length,tableWrap(numericTable.node,'Записанные численные значения')));}
      else measurements.append(el('p','Численные значения в структурированных записях отсутствуют.','fl-note'));
      body.append(measurements);
      const matrix=table(['Условие','Исследование A','Исследование B','Совпадение'],'fl-gate-matrix');
      for(const[key,label]of Object.entries(dimensionNames)){
        const values=rows=>[...new Set(rows.map(row=>text(row[key])).filter(knownDimension))];const a=values(leftRows),b=values(rightRows),known=a.length>0&&b.length>0,same=known&&a.length===1&&b.length===1&&a[0]===b[0];
        const tr=el('tr');add(tr,el('th',label),el('td',a.length?a.join(' / '):unknown),el('td',b.length?b.join(' / '):unknown),add(el('td'),badge(!known?'Неизвестно':same?'Совпадает':'Различается',!known?'missing':same?'recorded':'partial')));tr.firstChild.scope='row';matrix.body.append(tr);
      }
      const conditions=add(el('section',undefined,'fl-comparison-section'),add(el('div',undefined,'fl-section-head'),el('h3','Условия сопоставимости'),el('span','По измерительным записям','fl-muted')),tableWrap(matrix.node,'Матрица условий сопоставимости'));
      conditions.append(paragraph('Совпадение отдельных полей не устанавливает сопоставимость всей пары. Заявления авторов и внешние значения остаются результатами источников.','fl-note'));body.append(conditions);
      if(typeof options.onOpenValidation==='function')body.append(button('Посмотреть пробелы проверки →',options.onOpenValidation,'fl-button'));
    }
    refresh();
  }

  function pairChart(a,b){
    const chart=el('figure',undefined,'fl-pair-chart');chart.dataset.comparablePair='true';const max=Math.max(a.value,b.value);
    add(chart,el('figcaption',text(a.metric)+' · '+text(a.unit)),el('span','Значения источников · '+(a.direction==='minimize'?'меньше — лучше':a.direction==='maximize'?'больше — лучше':'описательная метрика'),'fl-cell-note'));
    for(const[row,label]of [[a,'A'],[b,'B']]){const line=el('div',undefined,'fl-pair-line'),track=el('div',undefined,'fl-pair-track'),bar=el('span',undefined,'fl-pair-bar');bar.style.width=(max>0?100*row.value/max:0)+'%';if(label==='B')bar.classList.add('fl-pair-bar-b');add(track,bar);add(line,el('span',label+' · '+text(row.label)),track,el('strong',numeric(row.value),'fl-number'),sourceLink(sourceFor(row),'Источник ↗'));chart.append(line);}
    chart.append(el('p','Шкала от 0 до '+numeric(max)+' '+text(a.unit)+'. Размер выборки: '+(text(a.sample_size)||'не указан')+' / '+(text(b.sample_size)||'не указан')+'. Проверка лаборатории этим не подтверждена.','fl-note'));return chart;
  }

  function renderValidation({options,root,head}) {
    const readiness=object(options.selectedResearch?.readiness);
    if(readiness.version!=='readiness-v1') {root.append(empty('Проверка ещё не загружена','Для этого исследования нет сохранённой сводки готовности.'));return;}
    const coverage=object(readiness.claim_coverage),provenance=object(readiness.provenance),external=object(readiness.external_results);
    head.append(badge(text(readiness.label)||text(readiness.stage)||'Статус не указан',readiness.state));
    const notice=add(el('div',undefined,'fl-validation-context'),el('strong',titleFor(options.selectedRun,options.selectedPresentation)),paragraph(readiness.notice,'fl-note'));root.append(notice);
    const evidenceCounts=el('div',undefined,'fl-evidence-counts');
    function countRows(title,rows){const card=add(el('section',undefined,'fl-count-card'),el('h3',title));for(const[label,value]of rows)add(card,add(el('div',undefined,'fl-count-row'),el('span',label),el('strong',typeof value==='number'&&Number.isFinite(value)?numeric(value):'—','fl-number')));return card;}
    add(evidenceCounts,countRows('Утверждения и источники',[['Выделено утверждений',coverage.total],['Связано с источниками',coverage.source_backed],['Без привязки к источнику',coverage.unbound],['Внешних пар результатов',external.reported_pairs]]),countRows('Записанные проверки',[['Испытаний технологии',provenance.executed_technology_tests],['API-кейсов в журнале',provenance.recorded_api_cases],['Импортированных наблюдений',provenance.imported_observations],['Симуляций',provenance.simulation_records]]));
    root.append(evidenceCounts);root.append(paragraph('API-кейс — запись вызова. Анализ источников, импорт наблюдений и симуляция сами по себе не подтверждают испытание технологии.','fl-note'));
    const gates=table(['Что требуется','Статус записи','Что отсутствует'],'fl-readiness-table');
    for(const[key,fallbackLabel]of Object.entries(gateNames)){
      const gate=object(readiness.gates?.[key]),tr=el('tr'),label=el('th',text(gate.label)||fallbackLabel);label.scope='row';
      const gaps=list(gate.missing_labels).map(text).filter(Boolean),missingCell=el('td');
      missingCell.append(el('span',gaps.length?gaps.join(' · '):gate.status==='recorded'?'Обязательные поля записаны':gate.status==='not_executed'?'Выполнение не зафиксировано':'Подробности не указаны'));
      if(text(gate.details))missingCell.append(disclosure('Подробности',paragraph(gate.details)));
      add(tr,label,add(el('td'),badge(statusNames[gate.status]||'Статус не указан',gate.status)),missingCell);gates.body.append(tr);
    }
    root.append(tableWrap(gates.node,'Готовность проверки по обязательным условиям'));
    const actions=list(readiness.next_actions);
    if(actions.length){const next=add(el('section',undefined,'fl-next-actions'),el('h3','Следующие шаги'));const ol=el('ol');for(const action of actions){const li=el('li');add(li,el('strong',text(action.action)||gateNames[action.gate]||'Уточнить данные'));ol.append(li);}next.append(ol);root.append(next);}
    const last=object(readiness.last_step);
    if(text(last.label))root.append(add(el('div',undefined,'fl-last-step'),badge(statusNames[last.status]||text(last.status)||'Статус не указан',last.status),paragraph(last.label),text(last.notice)?paragraph(last.notice,'fl-note'):null));
    root.append(disclosure('Пути дальнейшей проверки',dl([['Внешний кейс','Чужой сценарий и его условия; применимость к своей задаче проверяется отдельно.'],['Опубликованный benchmark','Внешние значения с методикой, версиями и источником. Это результаты авторов.'],['Контролируемый эксперимент','Отдельный протокол, общие условия и фактическое выполнение. Запуск здесь не выполняется.'],['Симуляция','Иллюстрация заданных предположений. Не реальное измерение технологии.']])));
    if(text(provenance.notice))root.append(paragraph('Авторские результаты, внешние замеры, импорт и симуляции учитываются раздельно. Для прикладного подтверждения нужен связанный журнал проверки.','fl-note'));
  }

  window.FrontierLibrary = Object.freeze({mount});
})();
