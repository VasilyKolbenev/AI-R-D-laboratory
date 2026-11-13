/* Published claims, locally recomputed prevalence. GET-only: no model or publication actions. */
(function () {
  'use strict';
  const arr = value => Array.isArray(value) ? value : [];
  const obj = value => value && typeof value === 'object' && !Array.isArray(value) ? value : {};
  const text = value => typeof value === 'string' ? value.trim() : typeof value === 'number' && Number.isFinite(value) ? String(value) : '';
  const finite = value => typeof value === 'number' && Number.isFinite(value);
  const fmt = (value, digits = 0) => finite(value) ? value.toLocaleString('ru-RU', {maximumFractionDigits: digits}) : '—';
  const percent = value => finite(value) ? fmt(value, 2) + ' %' : '—';
  const delta = value => finite(value) ? (value > 0 ? '+' : '') + fmt(value, 2) + ' п.п.' : '—';
  const NS = 'http://www.w3.org/2000/svg';
  function el(tag, value, cls) { const node = document.createElement(tag); if (value !== undefined && value !== null) node.textContent = String(value); if (cls) node.className = cls; return node; }
  function add(parent, ...children) { for (const child of children.flat()) if (child) parent.append(child); return parent; }
  function button(label, action, cls = 'fc-button') { const node = el('button', label, cls); node.type = 'button'; node.addEventListener('click', action); return node; }
  function badge(label, cls = '') { return el('span', label, 'fc-badge ' + cls); }
  function svg(tag, attrs, value) { const node = document.createElementNS(NS, tag); for (const [key,item] of Object.entries(attrs || {})) node.setAttribute(key, String(item)); if (value !== undefined) node.textContent = String(value); return node; }
  function link(value, label, cls = 'fc-source-link') {
    try {
      const url = new URL(value);
      if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password ||
          !['aclanthology.org', 'arxiv.org', 'huggingface.co', 'github.com', 'doi.org'].includes(url.hostname.toLowerCase())) return null;
      const node = el('a', label || url.hostname, cls); node.href = url.href; node.target = '_blank'; node.rel = 'noopener noreferrer'; return node;
    } catch (_) { return null; }
  }
  function empty(title, detail) { return add(el('div', undefined, 'fc-empty'), el('strong', title), detail ? el('p', detail) : null); }
  function disclosure(label, ...children) { return add(el('details'), el('summary', label), ...children); }
  function facts(rows) { const node = el('dl', undefined, 'fc-source-facts'); for (const [key,value] of rows) add(node, el('dt', key), el('dd', text(value) || 'Не опубликовано')); return node; }
  function topicName(topic) { return text(topic?.name) || text(topic?.full_name) || (topic?.id === -1 ? 'Вне тематических групп' : 'Тема без названия'); }
  function points(topic) { return arr(topic?.trajectory).filter(p => finite(p.year)).slice().sort((a,b) => a.year - b.year); }
  function change(topic) { if (finite(topic?.delta_pp)) return topic.delta_pp; const rows = points(topic); return rows.length && finite(rows[0].share) && finite(rows.at(-1).share) ? rows.at(-1).share - rows[0].share : null; }

  function validTrendSeries(value) {
    if (!Array.isArray(value) || !value.length || value.length > 1001) return false;
    const ids = new Set(), reference = value[0]?.points;
    if (!Array.isArray(reference) || reference.length < 2 || reference.length > 100) return false;
    return value.every(series => {
      if (!Number.isInteger(series?.id) || ids.has(series.id) || !Array.isArray(series.points) || series.points.length !== reference.length) return false;
      ids.add(series.id);
      return series.points.every((point, index, rows) => Number.isInteger(point?.year) && point.year === reference[index]?.year &&
        (!index || point.year > rows[index - 1].year) && Number.isInteger(point.numerator) && Number.isInteger(point.denominator) &&
        point.denominator > 0 && point.denominator === reference[index]?.denominator && point.numerator >= 0 && point.numerator <= point.denominator &&
        finite(point.share) && point.share >= 0 && point.share <= 100 && Math.abs(point.share - point.numerator * 100 / point.denominator) <= 0.00005001);
    });
  }

  function visualSpec(value, snapshotId) {
    const spec=obj(value),blocks=arr(spec.blocks),kinds=new Set(['corpus_overview','trend_lines','topic_table','applicability','evidence_ledger']);
    if(spec.version!=='visual-spec-v1'||spec.subject?.type!=='corpus'||spec.subject.id!==snapshotId||spec.input_binding?.snapshot_id!==snapshotId||!blocks.length||blocks.length>24||new Set(blocks.map(block=>block?.id)).size!==blocks.length)return null;
    if(blocks.some(block=>!text(block?.id)||!kinds.has(block.kind)||typeof block.selected!=='boolean'||typeof block.available!=='boolean'))return null;
    const primary=blocks.find(block=>block.id===spec.primary_block_id&&block.selected&&block.available);
    if(!primary||!['corpus_overview','trend_lines','topic_table'].includes(primary.kind))return null;
    const trend=blocks.find(block=>block.kind==='trend_lines'&&block.selected&&block.available);
    if(trend&&(trend.data?.unit!=='percent'||trend.data?.quantity!=='distinct_paper_share'||!validTrendSeries(trend.data?.series)))return null;
    return {...spec,primary,block:kind=>blocks.find(block=>block.kind===kind&&block.selected&&block.available)};
  }

  function mount(host, options = {}) {
    if (!host || typeof host.replaceChildren !== 'function') throw new TypeError('FrontierCorpus.mount: нужен DOM-контейнер.');
    let destroyed = false, data = null, currentTopic = null, currentYear = null, currentCohort = 'numerator',
      currentOffset = 0, currentPaper = null, search = '', loading = false, overviewEpoch = 0,
      topicEpoch = 0, paperEpoch = 0, allClaims = false, selectedPaperId = null, visual = null,
      activeChart = null, chartObserver = null, chartDeadline = null, trendEpoch = 0, resizeFrame = null, renderer = 'native_dom_svg', rendererState = 'fallback', rendererReason = '';
    const controllers = new Set();
    const root = el('section', undefined, 'fc-corpus');
    root.dataset.corpusView = 'true'; host.replaceChildren(root);
    const message = el('div', undefined, 'fc-message'); message.hidden = true; message.setAttribute('role', 'status');
    const overview = el('div'), content = el('div'), methods = el('details', undefined, 'fc-methods');
    const topicsHost = el('aside', undefined, 'fc-topic-list'); topicsHost.setAttribute('aria-label', 'Темы научных вкладов');
    const trendHost = el('section', undefined, 'fc-trend'); trendHost.setAttribute('aria-label', 'Динамика выбранной темы');
    const papersHost = el('section', undefined, 'fc-papers'); papersHost.setAttribute('aria-label', 'Статьи выбранной точки');
    const sourceHost = el('aside', undefined, 'fc-source'); sourceHost.setAttribute('aria-label', 'Статья и импортированные утверждения');
    sourceHost.tabIndex = -1;
    const searchInput = el('input'); searchInput.type = 'search'; searchInput.placeholder = 'Например: reasoning, retrieval, agents'; searchInput.autocomplete = 'off'; searchInput.dataset.corpusControl='topic-search';searchInput.setAttribute('aria-label', 'Найти тему по названию или описанию');
    let listData = null;
    const detailStates = new Map();
    root.addEventListener('toggle',event=>{const node=event.target;if(node.matches?.('details[data-corpus-detail]')&&root.contains(node))detailStates.set(node.dataset.corpusDetail,node.open);},true);
    function details(key,label,...children) {
      const node=disclosure(label,...children);node.dataset.corpusDetail=key;node.open=detailStates.get(key)===true;
      node.querySelector('summary').dataset.corpusControl='detail-'+key;return node;
    }
    function rememberDetails() { for(const node of root.querySelectorAll('details[data-corpus-detail]'))detailStates.set(node.dataset.corpusDetail,node.open); }
    function focusKey() {return root.contains(document.activeElement)?document.activeElement?.dataset?.corpusControl:null;}
    function restoreFocus(key) {if(key)[...root.querySelectorAll('[data-corpus-control]')].find(node=>node.dataset.corpusControl===key)?.focus({preventScroll:true});}
    function topicPoints(topic) {
      const series=visual?.block('trend_lines')?.data?.series;
      if(series)return points({trajectory:series.find(item=>String(item?.id)===String(topic?.id))?.points});
      if(visual)return [];
      return points(topic);
    }
    function topicChange(topic) {if(!visual)return change(topic);const rows=topicPoints(topic);return rows.length&&finite(rows[0].share)&&finite(rows.at(-1).share)?rows.at(-1).share-rows[0].share:null;}
    function visualDisclosure() {
      const runtime = renderer === 'antv_g2' ? 'Фактический рендерер: AntV G2 5.4.8 · локальная библиотека. Нативные подсказка и перекрестие; клик по точке раскрывает статьи выбранного года.' :
        rendererState === 'loading' ? 'Подготавливается AntV G2. Значения и кнопки годов уже доступны.' :
        'Фактический рендерер: встроенный HTML/SVG. ' + rendererReason + ' Значения и точные статьи доступны через кнопки годов.';
      if(!visual)return details('visual-choice','Почему этот визуал',el('p','VisualSpec отсутствует, повреждён или его версия не поддерживается. Запасной вид: trend_lines из опубликованной траектории. Неизвестные значения не заменяются нулём.'),el('p',runtime));
      const primary=visual.primary,body=[el('p','Выбранный вид: '+primary.kind+'. '+text(primary.reason)),
        el('p','Происхождение: '+(text(primary.provenance?.origin)||'не указано')+'.'),
        el('p',runtime)];
      for(const choice of arr(visual.choices).filter(choice=>choice?.status==='deferred'))body.push(el('p',(text(choice.kind)||'Отложенный визуал')+': '+text(choice.reason)));
      return details('visual-choice','Почему этот визуал',...body);
    }

    function setRenderer(name, state, reason = '', chartHost = null) {
      renderer = name; rendererState = state; rendererReason = reason;
      for (const node of [root, trendHost, chartHost].filter(Boolean)) {
        node.dataset.corpusRenderer = name; node.dataset.corpusRendererState = state;
        node.dataset.corpusRendererReason = reason;
        if (name === 'antv_g2') node.dataset.corpusRendererVersion = '5.4.8'; else delete node.dataset.corpusRendererVersion;
      }
      const previous = trendHost.querySelector('.fc-visual-choice');
      if (previous) { const focus=focusKey();rememberDetails();const next=visualDisclosure();next.classList.add('fc-visual-choice');previous.replaceWith(next);restoreFocus(focus); }
    }
    function disposeTrend() {
      ++trendEpoch;
      if (chartDeadline !== null) { clearTimeout(chartDeadline); chartDeadline = null; }
      if (chartObserver) { chartObserver.disconnect(); chartObserver = null; }
      if (resizeFrame !== null) { cancelAnimationFrame(resizeFrame); resizeFrame = null; }
      const chart = activeChart; activeChart = null;
      if (chart) { try { Promise.resolve(chart.destroy()).catch(() => {}); } catch (_) { /* A failed renderer must not interrupt the evidence browser. */ } }
    }

    function setMessage(value) { message.hidden = !value; message.textContent = value || ''; }
    async function read(path) {
      const url = new URL(path, location.origin);
      if (url.origin !== location.origin || !/^\/api\/corpus(?:\/topics\/-?\d+|\/papers\/[A-Za-z0-9._:-]+)?$/.test(url.pathname)) throw new Error('Неизвестный адрес корпуса.');
      for (const key of url.searchParams.keys()) if (!['year', 'offset', 'limit', 'cohort'].includes(key)) throw new Error('Неизвестный фильтр корпуса.');
      const controller = new AbortController(); controllers.add(controller);
      try {
        const response = await fetch(url.pathname + url.search, {method: 'GET', credentials: 'same-origin', cache: 'no-store', signal: controller.signal, headers: {Accept: 'application/json'}});
        const value = await response.json();
        if (!response.ok) throw new Error(text(value.error) || 'Не удалось прочитать корпус.');
        return value;
      } finally { controllers.delete(controller); }
    }
    function cancel() { for (const controller of controllers) controller.abort(); controllers.clear(); }
    function topics() { return arr(data?.topics).filter(topic => Number.isInteger(topic.id)); }
    function topicById(id) { return topics().find(topic => topic.id === id); }
    function yearPoint() { return topicPoints(currentTopic).find(row => row.year === currentYear); }
    function setSourceLoading() { sourceHost.replaceChildren(el('span', 'ИСТОЧНИК / ORIGINAL TEXT', 'fc-eyebrow'), el('p', 'Читаем статью и утверждения…', 'fc-muted')); }
    function clearSource() { sourceHost.replaceChildren(el('span', 'ОБСЕРВАТОРИЯ / ИСТОЧНИК', 'fc-eyebrow'), empty('Раскрыть до статьи', 'Выбери работу слева: здесь появятся утверждения, аннотация и первоисточник.')); }

    function drawOverview() {
      const corpus = obj(data?.corpus), counts = obj(corpus.counts), provenance = obj(corpus.provenance), reproduction = obj(corpus.reproduction);
      const heading = add(el('header', undefined, 'fc-head'), add(el('div'), el('span', 'CORPUS / DRIFT INSPECTOR', 'fc-eyebrow'), el('h2', 'Корпус исследований')),
        add(el('div', undefined, 'fc-head-actions'), badge('Внешнее модельное извлечение', 'fc-neutral'),
          badge(reproduction.matched === true ? 'Агрегаты сверены' : 'Сверка требует внимания', reproduction.matched === true ? '' : 'fc-attention')));
      const stats = el('div', undefined, 'fc-overview');
      for (const [value,label] of [[counts.papers,'статей импортировано'],[counts.claims,'утверждений авторов'],[counts.analytic_papers,'статей в расчёте трендов'],[counts.topics,'тематических групп']]) {
        stats.append(add(el('div', undefined, 'fc-stat'), el('strong', fmt(value)), el('span', label)));
      }
      const scope = add(el('p', undefined, 'fc-scope'), el('strong', 'EMNLP · 2020–2025 · фиксированная выборка'), document.createTextNode(' ' + fmt(counts.analytic_claims) + ' утверждений в расчёте. Импорт корпуса не запускает модели.'));
      const toolbar = add(el('div', undefined, 'fc-toolbar'), add(el('label', undefined, 'fc-search'), el('span', 'Найти направление'), searchInput), scope);
      overview.replaceChildren(heading, stats, toolbar);
      methods.replaceChildren(el('summary', 'Как получены данные и что означает график'));
      const grid = el('div', undefined, 'fc-method-grid');
      grid.append(add(el('section'), el('h4', 'Источник и версии'),
        el('p', text(corpus.title) || 'Drift Inspector · EMNLP 2020–2025'),
        link(provenance.dataset_url, 'Открытый корпус авторов ↗'), link(provenance.paper_url, 'Методика Drift Inspector ↗'),
        el('p', 'Лицензия данных: ' + (text(provenance.license) || 'не указана') + '. ' + (text(provenance.publisher) || 'Авторы Drift Inspector') + '.', 'fc-muted'),
        el('p', 'Снимок ' + (text(corpus.revision) || text(provenance.revision) || 'не зафиксирован'), 'fc-hash')));
      grid.append(add(el('section'), el('h4', 'Единица измерения'),
        el('p', 'Доля уникальных статей года хотя бы с одним утверждением в теме. Несколько утверждений одной статьи дают один голос в этой теме.'),
        el('p', 'Темы могут пересекаться: их проценты не обязаны складываться в 100 %. Рост отражает внимание исследователей, а не доказанный выигрыш технологии.')));
      grid.append(add(el('section'), el('h4', 'Границы выборки'),
        el('p', 'Для трендов используется годовая сбалансированная выборка авторов. Полный импорт и аналитическая выборка показаны отдельно. Это корпус конкретной конференции, а не вся наука об ИИ.'),
        el('p', 'Неклассифицированные утверждения сохранены отдельно. Отсутствие утверждений или назначения темы не считается отсутствием научного вклада.')));
      const validation = add(el('section'), el('h4', 'Что проверено здесь'),
        el('p', reproduction.matched === true ? 'Доли пересчитаны из импортированных назначений тем и сверены с опубликованным снимком. Извлечение и кластеризация заново не выполнялись.' : 'Импортированные данные доступны для чтения; совпадение агрегатов требует проверки.'),
        el('p', 'Утверждения и названия тем подготовлены авторами корпуса. Точная цитатная привязка для каждого утверждения не опубликована; независимая проверка истины здесь не выполнялась.'));
      if (finite(reproduction.comparisons)) validation.append(el('p', 'Сопоставлено значений: ' + fmt(reproduction.comparisons) + '. Максимальное расхождение: ' + (finite(reproduction.max_abs_diff_pp) ? fmt(reproduction.max_abs_diff_pp, 8) + ' п.п.' : 'не указано') + '.'));
      grid.append(validation); methods.append(grid);
      for (const notice of arr(corpus.notices)) if (text(notice)) methods.append(el('p', text(notice)));
      options.onSummary?.(fmt(counts.papers) + ' статей · ' + fmt(counts.claims) + ' утверждений · внешний корпус');
    }

    function drawTopics() {
      const needle = search.trim().toLocaleLowerCase('ru-RU');
      const visible = topics().filter(topic => !needle || [topic.name,topic.full_name,topic.description].map(text).join(' ').toLocaleLowerCase('ru-RU').includes(needle));
      const list = el('div', undefined, 'fc-topic-list-scroll');
      const max = Math.max(1, ...visible.map(topic => finite(topicPoints(topic).at(-1)?.share) ? topicPoints(topic).at(-1).share : 0));
      for (const topic of visible) {
        const item = button('', () => selectTopic(topic.id), 'fc-topic'); item.dataset.topicId = String(topic.id); item.setAttribute('aria-pressed', String(currentTopic?.id === topic.id));
        const last = topicPoints(topic).at(-1), difference = topicChange(topic), differenceNode = el('span', delta(difference), 'fc-topic-change'); differenceNode.dataset.negative = String(difference < 0);
        const bar = el('span', undefined, 'fc-topic-bar'), fill = el('span'); fill.style.width = (finite(last?.share) ? Math.min(100, Math.max(0, last.share / max * 100)) : 0) + '%'; bar.append(fill);
        const trends=!visual||visual.block('trend_lines');
        add(item, el('span', topicName(topic), 'fc-topic-title'),trends?add(el('span', undefined, 'fc-topic-bottom'), el('span', percent(last?.share)), differenceNode):null,trends?bar:null);
        list.append(item);
      }
      if (!visible.length) list.append(empty('Тема не найдена', 'Попробуй английское название направления.'));
      topicsHost.replaceChildren(add(el('div', undefined, 'fc-topic-list-head'), el('span', 'ТЕМЫ / EN'), el('span', fmt(visible.length))), list);
    }

    function nativeTrend(topic, rows) {
      const valid = rows.filter(row => finite(row.share) && row.share >= 0 && row.share <= 100);
      if (!valid.length) return empty('Недостаточно данных для линии', 'Неизвестные значения не заменяются нулём.');
      const width = root.clientWidth < 570 ? 400 : 680, height = 265, left = 42, right = 30, top = 30, bottom = 35;
      const max = Math.min(100, Math.max(1, ...valid.map(row => row.share)) * 1.18);
      const x = index => left + (rows.length > 1 ? index / (rows.length - 1) : .5) * (width-left-right);
      const y = value => height-bottom-(value/max)*(height-top-bottom);
      const chart = svg('svg', {viewBox: '0 0 ' + width + ' ' + height, role:'img', 'aria-label':topicName(topic) + ': доля уникальных статей по годам. Кнопки годов под графиком открывают точные статьи.'});
      for (const value of [0, max/2, max]) add(chart, svg('line', {x1:left,y1:y(value),x2:width-right,y2:y(value),class:'fc-chart-grid'}), svg('text',{x:0,y:y(value)+4,class:'fc-chart-axis'},fmt(value,1)+'%'));
      const coordinates = rows.map((row,index) => finite(row.share) && row.share >= 0 && row.share <= 100 ? [x(index),y(row.share)] : null);
      let line = '', area = '', segment = [];
      function finishSegment() { if (!segment.length) return; line += segment.map((point,index) => (index ? 'L':'M') + point.join(',')).join(' '); area += 'M' + segment[0][0] + ',' + y(0) + ' ' + segment.map(point => 'L' + point.join(',')).join(' ') + ' L' + segment.at(-1)[0] + ',' + y(0) + ' Z '; segment = []; }
      for (const point of coordinates) { if (point) segment.push(point); else finishSegment(); } finishSegment();
      add(chart, svg('path',{d:area,class:'fc-chart-area'}), svg('path',{d:line,class:'fc-chart-line'}));
      rows.forEach((row,index) => {
        const point = coordinates[index]; if (!point) return;
        const dot = svg('circle',{cx:point[0],cy:point[1],r:6,class:'fc-chart-dot',tabindex:0,role:'button','aria-pressed':String(currentYear===row.year),'aria-label':row.year+': '+percent(row.share)+', '+fmt(row.numerator)+' из '+fmt(row.denominator)+' статей','data-selected':String(currentYear===row.year),'data-corpus-control':'point-'+row.year});
        dot.append(svg('title',{},row.year+': '+fmt(row.numerator)+' / '+fmt(row.denominator)+' · '+percent(row.share)));
        dot.addEventListener('click',()=>selectYear(row.year)); dot.addEventListener('keydown',event=>{if(['Enter',' '].includes(event.key)){event.preventDefault();selectYear(row.year);}});
        add(chart, svg('text',{x:point[0],y:point[1]-16,'text-anchor':'middle',class:'fc-chart-value'},percent(row.share)),dot,svg('text',{x:point[0],y:height-9,'text-anchor':'middle',class:'fc-chart-label'},row.year));
      });
      return chart;
    }

    async function renderG2(chartHost, topic, rows, generation, revealTooltip) {
      let chart, deadline = null, pointerType = '';
      const isCurrent = () => !destroyed && generation === trendEpoch && chartHost.isConnected;
      try {
        chartHost.addEventListener('pointerdown',event=>{pointerType=event.pointerType;},{passive:true});
        const compact = chartHost.clientWidth < 500;
        chart = new window.G2.Chart({container:chartHost,autoFit:false,width:chartHost.clientWidth,height:chartHost.clientHeight});
        activeChart = chart;
        const tooltip = {title:datum=>String(datum.year),items:[
          {field:'share',name:'Доля статей',valueFormatter:percent},
          {field:'numerator',name:'С темой · уникальных',valueFormatter:value=>fmt(value)},
          {field:'denominator',name:'Всего за год · уникальных',valueFormatter:value=>fmt(value)}]};
        chart.options({
          type:'view',data:rows,animate:false,paddingTop:24,paddingRight:24,paddingBottom:34,paddingLeft:compact?46:54,
          theme:{type:'dark',view:{viewFill:'transparent',plotFill:'transparent'},defaultColor:'#dbff71'},
          encode:{x:'year',y:'share'},
          scale:{x:{type:'linear',domain:[rows[0].year,rows.at(-1).year],tickMethod:()=>rows.map(row=>row.year),nice:false},
            y:{type:'linear',domain:[0,Math.min(100,Math.max(1,...rows.map(row=>row.share))*1.22)],nice:true}},
          axis:{
            x:{title:false,line:false,tick:false,grid:false,labelFill:'#b7bea9',labelFontSize:12,labelFontFamily:'Segoe UI, sans-serif',labelFormatter:value=>String(Math.round(Number(value))),labelAutoHide:false,labelAutoRotate:false},
            y:{title:false,line:false,tick:false,grid:true,gridStroke:'#3a4132',gridLineDash:[3,6],gridStrokeOpacity:.8,labelFill:'#939e83',labelFontSize:11,labelFormatter:value=>fmt(Number(value),1)+' %'}
          },
          legend:false,
          interaction:{tooltip:{series:true,shared:false,crosshairs:true,crosshairsX:false,crosshairsYStroke:'#b4c591',crosshairsYLineDash:[4,4],marker:true,markerFill:'#dbff71',markerStroke:'#1b2018',markerLineWidth:2,offset:[12,12],
            render:(_event,options)=>{
              const node = el('div',undefined,'fc-g2-tooltip'); node.setAttribute('role','tooltip');
              add(node,el('strong',text(options.title)+' · аналитическая выборка','fc-g2-tooltip-title'));
              const list = el('dl');
              for (const item of arr(options.items)) add(list,el('dt',text(item.name)),el('dd',text(item.value)));
              return add(node,list,el('span','Нажми точку → точные статьи','fc-g2-tooltip-hint'));
            }}},
          children:[
            {type:'area',style:{fill:'#dbff71',fillOpacity:.075},tooltip:false,animate:false},
            {type:'line',style:{stroke:'#dbff71',lineWidth:3,lineCap:'round',lineJoin:'round'},tooltip,animate:false},
            {type:'lineX',data:rows.filter(row=>row.year===currentYear),encode:{x:'year'},style:{stroke:'#dbff71',strokeOpacity:.38,lineDash:[3,6],lineWidth:1},tooltip:false,animate:false},
            {type:'point',encode:{shape:'point',size:5},style:{fill:'#20261a',stroke:'#dbff71',lineWidth:2,cursor:'pointer'},tooltip:false,animate:false},
            {type:'point',data:rows.filter(row=>row.year===currentYear),encode:{shape:'point',size:7},style:{fill:'#dbff71',stroke:'#20261a',lineWidth:3,cursor:'pointer'},tooltip:false,animate:false}
          ]
        });
        chart.on('point:click',event=>{const row=event?.data?.data;if(isCurrent()&&Number.isInteger(row?.year)&&rows.some(point=>point.year===row.year))selectYear(row.year,pointerType==='touch');});
        await Promise.race([chart.render(),new Promise((_,reject)=>{deadline=setTimeout(()=>reject(new Error('Chart render timeout')),6000);chartDeadline=deadline;})]);
        if (!isCurrent() || activeChart !== chart) return;
        chartHost.querySelector('canvas')?.setAttribute('aria-hidden','true');
        chartHost.removeAttribute('aria-busy');
        setRenderer('antv_g2','ready','',chartHost);
        if (revealTooltip) chart.emit('tooltip:show',{data:{data:{x:currentYear}}});
        if (typeof ResizeObserver === 'function') {
          let width=chartHost.clientWidth,height=chartHost.clientHeight,resizing=false,repeat=false;
          const fit=async()=>{
            resizeFrame=null;
            if (!isCurrent() || activeChart!==chart) return;
            if (resizing) { repeat=true;return; }
            const nextWidth=chartHost.clientWidth,nextHeight=chartHost.clientHeight;
            if (!nextWidth || !nextHeight || (width===nextWidth&&height===nextHeight)) return;
            width=nextWidth;height=nextHeight;resizing=true;
            try { await chart.changeSize(width,height); }
            catch (_) {
              if (isCurrent()&&activeChart===chart) {disposeTrend();chartHost.replaceChildren(nativeTrend(topic,rows));chartHost.classList.add('fc-chart-fallback');setRenderer('native_dom_svg','fallback','AntV G2 не смог обновить размер графика.',chartHost);}
            } finally {resizing=false;if(repeat&&isCurrent()){repeat=false;resizeFrame=requestAnimationFrame(fit);}}
          };
          chartObserver=new ResizeObserver(()=>{if(!isCurrent())return;if(resizeFrame!==null)cancelAnimationFrame(resizeFrame);resizeFrame=requestAnimationFrame(fit);});
          chartObserver.observe(chartHost);
        }
      } catch (_) {
        if (!isCurrent()) return;
        if (activeChart === chart) activeChart = null;
        try { if(chart) await chart.destroy(); } catch (_) { /* Continue with the bounded native fallback. */ }
        if (!isCurrent()) return;
        chartHost.replaceChildren(nativeTrend(topic,rows));chartHost.classList.add('fc-chart-fallback');chartHost.removeAttribute('aria-busy');
        setRenderer('native_dom_svg','fallback','AntV G2 не смог построить график в этом окружении.',chartHost);
      } finally {
        if (deadline !== null) clearTimeout(deadline);
        if (chartDeadline === deadline) chartDeadline = null;
      }
    }

    function drawTrend(revealTooltip = false) {
      rememberDetails();const focus=focusKey(),topic=currentTopic,rows=topicPoints(topic),difference=topicChange(topic);
      disposeTrend();
      if (!topic) { setRenderer('native_dom_svg','empty','Нет выбранной темы.');trendHost.replaceChildren(empty('Выбери направление', 'Показатели раскроются до утверждений и статей.'));return; }
      const changeNode=el('div',delta(difference),'fc-trend-delta');changeNode.dataset.negative=String(difference<0);changeNode.append(el('small',rows.length?rows[0].year+' → '+rows.at(-1).year+' · доля статей':'Изменение доли'));
      const trends=!visual||visual.block('trend_lines');
      const heading=add(el('div',undefined,'fc-trend-head'),add(el('div'),el('span',topic.is_noise?'ШУМ В АНАЛИТИЧЕСКОЙ ВЫБОРКЕ':'ВЫБРАННОЕ НАПРАВЛЕНИЕ','fc-eyebrow'),el('h3',text(topic.full_name)||topicName(topic))),trends?changeNode:null);
      const plot=el('div',undefined,'fc-plot'),point=rows.find(row=>row.year===currentYear);
      const kicker=add(el('div',undefined,'fc-plot-kicker'),el('span',trends?'ДОЛЯ УНИКАЛЬНЫХ СТАТЕЙ':'СОХРАНЁННЫЙ СОСТАВ ВЫБОРКИ'),el('span','ТОЧКА ИЛИ ГОД → СТАТЬИ'));
      plot.append(kicker);
      if (point && trends) {
        const readout=el('div',undefined,'fc-point-readout');readout.dataset.corpusSelectedYear=String(point.year);
        add(readout,add(el('div',undefined,'fc-readout-year'),el('span','ВЫБРАННЫЙ ГОД'),el('strong',point.year)),
          add(el('div',undefined,'fc-readout-share'),el('strong',percent(point.share)),el('span','доля статей с темой')),
          add(el('div',undefined,'fc-readout-count'),el('strong',fmt(point.numerator)+' / '+fmt(point.denominator)),el('span','уникальных статей · с темой / всего')));
        plot.append(readout);
      }
      const chartHost=el('div',undefined,'fc-g2-chart');chartHost.dataset.corpusChart='trend-lines';chartHost.setAttribute('role','group');chartHost.setAttribute('aria-label',topicName(topic)+': динамика доли уникальных статей. Выбери год кнопками под графиком, чтобы открыть источники.');
      const canRender=!!(trends&&rows.some(row=>finite(row.share)&&row.share>=0&&row.share<=100));
      const useG2=canRender&&!!visual?.block('trend_lines')&&typeof window.G2?.Chart==='function';
      if (canRender) {
        if (useG2) {chartHost.setAttribute('aria-busy','true');setRenderer('native_dom_svg','loading','',chartHost);}
        else {chartHost.classList.add('fc-chart-fallback');chartHost.append(nativeTrend(topic,rows));setRenderer('native_dom_svg','fallback',visual?'Локальная библиотека AntV G2 недоступна.':'Нет валидного VisualSpec для AntV G2.',chartHost);}
        plot.append(chartHost);
      } else {setRenderer('native_dom_svg','empty','Недостаточно проверенных данных для линии.');plot.append(empty('Недостаточно данных для линии','Неизвестные значения не заменяются нулём.'));}
      const years=el('div',undefined,'fc-year-grid');years.setAttribute('role','group');years.setAttribute('aria-label','Год и точный состав выборки');
      for (const row of rows) {
        const year=button('',()=>selectYear(row.year),'fc-year');year.dataset.corpusYear=String(row.year);year.dataset.corpusControl='year-'+row.year;year.setAttribute('aria-pressed',String(currentYear===row.year));
        add(year,el('strong',row.year),el('span',percent(row.share),'fc-year-share'),el('span',fmt(row.numerator)+' / '+fmt(row.denominator),'fc-year-count'));
        year.setAttribute('aria-label',row.year+': '+percent(row.share)+', показать '+fmt(row.numerator)+' из '+fmt(row.denominator)+' уникальных статей');years.append(year);
      }
      plot.append(years,el('p','Доля отражает внимание исследователей. Рост не означает доказанный выигрыш технологии. Темы пересекаются; проценты не складываются в 100 %.','fc-chart-note'));
      trendHost.replaceChildren(heading);
      if(text(topic.description))trendHost.append(el('p',topic.description,'fc-topic-description'));
      const why=visualDisclosure();why.classList.add('fc-visual-choice');trendHost.append(plot,why);restoreFocus(focus);
      if(useG2)void renderG2(chartHost,topic,rows,trendEpoch,revealTooltip);
    }
    function drawPapers(isLoading = false) {
      const point = yearPoint();
      const label = currentCohort === 'denominator' ? 'Знаменатель: все статьи года' : 'Статьи с выбранной темой';
      const title = add(el('div', undefined, 'fc-section-head'), add(el('div'), el('span','ПРОВЕРИТЬ РАСЧЁТ / '+(currentYear || 'ВСЕ ГОДЫ'),'fc-eyebrow'),el('h4',label)),
        el('span',point ? fmt(point.numerator)+' / '+fmt(point.denominator)+' · '+percent(point.share) : '', 'fc-tally'));
      const switcher = button(currentCohort === 'denominator' ? '← Статьи с темой' : 'Показать знаменатель ('+fmt(point?.denominator)+') →', () => {
        currentCohort = currentCohort === 'numerator' ? 'denominator' : 'numerator'; currentOffset=0; loadPapers();
      },'fc-text-button');
      const list = el('div',undefined,'fc-paper-list'); list.tabIndex=0; list.setAttribute('role','region'); list.setAttribute('aria-label','Список статей выбранной точки');
      if (isLoading) list.append(el('p','Читаем точные статьи выбранной точки…','fc-loading'));
      else if (!arr(listData?.items).length) list.append(empty('В этой точке нет статей', currentCohort === 'denominator' ? 'Знаменатель не содержит записей.' : 'Нулевая доля подтверждается отсутствием назначенных статей; это не оценка качества технологии.'));
      else for (const paper of listData.items) {
        const id = text(paper.paper_id), row = button('',()=>selectPaper(id,true),'fc-paper'); row.dataset.paperId=id; row.setAttribute('aria-pressed',String(selectedPaperId===id));
        add(row,el('span',text(paper.title)||id,'fc-paper-title'),add(el('span',undefined,'fc-paper-meta'),el('span',paper.year),el('span',id),finite(paper.claim_count)?el('span',fmt(paper.claim_count)+' в теме'):null)); list.append(row);
      }
      papersHost.replaceChildren(title,switcher,list);
      if (!isLoading && listData && listData.total > 0) {
        const previous=button('← Назад',()=>{currentOffset=Math.max(0,currentOffset-20);loadPapers();}),next=button('Ещё →',()=>{currentOffset+=20;loadPapers();});
        previous.disabled=currentOffset===0;next.disabled=currentOffset+arr(listData.items).length>=listData.total;
        papersHost.append(add(el('div',undefined,'fc-pagination'),previous,el('span',fmt(currentOffset+1)+'–'+fmt(currentOffset+arr(listData.items).length)+' из '+fmt(listData.total)),next));
      }
    }

    function drawSource() {
      rememberDetails();
      if (!currentPaper) { clearSource(); return; }
      const paper=obj(currentPaper.paper), claims=arr(currentPaper.claims);
      const matching=claims.filter(claim=>claim.topic_id===currentTopic?.id);
      const ordered=[...matching,...claims.filter(claim=>claim.topic_id!==currentTopic?.id)];
      sourceHost.replaceChildren(el('span','ОБСЕРВАТОРИЯ / ORIGINAL TEXT','fc-eyebrow'),el('h4',text(paper.title)||text(paper.paper_id)),
        add(el('div',undefined,'fc-source-meta'),el('span',paper.year),el('span',text(paper.paper_id)),el('span',paper.in_analytic_sample?'В расчёте трендов':'Вне аналитической выборки')));
      const source=link(paper.url,'Открыть оригинал статьи ↗');if(source)sourceHost.append(source);
      const heading=el('div',undefined,'fc-detail-block');heading.append(el('span','УТВЕРЖДЕНИЯ / '+fmt(claims.length),'fc-eyebrow'),
        el('p','Модельное извлечение авторов корпуса. Подтверждающие цитаты не опубликованы; нашей проверки утверждений пока нет.','fc-muted'));
      const group=el('div',undefined,'fc-claims');
      for(const [index,claim]of (allClaims?ordered:ordered.slice(0,3)).entries()){
        const item=el('article',undefined,'fc-claim');item.dataset.claimId=text(claim.claim_id);
        const topicLabel=claim.topic_id===null?'Вне тематической выборки':claim.topic_id===-1?'Шум внутри выборки':text(claim.topic_name)||'Тема '+text(claim.topic_id);
        const current=claim.topic_id===currentTopic?.id;
        add(item,add(el('div',undefined,'fc-claim-index'),el('span',String(index+1).padStart(2,'0')+(current?' / ВЫБРАННАЯ ТЕМА':'')),el('span',topicLabel)),el('p',text(claim.text)||'Текст не опубликован'));
        const proof=el('p',text(claim.supporting_quote)||'Без точной цитатной привязки','fc-claim-proof');proof.dataset.missing=String(!text(claim.supporting_quote));item.append(proof);
        const proofDetails=details('claim-'+text(paper.paper_id)+'-'+text(claim.claim_id),'Происхождение утверждения',facts([['Модель извлечения',claim.extractor_model],['Версия промпта',claim.prompt_hash],['Claim ID',claim.claim_id],['Статус','Импортировано, независимо не проверено']]));item.append(proofDetails);group.append(item);
      }
      if(!claims.length)group.append(el('p','В опубликованном извлечении нет утверждений для этой статьи. Это не означает отсутствие научного вклада.','fc-muted'));
      heading.append(group);
      if(ordered.length>3)heading.append(button(allClaims?'Свернуть утверждения':'Показать все '+fmt(ordered.length)+' утверждений',()=>{allClaims=!allClaims;drawSource();},'fc-text-button'));
      sourceHost.append(heading,details('abstract-'+text(paper.paper_id),'Аннотация статьи · EN',el('p',text(paper.abstract)||'Аннотация в снимке отсутствует.')));
    }

    async function selectPaper(id, focus = false, preserve = false) {
      if (!id || destroyed) return;
      rememberDetails();const epoch=++paperEpoch;selectedPaperId=id;currentPaper=null;if(!preserve)allClaims=false;drawPapers();setSourceLoading();
      try {
        const value=await read('/api/corpus/papers/'+encodeURIComponent(id));
        if(destroyed||epoch!==paperEpoch)return;currentPaper=value;drawSource();
        if(focus){sourceHost.focus({preventScroll:true});if(matchMedia('(max-width:1200px)').matches)sourceHost.scrollIntoView({block:'start',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});}
      } catch(error) { if(destroyed||epoch!==paperEpoch||error.name==='AbortError')return;sourceHost.replaceChildren(empty('Источник не прочитан',error.message)); }
    }
    async function loadPapers(preserve = false) {
      if(!currentTopic||!currentYear||destroyed)return;
      rememberDetails();const previousId=preserve?selectedPaperId:null,epoch=++topicEpoch;++paperEpoch;selectedPaperId=previousId;currentPaper=null;listData=null;drawPapers(true);clearSource();
      const path='/api/corpus/topics/'+currentTopic.id+'?'+new URLSearchParams({year:String(currentYear),offset:String(currentOffset),limit:'20',cohort:currentCohort});
      try {
        const value=await read(path);if(destroyed||epoch!==topicEpoch)return;
        listData=value;drawPapers();if(arr(value.items).length){const id=arr(value.items).some(item=>text(item.paper_id)===previousId)?previousId:text(value.items[0].paper_id);selectPaper(id,false,preserve&&id===previousId);}
      } catch(error) { if(destroyed||epoch!==topicEpoch||error.name==='AbortError')return;papersHost.replaceChildren(empty('Статьи не прочитаны',error.message)); }
    }
    function selectYear(year,revealTooltip = false) { if(destroyed||!topicPoints(currentTopic).some(row=>row.year===year))return;currentYear=year;currentOffset=0;currentCohort='numerator';drawTrend(revealTooltip);loadPapers(); }
    function selectTopic(id) {
      const topic=topicById(id);if(!topic||destroyed)return;currentTopic=topic;currentOffset=0;currentCohort='numerator';
      if(!topicPoints(topic).some(row=>row.year===currentYear))currentYear=topicPoints(topic).at(-1)?.year||null;
      drawTopics();drawTrend();loadPapers();
    }
    async function refresh() {
      if(destroyed)return;rememberDetails();cancel();const focus=focusKey(),epoch=++overviewEpoch;++topicEpoch;++paperEpoch;loading=true;setMessage('');
      if(!data)root.replaceChildren(message,el('p','Читаем опубликованный корпус и пересчитанные тренды…','fc-loading'));
      try {
        const value=await read('/api/corpus');if(destroyed||epoch!==overviewEpoch)return;data=value;visual=visualSpec(value.visual_spec,value.corpus?.snapshot_id);
        root.dataset.corpusVisualSpec=visual?.version||'fallback';root.dataset.corpusVisualKind=visual?.primary.kind||'trend_lines';
        if(value.available!==true){disposeTrend();root.replaceChildren(empty('Корпус ещё не импортирован',text(value.message)||'Импорт готовых данных подключается отдельно. Модельные вызовы для него не нужны.'));return;}
        drawOverview();
        const layout=add(el('div',undefined,'fc-layout'),topicsHost,add(el('div',undefined,'fc-main'),trendHost,add(el('div',undefined,'fc-evidence'),papersHost,sourceHost)));
        content.replaceChildren(layout);root.replaceChildren(message,overview,content,methods);
        const selected=topicById(currentTopic?.id)||topics().filter(topic=>!topic.is_noise).sort((a,b)=>(change(b)||0)-(change(a)||0))[0]||topics()[0];
        if(selected&&selected.id===currentTopic?.id&&topicPoints(selected).some(row=>row.year===currentYear)){
          currentTopic=selected;drawTopics();drawTrend();loadPapers(true);restoreFocus(focus);
        }else if(selected)selectTopic(selected.id);else{drawTopics();drawTrend();clearSource();}
      } catch(error) { if(destroyed||epoch!==overviewEpoch||error.name==='AbortError')return;disposeTrend();root.replaceChildren(empty('Корпус недоступен',error.message),button('Повторить чтение',refresh)); }
      finally { if(epoch===overviewEpoch)loading=false; }
    }
    searchInput.addEventListener('input',()=>{search=searchInput.value;drawTopics();});
    const resize=()=>{if(!destroyed&&currentTopic&&rendererState!=='loading'&&renderer!=='antv_g2'){if(resizeFrame!==null)cancelAnimationFrame(resizeFrame);resizeFrame=requestAnimationFrame(()=>{resizeFrame=null;if(!destroyed)drawTrend();});}};window.addEventListener('resize',resize);
    refresh();
    return {refresh,destroy(){destroyed=true;++overviewEpoch;++topicEpoch;++paperEpoch;disposeTrend();cancel();if(resizeFrame!==null)cancelAnimationFrame(resizeFrame);window.removeEventListener('resize',resize);},snapshot:()=>({available:data?.available===true,topicId:currentTopic?.id??null,year:currentYear,cohort:currentCohort,paperId:selectedPaperId,loading,readOnly:true,renderer,rendererState})};
  }
  window.FrontierCorpus={mount};
})();
