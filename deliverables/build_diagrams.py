from pathlib import Path
import json

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'architecture'
OUT.mkdir(exist_ok=True)
BASE='''graph [fontname="Segoe UI", bgcolor="#ffffff", pad="0.35", nodesep="0.4", ranksep="0.65", splines=polyline, labelloc="t", fontsize=22, fontcolor="#172435"];
node [fontname="Segoe UI", shape=box, style="rounded,filled", fillcolor="#e9f0ff", color="#7696ce", fontcolor="#18385f", penwidth=1.2, fontsize=12, margin="0.2,0.16"];
edge [fontname="Segoe UI", fontsize=10, fontcolor="#52647b", color="#9aacc2", arrowsize=0.65, penwidth=1.1];
'''
def n(i,title,kind,tech='',desc='',external=False):
    parts=[title, '['+kind+']']
    if tech: parts.append(tech)
    if desc: parts.append(desc)
    attrs='label='+json.dumps('\n'.join(parts),ensure_ascii=False)
    if external: attrs+=', fillcolor="#f0f2f5", color="#aab3c0", fontcolor="#475364"'
    return i+' ['+attrs+'];\n'
def edge(a,b,label,extra=''):
    return a+' -> '+b+' [label='+json.dumps(label,ensure_ascii=False)+(','+extra if extra else '')+'];\n'
def cluster(i,label,body,color='#8aa7d0'):
    return 'subgraph cluster_'+i+' {label='+json.dumps(label,ensure_ascii=False)+';style="rounded,dashed";color="'+color+'";fontcolor="#566b86";fontsize=15;\n'+body+'}\n'
def save(name,title,body,direction='TB'):
    (OUT/(name+'.dot')).write_text('digraph "'+name+'" {\n'+BASE+'rankdir='+direction+';\nlabel='+json.dumps(title,ensure_ascii=False)+';\n'+body+'\n}\n',encoding='utf-8')

body=n('user','Исследователь / команда','Person','','Задаёт вопрос, утверждает план,\nчитает и сравнивает выводы')
body+=n('lab','R&D Laboratory','Software System','','Организует исследования,\nисполнение, измерения и evidence')
for args in [
('tg','Telegram','Software System','Bot API','Пересланные материалы',True),
('sources','Публикации, код, данные','Software Systems','Web / arXiv / GitHub / HF','Первичные источники и версии',True),
('models','Провайдеры моделей','Software Systems','OpenAI / Anthropic / другие','Исследователь, subject, judge',True),
('identity','Identity provider','Software System','OIDC / OAuth2','Вход и управление аккаунтами',True),
('compute','Внешние вычисления','Software System','GPU / isolated job service','Опциональные resource profiles',True)]:
    body+=n(*args)
body+=edge('user','lab','Обсуждает, подтверждает,\nнаблюдает и повторяет')
body+=edge('user','tg','Пересылает материалы')
body+=edge('tg','lab','Доставляет сообщения\nи вложения')
body+=edge('lab','sources','Читает и фиксирует\nверсии источников')
body+=edge('lab','models','Запрашивает исследование,\nответы и оценивание')
body+=edge('lab','identity','Проверяет идентичность')
body+=edge('lab','compute','Запускает утверждённые jobs;\nполучает outputs')
save('c1-context','C4 L1 · Системный контекст',body,'LR')

trusted=''
for args in [
('web','Web workspace','Container','Next.js / React / TS','Планы, отчёты, сравнения'),
('api','Control API','Container','FastAPI / PostgreSQL client','Доменные правила и доступ'),
('workflow','Workflow worker','Container','Python / Temporal SDK','Research и Run workflows'),
('gateway','Model Gateway','Container','Python / native adapters','Разрешения, usage и лимиты'),
('runner','Runner coordinator','Container','Python / Inspect adapters','Jobs, receipts, сбор outputs'),
('measure','Measurement worker','Container','Polars / DuckDB / SciPy','Trusted built-ins; validated facts'),
('temporal','Temporal','Container','Durable execution service','Workflow history и task queues'),
('db','PostgreSQL','Container: Database','SQL / RLS / optional pgvector','Планы, approvals, ledger, lineage'),
('objects','Object storage','Container: Store','S3 API / dev filesystem','Снимки, наборы, outputs, отчёты')]:
    trusted+=n(*args)
untrusted=n('sandbox','Sandbox pool','Container','OCI / gVisor or VM','Subject / custom scorer jobs;\nразные tokens и права на artifacts')
agent_boundary=n('runtime','Agent runtime','Container','Native SDKs / Codex / Claude','Scoped researcher sessions;\nизолированное выполнение tools')
body=cluster('lab','R&D Laboratory',cluster('trusted','Trusted application services',trusted)+cluster('agent','Researcher runtime trust boundary',agent_boundary,'#a290bf')+cluster('execution','Evaluated subject trust boundary',untrusted,'#c39876'))
body+=n('providers','Model providers','External System','HTTPS','Research / subject / judge',True)
body+=n('input','Telegram / Web / GitHub / HF','External Systems','HTTPS','Материалы и версии',True)
body+=n('idp','Identity provider','External System','OIDC','Аккаунты',True)
for a,b,l in [
('web','api','REST JSON / SSE'),
('web','idp','OIDC login'),
('api','idp','JWT / JWKS validation'),
('input','api','Telegram webhook: hosted HTTPS'),
('api','db','SQL: domain, outbox, ledger'),
('api','objects','S3: signed object access'),
('api','temporal','gRPC: start / update / cancel'),
('workflow','temporal','gRPC: poll tasks / history'),
('workflow','api','Internal REST: domain commands'),
('workflow','input','HTTPS: snapshots / revisions;\nTelegram getUpdates: private profile'),
('workflow','runtime','RPC: scoped research session'),
('runtime','workflow','Tool Broker: scoped actions / evidence'),
('runtime','gateway','Native API proxy: research calls'),
('workflow','runner','Activity: approved manifest'),
('runner','sandbox','Job API: launch / stop / collect'),
('sandbox','gateway','Scoped run token: subject calls'),
('gateway','api','Atomic reserve / settle'),
('gateway','providers','Native HTTPS APIs'),
('runner','objects','S3: outputs + execution receipt'),
('runner','api','Run / attempt status'),
('workflow','measure','Activity: score artifact refs'),
('measure','objects','S3: read raw, write observations'),
('measure','gateway','Scoped judge calls'),
('measure','runner','Custom scorers: isolated eval jobs'),
('measure','api','Validated observations / reports')]:
    body+=edge(a,b,l)
save('c2-containers','C4 L2 · Контейнеры и связи',body)

comp=''
for args in [
('identity','Identity & Workspace Policy','Component','JWT / role policies','Проверенный tenant context'),
('catalog','Source & Claim Catalog','Component','Domain service','Источники, claims и связи'),
('protocol','Protocol Registry','Component','Versioning / JSON Schema','Методика и immutable plan'),
('approval','Approval Service','Component','Policy + plan hash','Человек, scope, budget, expiry'),
('budget','Budget Ledger','Component','Transactional reservations','Расход + in-flight + unknown'),
('registry','Run Registry & Outbox','Component','SQL transactions','Run state и durable commands'),
('compare','Comparison Service','Component','Compatibility policy','Сопоставимые условия'),
('evidence','Evidence & Report Queries','Component','Read model / evidence refs','Графики и проверенные выводы')]:
    comp+=n(*args)
body=cluster('api','Control API · FastAPI',comp)
body+=n('web','Web / Tool Broker','External Containers','','Действия пользователя / агента',True)
body+=n('db','PostgreSQL','External Container','','RLS / domain records',True)
body+=n('workflow','Workflow worker / Gateway','External Containers','','Команды и usage receipts',True)
for a,b,l in [('web','identity','Authenticated REST'),('identity','catalog','Scoped access'),('identity','protocol','Scoped access'),('identity','approval','User role only'),('protocol','approval','Frozen plan hash'),('approval','budget','Approved ceiling'),('approval','registry','Create approved run'),('workflow','budget','reserve / settle / reconcile'),('workflow','registry','Idempotent events'),('registry','db','Atomic run + outbox'),('catalog','db','Snapshots / claims'),('protocol','db','Immutable versions'),('budget','db','Ledger transaction'),('evidence','db','Tenant-scoped query'),('compare','evidence','Compatible cohorts'),('web','compare','Compare runs'),('web','evidence','Report / chart / raw evidence')]:
    body+=edge(a,b,l)
save('c3-control','C4 L3 · Компоненты Control API',body,'LR')

comp=''
for args in [
('rw','ResearchWorkflow','Component','Temporal workflow','Разбор → план → ожидание'),
('runw','RunWorkflow','Component','Temporal workflow','Запуск → сбор → оценка'),
('ingest','IngestActivity','Component','Fetcher / parsers','Snapshot, dedup, primary sources'),
('planning','PlanningActivity','Component','Researcher session adapter','Гипотезы, package, draft plan'),
('tool','ToolBroker','Component','Scoped function tools','Проверка каждой операции агента'),
('dispatch','DispatchActivity','Component','Runner adapter','Утверждённый manifest / job'),
('analysis','AnalyzeActivity','Component','Measurement adapter','Scoring / facts / report checks')]:
    comp+=n(*args)
body=cluster('worker','Workflow worker · Python',comp)
for args in [('api','Control API','External Container','','Policy, approvals, run registry',True),('rt','Agent runtime','External Container','','Researcher / coding agent',True),('runner','Runner coordinator','External Container','','Sandbox job lifecycle',True),('measure','Measurement worker','External Container','','Observed data → metrics',True)]:
    body+=n(*args)
for a,b,l in [('rw','ingest','Activity: snapshot refs'),('rw','planning','Activity: research context'),('planning','rt','RPC: start / resume'),('rt','tool','Scoped proposed action'),('tool','api','Validated domain command'),('rw','api','Plan draft / wait on approval'),('rw','runw','Start approved child run'),('runw','dispatch','Activity: immutable manifest'),('dispatch','runner','submit / poll / cancel'),('runw','analysis','Activity: artifact refs'),('analysis','measure','score / aggregate / verify'),('runw','api','Run projection / events')]:
    body+=edge(a,b,l)
save('c3-execution','C4 L3 · Компоненты Workflow worker',body,'LR')

body=cluster('protocol','Protocol Registry · проектируемые программные контракты',
    n('plan','PlanVersion','Class','plan_id, hash, mode, budget','validate(); freeze()')+
    n('protocol','ProtocolVersion','Class','task, package/image hashes','metric policies; compatibility_key')+
    n('dataset','DatasetVersion','Class','artifact hash, split, sample IDs','holdout policy')+
    n('candidate','CandidateSpec','Class','provider/package, exact version','role; parameters; capabilities')+
    n('approval','Approval','Class','actor, plan_hash, scope, expiry','authorize(manifest)')+
    n('run','RunManifest','Class','run_id, approval_id, plan_hash','materialize(); verify()')+
    n('attempt','Attempt','Class','candidate, sample, repeat, job_ref','status; execution receipt')+
    n('observation','Observation','Class','metric_id, unit, value, evidence','scorer_version; provenance'))
body+=cluster('ports','Внешние порты компонента',
    n('provider','ProviderAdapter','Interface','capabilities / estimate / invoke / stream','cancel / reconcile (if supported)',True)+
    n('runner','RunnerAdapter','Interface','validate / prepare / submit / poll','collect / cancel; prepare optional',True)+
    n('scorer','Scorer','Interface','score(output, target, rubric)','returns Observation',True)+
    n('comparison','ComparisonPolicy','Interface','check(run_a, run_b)','returns CompatibilityReport',True))
for a,b,l in [('plan','protocol','contains 1'),('plan','dataset','references 1..n'),('plan','candidate','contains 1..n'),('approval','plan','binds exact hash'),('run','approval','requires 1 valid'),('run','plan','materializes 1 frozen'),('run','attempt','creates 1..n'),('attempt','provider','requests subject call'),('attempt','runner','executes job'),('scorer','observation','produces 0..n'),('attempt','observation','evidence source'),('comparison','run','compares 2..n')]:
    body+=edge(a,b,l)
save('c4-contracts','C4 L4 · Контракты плана и исполнения',body,'LR')

body=''
for args in [('user','Пользователь','Person'),('api','Control API','Container'),('workflow','Workflow worker','Container'),('runner','Runner coordinator','Container'),('sandbox','Sandbox pool','Container'),('gateway','Model Gateway','Container'),('provider','Provider','External System'),('measure','Measurement worker','Container'),('storage','Evidence store','Containers','PostgreSQL / S3')]:
    body+=n(*args)
for a,b,l in [
('user','api','1. Подтверждает plan_hash + ceiling'),
('api','storage','2. Approval + Run + outbox transaction'),
('api','workflow','3. Доставляет idempotent command'),
('workflow','runner','4. Запускает frozen manifest'),
('runner','sandbox','4a. Isolated subject job'),
('sandbox','gateway','5. Subject call через scoped token'),
('gateway','api','6. Reserve cost exposure'),
('gateway','provider','7. Request + operation ID'),
('gateway','api','8. Settle usage / mark unknown'),
('sandbox','runner','8a. Outputs + job receipt'),
('runner','storage','9. Raw outputs + receipt'),
('workflow','measure','10. Score saved outputs'),
('measure','storage','11. Observations + validated facts'),
('api','user','12. SSE status + report + evidence')]:
    body+=edge(a,b,l)
save('dynamic-run','Dynamic view · Утверждённый эксперимент',body,'LR')

body=''
states=[
('draft','DRAFT','План редактируется'),('ready','AWAITING_APPROVAL','Пакет и условия зафиксированы'),
('approved','APPROVED','Hash + scope + budget'),
('queued','QUEUED','Manifest проверен'),
('running','RUNNING','Jobs / calls / heartbeats'),
('scoring','SCORING','Raw evidence сохранён'),
('completed','COMPLETED','Report + facts + lineage'),
('blocked','BLOCKED','Нужен доступ или ресурс'),
('unknown','EXECUTION_UNKNOWN','Нужна сверка job/request'),
('cancel','CANCEL_REQUESTED','Новые calls запрещены'),
('partial','PARTIAL','Сохранён неполный результат'),
('cancelled','CANCELLED','Получен receipt остановки'),
('failed','FAILED','Неустранимая ошибка')]
for i,title,desc in states: body+=n(i,title,'State','',desc)
for a,b,l in [('draft','ready','validate + freeze'),('ready','approved','human confirms exact hash'),('approved','queued','reserve / enqueue'),('queued','running','job receipt'),('running','scoring','all outputs collected'),('scoring','completed','metrics/report valid'),('draft','blocked','missing dependency'),('queued','blocked','resource unavailable'),('blocked','draft','resolve / replan'),('running','unknown','timeout after dispatch'),('unknown','running','reconcile: still active'),('unknown','scoring','reconcile: finished'),('running','cancel','user cancel / budget cap'),('cancel','cancelled','stop receipt, no usable result'),('cancel','partial','stop receipt, usable result'),('running','partial','declared partial finish'),('scoring','failed','invalid evidence'),('running','failed','fatal failure'),('ready','draft','change content → new version')]:
    body+=edge(a,b,l)
for a in ['queued','scoring','unknown']:
    body+=edge(a,'cancel','cancel request; preserve reconciliation')
save('run-state','Run lifecycle · Состояния и переходы',body,'LR')

dev=n('devuser','Разработчик / пользователь','Person')
dev+=cluster('local','Private local · Windows + WSL2 / Linux VM',
    n('localui','UI + API','Container instances','Next / FastAPI','localhost only')+
    n('localworkers','Workflow / Agent / Runner / Measurement','Container instances','Python / Node / Compose','Общий repo, разные процессы')+
    n('localstate','PostgreSQL + Temporal + Filesystem','Infrastructure','Persistent volumes','Private dev storage')+
    n('localsandbox','Sandbox VM / isolated OCI runtime','Execution node','CPU profiles','Без host mounts и DB access'))
dev+=edge('devuser','localui','Browser / localhost')
dev+=edge('localui','localworkers','Local authenticated API')
dev+=edge('localworkers','localstate','SQL / gRPC / artifact API')
dev+=edge('localworkers','localsandbox','Approved jobs')
prod=cluster('hosted','Hosted beta · отдельное окружение',
    n('ingress','TLS ingress','Infrastructure','HTTPS','Public web / Telegram webhook')+
    n('apps','Web + API + Gateway','Container instances','Control network','OIDC / secret references')+
    n('workers','Workflow / Agent / Measurement','Container instances','Worker network','No public inbound')+
    n('state','Managed PG + S3 + Temporal','Managed services','Private access / IAM','Backup, PITR, retention')+
    n('secrets','IdP + secret manager + OTel','Managed services','OIDC / KMS / OTLP','Identity / credentials / telemetry')+
    cluster('exec','Dedicated execution hosts',
        n('prod_runner','Runner coordinator','Container instance','Scoped service identity','Launch / collect / cancel')+
        n('prod_sandbox','Sandbox pool','Execution nodes','gVisor / dedicated VM','CPU limits / egress proxy')+
        n('gpu','GPU execution profile','Optional execution nodes','Dedicated VM / job provider','Special compatibility checks'),'#c39876'))
body=dev+prod
for a,b,l in [('devuser','ingress','Browser HTTPS (hosted)'),('ingress','apps','TLS / authenticated routes'),('apps','workers','Internal commands'),('apps','state','SQL / S3 / gRPC'),('workers','state','Task queue / artifacts'),('apps','secrets','JWT / scoped secret lookup'),('workers','prod_runner','Approved manifest'),('prod_runner','prod_sandbox','Job API'),('prod_runner','gpu','Opt-in GPU jobs'),('prod_runner','state','Artifacts / receipts'),('prod_sandbox','apps','Scoped gateway only')]:
    body+=edge(a,b,l)
save('deployment','Deployment · Local private и Hosted beta',body,'TB')
print('8 editable Graphviz DOT views generated.')
