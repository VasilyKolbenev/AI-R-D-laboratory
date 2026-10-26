/* FIELDWORK. Read-only design study over saved lab data. No dispatch or write route. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const arr = v => Array.isArray(v) ? v : [];
  const obj = v => v && typeof v === 'object' && !Array.isArray(v) ? v : {};
  const str = (v, max = 2000) => typeof v === 'string' ? v.trim().slice(0, max) : '';
  const finite = v => typeof v === 'number' && Number.isFinite(v);
  const pretty = v => finite(v) ? v.toLocaleString('ru-RU', {maximumFractionDigits: 2}) : '—';
  const NS = 'http://www.w3.org/2000/svg';
  const labels = {planned: 'Ждёт вашего апрува', completed: 'Разбор сохранён', failed: 'Не завершено', outcome_unknown: 'Исход неизвестен', queued: 'Ожидает запуска', running: 'Выполняется', cancelled: 'Остановлено'};
  const phaseNames = {researcher: 'Исследователь', critic: 'Критик', reviewer: 'Редактор'};
  const state = {runs: [], run: null, p: null, quality: null, research: null, queue: null, lens: 'mechanism', space: 'study', knowledge: null, workspace: null, libraryLoading: false, selected: null, epoch: 0, loading: false, frame: 0, graph: null, playing: false, abort: null};
  const cache = new Map();
  const researchReads = new Map();
  let libraryRequest = null, libraryInstance = null, benchmarkInstance = null, benchmarkTimer = null, benchmarkUntil = 0;
  const benchmarkState = {plans:[],selected:null,loaded:false,loading:false};
  let benchmarkRead = 0;
  if(location.hash==='#benchmarks')state.space='benchmarks';
  function el(tag, value, cls) {const n = document.createElement(tag); if (value !== undefined) n.textContent = value; if (cls) n.className = cls; return n;}
  function svg(tag, attrs = {}, value) {const n = document.createElementNS(NS, tag); for (const [k,v] of Object.entries(attrs)) n.setAttribute(k, String(v)); if (value !== undefined) n.textContent = value; return n;}
  function add(parent, ...nodes) {for (const n of nodes.flat()) if (n) parent.append(n); return parent;}
  function replace(id, ...nodes) {$(id).replaceChildren(...nodes.filter(Boolean));}
  function tag(value, warning = false) {return el('span', value, 'tag' + (warning ? ' warning' : ''));}
  function button(value, callback, cls = 'claim-button') {const n = el('button', value, cls); n.type = 'button'; n.addEventListener('click', callback); return n;}
  function safeUrl(value) {try {const u = new URL(value); return ['https:', 'http:'].includes(u.protocol) && !u.username && !u.password && !/^(localhost|127\.|0\.|10\.|192\.168\.|\[?::1)/i.test(u.hostname) ? u.href : null;} catch {return null;}}
  function link(value, label) {const href = safeUrl(value); if (!href) return el('span', 'URL источника отсутствует', 'muted'); const a = el('a', label || new URL(href).hostname, 'paper-link'); a.href = href; a.target = '_blank'; a.rel = 'noopener noreferrer'; return a;}
  function section(title, ...nodes) {return add(el('section', undefined, 'detail-section'), el('h3', title), ...nodes);}
  function disclosure(title, ...nodes) {return add(el('details', undefined, 'detail-section'), el('summary', title), ...nodes);}
  function paragraph(value, fallback = 'Не зафиксировано в отчёте.') {return el('p', str(value) || fallback);}
  function date(value) {const d = new Date(value); return Number.isFinite(d.getTime()) ? d.toLocaleString('ru-RU', {timeZone: 'Europe/Moscow', day:'numeric', month:'short', hour:'2-digit', minute:'2-digit'}) + ' МСК' : 'Дата не сохранена';}
  function shortTitle(run) {return str(run.plan?.sources?.[0]?.title, 160) || str(run.plan?.question, 100) || 'Сохранённое исследование';}
  function textList(items) {const ul = el('ul', undefined, 'inspector-list'); for (const item of arr(items)) ul.append(el('li', typeof item === 'string' ? item : str(item.detail || item.reason || item.problem || item.title))); return ul;}
  async function api(path, signal) {
    if (!/^\/api\/(?:runs(?:\/[a-f0-9]{32}(?:\/(?:presentation|quality|research))?)?|publication|health|knowledge|research|benchmarks\/lexical(?:\/[a-f0-9]{64}(?:\/export)?)?)$/.test(path)) throw new Error('Этот адрес не входит в режим просмотра.');
    const response = await fetch(path, {method: 'GET', credentials: 'same-origin', signal, cache: 'no-store', headers: {Accept: 'application/json'}});
    const data = await response.json(); if (!response.ok) throw new Error(str(data.error, 200) || 'Не удалось прочитать сохранённые данные.'); return data;
  }
  function error(value) {const node = $('error-panel'); node.hidden = !value; node.textContent = value || '';}
  function stop() {cancelAnimationFrame(state.frame); state.frame = 0; state.playing = false; if ($('graph-play')) $('graph-play').textContent = 'Показать движение'; const packet = $('graph-stage').querySelector('.graph-packet'); if (packet) packet.setAttribute('opacity', '0');}
  function clearSelection() {state.selected = null; stop();}
  function titleInspector(kicker, title, ...content) {replace('inspector', el('p', kicker, 'eyebrow'), el('h2', title), ...content);}
  function phaseRecord(role) {
    const run = state.run || {}, current = arr(run.agent_pipeline?.phases).find(x => x.role === role), saved = arr(run.plan?.continuation?.prefix).find(x => x.role === role), reused = arr(run.agent_pipeline?.reused_phases).find(x => x.role === role);
    return {row: current || saved || reused || {}, reused: Boolean(saved || reused), status: [current,saved,reused].map(x => str(x?.status)).find(v => v && v !== 'reused') || 'unknown'};
  }
  function practical() {
    const p = state.p || {}, recipe = state.research?.recipe;
    titleInspector('ПРИКЛАДНОЙ РАКУРС', 'Что это даёт в работе', tag('Вывод сохранённого разбора'), section('Задача', paragraph(p.use_case || p.problem)), disclosure('Кому пригодится', paragraph(p.audience)), disclosure('Следующая проверка', paragraph(recipe?.next_steps?.[0] || p.next_step)), disclosure('Границы применимости', paragraph(arr(p.limitations)[0] || arr(p.cons)[0], 'Границы не выделены отдельными полями. Смотрите полный отчёт.')));
  }
  function phaseInspector(role) {
    stop(); const record = phaseRecord(role), review = obj(state.p?.agent_review);
    if (role === 'critic') {
      const issues = arr(review.critic?.issues), dispositions = arr(review.dispositions || review.review_dispositions);
      titleInspector('КОНТРПРОВЕРКА', 'Что оспорил критик', tag(issues.length ? issues.length + ' замечаний в записи' : 'Структурированных замечаний нет', !issues.length));
      if (!issues.length) $('inspector').append(paragraph('Отсутствие записанных замечаний не означает отсутствия ошибок.'));
      for (const issue of issues) {
        const disposition = dispositions.find(d => d.issue_id === issue.id);
        const details = el('details'); add(details, el('summary', str(issue.problem, 150) || issue.id), paragraph(issue.problem), section('Что требовалось', paragraph(issue.required_change)));
        if (disposition) add(details, tag(disposition.status === 'fixed' ? 'Редактор отметил исправление' : str(disposition.status)), paragraph(disposition.reason), section('Сохранённое исправление', paragraph(disposition.resolution_excerpt)));
        else details.append(tag('Ответ редактора не найден', true));
        $('inspector').append(details);
      }
      $('inspector').append(el('p', 'Статус исправления сохранён редактором; это не независимая проверка.', 'provenance'));
    } else if (role === 'researcher') {
      titleInspector('ИСТОЧНИКИ И КОНТЕКСТ', 'На чём строился разбор', tag(record.status === 'completed' ? 'Этап завершён' : labels[record.status] || 'Исход не установлен', record.status !== 'completed'));
      for (const source of arr(state.run?.plan?.sources)) $('inspector').append(section(str(source.title) || 'Исходный материал', link(source.url, 'Открыть первоисточник ↗')));
      $('inspector').append(paragraph('Выбранная память и уроки находятся на нижней дорожке. Полные запросы исполнителей здесь не загружаются.'));
    } else {
      titleInspector('РЕДАКТОРСКИЙ ВЫХОД', 'Как собран результат', tag(record.reused ? 'Использован сохранённый этап' : 'Сохранённый этап'), section('Прикладной вывод', paragraph(state.p?.public_takeaway || state.p?.verdict)), section('Проверки записи', paragraph(state.quality?.notice, 'Доступны в «Обсерватории» рабочего интерфейса.')));
      const findings = arr(state.quality?.findings).filter(f => !['pass', 'not_applicable'].includes(f.status));
      $('inspector').append(textList(findings.slice(0, 6)));
    }
    $('inspector').focus({preventScroll:true});
  }
  function memoryInspector(item, group) {
    const body = obj(item.body || item);
    titleInspector('ПАМЯТЬ ЭТОГО ПЛАНА', group, tag('Снимок до апрува'), section('Сохранённая запись', paragraph(body.rule || body.title || body.claim || body.text || body.summary)), section('Версия и область', paragraph([body.version ? 'Версия ' + body.version : '', body.scope || body.applicability || 'Границы — в исходной записи'].filter(Boolean).join(' · '))), el('p', 'Память даёт контекст. Она не заменяет первоисточник текущего исследования.', 'provenance'));
  }
  function renderTracks() {
    replace('phase-track');
    for (const [role, name] of Object.entries(phaseNames)) {
      const r = phaseRecord(role), b = button('', () => phaseInspector(role), 'phase'); b.dataset.state = r.status;
      add(b, el('span', ({researcher:'01', critic:'02', reviewer:'03'})[role], 'eyebrow'), el('strong', name), el('span', (r.status === 'completed' ? 'Сохранён' : labels[r.status] || 'Нет данных') + (r.reused ? ' · переиспользован' : ''), 'muted'));
      $('phase-track').append(b);
    }
    const usage = obj(state.run?.usage), pipeline = obj(state.run?.agent_pipeline), dl = el('dl');
    for (const [k,v] of [['Вызовов в этом запуске',pretty(pipeline.dispatched_calls)],['Входные токены',pretty(usage.input_tokens)],['Выходные токены',pretty(usage.output_tokens)],['Из входа — кеш',pretty(usage.cached_input_tokens)]]) add(dl, el('dt', k), el('dd', v));
    replace('usage-track', dl, el('p','Только известный расход этого запуска. Кеш входит во входные токены. Денежная стоимость не установлена.','provenance'));
    replace('memory-track'); const memory = obj(state.run?.plan?.memory);
    if (memory.enabled === false) $('memory-track').append(el('p', 'Память была отключена в этом плане.', 'muted'));
    else {
      for (const [key,label] of [['items','Прошлые выводы'],['lessons','Уроки'],['corrections','Ваши поправки']]) {
        const entries=arr(memory[key]);if(!entries.length)continue;
        const b=button('',()=>setSpace('knowledge'),'memory-entry');add(b,el('span',label,'eyebrow'),el('strong',String(entries.length)+' в снимке плана →'));$('memory-track').append(b);
      }
      if (!$('memory-track').children.length) $('memory-track').append(el('p', 'Отдельных прошлых выводов, уроков и поправок в плане нет.', 'muted'));
      if (memory.profile) $('memory-track').append(el('p', 'Профиль интересов включён в зафиксированный план.', 'provenance'));
    }
    const queue = arr(state.queue?.items).find(x => x.run_id === state.run?.id);
    const qlabels = {queued:'Назначен выпуск', published:'Опубликовано', publishing:'Публикация выполняется', blocked:'Выпуск заблокирован', awaiting_owner:'Ждёт владельца', outcome_unknown:'Исход отправки неизвестен', cancelled:'Снят с выпуска'};
    replace('queue-track', el('strong', queue ? qlabels[queue.status] || 'Статус выпуска не установлен' : state.queue ? 'Пакета в очереди нет' : 'Очередь недоступна'), el('p', queue?.due_at ? date(queue.due_at) : 'Публикация доступна после вашего «В очередь» в Telegram.', 'muted'));
  }
  function diagramData() {
    const saved = obj(state.p?.motion_story);
    if (state.lens === 'mechanism') {
      if (saved.version !== 'dataflow-v1') return null;
      const nodes = arr(saved.nodes).filter(n => n.lane === 'technology').slice(0, 16);
      const ids = new Set(nodes.map(n => n.id));
      return nodes.length ? {nodes, edges: arr(saved.edges).filter(e => ids.has(e.from) && ids.has(e.to)).slice(0, 24), saved} : null;
    }
    const evidence = arr(state.p?.evidence);
    if (!evidence.length) return null;
    const nodes = [], edges = [];
    for (const [i,e] of evidence.slice(0, 6).entries()) {
      const checks = boundChecks(e), source = checks.find(c => c.document_id && c.segment_id), literal = checks.find(c => c.literal_quote === true);
      const row = [{id:'claim_'+i,label:e.claim,role:'claim',evidence:e,rank:0}, {id:'quote_'+i,label:literal ? 'Дословная цитата найдена' : 'Привязка цитаты не установлена',role:literal?'quote':'gap',evidence:e,rank:1}, {id:'source_'+i,label:source ? 'Сегмент '+source.segment_id : 'Источник / URL',role:source?'source':'gap',evidence:e,rank:2}];
      nodes.push(...row); edges.push({from:row[0].id,to:row[1].id,label:'Запись проверки',evidence:e},{from:row[1].id,to:row[2].id,label:source?'ID документа':'Не установлено',evidence:e});
    }
    return {nodes,edges,evidenceMode:true};
  }
  function boundChecks(evidence) {
    const checks = arr(state.p?.source_validation?.checks).length ? state.p.source_validation.checks : arr(state.p?.agent_review?.source_validation?.checks);
    // Duplicate claim IDs cannot be safely joined, even when labels look alike.
    if (!evidence.id || arr(state.p?.evidence).filter(x => x.id === evidence.id).length !== 1) return [];
    return checks.filter(c => c.evidence_id === evidence.id);
  }
  function evidenceInspector(e) {
    const checks = boundChecks(e), documents = arr(state.run?.plan?.evidence_bundle?.documents);
    titleInspector('УТВЕРЖДЕНИЕ / ' + (e.id || 'БЕЗ ID'), 'От вывода к оригиналу', tag(checks.length ? checks.length + ' записей привязки' : 'Привязка не найдена', !checks.length), section('Что утверждается', paragraph(e.claim)), section('Ограничение вывода', paragraph(e.limitations)));
    if (!checks.length) $('inspector').append(section('Фрагмент сохранённого отчёта', paragraph(e.excerpt)), link(e.source_url, 'URL из отчёта ↗'));
    for (const c of checks) {
      const matches = str(c.document_id) ? documents.filter(d => [d.id,d.document_id,d.asset_id].includes(c.document_id)) : [];
      const doc = matches.length === 1 ? matches[0] : null, segments = str(c.segment_id) ? arr(doc?.segments).filter(s => s.id === c.segment_id || s.segment_id === c.segment_id) : [];
      const segment = segments.length === 1 ? segments[0] : null;
      const verifiedLiteral = c.literal_quote === true && c.source_bound === true;
      const details = el('details'); details.open = checks.indexOf(c) === 0;
      add(details, el('summary', verifiedLiteral ? 'Цитата · ' + (c.segment_id || 'нет ID сегмента') : 'Сохранённая оценка связи'), tag(verifiedLiteral ? 'Есть запись дословного совпадения' : 'Сопоставление неполно', !verifiedLiteral), el('blockquote', c.quote || 'Точная цитата не сохранена.'), link(doc?.url || e.source_url, 'Открыть источник ↗'), section('Оценка смысла моделью', paragraph(c.reason)), el('code', [c.document_id,c.segment_id].filter(Boolean).join(' / ')));
      if (segment) {const exact = el('details'); add(exact, el('summary','Сохранённый сегмент целиком'), paragraph(segment.text)); details.append(exact);}
      else details.append(el('p','Текст сегмента отсутствует в текущем снимке плана.','provenance'));
      $('inspector').append(details);
    }
    $('inspector').append(el('p','Связь с цитатой подтверждает происхождение записи. Научная истинность и воспроизводимость этим не установлены.','provenance'));
  }
  function nodeInspector(node) {
    if (node.evidence) {evidenceInspector(node.evidence); return;}
    const story = obj(state.p?.motion_story), fragments = arr(story.evidence).filter(e => arr(node.evidence_ids).includes(e.id));
    titleInspector('МЕХАНИЗМ / ' + str(node.id).toUpperCase(), str(node.label), tag('Шаг из сохранённой схемы'), section('Откуда взято', paragraph(story.selection?.reason, 'Сохранённая схема редактора.')));
    for (const f of fragments) $('inspector').append(section('Фрагмент разбора', paragraph(f.excerpt), link(f.source_url, 'Источник схемы ↗')));
    if (!fragments.length) $('inspector').append(tag('Основание шага не выделено по ID', true));
    $('inspector').append(el('p','Это схема описанного процесса, не выполненная симуляция. Направление стрелок не измеряет скорость и не доказывает эффект.','provenance'));
  }
  function selectNode(node, root) {
    state.selected = node.id;
    for (const n of root.querySelectorAll('.graph-node')) n.setAttribute('data-selected', String(n.dataset.node === node.id));
    nodeInspector(node);
  }
  function lines(value, limit = 24, max = 3) {
    const words = str(value, 400).split(/\s+/), result = []; let line = '';
    for (const word of words) {if ((line + ' ' + word).trim().length > limit && line) {result.push(line); line = word;} else line = (line + ' ' + word).trim();}
    if (line) result.push(line); return result.length > max ? [...result.slice(0,max-1),result[max-1].slice(0,limit-1)+'…'] : result;
  }
  function drawDiagram() {
    const data = diagramData(); state.graph = null;
    if (!data) {replace('graph-stage', add(el('div',undefined,'empty-state'),el('span','∅','empty-symbol'),el('h3',state.lens==='evidence'?'Утверждения не выделены по ID':'Схема механизма не сохранена'),paragraph('Честный пробел. Полный отчёт доступен в рабочей лаборатории.'))); $('graph-play').disabled = true; $('graph-step').disabled = true; return;}
    const ranks = new Map(data.nodes.map(n => [n.id, n.rank || 0]));
    if (!data.evidenceMode) for (let i=0;i<data.nodes.length;i++) {let changed=false; for (const e of data.edges) {const next=Math.min(data.nodes.length-1,(ranks.get(e.from)||0)+1); if (next>(ranks.get(e.to)||0)) {ranks.set(e.to,next);changed=true;}} if(!changed)break;}
    const levels = [...new Set(ranks.values())].sort((a,b)=>a-b), columns = levels.map(rank=>data.nodes.filter(n=>ranks.get(n.id)===rank));
    const rowCount = Math.max(1,...columns.map(c=>c.length)), folded = levels.length > 4, width = folded ? 1000 : Math.max(1000,levels.length*255), height = Math.max(480,rowCount*132+80,folded?Math.ceil(levels.length/3)*190+80:0), nodeWidth=210,nodeHeight=100;
    const root=svg('svg',{viewBox:`0 0 ${width} ${height}`,role:'group','aria-label':state.lens==='evidence'?'Сохранённые связи утверждений, цитат и источников':'Сохранённая схема механизма'}), coordinates=new Map();
    const defs=svg('defs'),marker=svg('marker',{id:'field-arrow',viewBox:'0 0 10 10',refX:9,refY:5,markerWidth:5,markerHeight:5,orient:'auto'});marker.append(svg('path',{d:'M 0 1 L 9 5 L 0 9',fill:'none',stroke:'currentColor','stroke-width':1.5}));defs.append(marker);root.append(defs);
    columns.forEach((column,index)=>column.forEach((node,row)=>{const band=Math.floor(index/3),xIndex=band%2?2-index%3:index%3;coordinates.set(node.id,folded?{x:45+xIndex*340,y:50+band*190+row*115}:{x:45+(levels.length>1?index*(width-300)/(levels.length-1):width/2-150),y:height/(column.length+1)*(row+1)-nodeHeight/2});}));
    for(let i=0;i<6;i++)root.append(svg('path',{d:`M 0 ${70+i*75} H ${width}`,class:'graph-guide'}));
    const paths=[];
    for(const edge of data.edges){const a=coordinates.get(edge.from),b=coordinates.get(edge.to);if(!a||!b)continue;const start={x:a.x+nodeWidth,y:a.y+nodeHeight/2},end={x:b.x,y:b.y+nodeHeight/2},mid=(start.x+end.x)/2;
      const path=svg('path',{d:`M ${start.x} ${start.y} C ${mid} ${start.y}, ${mid} ${end.y}, ${end.x} ${end.y}`,class:'graph-edge','marker-end':'url(#field-arrow)'});root.append(path);paths.push({path,edge});
      if(levels.length<5&&data.edges.length<10)root.append(svg('text',{x:mid,y:(start.y+end.y)/2-12,'text-anchor':'middle',class:'edge-label'},str(edge.label,24)));
    }
    data.nodes.forEach((node,index)=>{
      const pos=coordinates.get(node.id),group=svg('g',{transform:`translate(${pos.x} ${pos.y})`,class:'graph-node',role:'button',tabindex:0,'aria-label':node.label,'data-node':node.id,'data-selected':String(state.selected===node.id)});
      add(group,svg('rect',{width:nodeWidth,height:nodeHeight,rx:12,class:'node-body'}),svg('text',{x:16,y:24,class:'node-index'},String(index+1).padStart(2,'0')));
      const title=svg('text',{x:16,y:49,class:'node-label'}); lines(node.label,20,2).forEach((line,i)=>title.append(svg('tspan',{x:16,dy:i?20:0},line)));group.append(title);
      const kind={input:'вход',compute:'операция',decision:'проверка',memory:'память',output:'выход',data:'данные',claim:'утверждение',quote:'цитата',gap:'пробел',source:'источник'}[node.role]||'шаг';group.append(svg('text',{x:16,y:88,class:'node-kind'},kind));
      group.addEventListener('click',()=>{stop();selectNode(node,root);});group.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();stop();selectNode(node,root);}});root.append(group);
    });
    const packet=svg('circle',{r:5,opacity:0,class:'graph-packet'});root.append(packet);replace('graph-stage',root);state.graph={root,data,paths,packet,index:0};
    $('graph-play').disabled=!paths.length;$('graph-step').disabled=!paths.length;
    if(state.lens==='evidence')evidenceInspector(data.nodes[0].evidence); else practical();
  }
  function nextEdge() {if(!state.graph)return;stop();const graph=state.graph,entry=graph.paths[graph.index++%graph.paths.length];if(!entry)return;const target=graph.data.nodes.find(n=>n.id===entry.edge.to);if(target)selectNode(target,graph.root);$('graph-caption').textContent=(entry.edge.label||'Сохранённая связь')+' · иллюстрация порядка, не замер производительности.';}
  function animate() {
    if(state.playing){stop();return;}const graph=state.graph;if(!graph?.paths.length)return;
    if(matchMedia('(prefers-reduced-motion: reduce)').matches){nextEdge();return;}
    state.playing=true;$('graph-play').textContent='Остановить движение';const start=performance.now(),duration=1300,total=graph.paths.length;
    const frame=now=>{if(!state.playing||state.graph!==graph)return;const t=(now-start)/duration,index=Math.floor(t);if(index>=total){stop();return;}const item=graph.paths[index],point=item.path.getPointAtLength(item.path.getTotalLength()*(t-index));graph.packet.setAttribute('opacity','1');graph.packet.setAttribute('transform',`translate(${point.x} ${point.y})`);const target=graph.data.nodes.find(n=>n.id===item.edge.to);if(target&&state.selected!==target.id)selectNode(target,graph.root);state.frame=requestAnimationFrame(frame);};state.frame=requestAnimationFrame(frame);
  }
  function metricEvidence(row) {return [...arr(row.baseline?.evidence_ids),...arr(row.candidate?.evidence_ids)].every(id=>str(id)&&arr(state.p?.evidence).filter(e=>e.id===id).length===1);}
  function renderComparison() {
    const rows=arr(state.p?.applied_analysis?.rows),container=el('div',undefined,'comparison-view');
    const measuredBases=['author_claim','external_measurement'];
    const comparable=rows.filter(r=>r.comparability==='comparable'&&str(r.conditions)&&finite(r.baseline?.value)&&finite(r.candidate?.value)&&r.baseline.value>=0&&r.candidate.value>=0&&arr(r.baseline?.evidence_ids).length&&arr(r.candidate?.evidence_ids).length&&metricEvidence(r)&&measuredBases.includes(r.baseline?.basis)&&measuredBases.includes(r.candidate?.basis));
    if(!rows.length)add(container,el('span','— ↔ —','empty-symbol'),el('h3','Преимущество пока не измерено'),paragraph('В этом отчёте нет структурированных числовых пар с baseline. Рисовать выигрыш было бы нечестно.'));
    for(const row of rows){const s=section(str(row.metric)||'Метрика',tag(str(row.comparability)||'Сопоставимость не установлена',!comparable.includes(row)));const table=el('table',undefined,'metric-table');const head=el('tr');for(const value of ['Вариант','Значение','Основание'])head.append(el('th',value));table.append(head);for(const key of ['baseline','candidate']){const item=obj(row[key]),tr=el('tr');add(tr,el('td',str(item.label)||key),el('td',pretty(item.value)+(row.unit?' '+row.unit:'')),el('td',str(item.basis)||'неизвестно'));table.append(tr);}s.append(table,paragraph(row.conditions,'Условия сравнения не зафиксированы.'));container.append(s);
      if(comparable.includes(row)){const plot=svg('svg',{viewBox:'0 0 700 130',role:'img','aria-label':str(row.metric)+' при сохранённых одинаковых условиях'});const max=Math.max(Math.abs(row.baseline.value),Math.abs(row.candidate.value),1);for(const [i,key]of ['baseline','candidate'].entries()){const v=row[key].value;if(v<0)continue;add(plot,svg('text',{x:10,y:26+i*58,class:'edge-label'},str(row[key].label,23)),svg('rect',{x:220,y:10+i*58,width:Math.max(0,v/max*360),height:28,rx:4,class:i?'metric-candidate':'metric-baseline'}),svg('text',{x:590,y:29+i*58,class:'node-label'},pretty(v)));}container.append(plot,el('p','Числа из сохранённых авторских или внешних измерений. Собственный benchmark здесь не выполнялся.','provenance'));}
    }
    const analogues=arr(state.p?.applied_analysis?.analogues);if(analogues.length){container.append(el('h3','Аналогии из выбранной памяти'));for(const a of analogues){const details=el('details');add(details,el('summary',a.relation==='context'?'Контекст, не конкурентный baseline':str(a.relation)||'Связь с прошлой работой'),paragraph(a.relevance),section('Почему условия различаются',paragraph(a.conditions_difference)),el('code',[a.memory_id,a.memory_version?'v'+a.memory_version:''].filter(Boolean).join(' · ')));container.append(details);}}
    replace('graph-stage',container);$('graph-play').disabled=true;$('graph-step').disabled=true;
    const recipe=state.research?.recipe;
    titleInspector('КОНТРАКТ СРАВНЕНИЯ','Что нужно измерить',tag(recipe?.execution==='not_executed'?'Проверка ещё не выполнена':'Сохранённый план проверки',true),section('Прикладной сценарий',paragraph(state.p?.use_case)),section('Что пока неизвестно',textList(arr(recipe?.unknowns).length?recipe.unknowns:arr(state.p?.applied_analysis?.unknowns))));
    for(const criterion of arr(recipe?.acceptance_criteria))$('inspector').append(section(str(criterion.metric)||'Критерий',paragraph(criterion.definition),el('p','Цель: '+(criterion.threshold||'не задана')+' · ожидание: '+(criterion.expected||'неизвестно'),'provenance')));
    if(!recipe)$('inspector').append(el('p','Загружаем сохранённый рецепт проверки…','muted'));
  }
  function renderLens() {
    clearSelection(); for(const b of $('lens-tabs').querySelectorAll('button')){const selected=b.dataset.lens===state.lens;b.setAttribute('aria-selected',String(selected));b.tabIndex=selected?0:-1;}
    $('graph-title').textContent={mechanism:'Механизм в разрезе',comparison:'Разница, которую можно доказать',evidence:'Откуда взялся каждый вывод'}[state.lens];
    $('graph-meta').textContent=state.lens==='mechanism'?'СОХРАНЁННАЯ СХЕМА':state.lens==='comparison'?'BASELINE / УСЛОВИЯ / ПРОБЕЛЫ':'УТВЕРЖДЕНИЕ → ЦИТАТА → ИСТОЧНИК';
    $('graph-caption').textContent=state.lens==='mechanism'?'Нажмите на узел: увидите фрагмент, из которого он собран. Движение иллюстрирует порядок, не скорость.':state.lens==='comparison'?'Отсутствующие значения не заменяются нулями. Аналогия из памяти не становится baseline автоматически.':'Только сохранённые ID-связи. Запись привязки и научная истинность — разные уровни проверки.';
    if(state.lens==='comparison')renderComparison();else drawDiagram();
  }
  function renderReadiness() {
    const readiness=state.research?.readiness,host=$('readiness-summary');host.replaceChildren();
    if(!readiness){host.append(tag('Глубина проверки ещё не определена',true),button('Посмотреть пробелы',()=>setSpace('validation'),'inline-link'));return;}
    const coverage=obj(readiness.claim_coverage),provenance=obj(readiness.provenance);
    add(host,tag(readiness.label||'Уровень проверки',readiness.stage!=='locally_tested'),el('span','Привязки: '+pretty(coverage.source_backed)+' / '+pretty(coverage.total),'provenance'),el('span','Тестов технологии: '+pretty(provenance.executed_technology_tests),'provenance'),button('Что осталось проверить →',()=>setSpace('validation'),'inline-link'));
    $('study-status').textContent=readiness.label||labels[state.run?.status]||'Не определено';
  }
  function libraryReports() {return [...cache.values()].filter(v=>v.run&&v.p).map(v=>({run:v.run,p:v.p,research:v.research}));}
  function paintLibrary() {
    if(state.space==='study')return;
    if(state.space==='benchmarks'){paintBenchmark();return;}
    const host=$('library-workspace');libraryInstance?.destroy?.();
    if(!window.FrontierLibrary?.mount){replace('library-workspace',paragraph('Компонент таблиц не загрузился. Обновите страницу.'));return;}
    if(state.libraryLoading&&!state.knowledge){replace('library-workspace',paragraph('Читаем таблицу знаний и реестр измерений…'));return;}
    libraryInstance=window.FrontierLibrary.mount(host,{mode:state.space,knowledge:arr(state.knowledge),selectedRun:state.run,selectedPresentation:state.p,selectedResearch:state.research,workspace:state.workspace,reports:libraryReports(),onSelectRun:async id=>{state.space='study';$('research-select').value=id;await select(id);},onOpenValidation:()=>setSpace('validation'),onOpenBenchmark:async id=>{benchmarkState.selected={plan_id:id};await setSpace('benchmarks');}});
  }
  async function loadLibrary() {
    if(libraryRequest)return libraryRequest;
    if(state.knowledge&&state.workspace)return;
    state.libraryLoading=true;paintLibrary();
    libraryRequest=(async()=>{
      const results=await Promise.allSettled([api('/api/knowledge'),api('/api/research')]);
      state.knowledge=results[0].status==='fulfilled'?arr(results[0].value.items):null;state.workspace=results[1].status==='fulfilled'?results[1].value:null;
      if(results.some(r=>r.status==='rejected'))error('Часть таблицы знаний или реестра недоступна. Неизвестные результаты не подставляются.');
      state.libraryLoading=false;libraryRequest=null;
      const local=arr(state.workspace?.lexical_benchmarks).filter(x=>x.completed===true&&x.origin==='executed_local_lexical').length;
      $('workspace-summary').textContent=(state.knowledge?state.knowledge.length+' знаний':'Знания недоступны')+' · '+(state.workspace?arr(state.workspace.measurements).length+' замеров источников':'Реестр замеров недоступен')+(local?' · '+local+' CPU-проверка':'');paintLibrary();
    })();return libraryRequest;
  }
  async function compareReports() {
    const other=state.runs.find(r=>r.status==='completed'&&r.id!==state.run?.id&&!cache.has(r.id));
    if(!other||libraryReports().length>=2)return;
    try{const p=await api('/api/runs/'+other.id+'/presentation');cache.set(other.id,{run:other,p,quality:null,research:null});if(state.space==='compare')paintLibrary();}catch(e){if(state.space==='compare')error('Второй отчёт не прочитан: '+e.message);}
  }
  async function setSpace(space) {
    if(!['study','knowledge','compare','validation','benchmarks'].includes(space))return;
    stop();state.space=space;const library=space!=='study';
    const controlled=space==='benchmarks'&&location.origin==='http://127.0.0.1:8795';
    $('mode-notice').textContent=controlled?'CPU-проверка · один прогон после подтверждения · без моделей и API':'Режим чтения · сохранённые данные · без запусков';
    $('connection-status').textContent=controlled?'Точный план перед CPU-запуском':'Ваши сохранённые данные · только чтение';
    document.querySelector('.rail-footnote').textContent=controlled?'Контролируемый CPU-прогон после подтверждения.':'Только чтение локальных результатов.';
    if(space!=='benchmarks'){clearTimeout(benchmarkTimer);benchmarkTimer=null;benchmarkInstance?.destroy?.();benchmarkInstance=null;}
    document.querySelector('.reading-field').hidden=library;document.querySelector('.paper-panel').hidden=library;document.querySelector('.record-strip').hidden=library;$('library-workspace').hidden=!library;
    for(const b of $('space-tabs').querySelectorAll('button')){if(b.dataset.space===space)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');}
    if(space==='benchmarks'){libraryInstance?.destroy?.();libraryInstance=null;paintBenchmark();try{await loadBenchmarkData();paintBenchmark();}catch(e){error('CPU-проверки недоступны: '+e.message);}}
    else if(library){paintLibrary();await Promise.all([loadLibrary(),loadResearch()]);if(space==='compare')await compareReports();paintLibrary();}
    else libraryInstance?.destroy?.();
  }
  async function benchmarkPost(action,body) {
    if(location.origin!=='http://127.0.0.1:8795')throw new Error('Подтвердите запуск в рабочей лаборатории на порту 8795.');
    if(!['prepare','start'].includes(action))throw new Error('Неизвестное действие CPU-проверки.');
    const bootstrap=await fetch('/api/bootstrap',{method:'GET',credentials:'same-origin',cache:'no-store'});
    if(!bootstrap.ok)throw new Error('Не удалось прочитать локальный токен подтверждения.');
    const config=await bootstrap.json();
    const response=await fetch('/api/benchmarks/lexical/'+action,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-Lab-Token':config.csrf},body:JSON.stringify(body)});
    const result=await response.json();if(!response.ok)throw new Error(result.error||'CPU-проверка не принята.');return result;
  }
  async function loadBenchmarkData(id) {
    benchmarkState.loading=true;const request=++benchmarkRead;
    try{const list=await api('/api/benchmarks/lexical');const plans=arr(list.items),selected=id||benchmarkState.selected?.plan_id||plans[0]?.plan_id;
      const result=selected?await api('/api/benchmarks/lexical/'+selected):null;if(request!==benchmarkRead)return {plans:benchmarkState.plans,selected:benchmarkState.selected};
      benchmarkState.plans=plans;benchmarkState.selected=result;benchmarkState.loaded=true;
      return {plans:benchmarkState.plans,selected:benchmarkState.selected};
    }finally{if(request===benchmarkRead)benchmarkState.loading=false;}
  }
  function benchmarkPoll() {
    clearTimeout(benchmarkTimer);benchmarkTimer=null;
    if(document.hidden||state.space!=='benchmarks'||benchmarkState.selected?.status!=='running'||Date.now()>benchmarkUntil)return;
    benchmarkTimer=setTimeout(async()=>{try{await loadBenchmarkData(benchmarkState.selected.plan_id);if(state.space==='benchmarks')paintBenchmark();}catch(e){error('Статус CPU-проверки недоступен: '+e.message);}benchmarkPoll();},1000);
  }
  function paintBenchmark() {
    if(state.space!=='benchmarks')return;
    if(!window.FrontierBenchmark?.mount){replace('library-workspace',paragraph('Компонент CPU-проверки не загрузился.'));return;}
    const selected=benchmarkState.selected;
    const options={plans:benchmarkState.plans,selected,readOnly:location.origin!=='http://127.0.0.1:8795',onPreviewLinkURL:'http://127.0.0.1:8795/workbench/#benchmarks',
      onPrepare:async()=>{const plan=await benchmarkPost('prepare',{});await loadBenchmarkData(plan.plan_id);return benchmarkState.selected;},
      onStart:async(plan_id,plan_hash)=>{const command_id='cpu-'+(crypto.randomUUID?crypto.randomUUID():String(Date.now())+'-'+Math.random().toString(16).slice(2));const started=await benchmarkPost('start',{plan_id,plan_hash,consent:true,command_id});benchmarkState.selected={...benchmarkState.selected,...started};benchmarkUntil=Date.now()+195000;benchmarkPoll();return benchmarkState.selected;},
      onRefresh:async id=>{const result=await loadBenchmarkData(id);if(benchmarkState.selected?.status==='running'){benchmarkUntil=Math.max(benchmarkUntil,Date.now()+15000);benchmarkPoll();}return result;}};
    if(benchmarkInstance)benchmarkInstance.update(options);else benchmarkInstance=window.FrontierBenchmark.mount($('library-workspace'),options);
    if(selected?.result_id){const a=el('a','Скачать протокол, выдачи и метрики ↗','paper-link');a.href='/api/benchmarks/lexical/'+encodeURIComponent(selected.plan_id)+'/export';a.target='_blank';a.rel='noopener';const old=$('library-workspace').querySelector('[data-benchmark-export]');old?.remove();a.dataset.benchmarkExport='true';$('library-workspace').append(a);}
  }
  async function loadResearch() {
    if(state.research||!state.run)return;const id=state.run.id,epoch=state.epoch;
    const pending=researchReads.get(id)||api('/api/runs/'+id+'/research');researchReads.set(id,pending);
    try{const research=await pending;if(epoch!==state.epoch||id!==state.run?.id)return;state.research=research;const known=cache.get(id);if(known)known.research=research;renderReadiness();if(state.space==='study'&&state.lens==='comparison')renderComparison();else if(state.space!=='study')paintLibrary();}
    catch(e){if(epoch===state.epoch&&state.lens==='comparison')$('inspector').append(el('p','Рецепт недоступен: '+e.message,'warning'));}
    finally{if(researchReads.get(id)===pending)researchReads.delete(id);}
  }
  function render() {
    const run=state.run,p=state.p||{};
    $('study-title').textContent=str(p.title)||shortTitle(run);$('study-summary').textContent=str(p.summary,500)||'Данные выбранного плана. Готовый разбор ещё не сохранён.';
    $('study-status').textContent=labels[run.status]||'Статус не установлен';$('study-date').textContent=date(run.finished_at||run.created_at);
    $('study-verdict').textContent=str(p.public_takeaway||p.verdict,1200)||'Прикладной вывод ещё не сохранён.';
    const target='http://127.0.0.1:8795/?run='+encodeURIComponent(run.id);$('open-lab').href=target;$('open-report').href=target;$('open-evidence').href=target+'&mode=evidence';
    $('workspace').hidden=false;renderTracks();renderLens();renderReadiness();setSpace(state.space);loadResearch();
  }
  async function select(id, refresh=false) {
    if(!/^[a-f0-9]{32}$/.test(id))return;stop();const epoch=++state.epoch;state.abort?.abort();state.abort=new AbortController();state.loading=true;error('');$('workspace').hidden=true;$('loading-panel').hidden=false;
    state.run=null;state.p=null;state.research=null;state.quality=null;
    try{
      let saved=!refresh?cache.get(id):null;
      if(!saved){const hint=state.runs.find(r=>r.id===id),results=await Promise.allSettled([api('/api/runs/'+id,state.abort.signal),hint?.status==='completed'?api('/api/runs/'+id+'/presentation',state.abort.signal):Promise.resolve(null),api('/api/runs/'+id+'/quality',state.abort.signal)]);if(epoch!==state.epoch)return;if(results[0].status!=='fulfilled')throw results[0].reason;saved={run:results[0].value,p:results[1].status==='fulfilled'?results[1].value:null,quality:results[2].status==='fulfilled'?results[2].value:null,research:null};const failures=results.slice(1).filter(r=>r.status==='rejected');if(failures.length)error('Часть сохранённых данных недоступна. Схемы и подтверждения для них не подставляются.');else{cache.set(id,saved);while(cache.size>8)cache.delete(cache.keys().next().value);}}
      if(epoch!==state.epoch)return;Object.assign(state,saved);state.loading=false;$('connection-status').textContent='Ваши сохранённые данные · только чтение';render();
    }catch(e){if(epoch!==state.epoch||e.name==='AbortError')return;error('Не удалось открыть исследование: '+e.message);$('connection-status').textContent='Нет подключения к данным';}
    finally{if(epoch===state.epoch){state.loading=false;$('loading-panel').hidden=true;}}
  }
  async function start(refresh=false) {
    $('connection-status').textContent='Читаем сохранённые исследования…';error('');
    try{const results=await Promise.allSettled([api('/api/runs'),api('/api/publication')]);if(results[0].status!=='fulfilled')throw results[0].reason;const old=state.run?.id;state.runs=arr(results[0].value.items);state.queue=results[1].status==='fulfilled'?results[1].value:null;$('count-runs').textContent=String(state.runs.length);const selectEl=$('research-select');selectEl.replaceChildren();for(const run of state.runs){const option=el('option',shortTitle(run)+' · '+(labels[run.status]||run.status));option.value=run.id;selectEl.append(option);}
      if(!state.runs.length){state.run=null;state.p=null;stop();$('loading-panel').hidden=true;$('workspace').hidden=true;error('Сохранённых исследований пока нет. Добавьте материал в действующей лаборатории.');$('connection-status').textContent='История пуста';return;}
      const id=state.runs.find(r=>r.id===old)?.id||state.runs.find(r=>r.status==='completed')?.id||state.runs[0].id;selectEl.value=id;await select(id,refresh);
    }catch(e){state.run=null;state.p=null;state.quality=null;state.research=null;stop();$('workspace').hidden=true;$('loading-panel').hidden=true;error('Лаборатория на порту 8795 недоступна. '+e.message);$('connection-status').textContent='Нет подключения к лаборатории';}
  }
  $('research-select').addEventListener('change',e=>select(e.target.value));$('refresh-button').addEventListener('click',()=>{state.knowledge=null;state.workspace=null;start(true);});
  for(const b of $('space-tabs').querySelectorAll('button'))b.addEventListener('click',()=>setSpace(b.dataset.space));
  for(const b of $('lens-tabs').querySelectorAll('button'))b.addEventListener('click',()=>{if(!state.run)return;state.lens=b.dataset.lens;renderLens();if(state.lens==='comparison')loadResearch();});
  $('lens-tabs').addEventListener('keydown',e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;const buttons=[...$('lens-tabs').querySelectorAll('button')],index=buttons.indexOf(document.activeElement);if(index<0)return;e.preventDefault();const next=e.key==='Home'?0:e.key==='End'?buttons.length-1:(index+(e.key==='ArrowRight'?1:-1)+buttons.length)%buttons.length;buttons[next].focus();buttons[next].click();});
  $('graph-step').addEventListener('click',nextEdge);$('graph-play').addEventListener('click',animate);
  document.addEventListener('visibilitychange',()=>{if(document.hidden){stop();clearTimeout(benchmarkTimer);benchmarkTimer=null;}else benchmarkPoll();});window.addEventListener('pagehide',()=>{stop();clearTimeout(benchmarkTimer);});
  window.FrontierFieldwork={snapshot:()=>({runId:state.run?.id||null,lens:state.lens,space:state.space,loading:state.loading,playing:state.playing,evidenceCount:arr(state.p?.evidence).length,readiness:state.research?.readiness?.stage||null,benchmarkId:benchmarkState.selected?.plan_id||null,benchmarkStatus:benchmarkState.selected?.status||null,readOnly:state.space!=='benchmarks'||location.origin!=='http://127.0.0.1:8795'})};
  start();
})();
