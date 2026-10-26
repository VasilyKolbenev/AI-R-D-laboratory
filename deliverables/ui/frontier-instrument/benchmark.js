(function () {
  'use strict';

  const obj = value => value && typeof value === 'object' && !Array.isArray(value) ? value : {};
  const arr = value => Array.isArray(value) ? value : [];
  const str = value => typeof value === 'string' ? value.trim() : typeof value === 'number' && Number.isFinite(value) ? String(value) : '';
  const num = value => typeof value === 'number' && Number.isFinite(value) ? value : null;
  const missing = 'Не зафиксировано';
  const attempted = new Set();
  const formats = new Map();
  const states = {planned:'План зафиксирован',running:'Выполняется',outcome_unknown:'Исход запуска неизвестен',completed:'Прогон завершён',failed:'Прогон остановлен с ошибкой',cancelled:'Прогон отменён'};
  const metricSpecs = [
    {key:'ndcg_at_10',alias:'ndcg@10',label:'nDCG@10',description:'Качество порядка первых 10 документов',primary:true},
    {key:'recall_at_100',alias:'recall@100',label:'Recall@100',description:'Доля релевантных документов в первых 100'},
    {key:'mrr_at_10',alias:'mrr@10',label:'MRR@10',description:'Обратный ранг первого релевантного документа, до 10'}
  ];
  function el(tag, value, className) { const node = document.createElement(tag); if (value !== undefined && value !== null) node.textContent = String(value); if (className) node.className = className; return node; }
  function add(parent, ...children) { for (const child of children.flat()) if (child) parent.append(child); return parent; }
  function p(value, className = '') { return el('p', str(value) || missing, className); }
  function button(label, action, style = '') { const node = el('button', label, 'fb-button ' + style); node.type = 'button'; node.addEventListener('click', action); return node; }
  function details(label, ...children) { return add(el('details', undefined, 'fb-disclosure'), el('summary', label), ...children); }
  function factList(rows) { const node = el('dl', undefined, 'fb-facts'); for (const [label,value] of rows) add(node, el('dt',label), el('dd',str(value) || missing)); return node; }
  function format(value, digits = 2) { if (num(value) === null) return '—'; if (!formats.has(digits)) formats.set(digits,new Intl.NumberFormat('ru-RU',{maximumFractionDigits:digits,minimumFractionDigits:digits})); return formats.get(digits).format(value); }
  function count(value) { return num(value) === null ? missing : format(value,0); }
  function scalar(value) { if (typeof value === 'boolean') return value ? 'Да' : 'Нет'; if (Array.isArray(value)) return value.map(scalar).filter(Boolean).join(' · '); if (value && typeof value === 'object') return Object.entries(value).map(([key,item]) => key + ': ' + scalar(item)).join('; '); return str(value); }
  function first(...values) { return values.find(value => value !== undefined && value !== null && value !== ''); }
  function safeLink(url, label) { try { const parsed = new URL(url); if (!['https:','http:'].includes(parsed.protocol) || parsed.username || parsed.password) return null; const node = el('a',label || parsed.hostname,'fb-link'); node.href = parsed.href; node.target = '_blank'; node.rel = 'noopener noreferrer'; return node; } catch (_) { return null; } }
  function table(headers, className = '') { const node = el('table',undefined,'fb-table ' + className), row = el('tr'), body = el('tbody'); for (const label of headers) { const th = el('th',label); th.scope = 'col'; row.append(th); } add(node,add(el('thead'),row),body); return {node,body}; }
  function tableRegion(node, label) { const region = el('div',undefined,'fb-table-scroll'); region.tabIndex = 0; region.setAttribute('role','region'); region.setAttribute('aria-label',label); region.append(node); return region; }
  function badge(value, state) { const node = el('span',value,'fb-badge'); if (state) node.dataset.state = state; return node; }
  function planPayload(value) { const item = obj(value); return obj(item.payload || item.plan || item); }
  function planId(value) { return str(first(value?.plan_id,planPayload(value).plan_id)); }
  function planHash(value) { return str(first(value?.plan_hash,planPayload(value).plan_hash)); }
  function planKey(value) { return planId(value) + ':' + planHash(value); }
  function manifestFor(plan) { return obj(plan.dataset_manifest || plan.manifest || plan.dataset); }
  function resultFor(selected) { let value = obj(selected?.result); for (let i = 0; i < 5; i++) { if (value.metrics || value.per_query || value.schema_version === 'lexical-retrieval-v1') return value; const nested = value.engine || value.results || value.result || value.payload || value.raw; if (!nested || typeof nested !== 'object') break; value = obj(nested); } return value; }
  function fraction(arm,spec) { const value = num(first(obj(arm)[spec.key],obj(arm)[spec.alias])); return value !== null && value >= 0 && value <= 1 ? value : null; }
  function percent(value) { return num(value) === null ? '—' : format(value * 100) + ' %'; }
  function deltaLabel(value) { return num(value) === null ? '—' : (value > 0 ? '+' : '') + format(value * 100) + ' п.п.'; }
  function metricDelta(metrics,spec) { const recorded = num(first(obj(metrics.delta)[spec.key],obj(metrics.delta)[spec.alias])); if (recorded !== null && recorded >= -1 && recorded <= 1) return recorded; const a = fraction(metrics.tfidf,spec), b = fraction(metrics.bm25,spec); return a === null || b === null ? null : b - a; }
  function metricChange(label,value) { if (value === null) return ''; return label + (value === 0 ? ' без изменений' : (value > 0 ? ' выше на ' : ' ниже на ') + format(Math.abs(value) * 100) + ' п.п.'); }
  function queryRows(result) { const input = result.per_query; const rows = Array.isArray(input) ? input.map((row,index) => ({...obj(row),qid:str(first(row.qid,row.query_id,index))})) : Object.entries(obj(input)).map(([qid,row]) => ({...obj(row),qid})); return rows.sort((a,b) => a.qid.localeCompare(b.qid,'en',{numeric:true})); }
  function outcome(row) { if (['win','tie','loss'].includes(row.outcome)) return row.outcome; const delta = num(obj(row.delta).ndcg_at_10); return delta === null ? 'unknown' : delta > 0 ? 'win' : delta < 0 ? 'loss' : 'tie'; }
  const outcomeNames = {win:'BM25 выше',tie:'Равенство',loss:'BM25 ниже',unknown:'Нет оценки'};

  function mount(host, options = {}) {
    if (!host || typeof host.replaceChildren !== 'function') throw new TypeError('FrontierBenchmark.mount: нужен DOM-контейнер.');
    let config = {...options}, plans = arr(options.plans), selected = options.selected || null, busy = false, destroyed = false, message = '', messageKind = '', generation = 0;
    const root = el('section',undefined,'fb-benchmark');
    host.replaceChildren(root);
    function currentPlan() { return plans.find(item => planId(item) === planId(selected)) || selected; }
    function setMessage(value, kind = '') { message = value; messageKind = kind; }
    function accept(response) {
      if (!response || typeof response !== 'object') return;
      if (Array.isArray(response.plans)) plans = response.plans;
      const next = Object.prototype.hasOwnProperty.call(response,'selected') ? response.selected : response.status && typeof response.status === 'object' ? response.status : response;
      if (next && (planId(next) || str(next.status))) {
        selected = next;
        const id = planId(next), index = plans.findIndex(item => planId(item) === id);
        if (id && index < 0) plans = [next,...plans];
        else if (index >= 0) plans = plans.map((item,i) => i === index ? {...item,...next} : item);
      } else if (Object.prototype.hasOwnProperty.call(response,'selected')) selected = null;
    }
    async function act(kind) {
      if (busy || destroyed) return;
      if (config.readOnly && ['prepare','start'].includes(kind)) return;
      const callback = config[kind === 'prepare' ? 'onPrepare' : kind === 'start' ? 'onStart' : 'onRefresh'];
      if (typeof callback !== 'function') return;
      const identity = {...obj(currentPlan()),...obj(selected)};
      if (kind === 'start') {
        if (identity.status !== 'planned' || !planId(identity) || !planHash(identity) || attempted.has(planKey(identity))) return;
        attempted.add(planKey(identity));
      }
      busy = true; setMessage(''); const token = ++generation;
      if (kind === 'start') selected = {...identity,status:'running',completed:false};
      render();
      try {
        const response = kind === 'start' ? await callback(planId(identity),planHash(identity)) : kind === 'refresh' ? await callback(planId(identity) || null) : await callback();
        if (destroyed || token !== generation) return;
        accept(kind === 'prepare' && planId(response) && !response.status ? {...response,status:'planned'} : response);
        if (kind === 'prepare') setMessage('План зафиксирован. Проверьте данные, ограничения и отпечаток перед разрешением запуска.','success');
        if (kind === 'start' && !response) selected = {...identity,status:'outcome_unknown',completed:false};
      } catch (error) {
        if (destroyed || token !== generation) return;
        const reason = str(error?.message) || 'Сервис не вернул подтверждённый ответ.';
        if (kind === 'start') { selected = {...identity,status:'outcome_unknown',completed:false}; setMessage('Исход запуска неизвестен. Повторный запуск этого плана заблокирован. Обновите статус вручную. ' + reason,'error'); }
        else setMessage(reason,'error');
      } finally { if (!destroyed && token === generation) { busy = false; render(); } }
    }

    function renderPlan(plan, identity) {
      const manifest = manifestFor(plan), protocol = obj(plan.protocol), bounds = obj(plan.bounds || plan.limits), scope = obj(plan.scope);
      const sources = arr(manifest.sources || manifest.provenance?.sources || plan.sources);
      const datasetName = str(first(manifest.name,manifest.dataset_name,manifest.title,manifest.dataset,typeof plan.dataset === 'string' ? plan.dataset : null)) || 'BEIR · SciFact';
      const corpusCount = first(manifest.corpus_count,manifest.corpus_documents,manifest.corpus?.count,manifest.counts?.corpus,manifest.counts?.documents,manifest.documents,manifest.documents_count);
      const queryCount = first(manifest.test_query_count,manifest.counts?.test_queries,manifest.query_count,manifest.queries?.count,manifest.counts?.queries,manifest.test_queries,manifest.queries_count);
      const qrelCount = first(manifest.qrels_count,manifest.counts?.qrels,manifest.qrels?.count);
      const card = el('article',undefined,'fb-plan');
      const top = el('div',undefined,'fb-section-head'); add(top,el('h3','Зафиксированный план'),badge(states[identity.status] || 'Статус не получен',identity.status));
      card.append(top,p('Поиск научных свидетельств по биомедицинскому утверждению: TF-IDF → BM25. Одинаковые документы, запросы и человеческие qrels для обоих методов.','fb-description'));
      const facts = factList([['Данные',datasetName],['Корпус',num(corpusCount) === null ? missing : count(corpusCount) + ' документов'],['Тест',num(queryCount) === null ? missing : count(queryCount) + ' запросов'],['Разметка',num(qrelCount) === null ? 'Человеческие qrels · число не зафиксировано' : 'Человеческие qrels · ' + count(qrelCount) + ' оценок'],['Главная метрика','nDCG@10 · больше лучше'],['Дополнительные','Recall@100 · MRR@10'],['Критерий',scalar(first(protocol.acceptance,protocol.acceptance_criterion,plan.acceptance))],['Время','Построение индекса отдельно; p50 / p95 тёплого поиска'],['Протокол времени','1 прогрев + 6 измеренных проходов; порядок AB / BA']]);
      card.append(facts);
      const links = el('div',undefined,'fb-source-links');
      const sourceUrl = first(manifest.source_url,manifest.url,manifest.download_url,manifest.archive_url,manifest.source?.url);
      const firstLink = safeLink(sourceUrl,'Источник набора данных'); if (firstLink) links.append(firstLink);
      for (const source of sources) { const value = typeof source === 'string' ? source : first(source.url,source.source_url); const link = safeLink(value,str(source.title || source.name) || 'Источник данных'); if (link && link.href !== firstLink?.href) links.append(link); }
      if (!links.childElementCount) links.append(p('Ссылка на источник не зафиксирована.','fb-note'));
      card.append(links);
      const resourceRows = [
        ['Лимит времени',num(first(bounds.wall_seconds,bounds.wall_time_seconds,bounds.max_wall_seconds,bounds.timeout_seconds,bounds.wall_time_s,protocol.max_elapsed_seconds)) === null ? scalar(bounds.wall_time || bounds.timeout) : scalar(first(bounds.wall_seconds,bounds.wall_time_seconds,bounds.max_wall_seconds,bounds.timeout_seconds,bounds.wall_time_s,protocol.max_elapsed_seconds)) + ' с'],
        ['Бюджет памяти',num(first(bounds.memory_mib,bounds.max_memory_mib,bounds.rss_mib,bounds.estimated_peak_ram_mib)) === null ? scalar(bounds.memory) : scalar(first(bounds.memory_mib,bounds.max_memory_mib,bounds.rss_mib,bounds.estimated_peak_ram_mib)) + ' MiB' + (bounds.estimated_peak_ram_mib ? ' · оценка пика' : '')],
        ['Вычисления','CPU · 1 процесс · GPU 0'],['Модели / расходы','Без локальных моделей, LLM и платных API'],['Публикация','Не входит в этот план']
      ];
      const resources = add(el('div',undefined,'fb-resource-box'),el('h4','Рамки одного запуска'),factList(resourceRows));
      card.append(resources);
      const scopeText = str(first(typeof plan.scope === 'string' ? plan.scope : null,scope.description,scope.task,scope.claim)) || 'Проверяется только ранжирование документов в фиксированном SciFact test. Это не проверка качества RAG-ответов, памяти агента или QDRec и не медицинская рекомендация.';
      const license = first(manifest.license,manifest.licenses,manifest.licensing,plan.licenses);
      const provenance = details('Источник, лицензии и границы вывода',p(scopeText),p('Это проверка ранжирования документов, а не QDRec, памяти агента или качества ответов RAG. Биомедицинский корпус не даёт медицинских рекомендаций; метрики не подтверждают истинность утверждений.','fb-note'),factList([['Лицензии данных',scalar(license)],['Лицензия разметки',scalar(first(manifest.annotation_license,manifest.qrels_license,manifest.licenses?.annotations,manifest.qrels?.license,plan.licenses?.annotations,plan.licenses?.claims_annotations))],['Разбиение',scalar(first(manifest.split,protocol.split))],['Происхождение разметки',scalar(first(manifest.annotation_source,manifest.qrels?.source,manifest.annotations))]]));
      const licenseLink = safeLink(first(plan.licenses?.source_url,plan.licenses?.citation_url,plan.licenses?.url,manifest.license_url),'Официальные условия лицензий'); if (licenseLink) provenance.append(licenseLink);
      const fingerprint = details('Отпечаток плана и полный протокол',factList([['Plan ID',planId(identity)],['Plan SHA-256',planHash(identity)],['Engine SHA-256',first(plan.engine_sha256,plan.engine?.sha256)],['Runtime SHA-256',first(plan.runtime_sha256,plan.runtime?.sha256,plan.runtime?.executable_sha256)],['Manifest SHA-256',first(plan.dataset_manifest_sha256,manifest.manifest_sha256,manifest.sha256)],['Protocol SHA-256',first(plan.protocol_sha256,protocol.sha256,'Протокол входит в Plan SHA-256')]]),add(el('pre',undefined,'fb-json'),el('code',JSON.stringify({task:plan.task,protocol:plan.protocol,bounds:plan.bounds || plan.limits,scope:plan.scope,dataset_manifest:manifest},null,2))));
      card.append(provenance,fingerprint);
      return card;
    }

    function renderApproval(identity) {
      const state = str(identity.status), canStart = state === 'planned' && !identity.completed && !attempted.has(planKey(identity)) && !!planId(identity) && !!planHash(identity);
      const box = el('section',undefined,'fb-approval');
      if (config.readOnly && canStart) return null;
      if (canStart) {
        box.append(el('h3','Разрешение на один CPU-прогон'),p('Разрешение относится к этому отпечатку плана. Изменение данных, кода, среды или протокола требует нового плана и нового разрешения.','fb-note'));
        const label = el('label',undefined,'fb-consent'), check = el('input'); check.type = 'checkbox'; check.checked = false; check.disabled = busy; check.autocomplete = 'off';
        const start = button(busy ? 'Запрос выполняется…' : 'Разрешить и запустить один раз',() => { if (check.checked && !start.disabled) act('start'); },'fb-button-primary'); start.disabled = true;
        check.addEventListener('change',() => { start.disabled = !check.checked || busy; });
        add(label,check,el('span','Разрешаю один CPU-прогон этого плана; без моделей и публикации'));
        box.append(label,start);
      } else if (state === 'running') box.append(el('h3','Прогон выполняется'),p('Сервис выполняет разрешённый план. Обновите статус вручную; автоматического повторного запуска нет.','fb-note'));
      else if (state === 'outcome_unknown' || state === 'planned' && attempted.has(planKey(identity))) box.append(el('h3','Нужно подтвердить исход запуска'),p('Ответ сервиса не подтверждён. Повторная отправка этого плана заблокирована; сначала обновите статус вручную.','fb-note'));
      else if (['failed','cancelled'].includes(state)) box.append(el('h3',states[state]),p('Это не результат сравнения качества. Причина остановки указана в деталях; следующий прогон требует отдельного зафиксированного плана.','fb-note'));
      else return null;
      return box;
    }

    function renderResults(result,identity) {
      const completed = result.completed === true || identity.completed === true;
      const section = el('section',undefined,'fb-results');
      if (!completed) {
        if (['failed','cancelled'].includes(identity.status) || Object.keys(obj(result.error)).length || result.error) section.append(details('Причина остановки',p(scalar(result.error || identity.error || result.failure || identity.failure) || 'Сервис не передал причину.')));
        return section.childElementCount ? section : null;
      }
      const metrics = obj(result.metrics), rows = queryRows(result), passed = typeof result.passed === 'boolean' ? result.passed : identity.passed;
      const heading = el('div',undefined,'fb-section-head'); add(heading,el('h3','Измеренный результат'),badge('Собственный CPU-эксперимент','completed')); section.append(heading);
      const summary = el('div',undefined,'fb-result-summary');
      if (typeof passed === 'boolean') summary.dataset.passed = String(passed);
      const ndcgDelta = metricDelta(metrics,metricSpecs[0]), recallDelta = metricDelta(metrics,metricSpecs[1]);
      const changes = [metricChange('nDCG@10',ndcgDelta),metricChange('Recall@100',recallDelta)].filter(Boolean);
      const reasons = [];
      if (ndcgDelta !== null && ndcgDelta <= 0) reasons.push('Нет требуемого прироста nDCG@10.');
      if (recallDelta !== null && recallDelta < 0) reasons.push('Нарушено условие «не терять полноту Recall@100».');
      const verdict = passed === true ? 'Критерий плана выполнен' : passed === false ? 'Критерий плана не выполнен' : 'Вердикт критерия не зафиксирован';
      add(summary,el('strong',verdict),p(changes.length ? 'На этом наборе BM25 относительно TF-IDF: ' + changes.join('; ') + '.' : 'Для сравнения nDCG@10 и Recall@100 недостаточно измерений.'),p(passed === false ? reasons.join(' ') || 'Причина невыполнения критерия не установлена по доступным метрикам.' : 'Результат относится к ранжированию документов на этом наборе.','fb-note'));
      section.append(summary);
      const chart = el('div',undefined,'fb-metric-grid');
      for (const spec of metricSpecs) {
        const figure = el('figure',undefined,'fb-metric');
        const caption = el('figcaption'); add(caption,el('strong',spec.label),spec.primary ? badge('Главная') : null); figure.append(caption,p(spec.description,'fb-note'));
        const a = fraction(metrics.tfidf,spec), b = fraction(metrics.bm25,spec);
        for (const [label,value,arm] of [['TF-IDF',a,'tfidf'],['BM25',b,'bm25']]) {
          const line = el('div',undefined,'fb-bar-row'), track = el('div',undefined,'fb-track'), bar = el('span',undefined,'fb-bar'); bar.dataset.arm = arm; bar.style.width = (value === null ? 0 : value * 100) + '%'; track.setAttribute('aria-hidden','true'); track.append(bar); add(line,el('span',label),track,el('strong',percent(value),'fb-number')); figure.append(line);
        }
        const change = a === null || b === null ? null : b - a;
        const changeNode = el('p','Δ ' + deltaLabel(change),'fb-delta fb-number'); changeNode.dataset.direction = change === null ? 'unknown' : change > 0 ? 'up' : change < 0 ? 'down' : 'same'; figure.append(changeNode); chart.append(figure);
      }
      section.append(chart,p('Общая шкала 0–100 %. Значения метрик — доли, умноженные на 100; Δ — процентные пункты. Больше лучше. Интервалы неопределённости не оценивались.','fb-note'));
      const actualCount = first(result.evaluated_queries,result.query_count,result.counts?.evaluated_queries,result.counts?.queries,result.dataset?.query_count,result.dataset?.test_query_count,rows.length || undefined);
      const actualDocuments = first(result.counts?.documents,result.dataset?.corpus_count,result.corpus_count);
      section.append(p('Оценено запросов: ' + count(actualCount) + (num(actualDocuments) === null ? '' : ' · корпус ' + count(actualDocuments) + ' документов') + (rows.length ? '. Win / tie / loss по nDCG@10: ' + rows.filter(row => outcome(row) === 'win').length + ' / ' + rows.filter(row => outcome(row) === 'tie').length + ' / ' + rows.filter(row => outcome(row) === 'loss').length + '.' : '.'),'fb-result-count'));
      const timings = obj(result.timings), arms = obj(timings.arms || timings);
      const latency = table(['Метод','Индекс, мс','Тёплый поиск p50, мс / запрос','Тёплый поиск p95, мс / запрос'],'fb-latency-table');
      for (const [key,label] of [['tfidf','TF-IDF'],['bm25','BM25']]) { const arm = obj(arms[key]); const warm = obj(arm.warm); add(latency.body,add(el('tr'),el('th',label),el('td',format(first(arm.index_build_ms,arm.index_ms))),el('td',format(first(arm.query_latency_p50_ms,warm.p50_ms,arm.p50_ms))),el('td',format(first(arm.query_latency_p95_ms,warm.p95_ms,arm.p95_ms))))); }
      section.append(add(el('div',undefined,'fb-section-head fb-spaced'),el('h4','Время на этой машине'),p('Построение индекса не включено в тёплый поиск','fb-note')),tableRegion(latency.node,'Время построения индекса и тёплого поиска'),p('Тёплый индекс · 6 замеров на запрос · p50/p95 по медианам','fb-note'));
      if (rows.length) {
        const cases = table(['Query ID','TF-IDF nDCG@10, %','BM25 nDCG@10, %','Δ, п.п.','Исход'],'fb-case-table');
        for (const row of rows.slice(0,20)) add(cases.body,caseRow(row));
        const queryDetails = details('Проверка отдельных запросов',p('Первые ' + Math.min(20,rows.length) + ' ID по порядку; выбор не зависит от исхода','fb-note'),tableRegion(cases.node,'Результаты первых запросов в порядке ID'));
        queryDetails.dataset.querySample = 'true'; section.append(queryDetails);
        const losses = rows.filter(row => outcome(row) === 'loss');
        const lossTable = table(['Query ID','TF-IDF nDCG@10, %','BM25 nDCG@10, %','Δ, п.п.','Исход'],'fb-case-table');
        for (const row of losses) add(lossTable.body,caseRow(row));
        section.append(details('Где BM25 хуже по nDCG@10 · ' + losses.length + ' запросов',losses.length ? tableRegion(lossTable.node,'Все запросы с ухудшением nDCG@10') : p('На оценённых запросах ухудшений по nDCG@10 нет.','fb-note')));
      } else section.append(p('Подробные результаты запросов не переданы.','fb-note'));
      const environment = obj(result.environment);
      section.append(details('Среда, проходы и воспроизводимость',factList([['Result ID',first(identity.result_id,result.result_id)],['Прогон завершён',completed ? 'Да' : 'Нет'],['Критерий выполнен',typeof passed === 'boolean' ? passed ? 'Да' : 'Нет' : missing],['Всего, wall time',num(timings.total_elapsed_ms) === null ? missing : format(timings.total_elapsed_ms) + ' мс'],['Всего, CPU time',num(timings.total_cpu_ms) === null ? missing : format(timings.total_cpu_ms) + ' мс'],['Среда',scalar(environment)],['Прогрев',scalar(timings.warmup)],['Измеренных проходов',arr(timings.passes).length || missing],['Область доказательства',scalar(first(result.evidence_scope,environment.evidence_scope))]]),add(el('pre',undefined,'fb-json'),el('code',JSON.stringify({protocol:result.protocol,quantile_definition:timings.quantile_definition,passes:timings.passes,failures:result.failures},null,2)))));
      if (result.failures && scalar(result.failures)) section.append(details('Ошибки / исключённые случаи',p(scalar(result.failures))));
      return section;
    }
    function caseRow(row) {
      const a = fraction(row.tfidf,metricSpecs[0]), b = fraction(row.bm25,metricSpecs[0]), state = outcome(row), node = el('tr');
      const id = el('th',row.qid); id.scope = 'row';
      const query = str(first(row.query,row.text,row.query_text)); if (query) id.append(el('span',query,'fb-case-query'));
      add(node,id,el('td',percent(a),'fb-number'),el('td',percent(b),'fb-number'),el('td',deltaLabel(a === null || b === null ? null : b - a),'fb-number'),el('td',outcomeNames[state])); node.dataset.outcome = state; return node;
    }
    function render() {
      if (destroyed) return;
      root.replaceChildren();
      const heading = el('header',undefined,'fb-view-head');
      add(heading,add(el('div'),el('span','04 / КОНТРОЛИРУЕМАЯ ПРОВЕРКА','fb-eyebrow'),el('h2','CPU-проверка поиска')),badge('TF-IDF → BM25'));
      root.append(heading,p('Фиксированный лексический пилот на BEIR SciFact. Человеческая разметка, локальный CPU, нулевые расходы на модели и API.','fb-intro'));
      const toolbar = el('div',undefined,'fb-toolbar');
      if (plans.length) {
        const label = el('label',undefined,'fb-plan-select'); label.append(el('span','Сохранённый план','fb-control-label')); const select = el('select'); select.disabled = busy;
        if (!selected) { const placeholder = el('option','Выберите план'); placeholder.value = ''; select.append(placeholder); }
        for (const item of plans) { const option = el('option',(states[item.status] || 'План') + ' · ' + (planId(item).slice(0,12) || 'без ID')); option.value = planId(item); option.selected = planId(item) === planId(selected); select.append(option); }
        select.addEventListener('change',() => { selected = plans.find(item => planId(item) === select.value) || null; setMessage(''); render(); if (selected && typeof config.onRefresh === 'function') act('refresh'); }); label.append(select); toolbar.append(label);
      }
      const activeState = str(selected?.status);
      if (config.readOnly) {
        const previewURL = str(first(config.onPreviewLinkURL,config.previewLinkURL,config.previewLinkUrl,config.previewUrl));
        const link = safeLink(previewURL,'Открыть план в лаборатории'); if (link) { link.classList.add('fb-button'); toolbar.append(link); }
        root.append(p('Предпросмотр · подготовка плана и разрешение запуска доступны в лаборатории.','fb-note fb-read-only'));
      } else {
        const prepare = button(busy ? 'Запрос выполняется…' : 'Зафиксировать план CPU-проверки',() => act('prepare'));
        prepare.disabled = busy || ['running','outcome_unknown'].includes(activeState) || typeof config.onPrepare !== 'function'; toolbar.append(prepare);
      }
      const refresh = button('Обновить статус',() => act('refresh'),'fb-button-quiet'); refresh.disabled = busy || typeof config.onRefresh !== 'function'; toolbar.append(refresh); root.append(toolbar);
      if (message) { const note = p(message,'fb-message'); note.dataset.kind = messageKind; note.setAttribute('role',messageKind === 'error' ? 'alert' : 'status'); root.append(note); }
      if (!selected) {
        const empty = el('div',undefined,'fb-empty'); add(empty,el('span','∅','fb-empty-symbol'),el('h3','Сначала зафиксируйте план'),p('Источник, фактическое число документов и запросов, лицензии, версии и ограничения появятся из сохранённого манифеста. Сохранение плана не запускает проверку.','fb-note'),factList([['Корпус / тест','Не загружены · число неизвестно'],['Запуск','Ожидает отдельного явного разрешения'],['Область','Ранжирование документов; не качество ответов RAG или памяти агента']])); root.append(empty); return;
      }
      const saved = currentPlan(), plan = planPayload(saved), identity = {...obj(saved),...obj(selected)};
      if (plan.test_only || plan.TEST_ONLY || plan.protocol?.test_only || selected.test_only || resultFor(selected).test_only || resultFor(selected).TEST_ONLY || resultFor(selected).protocol?.test_only) root.append(p('TEST_ONLY · Тестовые данные интерфейса. Этот экран не является выполненным benchmark.','fb-test-only'));
      const result = resultFor(selected), results = renderResults(result,identity);
      if (result.completed === true || identity.completed === true) {
        if (results) root.append(results);
        root.append(details('План, источник и зафиксированные условия',renderPlan(plan,identity)));
      } else {
        root.append(renderPlan(plan,identity));
        const approval = renderApproval(identity); if (approval) root.append(approval);
        if (results) root.append(results);
      }
    }
    render();
    return {
      update(next = {}) { if (destroyed) return; config = {...config,...next}; if (Array.isArray(next.plans)) plans = next.plans; if (Object.prototype.hasOwnProperty.call(next,'selected')) selected = next.selected; render(); },
      destroy() { destroyed = true; ++generation; root.remove(); }
    };
  }
  window.FrontierBenchmark = Object.freeze({mount});
})();
