/* Read-only research brief. Data, navigation and actions belong to the owner app. */
(() => {
  'use strict';
  const instances = new WeakMap(), active = new Set(), SVG = 'http://www.w3.org/2000/svg';
  const list = value => Array.isArray(value) ? value : [];
  const obj = value => value && typeof value === 'object' && !Array.isArray(value) ? value : {};
  const str = value => typeof value === 'string' ? value.replace(/\s+/g, ' ').trim() : '';
  const finite = value => typeof value === 'number' && Number.isFinite(value);
  const placeholder = value => !str(value) || /^(не определено(?: в отч[её]те)?|не установлено в отч[её]те|нужно уточнить|уточнить|нет данных|неизвестно)([.;:]|$)/i.test(str(value));
  const meaningful = values => list(values).map(value => typeof value === 'string' ? str(value) : str(value?.text)).filter(value => !placeholder(value));
  const clip = (value, limit = 90) => {
    const full = str(value);
    if (full.length <= limit) return full;
    const sentence = full.match(/^.*?[.!?](?:\s|$)/)?.[0]?.trim();
    if (sentence && sentence.length <= limit) return sentence;
    // Keep an uncertainty qualifier visible instead of cutting immediately after "не".
    const qualifier = sentence?.match(/(?:^|\s)(не (?:установлен[аоы]?|подтвержд[её]н[аоы]?|проверен[аоы]?)[.!?]?)$/i)?.[1];
    if (qualifier) {
      const head = full.slice(0,Math.max(15,limit - qualifier.length - 3));
      return head.slice(0,Math.max(0,head.lastIndexOf(' '))).replace(/[ ,;:]+$/, '') + '… ' + qualifier;
    }
    const cut = full.slice(0, limit - 1), end = cut.lastIndexOf(' ');
    return cut.slice(0, end > limit * .55 ? end : undefined).replace(/[ ,;:]+$/, '') + '…';
  };
  const el = (tag, cls, value) => { const node = document.createElement(tag); if (cls) node.className = cls; if (value !== undefined) node.textContent = value; return node; };
  const append = (node, ...children) => { for (const child of children.flat()) if (child) node.append(child); return node; };
  const svg = (tag, attributes = {}) => { const node = document.createElementNS(SVG, tag); for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value)); return node; };
  const safeURL = value => { try { const url = new URL(str(value)); return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? url.href : null; } catch { return null; } };
  const runTitle = run => str(run?.plan?.study_context?.task?.title) || str(run?.plan?.sources?.[0]?.title) || str(run?.title) || str(run?.plan?.question) || 'Исследование без названия';
  const basisNames = {author_claim:'Заявлено авторами',external_measurement:'Внешний замер',estimate:'Оценка',hypothesis:'Гипотеза',unknown:'Основание неизвестно',saved_report:'Сохранённый отчёт',supplied_text:'Переданный пересказ'};
  const roleNames = {input:'Вход',compute:'Обработка',decision:'Выбор',memory:'Память',output:'Выход',data:'Данные'};
  const stageNames = {source_review:'Разбор источников',incomplete:'Данных недостаточно',validation_designed:'Проверка спроектирована',externally_evaluated:'Есть внешние сравнения',locally_evaluated:'Есть локальные результаты'};
  let serial = 0;

  function visualSpec(value, runId) {
    const spec = obj(value), blocks = list(spec.blocks), kinds = new Set(['task_context','process_flow','comparison_bars','comparison_table','applicability','evidence_ledger']);
    if (spec.version !== 'visual-spec-v1' || spec.subject?.type !== 'run' || spec.subject.id !== runId || spec.input_binding?.run_id !== runId || !blocks.length || blocks.length > 24 || new Set(blocks.map(block => block?.id)).size !== blocks.length) return null;
    if (blocks.some(block => !str(block?.id) || !kinds.has(block.kind) || typeof block.selected !== 'boolean' || typeof block.available !== 'boolean')) return null;
    const primary = blocks.find(block => block.id === spec.primary_block_id && block.selected && block.available);
    if (!primary || !['task_context','process_flow','comparison_bars'].includes(primary.kind)) return null;
    return {...spec,primary,block:kind => blocks.find(block => block.kind === kind && block.selected && block.available)};
  }

  function savedGraph(presentation) {
    const graph = obj(presentation.motion_story), ids = new Set();
    if (graph.version !== 'dataflow-v1' || !list(graph.nodes).length || graph.nodes.length > 12 || !Array.isArray(graph.edges) || graph.edges.length > 16) return null;
    for (const node of graph.nodes) {
      if (!str(node?.id) || ids.has(node.id) || !str(node.label) || !Object.hasOwn(roleNames, node.role) || !['technology','baseline'].includes(node.lane)) return null;
      ids.add(node.id);
    }
    if (graph.edges.some(edge => !ids.has(edge?.from) || !ids.has(edge?.to) || edge.from === edge.to || !['data','control','feedback'].includes(edge.kind))) return null;
    const nodes = graph.nodes.filter(node => node.lane === 'technology'), technologyIds = new Set(nodes.map(node => node.id));
    if (!nodes.length) return null;
    return {...graph, nodes, edges:graph.edges.filter(edge => technologyIds.has(edge.from) && technologyIds.has(edge.to))};
  }

  function eligibleMeasurements(research) {
    const dimensions = obj(research?.readiness?.comparison_dimensions), result = [];
    for (const key of ['quality','latency','cost']) {
      for (const value of list(dimensions[key]?.measurements)) {
        // The backend binds both values to archived evidence and a complete common context.
        // A row's own "comparable" declaration is deliberately insufficient.
        if (value?.chart_eligible !== true || value.source_bound_pair !== true || value.comparability !== 'comparable') continue;
        if (![value.baseline, value.candidate].every(side => finite(side?.value) && ['author_claim','external_measurement'].includes(side.basis) && str(side.label))) continue;
        result.push({...value, dimension:key, dimensionLabel:str(dimensions[key].label)});
        if (result.length === 3) return result;
      }
    }
    return result;
  }

  function specMeasurements(block) {
    // The server selects rows. These checks only protect the renderer from malformed data.
    return list(block?.data?.rows).filter(value => value?.chart_eligible === true && value.source_bound_pair === true && value.comparability === 'comparable' &&
      [value.baseline,value.candidate].every(side => finite(side?.value) && ['author_claim','external_measurement'].includes(side.basis) && str(side.label)))
      .slice(0,3).map(value => ({...value,dimensionLabel:str(value.label)}));
  }

  function mount(host, props = {}) {
    if (!host || typeof host.replaceChildren !== 'function') return null;
    const prior = instances.get(host), previous = prior?.snapshot();
    prior?.destroy();
    const data = obj(props), run = obj(data.run), p = obj(data.presentation), research = obj(data.research), quality = obj(data.quality);
    const runId = str(run.id) || null, same = previous?.runId === runId;
    const state = {alive:true, selected:same ? previous.selected : null, open:new Set(same ? previous.open : []), raf:null, playing:false};
    const abort = new AbortController(), on = (node, event, fn) => node.addEventListener(event, fn, {signal:abort.signal});
    const prefix = 'fbrief-' + (++serial), root = el('section','fbrief'), headingId = prefix + '-title';
    root.dataset.briefRoot = runId || 'empty';
    root.setAttribute('aria-labelledby', headingId);
    const focusKey = same ? previous.focus : null;
    const message = el('p','fbrief-message'); message.setAttribute('role','status'); message.setAttribute('aria-live','polite');
    const act = name => {
      if (typeof data.onAction !== 'function') return;
      try { Promise.resolve(data.onAction(name, runId)).catch(() => { message.textContent = 'Не удалось открыть раздел. Попробуйте ещё раз.'; }); }
      catch { message.textContent = 'Не удалось открыть раздел. Попробуйте ещё раз.'; }
    };
    const button = (label, key, callback, cls = '') => {
      const node = el('button','fbrief-button ' + cls,label); node.type = 'button'; node.dataset.fbriefControl = key;
      if (callback) on(node,'click',callback); return node;
    };
    const action = (label, name, cls = '') => button(label,'action-' + name,() => act(name),cls);
    const details = (key, label, children, cls = '') => {
      const node = el('details','fbrief-details ' + cls); node.dataset.fbriefDetail = key; node.dataset.briefDetail = key; node.open = state.open.has(key);
      const summary = el('summary','',label); summary.dataset.fbriefControl = 'detail-' + key;
      append(node,summary,append(el('div','fbrief-detail-body'),children));
      on(node,'toggle',() => { if (node.open) state.open.add(key); else state.open.delete(key); }); return node;
    };
    const paragraphs = values => meaningful(values).map(value => el('p','',value));
    const link = (value, label) => {
      const url = safeURL(value); if (!url) return null;
      const node = el('a','fbrief-source-link',label || new URL(url).hostname); node.href = url; node.target = '_blank'; node.rel = 'noopener noreferrer'; return node;
    };

    const toolbar = el('div','fbrief-toolbar'), identity = el('div','fbrief-eyebrow','VV FRONTIER / СУТЬ');
    const select = el('select','fbrief-select'); select.setAttribute('aria-label','Выбрать исследование'); select.dataset.fbriefControl = 'run-select';
    const runs = list(data.runs).filter(item => str(item?.id));
    if (runId && !runs.some(item => item.id === runId)) runs.unshift(run);
    if (runs.length) for (const item of runs) { const option = el('option','',clip(item.id === runId && str(p.title) ? p.title : runTitle(item),100)); option.value = item.id; select.append(option); }
    else { const option = el('option','','Нет сохранённых исследований'); option.value = ''; select.append(option); select.disabled = true; }
    select.value = runId || ''; on(select,'change',() => {
      if (!select.value || typeof data.onSelectRun !== 'function') return;
      try { Promise.resolve(data.onSelectRun(select.value)).catch(() => { message.textContent = 'Не удалось открыть исследование.'; }); }
      catch { message.textContent = 'Не удалось открыть исследование.'; }
    });
    append(toolbar,identity,select,action('Полный отчёт ↗','report','fbrief-button-dark'));
    root.append(toolbar);

    const hasContent = Boolean(str(p.title) || str(p.problem) || str(p.summary));
    if (!hasContent) {
      const empty = el('div','fbrief-empty'), title = el('h2','','Исследование ещё не собрано'); title.id = headingId;
      append(empty,el('span','fbrief-eyebrow','СНАЧАЛА МАТЕРИАЛ'),title,el('p','','Здесь появятся задача, механизм, сравнение и основания готового разбора.'),action('Открыть входящие','inbox','fbrief-button-dark'),action('Посмотреть план','plan'));
      append(root,empty,message); host.replaceChildren(root);
      const instance = {snapshot:() => ({runId,open:[],selected:null,focus:null}),pause:() => {},destroy:() => { abort.abort(); root.remove(); instances.delete(host); active.delete(instance); }};
      instances.set(host,instance); active.add(instance); return instance;
    }

    const sources = list(research.sources), readiness = obj(research.readiness), provenance = obj(readiness.provenance);
    const fetched = sources.filter(source => source?.origin === 'fetched' && source.status === 'captured' && list(source.segments).length);
    const supplied = sources.some(source => source?.kind === 'supplied_text' && source.status === 'captured');
    const sourceLabel = fetched.length ? 'Сохранённый источник' : supplied ? 'Переданный пересказ' : 'Основание не подтверждено';
    let visual = visualSpec(research.visual_spec, runId);
    let graph = visual ? savedGraph({motion_story:visual.block('process_flow')?.data?.graph}) : savedGraph(p);
    let measurements = visual ? specMeasurements(visual.block('comparison_bars')) : eligibleMeasurements(research);
    if (visual && ((visual.primary.kind === 'process_flow' && !graph) || (visual.primary.kind === 'comparison_bars' && !measurements.length))) {
      visual = null; graph = savedGraph(p); measurements = eligibleMeasurements(research);
    }
    const primaryKind = visual?.primary.kind || (measurements.length ? 'comparison_bars' : graph ? 'process_flow' : 'task_context');
    root.dataset.briefVisualSpec = visual?.version || 'fallback'; root.dataset.briefVisualKind = primaryKind;
    const tests = finite(provenance.executed_technology_tests) ? provenance.executed_technology_tests : null;
    const hero = el('header','fbrief-hero'), lead = el('div','fbrief-lead'), title = el('h2','fbrief-title',str(p.title) || runTitle(run)); title.id = headingId;
    append(lead,el('div','fbrief-kicker','СТАТЬЯ → ЗАДАЧА → ПРОВЕРКА'),title);
    const problem = str(p.problem) || str(p.summary);
    append(lead,el('p','fbrief-problem',clip(problem,175)));
    if (problem.length > 175) lead.append(details('problem','Задача полностью',[el('p','',problem)]));
    const proof = el('div','fbrief-proof');
    append(proof,el('span','fbrief-status',stageNames[readiness.stage] || stageNames[readiness.state] || 'Сохранённый разбор'),el('strong','',sourceLabel),el('span','',tests === 0 ? 'Нет испытаний' : tests === null ? 'Испытания не подтверждены' : 'Испытаний: ' + tests));
    proof.append(action('Основания ↗','evidence'));
    append(hero,lead,proof); root.append(hero);

    const grid = el('div','fbrief-main-grid'), mechanism = el('article','fbrief-mechanism fbrief-panel');
    const sectionTitle = (number, title, suffix) => append(el('div','fbrief-section-heading'),el('span','fbrief-section-number',number),el('h3','',title),suffix ? el('span','fbrief-section-note',suffix) : null);
    mechanism.append(sectionTitle(primaryKind === 'comparison_bars' ? '02' : '01','Как это устроено','Сохранённая схема'));
    const diagram = el('div','fbrief-diagram'), graphButtons = new Map(), pathList = [];
    mechanism.dataset.briefMechanism = graph ? graph.version : 'unavailable';
    let wireSVG = null, packet = null, resizeObserver = null, infographic = null;
    const infographicHost = el('div','fbrief-infographic-stage'); infographicHost.dataset.state = 'pending';
    const rendererStatus = el('p','fbrief-renderer-status'), rendererExplanation = el('p','');
    mechanism.dataset.briefRenderer = 'native_dom_svg';
    const reportRenderer = ({renderer,reason = ''}) => {
      if (!state.alive) return;
      mechanism.dataset.briefRenderer = renderer;
      const enhanced = renderer === 'antv_infographic';
      const focusedNode = diagram.contains(document.activeElement) ? document.activeElement?.dataset?.fbriefNode : null;
      diagram.hidden = enhanced; trace.hidden = enhanced;
      infographicHost.hidden = !enhanced && infographicHost.dataset.state === 'fallback';
      rendererStatus.textContent = enhanced ? 'Выберите шаг, чтобы открыть сохранённое основание.' : reason;
      rendererStatus.hidden = !rendererStatus.textContent;
      rendererExplanation.textContent = enhanced ? 'Схема построена локально AntV Infographic 0.2.20: последовательность сохранённых операций. Каждый узел ведёт к своему основанию; это иллюстрация механизма, не испытание.' : 'Схема: встроенный HTML/SVG. ' + reason;
      if (enhanced && focusedNode) [...infographicHost.querySelectorAll('[data-fbrief-node]')].find(node => node.dataset.fbriefNode === focusedNode)?.focus({preventScroll:true});
    };
    const nodeDetail = el('div','fbrief-node-detail'); nodeDetail.setAttribute('aria-live','polite');
    const graphEvidence = graph ? list(graph.evidence) : [];
    const showNode = id => {
      state.selected = id;
      for (const [key,node] of graphButtons) { node.classList.toggle('is-selected',key === id); node.setAttribute('aria-pressed',String(key === id)); }
      infographic?.select(id);
      const node = graph?.nodes.find(item => item.id === id); nodeDetail.replaceChildren(); if (!node) return;
      const evidenceIds = new Set(list(node.evidence_ids));
      const evidence = graphEvidence.filter(item => evidenceIds.has(item.id));
      const body = [el('p','fbrief-node-full',str(node.label)),el('p','','Это фрагмент сохранённого описания механизма, не подтверждение результата.')];
      for (const item of evidence) body.push(el('blockquote','',str(item.excerpt) || 'Точная цитата не сохранена.'),el('p','fbrief-muted',basisNames[item.basis] || 'Основание: ' + (str(item.basis) || 'неизвестно')),link(item.source_url,'Указанный источник ↗'));
      if (!evidence.length) body.push(el('p','','Привязанная цитата для этого узла не сохранена.'));
      nodeDetail.append(details('node-' + id,'Основание шага',body));
    };
    const openNode = id => {
      state.open.add('node-' + id); showNode(id);
      const detail = nodeDetail.querySelector('details'); if (detail) detail.open = true;
    };
    const stop = () => { if (state.raf !== null) cancelAnimationFrame(state.raf); state.raf = null; state.playing = false; if (packet) packet.setAttribute('visibility','hidden'); };
    const trace = button('Проследить связи →','trace',() => {
      stop(); if (!pathList.length) return;
      if (globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches) { message.textContent = 'Связи показаны стрелками. Движение отключено настройкой уменьшения анимации.'; return; }
      let index = 0, began = performance.now(); state.playing = true; packet.setAttribute('visibility','visible');
      const frame = now => {
        if (!state.alive || !state.playing) return;
        const path = pathList[index], progress = Math.min(1,(now - began) / 850), point = path.getPointAtLength(path.getTotalLength() * progress);
        packet.setAttribute('cx',String(point.x)); packet.setAttribute('cy',String(point.y));
        if (progress === 1) { index += 1; began = now; if (index >= pathList.length) { stop(); return; } }
        state.raf = requestAnimationFrame(frame);
      }; state.raf = requestAnimationFrame(frame);
    });
    if (graph) {
      diagram.style.setProperty('--fbrief-nodes',String(Math.min(4,graph.nodes.length)));
      wireSVG = svg('svg',{'class':'fbrief-wires','aria-hidden':'true',focusable:'false'});
      const markerId = prefix + '-arrow', defs = svg('defs'), marker = svg('marker',{id:markerId,viewBox:'0 0 10 10',refX:8,refY:5,markerWidth:6,markerHeight:6,orient:'auto-start-reverse'});
      marker.append(svg('path',{d:'M 0 1 L 8 5 L 0 9',fill:'none',stroke:'currentColor','stroke-width':1.5})); defs.append(marker); wireSVG.append(defs); diagram.append(wireSVG);
      for (const [index,node] of graph.nodes.entries()) {
        const b = button('','node-' + node.id,() => openNode(node.id),'fbrief-node'); b.dataset.fbriefNode = node.id;
        b.setAttribute('aria-label','Шаг ' + (index + 1) + ': ' + str(node.label));
        append(b,append(el('span','fbrief-node-top'),el('span','fbrief-node-index',String(index + 1).padStart(2,'0')),el('span','fbrief-node-role',roleNames[node.role])),el('span','fbrief-node-label',clip(node.label,85)),el('span','fbrief-node-open','Основание ↗'));
        graphButtons.set(node.id,b); diagram.append(b);
      }
      packet = svg('circle',{r:4,'class':'fbrief-packet',visibility:'hidden'}); wireSVG.append(packet);
      const drawWires = () => {
        stop(); for (const path of pathList) path.remove(); pathList.length = 0;
        const box = diagram.getBoundingClientRect(); if (!box.width || !box.height) return;
        wireSVG.setAttribute('viewBox','0 0 ' + box.width + ' ' + box.height);
        for (const edge of graph.edges) {
          const a = graphButtons.get(edge.from).getBoundingClientRect(), b = graphButtons.get(edge.to).getBoundingClientRect();
          const vertical = Math.abs(a.top - b.top) > a.height * .5;
          const start = vertical ? [a.left + a.width / 2 - box.left,a.bottom - box.top] : [a.right - box.left,a.top + a.height / 2 - box.top];
          const end = vertical ? [b.left + b.width / 2 - box.left,b.top - box.top - 5] : [b.left - box.left - 5,b.top + b.height / 2 - box.top];
          const bend = vertical ? (start[1] + end[1]) / 2 : (start[0] + end[0]) / 2;
          const d = vertical ? `M${start} C${start[0]},${bend} ${end[0]},${bend} ${end}` : `M${start} C${bend},${start[1]} ${bend},${end[1]} ${end}`;
          const path = svg('path',{d,'class':'fbrief-wire' + (edge.kind === 'feedback' ? ' is-feedback' : ''),'marker-end':'url(#' + markerId + ')'});
          const title = svg('title'); title.textContent = str(edge.label) || (edge.kind === 'feedback' ? 'Обратная связь' : 'Сохранённая связь'); path.append(title); wireSVG.insertBefore(path,packet); pathList.push(path);
        }
      };
      append(mechanism,infographicHost,diagram,append(el('div','fbrief-mechanism-caption'),el('span','',graph.kind === 'process' ? 'Порядок операций · иллюстрация, не замер эффекта' : 'Связи из описания · иллюстрация, не замер'),graph.edges.length ? trace : null),rendererStatus,nodeDetail);
      mechanism.append(details('mechanism-notes','Границы схемы',paragraphs([...(list(graph.notes)),str(graph.selection?.reason)])));
      state.selected = graph.nodes.some(node => node.id === state.selected) ? state.selected : graph.nodes[0].id; showNode(state.selected);
      if (globalThis.ResizeObserver) { resizeObserver = new ResizeObserver(drawWires); resizeObserver.observe(diagram); }
      on(globalThis,'resize',drawWires);
      // Layout becomes measurable only after the host is attached below.
      state.drawWires = drawWires;
      const flowBlock = visual?.block('process_flow');
      state.mountInfographic = () => {
        if (flowBlock?.supported_renderer === 'antv_infographic' && globalThis.FrontierInfographic?.mount) {
          infographic = globalThis.FrontierInfographic.mount(infographicHost,{graph,selected:state.selected,onSelect:openNode,onStatus:reportRenderer,focusNodeId:focusKey?.startsWith('node-') ? focusKey.slice(5) : null});
        } else {
          infographicHost.dataset.state = 'fallback';
          reportRenderer({renderer:'native_dom_svg',reason:flowBlock?.supported_renderer === 'antv_infographic' ? 'Движок схемы не загрузился. Показан сохранённый граф.' : str(flowBlock?.renderer_fallback_reason) || 'Для сохранённых связей выбран встроенный граф.'});
        }
      };
    } else {
      append(mechanism,el('div','fbrief-unknown-mechanism','Механизм не восстановлен'),el('p','fbrief-muted','В сохранённом разборе нет схемы технологии с подтверждёнными связями.'),action('Открыть полный разбор','report'));
    }

    const comparison = el('article','fbrief-comparison fbrief-panel'); comparison.append(sectionTitle(primaryKind === 'comparison_bars' ? '01' : '02','Что меняется','Baseline → технология'));
    if (measurements.length) {
      for (const [index,m] of measurements.entries()) {
        const card = el('div','fbrief-metric'), min = Math.min(0,m.baseline.value,m.candidate.value), max = Math.max(0,m.baseline.value,m.candidate.value), range = max - min || 1;
        card.dataset.briefMetric = m.dimension; card.dataset.briefChart = str(m.row_id) || String(index);
        append(card,el('h4','',str(m.definition) || str(m.metric) || m.dimensionLabel));
        for (const [side,cls] of [[m.baseline,'baseline'],[m.candidate,'candidate']]) {
          const row = el('div','fbrief-bar-row'), track = el('div','fbrief-bar-track'), bar = el('span','fbrief-bar ' + cls);
          const start = (Math.min(0,side.value) - min) / range * 100, width = Math.abs(side.value) / range * 100;
          bar.style.left = start + '%'; bar.style.width = width + '%'; track.setAttribute('aria-hidden','true'); track.append(bar);
          append(row,el('span','fbrief-bar-label',clip(side.label,48)),el('strong','fbrief-bar-value',side.value.toLocaleString('ru-RU',{maximumFractionDigits:5}) + (str(m.unit) ? ' ' + str(m.unit) : '')),track); card.append(row);
        }
        const conditions = [str(m.conditions),...Object.entries(obj(m.measurement_context)).filter(([,value]) => str(value)).map(([key,value]) => key + ': ' + str(value))];
        append(card,el('p','fbrief-measurement-note','Сообщено источником · независимо не воспроизведено'),details('metric-' + (m.row_id || index),'Условия и происхождение',paragraphs([str(m.definition),...conditions,'Baseline: ' + (basisNames[m.baseline.basis] || m.baseline.basis),'Технология: ' + (basisNames[m.candidate.basis] || m.candidate.basis)]))); comparison.append(card);
      }
    } else {
      append(comparison,el('strong','fbrief-no-comparison','Численного сравнения нет'));
      const unknowns = el('ul','fbrief-unknown-list');
      for (const key of ['quality','latency','cost']) { const value = obj(readiness.comparison_dimensions?.[key]), card = el('li','', (str(value.label) || ({quality:'Качество',latency:'Задержка',cost:'Стоимость'}[key])) + ': сопоставимый результат не установлен.'); card.dataset.briefMetric = key; card.dataset.briefUnknown = 'true'; unknowns.append(card); }
      comparison.append(unknowns);
    }
    const baseline = obj(p.motion_story?.baseline), baselineKnown = ['reported','conceptual'].includes(baseline.status) && !placeholder(baseline.label);
    const baselineText = baselineKnown ? str(baseline.label) : 'Baseline не установлен';
    const conditionsRecorded = readiness.gates?.conditions?.status === 'recorded';
    append(comparison,append(el('div','fbrief-comparison-foot'),el('span','',baselineText),el('span','',conditionsRecorded ? 'Условия задачи записаны' : 'Общие условия не зафиксированы')));
    const comparisonDetails = [!measurements.length ? 'Нет пары значений с общими условиями и привязанными основаниями.' : '',str(baseline.note),str(p.use_case),...meaningful(p.applied_analysis?.unknowns)];
    comparison.append(details('comparison','С чем и при каких условиях сравнивать',paragraphs(comparisonDetails)));
    if (measurements.length) {
      if (primaryKind === 'comparison_bars') append(grid,comparison,graph ? mechanism : null);
      else append(grid,mechanism,comparison);
      if (!graph) grid.classList.add('fbrief-main-grid-single');
    } else { grid.append(mechanism); grid.classList.add('fbrief-main-grid-single'); }
    if (visual && primaryKind === 'task_context' && !graph && !measurements.length) grid.hidden = true;
    grid.dataset.briefPrimary = primaryKind; root.append(grid);
    const visualExplanation = [];
    if (visual) {
      const primary = visual.primary;
      visualExplanation.push(el('p','', 'Выбранный вид: ' + primary.kind + '. ' + str(primary.reason)),
        el('p','', 'Происхождение: ' + (str(primary.provenance?.origin) || 'не указано') + '.'),
        el('p','', 'Вид выбран по сохранённым данным и доступным основаниям. Новые исследования и испытания для визуализации не запускались.'));
      for (const block of visual.blocks.filter(block => block.selected && block.available && block.id !== primary.id && ['process_flow','comparison_bars','comparison_table'].includes(block.kind))) visualExplanation.push(el('p','',block.kind + ': ' + str(block.reason)));
      for (const choice of list(visual.choices).filter(choice => choice?.status === 'deferred')) visualExplanation.push(el('p','', (str(choice.kind) || 'Отложенный визуал') + ': ' + str(choice.reason)));
    } else visualExplanation.push(el('p','','VisualSpec отсутствует, повреждён или его версия не поддерживается. Запасной вид: ' + primaryKind + '. Использованы сохранённые данные и встроенные HTML/SVG/CSS адаптеры; численные пары проходят прежние проверки оснований.'));
    if (graph) visualExplanation.push(rendererExplanation);
    root.append(details('visual-choice','Почему этот визуал',visualExplanation,'fbrief-visual-choice'));
    if (!measurements.length) root.append(details('comparison-status','Сравнение · сопоставимые численные результаты не установлены',[comparison],'fbrief-comparison-collapse'));

    const quick = el('div','fbrief-quick-grid');
    const quickCard = (key, icon, title, values, fallback, cls = '') => {
      const full = meaningful(values), card = el('article','fbrief-quick ' + cls); append(card,el('span','fbrief-quick-icon',icon),el('h3','',title));
      card.append(el('p','fbrief-quick-line',full.length ? clip(full[0],90) : fallback));
      if (full.length) card.append(details(key,'Подробнее',paragraphs(full)));
      return card;
    };
    append(quick,
      quickCard('benefit','+','Польза',p.pros,'Преимущества в отчёте не установлены.','fbrief-benefit'),
      quickCard('limits','−','Ограничения',meaningful(p.cons).length ? p.cons : p.limitations,'Границы применимости не описаны.'),
      quickCard('resources','⌘','Что потребуется',meaningful(p.resources).length ? p.resources : p.infrastructure,'Требования к запуску неизвестны.')
    ); root.append(quick);

    const takeawayText = str(p.public_takeaway) || str(p.verdict), takeaway = el('section','fbrief-takeaway');
    append(takeaway,el('span','fbrief-eyebrow','ПРАКТИЧЕСКИЙ ВЫВОД'),el('p','',takeawayText ? clip(takeawayText,165) : 'Проверяемый прикладной вывод пока не сформулирован.'));
    if (str(p.audience)) append(takeaway,el('span','fbrief-eyebrow','КОМУ ПОЛЕЗНО'),el('p','fbrief-takeaway-audience',clip(p.audience,90)));
    if (takeawayText || str(p.audience)) takeaway.append(details('takeaway','Применимость и следующий шаг',paragraphs([takeawayText,str(p.audience),str(p.use_case),...list(p.applicability),str(p.next_step)])));
    root.insertBefore(takeaway,grid);

    const analogues = list(p.applied_analysis?.analogues).filter(item => item && str(item.memory_id));
    if (analogues.length) {
      const related = el('section','fbrief-related');
      const cards = el('div','fbrief-related-grid'), contextCards = el('div','fbrief-related-grid');
      for (const [index,item] of analogues.slice(0,6).entries()) {
        const frozen = list(run.plan?.memory?.items).find(record => [record?.id,record?.knowledge_id].includes(item.memory_id) && (item.memory_version === undefined || item.memory_version === record.version));
        const cached = list(Array.isArray(data.knowledge) ? data.knowledge : data.knowledge?.items).find(record => [record?.id,record?.knowledge_id,record?.memory?.id].includes(item.memory_id) && (item.memory_version === undefined || item.memory_version === (record.memory?.version ?? record.version)));
        const knowledge = frozen || cached;
        const title = str(frozen?.title) || str(cached?.memory?.title) || str(cached?.title) || 'Сохранённая работа ' + (index + 1);
        const relation = str(item.relation), context = relation === 'context', card = el('article','fbrief-related-card');
        card.dataset.briefRelated = item.memory_id; card.dataset.briefRelation = relation; card.dataset.briefMemoryVersion = String(knowledge?.memory?.version ?? knowledge?.version ?? item.memory_version ?? 'unknown');
        append(card,el('span','fbrief-relation',context ? 'Контекст · не baseline и не аналог' : relation === 'analogue' || relation === 'analog' ? 'Заявленный аналог · условия отдельно' : 'Сохранённая связь · сопоставимость не подтверждена'),el('h4','',title),el('p','',clip(item.relevance,90)));
        const body = paragraphs([str(item.relevance),str(item.conditions_difference),frozen ? 'Память зафиксирована в плане: версия ' + frozen.version + '.' : knowledge ? 'Использована совпадающая сохранённая версия памяти.' : 'Точная версия памяти недоступна; название и вывод не восстановлены.',str(frozen?.claim)]);
        const evidenceRun = frozen?.evidence_run_id || cached?.run_id;
        if (evidenceRun && typeof data.onSelectRun === 'function') body.push(button('Открыть прошлое исследование ↗','related-' + index,() => {
          try { Promise.resolve(data.onSelectRun(evidenceRun)).catch(() => { message.textContent = 'Не удалось открыть прошлое исследование.'; }); } catch { message.textContent = 'Не удалось открыть прошлое исследование.'; }
        }));
        card.append(details('related-' + index,'Почему связано и где граница',body)); (context ? contextCards : cards).append(card);
      }
      if (cards.children.length) append(related,sectionTitle('03','Связи с прошлым','Сопоставимость отдельно'),cards);
      if (contextCards.children.length) related.append(details('related-context','Связанный контекст · ' + contextCards.children.length,[contextCards]));
      root.append(related);
    }

    const foundation = [], sourceURLs = new Set();
    foundation.push(el('p','',str(quality.source_provenance?.label) || sourceLabel));
    if (!fetched.length) foundation.push(el('p','',supplied ? 'Сохранён только переданный пересказ. Первоисточник не сохранён / не прочитан; ссылка сама по себе не подтверждает изложение.' : 'Статус первичного источника неизвестен.'));
    foundation.push(el('p','','Статусы обработки и формальные проверки не являются научной оценкой. Числа показываются только при сохранённом основании обеих конфигураций и общих условиях.'));
    for (const source of sources) {
      const row = el('div','fbrief-source-row'), label = source.kind === 'supplied_text' ? 'Переданный текст / пересказ' : source.origin === 'fetched' && source.status === 'failed' ? 'Загрузка первоисточника не удалась' : source.origin === 'fetched' && source.status === 'captured' ? 'Сохранённый текст источника' : 'Запись источника';
      append(row,el('strong','',label),el('span','',str(source.title)));
      const url = safeURL(source.url); if (url) { row.append(link(url)); sourceURLs.add(url); } foundation.push(row);
    }
    for (const source of list(p.sources)) { const value = typeof source === 'string' ? source : source?.url; const url = safeURL(value); if (url && !sourceURLs.has(url)) { foundation.push(link(url)); sourceURLs.add(url); } }
    for (const evidence of list(p.evidence)) {
      const row = el('div','fbrief-evidence-row'); append(row,el('strong','',str(evidence.claim)),el('blockquote','',str(evidence.excerpt) || 'Точная цитата не сохранена.'),el('small','',str(evidence.locator)),el('p','fbrief-muted',str(evidence.limitations) || 'Сохранённое основание; независимая проверка не подтверждена.')); foundation.push(row);
    }
    append(root,details('foundations','Источники, цитаты и границы проверки',foundation,'fbrief-foundations'),append(el('footer','fbrief-footer'),action('Проверить доказательства ↗','evidence')),message);
    host.replaceChildren(root);
    if (state.drawWires) state.drawWires();
    if (focusKey) [...root.querySelectorAll('[data-fbrief-control]')].find(node => node.dataset.fbriefControl === focusKey)?.focus({preventScroll:true});
    if (state.mountInfographic) state.mountInfographic();
    const instance = {
      snapshot:() => ({runId,selected:state.selected,open:[...root.querySelectorAll('details[open]')].map(node => node.dataset.fbriefDetail),focus:root.contains(document.activeElement) ? document.activeElement?.dataset?.fbriefControl : null}),
      pause:() => { stop(); infographic?.pause(); },
      destroy:() => { if (!state.alive) return; state.alive = false; stop(); infographic?.destroy(); abort.abort(); resizeObserver?.disconnect(); root.remove(); instances.delete(host); active.delete(instance); }
    };
    instances.set(host,instance); active.add(instance); return instance;
  }
  window.FrontierBrief = {mount,unmount:host => instances.get(host)?.destroy(),pause:() => { for (const instance of active) instance.pause(); }};
})();
