/* Read-only REACTOR view. The owner application supplies data and explicit actions. */
(() => {
  'use strict';
  const instances = new WeakMap(), active = new Set(), SVG = 'http://www.w3.org/2000/svg';
  let serial = 0;
  const list = value => Array.isArray(value) ? value : [];
  const object = value => value && typeof value === 'object' && !Array.isArray(value) ? value : {};
  const text = (value, maximum = 500) => typeof value === 'string' ? value.replace(/\s+/g, ' ').trim().slice(0, maximum) : '';
  const statuses = {planned:'Ждёт апрува',queued:'В очереди',running:'Выполняется',completed:'Завершено',failed:'Не завершено',cancelled:'Остановлено',canceled:'Остановлено',outcome_unknown:'Исход неизвестен',unknown:'Нет данных',interrupted:'Прервано',loading:'Загрузка',dispatch_intent:'Исход отправки уточняется',skipped:'Пропущено',pending:'Ожидает'};
  const phaseNames = {researcher:'Исследователь',critic:'Критик',reviewer:'Редактор'};
  const roles = new Set(['input','compute','decision','memory','output','data']);
  const actions = [['inbox','Входящие'],['plan','План'],['memory','Память'],['evidence','Основания'],['report','Отчёт'],['knowledge','База знаний'],['queue','Очередь'],['settings','Сервис и настройки']];
  function el(tag, className, value) { const n=document.createElement(tag);if(className)n.className=className;if(value!==undefined)n.textContent=value;return n; }
  function svg(tag, attrs = {}, value) { const n=document.createElementNS(SVG,tag);for(const [key,v] of Object.entries(attrs))n.setAttribute(key,String(v));if(value!==undefined)n.textContent=value;return n; }
  function append(parent,...children) { for(const n of children.flat())if(n)parent.append(n);return parent; }
  function button(label, key, className='') { const b=el('button','fr-button '+className,label);b.type='button';b.dataset.frControl=key;return b; }
  function runTitle(run) { const p=object(run?.plan);return text(p.study_context?.task?.title,200)||text(p.sources?.[0]?.title,200)||text(p.question,200)||text(run?.title,200)||text(run?.question,200)||'Без сохранённого названия'; }
  function phaseRecord(run, role) {
    const current=list(run?.agent_pipeline?.phases).find(p=>p?.role===role);
    const reused=list(run?.agent_pipeline?.reused_phases).find(p=>p?.role===role);
    const saved=list(run?.plan?.continuation?.prefix).find(p=>p?.role===role);
    // "reused" records provenance, not the saved phase's outcome.
    const status=[current,saved,reused].map(row=>text(row?.status,50)).find(value=>value&&value!=='reused')||'unknown';
    return {status,reused:Boolean(reused||saved)};
  }
  function phaseStatus(run, role) { return phaseRecord(run,role).status; }
  function queueSummary(value, runId) {
    if(value===null||value===undefined)return 'Данные очереди ещё не загружены';
    const data=object(value),items=Array.isArray(value)?value:list(data.items);
    const item=items.find(x=>x&&x.run_id===runId)||(!runId?items.find(x=>x?.status==='queued'):null);
    if(!item)return runId?'Этот отчёт не находится в очереди':items.length?'В очереди есть сохранённые пакеты':'Очередь пуста';
    const labels={queued:'В очереди',awaiting_owner:'Ждёт просмотра владельца',published:'Опубликовано',publishing:'Публикуется',blocked:'Выпуск заблокирован',cancelled:'Снято с выпуска',outcome_unknown:'Исход публикации неизвестен'};
    let result=labels[item.status]||'Состояние выпуска неизвестно';
    if(item.status==='queued'&&typeof item.due_at==='string'){
      const date=new Date(item.due_at);
      if(Number.isFinite(date.getTime())){let zone=text(data.timezone,80)||'Europe/Moscow';try{result+=' · '+date.toLocaleString('ru-RU',{timeZone:zone,day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'})+' · '+zone;}catch{result+=' · '+text(item.due_at,80);}}
    }
    const blockers=list(item.blockers).filter(x=>typeof x==='string');if(blockers.length&&item.status!=='published')result+=' · '+text(blockers[0],180);
    return result;
  }
  function comparisonRows(presentation) {
    return list(presentation?.applied_analysis?.rows).filter(row=>row&&text(row.metric)&&text(row.baseline?.label)&&text(row.candidate?.label)).slice(0,8);
  }
  function savedGraph(presentation, lane) {
    const graph=object(presentation?.motion_story);
    if(graph.version!=='dataflow-v1'||!Array.isArray(graph.nodes)||!graph.nodes.length||graph.nodes.length>12||!Array.isArray(graph.edges)||graph.edges.length>16)return null;
    if(lane==='baseline'&&!['reported','conceptual'].includes(graph.baseline?.status))return null;
    const all=graph.nodes,ids=new Set();
    for(const n of all){if(!n||!text(n.id,80)||ids.has(n.id)||!text(n.label)||!roles.has(n.role)||!['technology','baseline'].includes(n.lane))return null;ids.add(n.id);}
    for(const e of graph.edges)if(!e||!ids.has(e.from)||!ids.has(e.to)||e.from===e.to||!['data','control','feedback'].includes(e.kind))return null;
    const nodes=all.filter(n=>n.lane===lane).map(n=>({id:n.id,label:text(n.label,240),detail:text(n.label,1500),role:n.role,evidence:list(n.evidence_ids)}));
    const included=new Set(nodes.map(n=>n.id));
    if(!nodes.length)return null;
    const edges=graph.edges.filter(e=>included.has(e.from)&&included.has(e.to)).map(e=>({from:e.from,to:e.to,label:text(e.label,300),feedback:e.kind==='feedback'}));
    return {nodes,edges,type:'technology',caption:lane==='baseline'?'Baseline из сохранённой структуры':'Механизм из сохранённой структуры',note:text(graph.selection?.reason,500)||'Показаны только сохранённые узлы и связи.',baselineNote:text(graph.baseline?.note,400)};
  }
  function workflow(run) {
    return {type:'workflow',caption:'Ход исследования; не схема технологии',note:'Технологические связи не восстановлены из текста. Сохранение в базу — отдельное действие.',nodes:[
      {id:'material',label:'Материал',role:'input',detail:'Исходные материалы из сохранённого плана.'},
      {id:'researcher',label:'Исследователь',role:'compute',detail:'Сохранённый этап исследования.',status:phaseStatus(run,'researcher')},
      {id:'critic',label:'Критик',role:'decision',detail:'Сохранённый этап критики.',status:phaseStatus(run,'critic')},
      {id:'result',label:'Выводы / база',role:'output',detail:'Выводы доступны в отчёте. Просмотр схемы ничего не сохраняет в базу.',status:phaseStatus(run,'reviewer')}
    ],edges:[{from:'material',to:'researcher'},{from:'material',to:'critic'},{from:'researcher',to:'result'},{from:'critic',to:'result'}]};
  }
  function mechanism(presentation, run) {
    const graph=savedGraph(presentation,'technology');if(graph)return graph;
    const steps=presentation?.visual?.kind==='process_flow'?list(presentation.visual.steps).map(x=>x?.text):[];
    if(steps.length===3&&steps.every(s=>typeof s==='string'&&text(s))){
      return {type:'technology',caption:'Порядок сохранённых шагов механизма',note:'Связи обозначают только порядок трёх явно сохранённых шагов.',nodes:steps.map((step,i)=>({id:'step-'+i,label:'Шаг '+(i+1),detail:text(step,1600),role:i===2?'output':'compute'})),edges:[{from:'step-0',to:'step-1'},{from:'step-1',to:'step-2'}]};
    }
    return workflow(run);
  }
  function layout(graph) {
    const rank=new Map(graph.nodes.map(n=>[n.id,0])),indegree=new Map(graph.nodes.map(n=>[n.id,0])),out=new Map(graph.nodes.map(n=>[n.id,[]]));
    for(const e of graph.edges)if(!e.feedback){indegree.set(e.to,indegree.get(e.to)+1);out.get(e.from).push(e.to);}
    const ready=graph.nodes.filter(n=>indegree.get(n.id)===0).map(n=>n.id);let visited=0;
    while(ready.length){const id=ready.shift();visited++;for(const next of out.get(id)){rank.set(next,Math.max(rank.get(next),rank.get(id)+1));indegree.set(next,indegree.get(next)-1);if(indegree.get(next)===0)ready.push(next);}}
    if(visited!==graph.nodes.length)return null;
    if(!graph.edges.length)graph.nodes.forEach((n,i)=>rank.set(n.id,i));
    const groups=new Map();for(const n of graph.nodes){const r=rank.get(n.id);if(!groups.has(r))groups.set(r,[]);groups.get(r).push(n);}
    const columns=Math.max(...rank.values())+1,maxRows=Math.max(...[...groups.values()].map(g=>g.length)),width=Math.max(1200,columns*260+100),height=Math.max(560,maxRows*190+160),positions=new Map();
    for(const [r,nodes]of groups)nodes.forEach((n,i)=>positions.set(n.id,{x:90+r*(width-370)/Math.max(1,columns-1),y:height/2-95+(i-(nodes.length-1)/2)*190}));
    return {width,height,positions};
  }
  function valueText(side,unit) { const n=side?.value;return typeof n==='number'&&Number.isFinite(n)&&n>=0&&n<=1e100&&['author_claim','external_measurement','estimate','hypothesis'].includes(side?.basis)&&list(side?.evidence_ids).length?n.toLocaleString('ru-RU')+(unit?' '+unit:''):'Неизвестно'; }
  function mount(host, props = {}) {
    if(!host||typeof host.replaceChildren!=='function')throw new TypeError('Нужен DOM-контейнер REACTOR.');
    const prior=instances.get(host),previous=prior?.snapshot();prior?.destroy();
    const data=object(props),run=object(data.run),hasRun=Boolean(text(run.id,160)),same=previous?.runId===(hasRun?run.id:null);
    const rawPresentation=object(data.presentation),presentation=run.status==='completed'&&!rawPresentation.loading?rawPresentation:{};
    const compare=comparisonRows(presentation),abort=new AbortController(),uid='fr-'+(++serial),root=el('section','frontier-reactor'),dialog=el('dialog','fr-inspector');
    const state={mode:same&&compare.length?previous.mode:'mechanism',role:same?previous.role:'researcher',step:same?previous.step:0,busy:false,alive:true,raf:null,selected:null};
    let graph,geometry,paths=[],packet,motor,sceneTitle,stageLabel,stepNumber,back,next,reset,modeTechnology,modeComparison,comparisonHost;
    const on=(target,type,handler)=>target.addEventListener(type,handler,{signal:abort.signal});
    function act(name) { if(!state.alive||typeof data.onAction!=='function')return;try{Promise.resolve(data.onAction(name,hasRun?run.id:null)).catch(()=>{message.textContent='Действие не завершено. Подробности доступны в основном разделе.';});}catch{message.textContent='Действие не завершено. Откройте основной раздел.';} }
    function action(label,name,disabled=false,cls='') { const b=button(label,'action:'+name,cls);b.disabled=disabled;b.dataset.frAction=name;return b; }
    const header=el('header','fr-header'),brand=el('div','fr-brand');append(brand,el('span','fr-brand-mark','VV'),el('strong','','Frontier'),el('span','fr-edition','REACTOR'));
    const selectLabel=el('label','fr-select-label','Исследование'),select=el('select','fr-run-select');select.setAttribute('aria-label','Выбрать сохранённое исследование');select.dataset.frFocus='run-select';
    const placeholder=el('option','','Выберите исследование');placeholder.value='';append(select,placeholder);
    const runs=list(Array.isArray(data.runs)?data.runs:data.runs?.items).filter(x=>x&&text(x.id,160)),seen=new Set();if(hasRun&&!runs.some(x=>x.id===run.id))runs.unshift(run);
    for(const item of runs){if(seen.has(item.id))continue;seen.add(item.id);const option=el('option','',runTitle(item)+' · '+(statuses[item.status]||'Состояние неизвестно'));option.value=item.id;select.append(option);}
    select.value=hasRun?run.id:'';select.disabled=!runs.length;selectLabel.append(select);append(header,brand,selectLabel);root.append(header);
    const nav=el('nav','fr-nav');nav.setAttribute('aria-label','Разделы лаборатории');for(const [key,label]of actions)nav.append(action(key==='plan'&&hasRun?'Сохранённый план':label,key,(['evidence'].includes(key)&&!hasRun)||(key==='report'&&!text(run.output,1))));root.append(nav);
    const main=el('div','fr-main'),intro=el('div','fr-intro'),titleGroup=el('div'),status=el('span','fr-status',hasRun?(statuses[run.status]||'Состояние неизвестно'):(data.context?.loading?'Загрузка':'Нет выбранного исследования'));
    status.dataset.state=Object.hasOwn(statuses,run.status)?run.status:'unknown';
    const title=hasRun?text(presentation.title,220)||runTitle(run):data.context?.loading?'Загрузка исследований':'Начните с рабочего вопроса';
    append(titleGroup,status,el('h1','fr-title',title));
    const purpose=el('p','fr-purpose',text(presentation.problem,600)||text(presentation.summary,600)||(hasRun?'Результат и условия доступны в сохранённом плане и отчёте.':'Добавьте материал или выберите сохранённое исследование. Просмотр не запускает исполнителя.'));
    append(intro,titleGroup,purpose);main.append(intro);
    const message=el('p','fr-message');message.setAttribute('role','status');if(run.error)message.textContent=text(run.error,900);else if(['running','queued'].includes(run.status))message.textContent='Исследование выполняется. Иллюстрация ниже не отражает скорость или прогресс внешнего вызова.';else if(['outcome_unknown','unknown','interrupted'].includes(run.status))message.textContent='Исход внешнего вызова неизвестен. Автоматического повтора нет.';else if(hasRun&&run.status==='completed'&&!Object.keys(presentation).length)message.textContent=rawPresentation.loading?'Краткий разбор загружается. Полный отчёт остаётся доступен.':'Структурированный механизм пока недоступен. Откройте сохранённый отчёт.';main.append(message);
    const perspective=el('div','fr-perspective'),roleButtons=el('div','fr-roles'),question=el('p','fr-question');
    for(const [key,label]of [['researcher','Исследователь'],['engineer','Инженер'],['lead','Руководитель']])roleButtons.append(button(label,'role:'+key));append(perspective,roleButtons,question);main.append(perspective);
    function updateRole(){for(const b of roleButtons.children)b.setAttribute('aria-pressed',String(b.dataset.frControl==='role:'+state.role));question.textContent=state.role==='engineer'?(text(presentation.use_case,350)||'Какие условия и ограничения сохранены для проверки?'):state.role==='lead'?(text(presentation.public_takeaway,350)||text(presentation.verdict,350)||'Какой вывод подкреплён этим исследованием?'):(text(run.plan?.question,350)||'Какие основания сохранены для вывода?');}updateRole();
    const phases=el('ol','fr-phases');phases.setAttribute('aria-label','Реальные статусы сохранённых проходов');for(const [key,label]of Object.entries(phaseNames)){const record=phaseRecord(run,key),item=el('li','fr-phase');append(item,el('strong','',label),el('span','',(statuses[record.status]||'Нет данных')+(record.reused?' · переиспользован':'')));item.dataset.state=record.status;item.dataset.reused=String(record.reused);phases.append(item);}main.append(phases);
    const machine=el('section','fr-machine'),toolbar=el('div','fr-machine-toolbar'),modeButtons=el('div','fr-mode');modeTechnology=button('Разрез','mode:mechanism');modeComparison=button('Сравнить с baseline','mode:comparison');modeComparison.disabled=!compare.length;modeComparison.title=compare.length?'Сохранённое прикладное сравнение':'В разборе нет структурированного прикладного сравнения';append(modeButtons,modeTechnology,modeComparison);sceneTitle=el('p','fr-scene-title');append(toolbar,modeButtons,sceneTitle);machine.append(toolbar);
    const noComparison=el('p','fr-comparison-reason',compare.length?'':'Baseline недоступен: прикладное сравнение не зафиксировано.');machine.append(noComparison);
    const scene=el('div','fr-scene');scene.tabIndex=0;scene.setAttribute('aria-label','Схема. При необходимости прокрутите её по горизонтали.');machine.append(scene);
    const consoleBox=el('div','fr-console'),phase=el('div','fr-illustration-phase');stepNumber=el('span','fr-step-number');stageLabel=el('strong','fr-step-label');append(phase,stepNumber,append(el('div'),el('small','','ИЛЛЮСТРАЦИЯ ПОРЯДКА'),stageLabel));const controls=el('div','fr-controls');reset=button('↶','reset','fr-icon');reset.setAttribute('aria-label','Начало иллюстрации');back=button('←','back','fr-icon');back.setAttribute('aria-label','Предыдущая связь');next=button('Следующая связь →','next','fr-primary');append(controls,reset,back,next);append(consoleBox,phase,controls);machine.append(consoleBox);
    const caption=el('p','fr-motion-caption','Движение — только иллюстрация сохранённого порядка. Оно не запускает исследование и не показывает измеренную скорость.');machine.append(caption);comparisonHost=el('div','fr-comparison');machine.append(comparisonHost);main.append(machine);
    const facts=el('div','fr-facts'),quality=object(data.quality),findings=list(quality.findings),qualityText=findings.length?findings.filter(x=>x?.status==='pass').length+' из '+findings.length+' проверок формата и оснований':text(quality.error,220)||'Данные проверок ещё не загружены';
    for(const [label,value]of [['Вывод',text(presentation.public_takeaway,700)||text(presentation.verdict,700)||'Вывод пока не установлен'],['Проверки',qualityText],['Очередь',queueSummary(data.queue,hasRun?run.id:null)]])append(facts,append(el('section'),el('h2','',label),el('p','',value)));main.append(facts);
    const footer=el('footer','fr-footer');append(footer,el('p','','Анализ источников не заменяет независимое воспроизведение.'),action(hasRun?'Открыть сохранённый план':'Добавить материал',hasRun?'plan':'inbox',false,'fr-link'));main.append(footer);root.append(main);
    const dialogHeading=el('h2');dialogHeading.id=uid+'-detail';dialog.setAttribute('aria-labelledby',dialogHeading.id);const dialogCopy=el('p'),dialogNote=el('p','fr-detail-note'),close=button('×','close','fr-close');close.setAttribute('aria-label','Закрыть пояснение');append(dialog,close,dialogHeading,dialogCopy,dialogNote,action('Открыть основания','evidence',!hasRun));root.append(dialog);
    function showNode(index){const n=graph.nodes[index];if(!n)return;state.selected=n.id;dialogHeading.textContent=n.label;dialogCopy.textContent=n.detail||n.label;dialogNote.textContent=(graph.type==='workflow'?'Это узел хода исследования, не технологии. ':'')+(n.status?'Сохранённый статус: '+(statuses[n.status]||'Нет данных')+'. ':'')+graph.note;dialog.showModal();}
    function renderComparison(){comparisonHost.replaceChildren();comparisonHost.hidden=state.mode!=='comparison';if(state.mode!=='comparison')return;const table=el('table'),head=el('thead'),tr=el('tr');for(const label of ['Показатель','Baseline','Кандидат','Условия и сопоставимость'])tr.append(el('th','',label));head.append(tr);const body=el('tbody');for(const row of compare){const line=el('tr');line.append(el('th','',text(row.metric,250)));for(const side of ['baseline','candidate']){const cell=el('td');append(cell,el('strong','',text(row[side].label,200)),el('p','',valueText(row[side],text(row.unit,60))),el('small','',({unknown:'Происхождение неизвестно',hypothesis:'Гипотеза',author_claim:'Данные авторов',external_measurement:'Внешнее измерение',estimate:'Оценка'}[row[side].basis]||'Происхождение неизвестно')));line.append(cell);}line.append(el('td','',text(row.conditions,800)+' · '+({comparable:'Сопоставимо в названных условиях',not_comparable:'Условия несопоставимы',unknown:'Сопоставимость неизвестна'}[row.comparability]||'Сопоставимость неизвестна')+(row.comparability_reason?' · '+text(row.comparability_reason,500):'')));body.append(line);}append(table,head,body);comparisonHost.append(table);}
    function nodeDrawing(n,index,p,shadow){
      const g=svg('g',{class:'fr-module',transform:`translate(${p.x} ${p.y})`,role:'button',tabindex:'0','data-fr-node':index,'aria-label':n.label+': открыть пояснение',filter:`url(#${shadow})`});
      append(g,svg('path',{class:'fr-node-top',d:'M0 25 24 0h170l-24 25Z'}),svg('path',{class:'fr-node-side',d:'m170 25 24-25v95l-24 25Z'}),svg('rect',{class:'fr-node-front',x:0,y:25,width:170,height:95,rx:2}));
      if(n.role==='compute'){const circle=svg('circle',{cx:85,cy:72,r:28,class:'fr-motor-shell'}),rotor=svg('g',{'data-fr-motor':index});append(rotor,svg('path',{d:'M85 48c18 0 25 19 14 30l-14-9Z',class:'fr-motor-blade'}),svg('path',{d:'M109 86c-9 15-29 10-30-5l13-7Z',class:'fr-motor-blade'}),svg('path',{d:'M67 88c-13-11-4-31 10-30l1 15Z',class:'fr-motor-blade'}));append(g,circle,rotor,svg('circle',{cx:85,cy:72,r:5,class:'fr-motor-center'}));if(!motor)motor=rotor;}
      else if(n.role==='memory'||n.role==='output'){append(g,svg('path',{d:'M20 48h130M20 91h130',class:'fr-node-slot'}),svg('rect',{x:27,y:63,width:116,height:10,rx:1,class:'fr-node-slot-fill'}));}
      else if(n.role==='decision')g.append(svg('path',{d:'m54 70 20 18 43-39',class:'fr-node-tick'}));
      else append(g,svg('rect',{x:58,y:45,width:43,height:43,rx:2,class:'fr-node-input'}),svg('path',{d:'M67 56h23M67 66h23M67 76h15',class:'fr-node-slot'}));
      const label=svg('text',{x:85,y:151,'text-anchor':'middle',class:'fr-node-label'}),words=n.label.split(' ');let line='',lines=[];for(const word of words){if((line+' '+word).trim().length>25&&line){lines.push(line);line=word;}else line=(line+' '+word).trim();}if(line)lines.push(line);lines.slice(0,2).forEach((value,i)=>label.append(svg('tspan',{x:85,dy:i?21:0},i===1&&lines.length>2?value+'…':value)));g.append(label);return g;
    }
    function updateStep(){state.step=Math.max(0,Math.min(state.step,paths.length));stepNumber.textContent=String(state.step);stageLabel.textContent=paths.length?(state.step?text(graph.edges[state.step-1]?.label,220)||'Связь '+state.step+' из '+paths.length:'Выберите связь для просмотра'):'Сохранённых переходов нет';next.disabled=!paths.length||state.busy;back.disabled=!state.step||state.busy;reset.disabled=!state.step&&!state.busy;next.textContent=state.step>=paths.length&&paths.length?'Сначала →':'Следующая связь →';for(const [i,p]of paths.entries())p.classList.toggle('fr-wire-selected',i===state.step-1);}
    function draw(){
      if(state.raf!==null)cancelAnimationFrame(state.raf);state.raf=null;state.busy=false;motor=null;paths=[];scene.replaceChildren();
      if(state.mode==='comparison'){
        graph=savedGraph(presentation,'baseline');
        if(!graph){const row=compare[0];graph={type:'comparison',caption:'Сопоставление из таблицы; топология baseline не описана',note:'Объекты сопоставлены в прикладной таблице. Стрелки технологии не добавлены.',nodes:row?[{id:'baseline',label:text(row.baseline.label,240),detail:text(row.metric,300),role:'data'},{id:'candidate',label:text(row.candidate.label,240),detail:text(row.metric,300),role:'data'}]:[],edges:[]};}
      }else graph=mechanism(presentation,run);
      geometry=layout(graph);if(!geometry){graph=workflow(run);geometry=layout(graph);}
      sceneTitle.textContent=graph.caption;scene.dataset.frGraph=graph.type;
      const drawing=svg('svg',{viewBox:`0 0 ${geometry.width} ${geometry.height}`,width:geometry.width,height:geometry.height,role:'group','aria-label':graph.caption}),defs=svg('defs'),shadow=svg('filter',{id:uid+'-shadow',x:'-40%',y:'-50%',width:'200%',height:'220%'});
      shadow.append(svg('feDropShadow',{dx:2,dy:15,stdDeviation:10,'flood-color':'#050704','flood-opacity':'.55'}));defs.append(shadow);drawing.append(defs);
      drawing.append(svg('ellipse',{cx:geometry.width/2,cy:geometry.height*.75,rx:geometry.width*.43,ry:geometry.height*.13,class:'fr-floor'}));
      for(const [i,edge]of graph.edges.entries()){
        const a=geometry.positions.get(edge.from),b=geometry.positions.get(edge.to),x=a.x+194,y=a.y+76,endX=b.x,endY=b.y+76;
        const d=edge.feedback?`M${x} ${y}C${x+90} ${y-190} ${endX-100} ${endY-190} ${endX} ${endY}`:`M${x} ${y}C${x+80} ${y} ${endX-80} ${endY} ${endX} ${endY}`;
        append(drawing,svg('path',{d,class:'fr-wire-back'}));const path=svg('path',{d,class:'fr-wire'+(edge.feedback?' fr-feedback':'')});path.dataset.frEdge=String(i);drawing.append(path);paths.push(path);
      }
      graph.nodes.forEach((n,i)=>drawing.append(nodeDrawing(n,i,geometry.positions.get(n.id),uid+'-shadow')));
      packet=svg('g',{class:'fr-packet',visibility:'hidden','aria-hidden':'true'});append(packet,svg('rect',{x:-13,y:-9,width:26,height:19,rx:2}),svg('path',{d:'M-6-2H6M-6 3H1'}));drawing.append(packet);scene.append(drawing);renderComparison();updateStep();
      modeTechnology.setAttribute('aria-pressed',String(state.mode==='mechanism'));modeComparison.setAttribute('aria-pressed',String(state.mode==='comparison'));
    }
    function moveStep(index){
      if(state.busy||!paths.length)return;
      if(index===0){state.step=0;packet.setAttribute('visibility','hidden');updateStep();return;}
      const path=paths[index-1];if(!path)return;state.step=index;state.busy=true;updateStep();packet.setAttribute('visibility','visible');
      const began=performance.now(),duration=globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches?0:750,length=path.getTotalLength();
      function frame(now){if(!state.alive)return;const raw=duration?Math.min(1,(now-began)/duration):1,t=raw*raw*(3-2*raw),p=path.getPointAtLength(length*t);packet.setAttribute('transform',`translate(${p.x} ${p.y})`);if(motor)motor.setAttribute('transform',`rotate(${(index-1+t)*100} 85 72)`);if(raw<1)state.raf=requestAnimationFrame(frame);else{state.raf=null;state.busy=false;updateStep();}}
      state.raf=requestAnimationFrame(frame);
    }
    on(root,'click',event=>{const b=event.target.closest('button');if(b&&root.contains(b)){const key=b.dataset.frControl||'';if(key.startsWith('action:')){if(dialog.open)dialog.close();act(key.slice(7));}else if(key.startsWith('role:')){state.role=key.slice(5);updateRole();}else if(key.startsWith('mode:')){if(!b.disabled){state.mode=key.slice(5);state.step=0;draw();}}else if(key==='next')moveStep(state.step>=paths.length?0:state.step+1);else if(key==='back')moveStep(Math.max(0,state.step-1));else if(key==='reset'){if(state.raf!==null)cancelAnimationFrame(state.raf);state.raf=null;state.busy=false;moveStep(0);}else if(key==='close')dialog.close();return;}const node=event.target.closest('[data-fr-node]');if(node&&root.contains(node))showNode(Number(node.dataset.frNode));});
    on(root,'keydown',event=>{const node=event.target.closest('[data-fr-node]');if(node&&['Enter',' '].includes(event.key)){event.preventDefault();showNode(Number(node.dataset.frNode));}});
    on(select,'change',()=>{if(!select.value||typeof data.onSelectRun!=='function')return;try{Promise.resolve(data.onSelectRun(select.value)).catch(()=>{message.textContent='Не удалось открыть выбранное исследование.';});}catch{message.textContent='Не удалось открыть выбранное исследование.';}});
    on(dialog,'click',event=>{if(event.target===dialog){const box=dialog.getBoundingClientRect();if(event.clientX<box.left||event.clientX>box.right||event.clientY<box.top||event.clientY>box.bottom)dialog.close();}});
    host.replaceChildren(root);draw();
    const pause=()=>{if(state.raf!==null)cancelAnimationFrame(state.raf);state.raf=null;if(state.busy)state.step=Math.max(0,state.step-1);state.busy=false;packet?.setAttribute('visibility','hidden');updateStep();};
    const instance={snapshot:()=>({runId:hasRun?run.id:null,role:state.role,mode:state.mode,step:state.step}),pause,destroy:()=>{if(!state.alive)return;state.alive=false;abort.abort();if(state.raf!==null)cancelAnimationFrame(state.raf);if(dialog.open)dialog.close();root.remove();instances.delete(host);active.delete(instance);}};
    instances.set(host,instance);active.add(instance);return instance;
  }
  window.FrontierReactor={mount,unmount:host=>instances.get(host)?.destroy(),pause:()=>{for(const instance of active)instance.pause();}};
})();
