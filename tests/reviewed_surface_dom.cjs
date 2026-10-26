'use strict';
// Offline DOM contract tests: never loads a browser, provider, or Telegram.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

class Element {
  constructor(tag) {this.tagName=tag;this.children=[];this.listeners={};this.dataset={};this.isConnected=true;this.value='';this.open=false;this.disabled=false;this._text='';}
  set textContent(value) {this._text=String(value);this.children=[];}
  get textContent() {return this._text+this.children.map(child=>child.textContent).join('');}
  set innerHTML(value) {throw new Error('HTML parsing is forbidden in owner-visible model surfaces');}
  append(...children) {this.children.push(...children);}
  replaceChildren(...children) {this._text='';this.children=children;}
  setAttribute(name,value) {this[name]=String(value);}
  addEventListener(name,callback) {this.listeners[name]=callback;}
  showModal() {this.open=true;}
}
const controls=new Map();
const control=id=>{if(!controls.has(id))controls.set(id,new Element('input'));return controls.get(id);};
const document={createElement:tag=>new Element(tag),querySelector:selector=>control(selector),querySelectorAll:()=>[]};
const context=vm.createContext({document,URL,crypto:{randomUUID:()=> 'TEST_ONLY_command'},setTimeout,clearTimeout,setInterval,clearInterval});
const source=fs.readFileSync(path.join(__dirname,'../laboratory/web/app.js'),'utf8');
vm.runInContext(source.slice(0,source.indexOf("$$('[data-view]')"))+`
globalThis.surface={reviewedProtocol,planValues,updateResearchMode,researchValues,renderAppliedAnalysis,renderAgentReview,renderApprovalComparison,renderAgentPipeline,showApproval,state};
renderApprovalContext=()=>{};renderApprovalMemory=()=>{};contextTrace=()=>node('div');
`,context);
const ui=context.surface;
const all=element=>[element,...element.children.flatMap(all)];
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const protocol={version:'three-pass-v1',roles:['researcher','critic','reviewer'],web_search_roles:['researcher','critic'],max_calls:3,total_timeout_seconds:240,phase_timeouts:[100,60,60]};

async function main() {
  assert.equal(ui.reviewedProtocol({research_mode:'reviewed'}),null,'stored mode alone must not upgrade legacy approvals');
  assert.equal(ui.planValues({plan:{sources:[],research_mode:'reviewed'}}).research_mode,'single');
  assert.equal(ui.planValues({plan:{sources:[],research_protocol:protocol}}).research_mode,'reviewed');
  control('#research-mode').value='reviewed';control('#research-timeout').value='180';ui.updateResearchMode('research');
  assert.equal(control('#research-timeout').value,'240');assert.equal(control('#research-timeout').min,'200');assert.equal(control('#research-timeout').max,'240');
  ui.updateResearchMode('research',213);assert.equal(control('#research-timeout').value,'213');
  control('#research-mode').value='single';ui.updateResearchMode('research',60);assert.equal(control('#research-timeout').value,'60');assert.equal(control('#research-timeout').max,'600');
  ui.state.bootstrap={settings:{source_grounding:true}};
  control('#research-mode').value='reviewed';ui.updateResearchMode('research',360);
  assert.equal(control('#research-timeout').value,'360');
  assert.equal(control('#research-timeout').max,'360');
  assert.ok(control('#research-mode-hint').textContent.includes('200–360'));
  const extended={...protocol,version:'three-pass-v3',total_timeout_seconds:360,phase_timeouts:[130,100,110]};
  assert.equal(ui.reviewedProtocol({research_protocol:extended}),extended);
  assert.equal(ui.planValues({plan:{sources:[],research_protocol:extended}}).research_mode,'reviewed');
  ui.state.bootstrap=null;control('#research-mode').value='single';
  control('#research-provider').value='claude';control('#research-model').value='TEST_ONLY_model';control('#research-question').value='TEST_ONLY question';
  assert.equal(ui.researchValues().research_mode,'single');assert.equal(ui.researchValues().provider,'claude');

  const selected={version:'applied-context-v1',metric_checklist:[{id:'metric_1',name:'TEST_ONLY latency',definition:'TEST_ONLY p95',unit:'ms',direction:'minimize',target:'100',expected:'unknown',primary:true,evidence_url:'https://example.org/TEST_ONLY'}],analogues:[{memory_id:'TEST_ONLY_memory',memory_version:7,title:'TEST_ONLY analogue',claim:'<img onerror=TEST_ONLY>',study_scope:{dataset:'TEST_ONLY data',conditions:'TEST_ONLY scope'},effective_status:'active'}],notices:['TEST_ONLY notice']};
  const approval=ui.renderApprovalComparison({comparison_context:selected});
  assert.ok(approval.textContent.includes('TEST_ONLY_memory'));assert.ok(approval.textContent.includes('TEST_ONLY scope'));
  assert.ok(all(approval).some(element=>element.tagName==='pre'&&JSON.stringify(JSON.parse(element.textContent))===JSON.stringify(selected)),'owner can inspect every selected comparison field');
  assert.equal(all(approval).filter(element=>element.tagName==='img').length,0,'model markup remains literal text');
  const rows=[{id:'metric_1',metric:'TEST_ONLY latency',definition:'TEST_ONLY p95',unit:'ms',direction:'minimize',baseline:{label:'TEST_ONLY old',value:0,basis:'external_measurement',evidence_ids:['e1']},candidate:{label:'TEST_ONLY new',value:null,basis:'unknown',evidence_ids:[]},conditions:'TEST_ONLY unmatched hardware',comparability:'not_comparable',comparability_reason:'TEST_ONLY different conditions'}];
  const applied=ui.renderAppliedAnalysis({rows,unknowns:['TEST_ONLY missing candidate'],analogues:[{memory_id:'TEST_ONLY_memory',memory_version:7,relation:'context',relevance:'TEST_ONLY context',conditions_difference:'TEST_ONLY data differs'}]});
  for(const text of ['0 ms','Неизвестно','Несопоставимы','TEST_ONLY different conditions','TEST_ONLY missing candidate','TEST_ONLY data differs'])assert.ok(applied.textContent.includes(text),text);
  assert.equal(all(applied).filter(element=>element.tagName==='tbody')[0].children.length,1);
  const review=ui.renderAgentReview({status:'incomplete',issues:['TEST_ONLY blocker remains'],critic:{issues:[{id:'i1',severity:'blocker',target:'report',problem:'TEST_ONLY metric unsupported',required_change:'TEST_ONLY restrict claim',evidence_ids:['e1']}]},dispositions:[{issue_id:'i1',status:'unresolved',reason:'TEST_ONLY no evidence',resolution_excerpt:'TEST_ONLY limited claim',resolution_evidence_ids:['e2']}],applied_analysis:{rows}});
  for(const text of ['TEST_ONLY blocker remains','TEST_ONLY metric unsupported','Не устранено','TEST_ONLY no evidence','TEST_ONLY limited claim','e2','Метрик в итоговом сравнении: 1'])assert.ok(review.textContent.includes(text),text);

  ui.showApproval({id:'TEST_ONLY',plan_hash:'TEST_ONLY_hash',plan:{sources:[],provider:'codex',web_search:true,timeout_seconds:240,research_protocol:protocol,comparison_context:selected}});
  const summary=control('#approval-summary').textContent;
  for(const text of ['Критик','Рецензент и редактор','3 / 3 за 24 часа','240 сек.','100 сек.','TEST_ONLY_memory','Веб-поиск разрешён ролям: Исследователь и прикладной аналитик, Критик. У остальных ролей отключён.'])assert.ok(summary.includes(text),text);
  ui.showApproval({id:'TEST_ONLY_validation',plan_hash:'TEST_ONLY_hash',plan:{sources:[],provider:'codex',web_search:true,timeout_seconds:240,research_protocol:{...protocol,validation_contract:{task:'TEST_ONLY routing task',baseline:{name:'TEST_ONLY rules',version:'v1'},measurable_metrics:[{name:'TEST_ONLY accuracy',unit:'%'}],conditions:{dataset:'TEST_ONLY fixed v1',evaluation:'TEST_ONLY exact match'},minimal_falsifying_check:'TEST_ONLY compare held out cases',acceptance_criteria:'TEST_ONLY no quality loss'}}}});
  for(const text of ['Паспорт прикладной проверки','TEST_ONLY routing task','TEST_ONLY rules','TEST_ONLY accuracy','TEST_ONLY fixed v1','TEST_ONLY compare held out cases','требует отдельного плана'])assert.ok(control('#approval-summary').textContent.includes(text),text);
  ui.showApproval({id:'TEST_ONLY_old',plan_hash:'TEST_ONLY_hash',plan:{sources:[],provider:'codex',web_search:false,timeout_seconds:180}});
  assert.ok(control('#approval-summary').textContent.includes('1 / 1 за 24 часа'));
  assert.ok(!control('#approval-summary').textContent.includes('Три отдельных'));

  let fetches=0;
  context.__fetch=async url=>{fetches++;assert.equal(url,'/api/runs/TEST_ONLY/agents');return {phases:[{index:0,role:'researcher',status:'completed',prompt:'TEST_ONLY exact prompt',output:'<img onerror=TEST_ONLY>',usage:{tokens:7},dispatched:true}]};};
  vm.runInContext('api=path=>__fetch(path)',context);
  const pipeline=ui.renderAgentPipeline({id:'TEST_ONLY',status:'completed',plan:{research_protocol:protocol},agent_pipeline:{reserved_calls:3,dispatched_calls:1,total_timeout_seconds:240,phases:[{role:'researcher',status:'completed',dispatched:true,usage:{tokens:7}}]}});
  assert.equal(fetches,0,'merely rendering/polling a run must not fetch its phase journal');
  const journal=all(pipeline).find(element=>element.className==='agent-journal');
  journal.open=true;journal.listeners.toggle();await flush();
  assert.equal(fetches,1);assert.ok(journal.textContent.includes('TEST_ONLY exact prompt'));assert.equal(all(journal).filter(element=>element.tagName==='img').length,0);
  journal.open=false;journal.listeners.toggle();journal.open=true;journal.listeners.toggle();await flush();
  assert.equal(fetches,1,'reopening a completed journal reuses its saved response');
  console.log('TEST_ONLY reviewed owner surfaces: modes, exact approval, comparison truthfulness, critic decisions, safe text, lazy journal passed');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
