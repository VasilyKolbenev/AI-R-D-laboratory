/* AntV Infographic 0.2.20 adapter. Saved VisualSpec data only; no resource/model calls. */
(() => {
  'use strict';
  const TEMPLATE = 'sequence-snake-steps-simple', ITEM = 'vv-frontier-process-v1';
  const FONT = 'Segoe UI, Arial, sans-serif', NS = 'http://www.w3.org/2000/svg';
  const clean = value => typeof value === 'string' ? value.replace(/\s+/g,' ').trim() : '';
  const roleNames = {input:'Вход',compute:'Обработка',decision:'Выбор',memory:'Память',output:'Выход',data:'Данные'};
  let configuredLibrary = null;

  // A sequence preset creates an adjacent arrow. Accept only graphs for which that
  // arrow is already present, and keep every original node/edge reference.
  function plan(graph) {
    const reject = reason => ({supported:false,reason});
    if (graph?.version !== 'dataflow-v1' || graph.kind !== 'process' || !Array.isArray(graph.nodes) || !Array.isArray(graph.edges) || graph.nodes.length < 2 || graph.nodes.length > 12) return reject('Для этой схемы линейный шаблон не подходит. Показан сохранённый граф.');
    const nodes = new Map(), incoming = new Map(), outgoing = new Map();
    for (const node of graph.nodes) {
      if (!clean(node?.id) || nodes.has(node.id) || !clean(node.label)) return reject('Узлы схемы не прошли проверку. Показан сохранённый граф.');
      nodes.set(node.id,node); incoming.set(node.id,0);
    }
    if (graph.edges.length !== nodes.size - 1) return reject('В схеме есть ветвление, цикл или отдельные узлы. Показан сохранённый граф.');
    for (const edge of graph.edges) {
      if (!nodes.has(edge?.from) || !nodes.has(edge?.to) || edge.from === edge.to || outgoing.has(edge.from) || incoming.get(edge.to) !== 0) return reject('Связи схемы не образуют одну последовательность. Показан сохранённый граф.');
      if (edge.kind !== 'data' || (clean(edge.label) && !/^(следующий шаг|next step|then)$/i.test(clean(edge.label)))) return reject('Тип или подписи связей требуют отдельного отображения. Показан сохранённый граф.');
      outgoing.set(edge.from,edge); incoming.set(edge.to,1);
    }
    const starts = [...nodes.keys()].filter(id => incoming.get(id) === 0);
    if (starts.length !== 1) return reject('В схеме нет единого начала. Показан сохранённый граф.');
    const ordered = [], edges = [], visited = new Set(); let id = starts[0];
    while (id && !visited.has(id)) {
      visited.add(id); ordered.push(nodes.get(id));
      const edge = outgoing.get(id); if (edge) edges.push(edge); id = edge?.to;
    }
    if (visited.size !== nodes.size || id) return reject('Связи схемы не образуют одну последовательность. Показан сохранённый граф.');
    return {supported:true,nodes:ordered,edges,template:TEMPLATE};
  }

  // Split an exact saved sentence at a word boundary; this is typography, not a
  // generated summary. Concatenating label and desc reconstructs the saved label.
  function phrases(value) {
    const full = clean(value), words = full.split(' '); let count = 1;
    while (count < words.length && words.slice(0,count + 1).join(' ').length <= 28) count += 1;
    while (count > 1 && /^(и|в|во|на|для|с|со|к|по|из|не|или)$/i.test(words[count - 1])) count -= 1;
    return {label:words.slice(0,count).join(' '),desc:words.slice(count).join(' ')};
  }

  function configure(lib) {
    if (configuredLibrary === lib) return;
    if (!['Infographic','jsx','registerItem','Group','Ellipse','Text','Rect','getFonts','registerFont'].every(key => typeof lib[key] === 'function') || !lib.getTemplate?.(TEMPLATE)) throw new Error('unsupported-library');
    // The pinned renderer loads all registered fonts after rendering. Empty the
    // public resource mappings before rendering so even blocked remote requests
    // are never attempted. Drawing and measurement use the local system font.
    for (const font of lib.getFonts()) {
      font.baseUrl = ''; font.fontWeight = {};
      lib.registerFont({...font,fontFamily:font.fontFamily.replace(/^['"]|['"]$/g,''),baseUrl:'',fontWeight:{}});
    }
    const h = lib.jsx;
    lib.registerItem(ITEM,{
      component:props => {
        const {datum,indexes,x = 0,y = 0,width = 220,height = 196} = props;
        const center = width / 2;
        const text = (value,attrs) => h(lib.Text,{fontFamily:FONT,fill:'#f1efe6',alignHorizontal:'center',wordWrap:true,...attrs,children:value});
        return h(lib.Group,{x,y,width,height,'data-fbrief-antv-node':datum.source_node_id,children:[
          h(lib.Rect,{width,height,fill:'transparent','data-fbrief-antv-hit':'true'}),
          h(lib.Ellipse,{x:center - 24,y:2,width:48,height:48,fill:'#d9f46e','data-fbrief-antv-disc':'true'}),
          text(String(indexes[0] + 1).padStart(2,'0'),{x:center - 24,y:2,width:48,height:48,alignVertical:'middle',fontSize:18,fontWeight:650,fill:'#20251e'}),
          text(datum.label,{x:0,y:66,width,height:48,fontSize:18,fontWeight:650,lineHeight:1.3,'data-element-type':'item-label','data-indexes':indexes}),
          text(datum.desc,{x:5,y:118,width:width - 10,height:58,fontSize:14,lineHeight:1.4,fill:'#c9cebd','data-element-type':'item-desc','data-indexes':indexes}),
          text(roleNames[datum.source_role] || '',{x:0,y:183,width,height:13,fontSize:10,fill:'#9fa88e'})
        ]});
      },composites:['label','desc']
    });
    configuredLibrary = lib;
  }

  function mount(host,options = {}) {
    const mapping = plan(options.graph), abort = new AbortController();
    let alive = true, engine = null, observer = null, raf = null, focusRaf = null, timer = null, nodeAbort = null, generation = 0, lastSize = '', selected = options.selected, pendingFocus = options.focusNodeId;
    const controls = new Map();
    const status = (renderer,reason = '') => { if (alive) options.onStatus?.({renderer,reason,template:renderer === 'antv_infographic' ? TEMPLATE : null}); };
    const clearEngine = () => { nodeAbort?.abort(); nodeAbort = null; controls.clear(); if (timer !== null) clearTimeout(timer); timer = null; try { engine?.destroy(); } catch {} engine = null; host.replaceChildren(); };
    const fail = reason => { if (!alive) return; generation += 1; clearEngine(); host.dataset.state = 'fallback'; status('native_dom_svg',reason); };
    const select = id => {
      selected = id;
      for (const [key,node] of controls) { node.classList.toggle('is-selected',key === id); node.setAttribute('aria-pressed',String(key === id)); }
    };
    const instance = {
      select,pause:() => {},
      destroy:() => { if (!alive) return; alive = false; generation += 1; if (raf !== null) cancelAnimationFrame(raf); if (focusRaf !== null) cancelAnimationFrame(focusRaf); observer?.disconnect(); abort.abort(); clearEngine(); }
    };
    if (!mapping.supported) { status('native_dom_svg',mapping.reason); return instance; }
    const lib = globalThis.AntVInfographic;
    if (!lib) { fail('Движок схемы не загрузился. Показан сохранённый граф.'); return instance; }
    try { configure(lib); } catch { fail('Версия движка схемы не поддерживается. Показан сохранённый граф.'); return instance; }

    const render = () => {
      raf = null; if (!alive || !host.isConnected) return;
      const available = Math.floor(host.getBoundingClientRect().width); if (available < 120) return;
      const columns = available < 620 ? 1 : Math.min(mapping.nodes.length,Math.max(2,Math.floor((available + 40) / 235)));
      const nodeWidth = Math.min(250,Math.floor((available - 40 - (columns - 1) * 40) / columns));
      const sizeKey = columns + ':' + nodeWidth;
      if (lastSize === sizeKey) return; lastSize = sizeKey;
      const focusedId = host.contains(document.activeElement) ? document.activeElement?.dataset?.fbriefNode : null;
      const token = ++generation; clearEngine(); host.dataset.state = 'pending';
      const rows = Math.ceil(mapping.nodes.length / columns), height = rows * 196 + (rows - 1) * 50 + 40;
      try {
        engine = new lib.Infographic({
          container:host,width:available,height,padding:20,editable:false,plugins:[],interactions:[],template:TEMPLATE,
          design:{structure:{type:'sequence-snake-steps',gap:40,rowGap:50,itemsPerRow:columns},items:[{type:ITEM,width:nodeWidth,height:196}]},
          data:{items:mapping.nodes.map(node => ({...phrases(node.label),source_node_id:node.id,source_role:node.role}))},
          themeConfig:{colorBg:'#272e24',colorPrimary:'#d9f46e',palette:['#d9f46e'],base:{text:{'font-family':FONT}},stylize:null},
          svg:{className:'fbrief-antv-svg',attributes:{'aria-label':'Последовательность сохранённого механизма','data-antv-template':TEMPLATE}}
        });
        timer = setTimeout(() => { if (alive && token === generation) fail('Движок не завершил схему. Показан сохранённый граф.'); },2500);
        engine.on('error',() => { if (alive && token === generation) fail('Не удалось построить инфографику. Показан сохранённый граф.'); });
        engine.on('rendered',({node:graphic}) => {
          if (!alive || token !== generation) return;
          const nodes = [...graphic.querySelectorAll('[data-fbrief-antv-node]')];
          if (nodes.length !== mapping.nodes.length || nodes.some((node,index) => node.getAttribute('data-fbrief-antv-node') !== mapping.nodes[index].id)) { fail('Движок изменил состав узлов. Показан сохранённый граф.'); return; }
          if (timer !== null) clearTimeout(timer); timer = null;
          graphic.setAttribute('role','group'); nodeAbort = new AbortController();
          for (const [index,node] of nodes.entries()) {
            const saved = mapping.nodes[index]; node.dataset.fbriefNode = saved.id; node.dataset.fbriefControl = 'node-' + saved.id;
            node.setAttribute('role','button'); node.setAttribute('tabindex','0'); node.setAttribute('aria-label','Шаг ' + (index + 1) + ': ' + clean(saved.label).replace(/[.!?]+$/,'') + '. Открыть основание');
            const title = document.createElementNS(NS,'title'); title.textContent = clean(saved.label); node.prepend(title);
            const activate = () => { select(saved.id); options.onSelect?.(saved.id); };
            node.addEventListener('click',activate,{signal:nodeAbort.signal});
            node.addEventListener('keydown',event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); activate(); } },{signal:nodeAbort.signal});
            controls.set(saved.id,node);
          }
          // Decorations carry no independent claims. Keep original edge refs in
          // the SVG for inspection; visible scope text explains their meaning.
          graphic.dataset.sourceNodeIds = JSON.stringify(mapping.nodes.map(node => node.id));
          graphic.dataset.sourceEdges = JSON.stringify(mapping.edges.map(edge => ({id:edge.id,from:edge.from,to:edge.to,kind:edge.kind,label:edge.label,evidence_ids:edge.evidence_ids || []})));
          select(selected); host.dataset.state = 'ready'; status('antv_infographic');
          const restore = focusedId || pendingFocus; pendingFocus = null;
          // AntV 0.2.20 clears visibility in its post-render MutationObserver.
          // Restore keyboard focus after that, without stealing a later focus.
          if (restore) focusRaf = requestAnimationFrame(() => {
            focusRaf = null;
            if (alive && token === generation && (!document.activeElement || document.activeElement === document.body || host.contains(document.activeElement))) controls.get(restore)?.focus({preventScroll:true});
          });
        });
        engine.render();
      } catch { if (alive && token === generation) fail('Не удалось построить инфографику. Показан сохранённый граф.'); }
    };
    const schedule = () => { if (alive && raf === null) raf = requestAnimationFrame(render); };
    if (globalThis.ResizeObserver) { observer = new ResizeObserver(schedule); observer.observe(host); }
    globalThis.addEventListener('resize',schedule,{signal:abort.signal});
    schedule(); return instance;
  }
  globalThis.FrontierInfographic = {mount,plan,phrases};
})();
