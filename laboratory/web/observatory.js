/* Read-only evidence Observatory. Relations describe saved records, never scientific truth. */
(() => {
  'use strict';
  const mounted = new WeakMap(), selections = new Map();
  let serial = 0;
  const object = value => value && typeof value === 'object' && !Array.isArray(value) ? value : {};
  const array = value => Array.isArray(value) ? value : [];
  const text = value => typeof value === 'string' ? value : '';
  const nonempty = value => text(value).trim().length > 0;
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  function element(tag, className, value) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value !== undefined) node.textContent = value;
    return node;
  }
  function svgElement(tag, attributes = {}, value) {
    const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
    Object.entries(attributes).forEach(([key, item]) => node.setAttribute(key, String(item)));
    if (value !== undefined) node.textContent = value;
    return node;
  }
  function button(label, action, className = 'fo-button') {
    const node = element('button', className, label);
    node.type = 'button'; node.addEventListener('click', action);
    return node;
  }
  function publicURL(value) {
    if (!nonempty(value) || /[\s\u0000-\u001f\u007f\\]/.test(value)) return '';
    try {
      const url = new URL(value);
      if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return '';
      const host = url.hostname.toLowerCase().replace(/^\[|\]$/g, '');
      if (host === 'localhost' || /\.(localhost|local|internal|lan)$/.test(host) || !host.includes('.')) return '';
      if (/^(0|10|127)\./.test(host) || /^169\.254\./.test(host) || /^192\.168\./.test(host) || /^172\.(1[6-9]|2\d|3[01])\./.test(host)) return '';
      if (url.port && !['80', '443'].includes(url.port)) return '';
      for (const key of url.searchParams.keys()) if (/token|secret|password|signature|credential|api.?key|auth|session/i.test(key)) return '';
      return value;
    } catch (_) { return ''; }
  }
  function appendLink(parent, label, value) {
    const url = publicURL(value);
    if (!url) { parent.append(element('p', 'fo-missing', label + ': публичный URL отсутствует или не разрешён.')); return; }
    const section = element('div', 'fo-link');
    section.append(element('span', 'fo-label', label));
    const link = element('a', '', url); link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer';
    section.append(link); parent.append(section);
  }
  function grouped(rows, key) {
    const result = new Map();
    rows.forEach(row => {
      const id = text(object(row)[key]);
      if (!id) return;
      if (!result.has(id)) result.set(id, []);
      result.get(id).push(row);
    });
    return result;
  }
  function model(options) {
    const run = object(options.run), data = object(options.presentation), context = object(options.context), quality = object(options.quality);
    const plan = object(run.plan), gate = object(data.agent_review);
    const planBundle = object(plan.evidence_bundle);
    const contextBundle = object(context.evidence_bundle || object(context.inputs).evidence_bundle || object(context.plan).evidence_bundle);
    const bundle = Array.isArray(planBundle.documents) ? planBundle : contextBundle;
    const documents = grouped(array(bundle.documents), 'asset_id');
    const assessment = object(data.source_validation || gate.source_validation);
    const checks = array(assessment.checks).map((row, index) => ({row: object(row), index}));
    const evidence = array(data.evidence), ids = grouped(evidence, 'id'), notices = [];
    const records = evidence.map((raw, index) => {
      const row = object(raw), id = text(row.id), duplicate = id && ids.get(id).length !== 1;
      const gaps = [];
      if (!id) gaps.push('У записи отсутствует evidence ID; привязка по позиции не выполняется.');
      if (duplicate) gaps.push('Evidence ID повторяется. Однозначная привязка не установлена.');
      if (!nonempty(row.claim)) gaps.push('Текст утверждения отсутствует.');
      if (!nonempty(row.excerpt)) gaps.push('Фрагмент основного отчёта отсутствует.');
      if (!publicURL(row.source_url)) gaps.push('Разрешённый публичный URL утверждения отсутствует.');
      const bindings = !id || duplicate ? [] : checks.filter(check => check.row.evidence_id === id).map(check => {
        const value = check.row, problems = [], candidates = documents.get(text(value.document_id)) || [];
        const document = candidates.length === 1 ? object(candidates[0]) : null;
        if (!document) problems.push(candidates.length ? 'Document ID не уникален.' : 'Документ с указанным ID отсутствует в пакете.');
        if (document && document.document_id !== undefined && document.document_id !== value.document_id) problems.push('Document ID и asset ID не совпадают.');
        const segments = document ? array(document.segments).filter(segment => object(segment).id === value.segment_id) : [];
        const segment = segments.length === 1 ? object(segments[0]) : null;
        if (!segment) problems.push(segments.length ? 'Segment ID не уникален.' : 'Указанный сегмент отсутствует.');
        if (document && !['captured', 'partial'].includes(document.status)) problems.push('Читаемый текст документа не зафиксирован.');
        if (!nonempty(value.quote)) problems.push('Цитата оригинала отсутствует.');
        if (segment && (!nonempty(value.quote) || !text(segment.text).includes(value.quote))) problems.push('Цитата не найдена дословно в указанном сегменте.');
        if (!publicURL(row.source_url) || !document || row.source_url !== document.url) problems.push('URL утверждения не совпадает с URL указанного документа.');
        if (value.literal_quote === false || value.source_bound === false) problems.push('Сохранённые флаги привязки отмечают несоответствие.');
        if (!['supports', 'contradicts', 'insufficient'].includes(value.relation)) gaps.push('Семантическая оценка модели для одной из привязок не записана.');
        if (['contradicts', 'insufficient'].includes(value.relation)) gaps.push('Есть модельная оценка ' + value.relation + '; это требует просмотра.');
        problems.forEach(problem => gaps.push(problem));
        return {row: value, index: check.index, document, segment, problems, linked: problems.length === 0};
      });
      if (!bindings.length) gaps.push('Нет однозначной записи привязки с этим evidence ID.');
      const findings = array(quality.findings).filter(finding => {
        const f = object(finding), pointer = text(f.evidence_pointer);
        if (pointer === '/presentation/evidence/' + index || pointer.startsWith('/presentation/evidence/' + index + '/')) return true;
        const match = pointer.match(/\/source_validation\/checks\/(\d+)(?:\/|$)/);
        if (match) return bindings.some(binding => binding.index === Number(match[1]));
        const numeric = pointer.match(/^\/presentation\/applied_analysis\/rows\/(\d+)\/(baseline|candidate)(?:\/|$)/);
        if (numeric) return array(object(object(array(object(data.applied_analysis).rows)[Number(numeric[1])])[numeric[2]]).evidence_ids).includes(id);
        return false;
      });
      findings.filter(f => object(f).status === 'needs_review').forEach(f => gaps.push(text(f.detail) || 'Для этой записи есть замечание аудита.'));
      const applied = array(object(data.applied_analysis).rows).filter(item => ['baseline', 'candidate'].some(side => array(object(object(item)[side]).evidence_ids).includes(id)));
      return {row, index, id, key: id && !duplicate ? 'id:' + id : 'row:' + index, bindings, findings, applied, gaps: [...new Set(gaps)], linked: bindings.some(binding => binding.linked)};
    });
    checks.forEach(check => {
      const matches = ids.get(text(check.row.evidence_id));
      if (!matches || matches.length !== 1) notices.push({label: 'Привязка без однозначного утверждения', id: text(check.row.evidence_id), document: text(check.row.document_id), segment: text(check.row.segment_id)});
    });
    if (Array.isArray(planBundle.documents) && Array.isArray(contextBundle.documents) && !same(planBundle, contextBundle)) notices.push({label: 'Пакет контекста отличается от плана. Связи показаны только по пакету плана.'});
    return {run, data, records, notices, assessment, quality};
  }
  function mount(host, options = {}) {
    if (!host || typeof host.replaceChildren !== 'function') throw new TypeError('Observatory needs a DOM host.');
    const previous = mounted.get(host); if (previous) previous.destroy();
    const info = model(options), runId = text(info.run.id), stored = runId ? selections.get(runId) : null;
    const state = {layer: stored?.layer || 'all', selected: stored?.id || '', binding: 0};
    const prefix = 'fo-' + (++serial), root = element('section', 'fo-root');
    root.setAttribute('aria-label', 'Обсерватория сохранённых оснований');
    host.replaceChildren(root);
    const header = element('header', 'fo-header'), headline = element('div');
    headline.append(element('p', 'fo-eyebrow', 'Обсерватория / связи сохранённой записи'), element('h2', 'fo-title', text(info.data.title) || text(object(info.run.plan).question) || 'Основания исследования'));
    const actions = element('nav', 'fo-actions'); actions.setAttribute('aria-label', 'Перейти к рабочему разделу');
    [['reactor', 'Реактор'], ['report', 'Полный отчёт'], ['plan', 'План'], ['memory', 'Память']].forEach(([name, label]) => {
      const control = button(label + ' ↗', () => { if (typeof options.onAction === 'function') options.onAction(name, runId); });
      control.disabled = !runId || typeof options.onAction !== 'function' || (name === 'report' && !nonempty(info.run.output));
      control.dataset.foAction = name; actions.append(control);
    });
    header.append(headline, actions); root.append(header);
    root.append(element('p', 'fo-scope', 'Показаны утверждения, цитаты и их связи по ID в сохранённой записи. Это не независимая проверка научной истинности.'));
    if (info.run.status !== 'completed' || !info.records.length) {
      const empty = element('div', 'fo-empty');
      empty.append(element('span', 'fo-empty-mark', '∅'), element('h3', '', info.run.status === 'completed' ? 'Реестр утверждений недоступен' : 'Сохранённый разбор ещё не завершён'));
      empty.append(element('p', '', info.run.status === 'completed' ? 'В этой записи нет структурированного presentation.evidence. Исторический текст не превращён в вымышленные привязки.' : 'Для незавершённого, прерванного или пустого запуска схема доказательств не строится. Частичный ответ можно посмотреть в отчёте, если он сохранён.'));
      if (info.notices.length) { empty.append(element('p', 'fo-missing', 'Сохранённых неоднозначных привязок: ' + info.notices.length + '. Они не присоединяются к другому утверждению.')); info.notices.forEach(item => { if (item.id) empty.append(element('code', 'fo-code', 'evidence_id: ' + item.id)); }); }
      root.append(empty);
      const controller = {destroy() { root.remove(); }}; mounted.set(host, controller); return controller;
    }
    const toolbar = element('div', 'fo-toolbar'), tabs = element('div', 'fo-tabs'); tabs.setAttribute('aria-label', 'Слой утверждений');
    const tabButtons = new Map();
    [['all', 'Все утверждения'], ['bound', 'Есть привязка'], ['gaps', 'Пробелы']].forEach(([key, label]) => {
      const control = button(label, () => { state.layer = key; state.binding = 0; render(); }, 'fo-tab');
      control.dataset.foLayer = key; tabs.append(control); tabButtons.set(key, control);
    });
    const pickerLabel = element('label', 'fo-picker', 'Утверждение');
    const picker = element('select'); picker.setAttribute('aria-label', 'Выбрать сохранённое утверждение');
    picker.addEventListener('change', () => { state.selected = picker.value; state.binding = 0; render(); }); pickerLabel.append(picker);
    toolbar.append(tabs, pickerLabel); root.append(toolbar);
    const workspace = element('div', 'fo-workspace'), map = element('div', 'fo-map'), sheet = element('aside', 'fo-sheet');
    sheet.setAttribute('aria-live', 'polite'); sheet.setAttribute('aria-label', 'Точные поля выбранного утверждения');
    const graphic = svgElement('svg', {class: 'fo-orbits', viewBox: '0 0 760 420', role: 'group', 'aria-label': 'Утверждение, фрагмент отчёта и привязка к оригиналу'});
    map.append(graphic, element('p', 'fo-map-note', 'Линии связывают поля записи. Связь с сегментом сплошная только при совпадении ID, URL и точной цитаты. Пунктир — пробел; смысловая оценка модели показана отдельно.'));
    workspace.append(map, sheet); root.append(workspace);
    const summary = element('p', 'fo-summary'); summary.setAttribute('role', 'status'); root.append(summary);
    if (info.notices.length) {
      const notices = element('details', 'fo-notices'); notices.append(element('summary', '', 'Неоднозначные и осиротевшие привязки: ' + info.notices.length));
      info.notices.forEach(notice => { const row = element('div', 'fo-notice'); row.append(element('p', '', notice.label)); if (notice.id) row.append(element('code', '', 'evidence_id: ' + notice.id)); if (notice.document) row.append(element('code', '', 'document_id: ' + notice.document)); if (notice.segment) row.append(element('code', '', 'segment_id: ' + notice.segment)); notices.append(row); });
      root.append(notices);
    }
    const globalFindings = array(info.quality.findings).filter(finding => !info.records.some(record => record.findings.includes(finding)));
    if (globalFindings.length) { const audit = element('details', 'fo-notices'); audit.append(element('summary', '', 'Общие находки аудита записи: ' + globalFindings.length)); globalFindings.forEach(finding => { const item = object(finding), node = element('div', 'fo-notice'); node.append(element('p', '', text(item.detail) || 'Описание не записано.'), element('code', '', text(item.id)), element('code', '', text(item.evidence_pointer))); audit.append(node); }); root.append(audit); }
    let observer, width = host.clientWidth;
    function visible() { return info.records.filter(record => state.layer === 'all' || (state.layer === 'bound' ? record.linked : record.gaps.length > 0)); }
    function save(record) { if (!runId) return; selections.set(runId, {id: record?.key || '', layer: state.layer}); if (selections.size > 50) selections.delete(selections.keys().next().value); }
    function openDetail(name) { const target = [...sheet.querySelectorAll('[data-fo-detail]')].find(node => node.dataset.foDetail === name); if (!target) return; if (target.tagName === 'DETAILS') target.open = true; const focus = target.querySelector('summary') || target; focus.focus({preventScroll: true}); target.scrollIntoView({block: 'nearest', behavior: 'auto'}); }
    function field(parent, label, value, className = 'fo-literal') { const block = element('div', 'fo-field'); block.append(element('h4', 'fo-label', label), element(nonempty(value) ? 'p' : 'span', nonempty(value) ? className : 'fo-missing', nonempty(value) ? value : 'Не записано.')); parent.append(block); return block; }
    function detail(name, title, open = false) { const node = element('details', 'fo-detail'); node.dataset.foDetail = name; node.open = open; node.append(element('summary', '', title)); sheet.append(node); return node; }
    function renderSheet(record, binding) {
      sheet.replaceChildren();
      const heading = element('div', 'fo-sheet-heading'); heading.append(element('p', 'fo-eyebrow', record.linked ? 'Есть сопоставленная привязка' : 'Привязка требует просмотра'), element('h3', '', record.id || 'Evidence ID отсутствует')); sheet.append(heading);
      const claim = field(sheet, 'Сохранённое утверждение', text(record.row.claim), 'fo-claim'); claim.dataset.foDetail = 'claim'; claim.tabIndex = -1;
      const excerpt = field(sheet, 'Фрагмент основного отчёта', text(record.row.excerpt)); excerpt.dataset.foDetail = 'excerpt'; excerpt.tabIndex = -1;
      appendLink(sheet, 'URL в записи утверждения', record.row.source_url);
      if (record.bindings.length > 1) { const label = element('label', 'fo-binding-picker', 'Запись привязки'); const select = element('select'); select.setAttribute('aria-label', 'Выбрать точную запись привязки'); record.bindings.forEach((item, index) => { const option = element('option', '', String(index + 1) + ' / ' + (text(item.row.segment_id) || 'без Segment ID')); option.value = String(index); select.append(option); }); select.value = String(state.binding); select.addEventListener('change', () => { state.binding = Number(select.value); render(); }); label.append(select); sheet.append(label); }
      const original = detail('binding', 'Цитата и проверка привязки', true);
      if (binding) {
        field(original, 'Цитата из сохранённой записи привязки', text(binding.row.quote));
        original.append(element('p', binding.linked ? 'fo-bound' : 'fo-missing', binding.linked ? 'Цитата найдена дословно в указанном сохранённом сегменте; URL совпадает.' : 'Связь с оригинальным сегментом не сопоставлена. Эта цитата не выдаётся за найденную в документе.'));
        field(original, 'evidence_id', text(binding.row.evidence_id), 'fo-code'); field(original, 'document_id', text(binding.row.document_id), 'fo-code'); field(original, 'segment_id', text(binding.row.segment_id), 'fo-code');
        if (nonempty(binding.row.relation)) field(original, 'Сохранённая семантическая оценка', text(binding.row.relation) + ' — оценка модели, не независимый научный вердикт.');
        if (nonempty(binding.row.reason)) field(original, 'Обоснование сохранённой оценки', binding.row.reason);
      } else original.append(element('p', 'fo-missing', 'Запись привязки с этим evidence ID отсутствует. Цитата оригинала и оценка модели не подставляются.'));
      const source = detail('source', 'Документ и точный сегмент');
      if (binding?.document) { field(source, 'Статус сохранённого документа', text(binding.document.status)); appendLink(source, 'URL указанного документа', binding.document.url); if (binding.segment) { field(source, 'Место в документе', text(binding.segment.locator)); field(source, 'Полный сохранённый текст сегмента', text(binding.segment.text)); } else source.append(element('p', 'fo-missing', 'Сегмент с этим ID недоступен.')); }
      else source.append(element('p', 'fo-missing', 'Указанный документ не найден однозначно; источник не восстанавливается по позиции или соседней записи.'));
      if (record.applied.length) { const applied = detail('applied', 'Сравнительные строки с этим evidence ID'); record.applied.forEach(row => { field(applied, 'Показатель', text(row.metric)); field(applied, 'Определение', text(row.definition)); field(applied, 'Единица', text(row.unit)); field(applied, 'Условия', text(row.conditions)); field(applied, 'Сохранённая сопоставимость', text(row.comparability)); field(applied, 'Причина', text(row.comparability_reason)); }); }
      if (record.gaps.length) { const gaps = detail('gaps', 'Пробелы и замечания: ' + record.gaps.length, true); const list = element('ul', 'fo-gap-list'); record.gaps.forEach(gap => list.append(element('li', '', gap))); gaps.append(list); }
      if (record.findings.length) { const audit = detail('audit', 'Связанные находки аудита'); record.findings.forEach(finding => { const row = object(finding); field(audit, text(row.id) || 'Находка', text(row.detail)); field(audit, 'Указатель записи', text(row.evidence_pointer), 'fo-code'); }); }
    }
    function draw(record, binding) {
      const mobile = width < 680, w = mobile ? 360 : 760, h = 420;
      const at = mobile ? {claim:[180,200], excerpt:[65,75], binding:[292,85], source:[280,325]} : {claim:[280,223], excerpt:[126,95], binding:[507,117], source:[571,328]};
      graphic.replaceChildren(); graphic.setAttribute('viewBox', `0 0 ${w} ${h}`);
      const center = at.claim, radius = mobile ? 121 : 167;
      graphic.append(svgElement('circle', {class:'fo-orbit',cx:center[0],cy:center[1],r:radius}), svgElement('circle', {class:'fo-orbit fo-orbit-dashed',cx:center[0],cy:center[1],r:radius+38}));
      function edge(a,b,valid) { const aa=at[a],bb=at[b]; graphic.append(svgElement('path',{class:'fo-edge'+(valid?'':' fo-edge-gap'),d:`M${aa[0]} ${aa[1]} Q${center[0]} ${center[1]} ${bb[0]} ${bb[1]}`})); }
      if (nonempty(record.row.excerpt)) edge('claim','excerpt',true);
      if (binding && nonempty(binding.row.quote)) edge('claim','binding',binding.linked);
      if (binding?.linked) edge('binding','source',true); else edge('claim','source',false);
      const definitions = [{key:'claim',label:'Утверждение',sub:record.id || 'ID не записан',mark:'◎',core:true,exists:true}, {key:'excerpt',label:'Фрагмент отчёта',sub:nonempty(record.row.excerpt)?'Сохранён в записи':'Не записан',mark:'≡',exists:nonempty(record.row.excerpt)}, {key:'binding',label:'Цитата оригинала',sub:binding&&nonempty(binding.row.quote)?'Запись привязки':'Не записана',mark:'❞',exists:Boolean(binding&&nonempty(binding.row.quote))}, {key:'source',label:binding?.linked?'Источник / сегмент':'Пробел привязки',sub:binding?.linked?text(binding.row.segment_id):'Требует просмотра',mark:binding?.linked?'↗':'?',exists:Boolean(binding?.linked)}];
      definitions.forEach(node => { const [x,y]=at[node.key],r=node.core?(mobile?57:70):22; const group=svgElement('g',{class:'fo-object'+(node.core?' fo-core':'')+(node.exists?'':' fo-object-missing'),role:'button',tabindex:'0','data-fo-object':node.key,'aria-label':node.label+'. '+node.sub}); group.append(svgElement('circle',{class:'fo-hit',cx:x,cy:y,r:Math.max(r,25)}),svgElement('circle',{class:'fo-node',cx:x,cy:y,r}));
        if(node.core){group.append(svgElement('text',{x,y:y-7,class:'fo-core-label','text-anchor':'middle'},'Утверждение')); const label=node.sub.length>16?node.sub.slice(0,15)+'…':node.sub; group.append(svgElement('text',{x,y:y+18,class:'fo-core-id','text-anchor':'middle'},label));}
        else { group.append(svgElement('text',{x,y:y+7,class:'fo-node-mark','text-anchor':'middle'},node.mark)); const anchor=mobile?(x>w/2?'end':'start'):'middle',labelX=mobile?(x>w/2?w-16:16):x; group.append(svgElement('text',{x:labelX,y:y+43,class:'fo-node-label','text-anchor':anchor},node.label)); group.append(svgElement('text',{x:labelX,y:y+61,class:'fo-node-sub','text-anchor':anchor},node.sub.length>27?node.sub.slice(0,26)+'…':node.sub)); }
        group.addEventListener('click',()=>openDetail(node.key)); group.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();openDetail(node.key);}}); graphic.append(group);
      });
      graphic.setAttribute('aria-label', 'Утверждение '+record.id+'. '+(binding?.linked?'Есть точная связь с указанным документом и сегментом.':'Точная связь с источником не установлена.'));
    }
    function render() {
      const list = visible();
      if (!list.some(row => row.key === state.selected)) state.selected = list[0]?.key || '';
      const record = list.find(row => row.key === state.selected);
      tabButtons.forEach((control, key) => control.setAttribute('aria-pressed', String(state.layer === key)));
      picker.replaceChildren(); list.forEach(row => { const option = element('option', '', (row.id || 'Без ID')+' · '+(text(row.row.claim)||'Текст утверждения отсутствует')); option.value = row.key; picker.append(option); }); picker.value = state.selected; picker.disabled = !record;
      const linkedCount = info.records.filter(row => row.linked).length, gapCount = info.records.filter(row => row.gaps.length).length;
      summary.textContent = `Записей утверждений: ${info.records.length}. Есть сопоставленная привязка: ${linkedCount}. Записей с пробелами: ${gapCount}. Это количество записей, не оценка качества науки.`;
      if (!record) { graphic.replaceChildren(); sheet.replaceChildren(element('h3','','В этом слое нет записей'),element('p','fo-missing','Отсутствие записей не означает подтверждение научной истинности.')); save(null); return; }
      if (state.binding >= record.bindings.length) state.binding = 0;
      const binding = record.bindings[state.binding]; renderSheet(record,binding); draw(record,binding); save(record);
    }
    if (typeof ResizeObserver === 'function') { observer = new ResizeObserver(entries => { const next = entries[0]?.contentRect.width || host.clientWidth; const changed = (width < 680) !== (next < 680); width = next; if (changed) { const record=visible().find(row=>row.key===state.selected); if(record) draw(record,record.bindings[state.binding]); } }); observer.observe(host); }
    render();
    const controller = {destroy() { if(observer) observer.disconnect(); root.remove(); }};
    mounted.set(host, controller); return controller;
  }
  window.FrontierObservatory = {mount};
})();
