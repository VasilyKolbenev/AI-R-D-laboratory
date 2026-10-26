/* Live coordinator. Read-only on mount; writes stay behind the existing forms. */
(()=>{'use strict';
let bridge,mode='reactor',epoch=0,current=null,queue=null,queueAt=0;
const cache=new Map();
const elem=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
const visible=()=>document.body.classList.contains('frontier-live')&&['reactor','observatory'].includes(bridge?.getState().view);
function status(text,error=false){const n=document.getElementById('frontier-state');if(!n)return;n.textContent=text||'';n.hidden=!text;n.classList.toggle('error',error);}
function payload(){return{...(current||{}),runs:bridge.getState().runs||[],queue,onSelectRun:id=>bridge.selectRun(id).catch(bridge.showError),onAction:(name,id)=>action(name,id).catch(bridge.showError)};}
function paint(){if(!visible())return;mode=bridge.getState().view;const target=document.getElementById(mode==='reactor'?'reactor-workspace':'observatory-workspace');const component=mode==='reactor'?window.FrontierReactor:window.FrontierObservatory;if(!component?.mount){status('Компонент интерфейса не загрузился. Обновите страницу.',true);return;}component.mount(target,payload());}
function key(run){return JSON.stringify([run.id,run.status,run.plan_hash,run.finished_at,run.output,run.agent_pipeline,run.agent_review]);}
async function selected(run){
 if(!bridge)return;const request=++epoch;
 if(!run){current={run:null,presentation:null,quality:null,context:null};status('');paint();return;}
 const fingerprint=key(run),known=cache.get(fingerprint);
 current=known||{run,presentation:null,quality:null,context:{plan:run.plan||{}},loading:true};
 if(!visible())return;
 status(known?'':'Загружаем сохранённые данные исследования…');paint();
 if(known&&Date.now()-queueAt<30000)return;
 const results=await Promise.allSettled([
  known?Promise.resolve(known.presentation):run.status==='completed'&&run.output?bridge.api('/api/runs/'+encodeURIComponent(run.id)+'/presentation'):Promise.resolve(null),
  known?Promise.resolve(known.quality):bridge.api('/api/runs/'+encodeURIComponent(run.id)+'/quality'),
  Date.now()-queueAt<30000?Promise.resolve(queue):bridge.api('/api/publication')]);
 if(request!==epoch||bridge.getState().runId!==run.id)return;
 const errors=[];const values=results.map((r,i)=>{if(r.status==='fulfilled')return r.value;errors.push(['Краткий разбор','Аудит записи','Очередь'][i]+': '+(r.reason?.message||'данные недоступны'));return null;});
 if(values[2]){queue=values[2];queueAt=Date.now();}
 current={run,presentation:values[0],quality:values[1],context:{plan:run.plan||{}},loading:false,error:errors.join(' · ')};
 if(!errors.length){cache.set(fingerprint,current);while(cache.size>5)cache.delete(cache.keys().next().value);}
 status(current.error,Boolean(current.error));paint();
}
async function enter(view){if(!bridge||!document.body.classList.contains('frontier-live'))return;mode=view;const state=bridge.getState();if(!state.bootstrap){status('Подключаемся к локальной лаборатории…');return;}if(!state.runs.length){await selected(null);return;}if(!state.runId){const requested=new URL(location.href).searchParams.get('run');const run=state.runs.find(r=>r.id===requested)||state.runs.find(r=>r.status==='completed')||state.runs[0];await bridge.selectRun(run.id);return;}if(current?.run?.id===state.runId)await selected(current.run);else await bridge.selectRun(state.runId);}
function showFrozenPlan(run,memoryOnly=false){
 const dialog=document.getElementById('frontier-plan-dialog'),host=document.getElementById('frontier-plan-content');host.replaceChildren();
 document.getElementById('frontier-plan-title').textContent=memoryOnly?'Память этого исследования':'Зафиксированный план';
 const plan=run.plan||{};host.append(elem('p',plan.question||run.question||'Вопрос не сохранён','frontier-plan-lede'),elem('p','Снимок выбранного исследования. Изменения профиля не переписывают этот план.','field-hint'));
 if(!memoryOnly){host.append(elem('p',[plan.provider,plan.model,Number.isFinite(plan.timeout_seconds)?'До '+plan.timeout_seconds+' с':null].filter(Boolean).join(' · ')),elem('p','Версия апрува: '+(run.plan_hash||'Не зафиксирована'),'field-hint'));const sources=elem('div');for(const s of plan.sources||[])sources.append(elem('p',s.title||s.url||s.id||'Материал'));host.append(sources);if(plan.study_context?.task){const section=elem('details');section.append(elem('summary','Прикладная задача и baseline'),elem('pre',JSON.stringify(plan.study_context.task,null,2),'technical-data'));host.append(section);}}
 const memory=plan.memory;host.append(elem('h3','Выбранная память'));
 if(!memory||memory.enabled===false)host.append(elem('p','Память в этом плане не использовалась.'));
 else{if(memory.profile)host.append(elem('p','Профиль включён в сохранённый снимок.'));for(const group of ['corrections','items','lessons']){const entries=Array.isArray(memory[group])?memory[group]:[];host.append(elem('h4',({corrections:'Поправки',items:'Прошлые выводы',lessons:'Уроки'})[group]+' · '+entries.length));for(const item of entries){const body=item.body||item;host.append(elem('p',body.rule||body.title||body.text||body.summary||item.knowledge_id||item.id||'Запись памяти'));}}const exact=elem('details');exact.append(elem('summary','Точный снимок памяти, доказательства и версии'),elem('pre',JSON.stringify(memory,null,2),'technical-data'));host.append(exact);}
 const raw=elem('details');raw.append(elem('summary','Полный сохранённый план'),elem('pre',JSON.stringify(plan,null,2),'technical-data'));host.append(raw);
 const change=elem('button','Открыть профиль для следующих исследований','button secondary');change.type='button';change.addEventListener('click',()=>{dialog.close();bridge.switchView('settings');document.getElementById('memory-profile-form')?.scrollIntoView({block:'start'});});host.append(change);dialog.showModal();
}
async function action(name,id){
 const run=current?.run;
 if(name==='reactor'||name==='evidence'){bridge.switchView(name==='evidence'?'observatory':'reactor');return;}
 if(name==='inbox'){bridge.switchView('inbox');return;}
 if(name==='plan'){if(!run){bridge.switchView('inbox');return;}if(run.status==='planned')await bridge.openPlanApproval(run);else showFrozenPlan(run);return;}
 if(name==='memory'){if(run)showFrozenPlan(run,true);else bridge.switchView('settings');return;}
 if(name==='report'){bridge.switchView('runs');if(id||run?.id)await bridge.selectRun(id||run.id);return;}
 if(name==='knowledge'){bridge.switchView('knowledge');return;}
 if(name==='queue'){bridge.switchView('settings');await bridge.refreshPublication();document.querySelector('.publication-settings')?.scrollIntoView({block:'start'});return;}
 if(name==='settings'){bridge.switchView('settings');return;}
 if(name==='tasks'){bridge.switchView('tasks');return;}
}
window.FrontierLive={configure(value){bridge=value;},enter,selected,action,
 loading(id){++epoch;if(current?.run?.id!==id){current=null;status('Загружаем выбранное исследование…');paint();}},
 failed(id,error){if(bridge?.getState().runId===id){current=null;status(error?.message||'Исследование недоступно.',true);paint();}},
 publication(data){queue=data;queueAt=Date.now();paint();},
 invalidate(){cache.clear();queueAt=0;},
 leave(){++epoch;status('');window.FrontierReactor?.pause?.();window.FrontierObservatory?.pause?.();},
 snapshot(){return{mode,runId:current?.run?.id||null,loading:Boolean(current?.loading),error:current?.error||null};}};
})();
