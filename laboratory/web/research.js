/* Owner-local evidence workbench. All mutations require a visible user action. */
(() => {
  'use strict';
  const startedPlans = new Set();
  const text = (value, fallback = 'Неизвестно') => {
    if (value === null || value === undefined || value === '') return fallback;
    return typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value);
  };
  const arr = value => Array.isArray(value) ? value : [];
  const body = item => item?.payload || item || {};
  function el(tag, className, value) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value !== undefined) node.textContent = text(value, '');
    return node;
  }
  function add(parent, ...children) {
    children.flat().filter(Boolean).forEach(child => parent.append(child));
    return parent;
  }
  function paragraph(value, className = 'research-note') {
    return el('p', className, value);
  }
  function button(label, action) {
    const node = el('button', 'button secondary', label);
    node.type = 'button';
    node.addEventListener('click', action);
    return node;
  }
  function detail(label, value) {
    return add(el('details', 'research-detail'), el('summary', '', label),
      el('pre', 'research-json', text(value)));
  }
  function section(title, note) {
    const node = add(el('section', 'research-section'), el('h3', '', title));
    if (note) node.append(paragraph(note));
    return node;
  }
  function field(parent, label, value = '', options = {}) {
    const wrap = el('label', 'research-field', label);
    const input = el(options.rows ? 'textarea' : 'input');
    if (options.rows) input.rows = options.rows;
    else input.type = options.type || 'text';
    input.value = value;
    input.required = Boolean(options.required);
    input.maxLength = options.maxLength || 12000;
    if (options.name) input.name = options.name;
    if (options.type === 'password') input.autocomplete = 'new-password';
    wrap.append(input);
    parent.append(wrap);
    return input;
  }
  function select(parent, label, values) {
    const wrap = el('label', 'research-field', label), input = el('select');
    for (const [value, title] of values) {
      const option = el('option', '', title);
      option.value = value;
      input.append(option);
    }
    wrap.append(input);
    parent.append(wrap);
    return input;
  }
  function consent(parent, label) {
    const wrap = el('label', 'research-consent'), input = el('input');
    input.type = 'checkbox';
    add(wrap, input, el('span', '', label));
    parent.append(wrap);
    return input;
  }
  function parse(input) {
    try { return JSON.parse(input.value); }
    catch { throw new Error('Нужен корректный JSON. Данные не отправлены.'); }
  }
  async function action(buttonNode, status, work, unlock = true) {
    buttonNode.disabled = true;
    status.textContent = 'Сохраняем…';
    try { await work(); }
    catch (error) { status.textContent = error?.message || 'Действие не подтверждено.'; }
    finally { if (unlock) buttonNode.disabled = false; }
  }
  function identity() {
    return globalThis.crypto?.randomUUID?.() || String(Date.now()) + Math.random();
  }
  function sourceCards(parent, values, api, refresh) {
    const names = {
      captured: 'Оригинал сохранён', partial: 'Сохранено частично',
      unparseable: 'Байты сохранены, текст не разобран', failed: 'Получить не удалось',
      blocked: 'Получение заблокировано', unsupported: 'Формат не поддерживается'
    };
    if (!arr(values).length) parent.append(paragraph('Сохранённых оригиналов пока нет.'));
    for (const item of arr(values)) {
      const value = body(item), card = el('article', 'research-source');
      const supplied = value.kind === 'supplied_text' || value.origin === 'supplied';
      add(card, el('h4', '', value.url || 'Переданный текст'),
        el('span', 'research-state', supplied ? 'Переданный текст' :
          names[value.status] || text(value.status)),
        paragraph('SHA-256 фиксирует байты снимка; авторство и истинность не проверяет.'),
        detail('Хеш, время и ограничения снимка', {
          sha256: value.sha256, retrieved_at: value.retrieved_at || value.retrieved_time,
          status: value.status, limitations: value.limitations
        }));
      const segments = el('details', 'research-detail');
      segments.append(el('summary', '', 'Фрагменты и локаторы · ' + arr(value.segments).length));
      for (const segment of arr(value.segments)) {
        add(segments, el('h5', '', segment.locator || segment.id),
          el('pre', 'research-quote', segment.text));
      }
      card.append(segments);
      if (api && value.source_id) {
        const status = paragraph('Новый снимок не меняет прежние апрувы.');
        const capture = button('Получить новую версию источника', () => {
          action(capture, status, async () => {
            await api('/api/research/capture', {source_id: value.source_id, refresh: true});
            status.textContent = 'Новый снимок подготовлен. Старые версии сохранены.';
            if (refresh) await refresh();
          });
        });
        add(card, capture, status);
      }
      parent.append(card);
    }
  }
  function evidenceSection(data) {
    const sectionNode = section('Что проверено в основаниях', data?.notice ||
      'Совпадение цитаты проверяется отдельно от модельного вывода о её значении.');
    add(sectionNode, paragraph('Состояние: ' + text(data?.status)));
    for (const issue of arr(data?.issues)) sectionNode.append(paragraph(issue, 'research-warning'));
    for (const check of arr(data?.checks)) {
      const card = el('article', 'research-evidence');
      const relation = {supports: 'поддерживает', contradicts: 'противоречит',
        insufficient: 'недостаточно данных'}[check.relation] || text(check.relation);
      add(card, el('h4', '', 'Основание ' + text(check.evidence_id)),
        paragraph('Цитата: ' + (check.literal_quote === true ?
          'буквальное совпадение найдено' : 'совпадение не подтверждено')),
        paragraph('Источник: ' + (check.source_bound === true ?
          'привязка к снимку подтверждена' : 'привязка не подтверждена')),
        paragraph('Модельная оценка: ' + relation),
        el('blockquote', 'research-quote', check.quote), paragraph(check.reason),
        detail('Точный локатор', {document_id: check.document_id, segment_id: check.segment_id}));
      sectionNode.append(card);
    }
    return sectionNode;
  }
  function measurementCards(parent, values) {
    if (!arr(values).length) parent.append(paragraph('Наблюдения ещё не зарегистрированы.'));
    for (const item of arr(values)) {
      const value = body(item), metric = body(value.metric);
      const card = el('article', 'research-metric');
      const name = typeof value.metric === 'string' ? value.metric : metric.name;
      add(card, el('h4', '', name || value.metric_name || 'Наблюдение'),
        paragraph('Значение: ' + text(value.value) + ' ' + text(value.unit || metric.unit, '')),
        paragraph('Основание: ' + text(value.basis || value.evidence_level)),
        paragraph('Сопоставимость устанавливается по определениям, единицам и условиям.'),
        detail('Определение, версии, данные, оборудование и происхождение', value));
      parent.append(card);
    }
  }
  function quality(parent, value, api) {
    const data = value || {}, coverage = data.coverage || {};
    add(parent, paragraph(data.notice ||
      'Пока нет ручной разметки, качество неизвестно. '
      + 'Успех тестов приложения не является оценкой.'),
    paragraph('Кейсов: ' + text(coverage.case_count, '0') + ' · размечено: ' +
      text(coverage.annotated_cases, '0') + ' · без оценки: ' + text(coverage.pending_cases, '0')));
    const titles = {factual_support: 'Поддержка фактами', number_extraction: 'Извлечение чисел',
      comparability: 'Оценка сопоставимости', reader_comprehension: 'Понятность для читателя'};
    for (const [key, title] of Object.entries(titles)) {
      const metric = data.metrics?.[key] || {};
      add(parent, paragraph(title + ': ' + (typeof metric.rate === 'number' ?
        (metric.rate * 100).toFixed(1) + '%' : 'не оценено') +
        ' · оценённых кейсов ' + text(metric.graded, '0')));
    }
    if (!api || !arr(data.cases).length) return;
    const form = el('form', 'research-form');
    const status = paragraph('Ручная оценка сохраняется отдельно.');
    const caseSelect = select(form, 'Какой сохранённый кейс оценить', arr(data.cases).map(item =>
      [item.id, text(body(item).title || body(item).run_id || item.id)]));
    const annotator = field(form, 'Кто выполнил оценку', '', {required: true, maxLength: 100});
    const choices = {
      factual_support: [['ungraded', 'Не оценено'], ['supported', 'Поддержано'],
        ['unsupported', 'Не поддержано'], ['uncertain', 'Неопределённо']],
      number_extraction: [['ungraded', 'Не оценено'], ['correct', 'Корректно'],
        ['incorrect', 'Некорректно']],
      comparability: [['ungraded', 'Не оценено'], ['correct', 'Корректно'],
        ['incorrect', 'Некорректно']],
      reader_comprehension: [['ungraded', 'Не оценено'], ['clear', 'Понятно'],
        ['unclear', 'Непонятно']]
    };
    const labels = {};
    for (const [key, title] of Object.entries(titles)) {
      labels[key] = select(form, title, choices[key]);
    }
    const notes = field(form, 'Основание оценки и ограничения', '', {rows: 3, maxLength: 2000});
    const save = el('button', 'button secondary', 'Сохранить ручную оценку');
    save.type = 'submit';
    add(form, save, status);
    form.addEventListener('submit', event => {
      event.preventDefault();
      action(save, status, async () => {
        const previous = arr(data.annotations).find(item =>
          body(item).case_id === caseSelect.value);
        const saved = await api('/api/research/evaluation', {case_id: caseSelect.value,
          annotator: annotator.value, notes: notes.value,
          labels: Object.fromEntries(Object.entries(labels).map(([key, input]) =>
            [key, input.value])),
          ...(previous ? {supersedes: previous.id} : {})});
        data.annotations = [saved, ...arr(data.annotations)];
        status.textContent = 'Оценка сохранена как новая неизменяемая запись.';
      });
    });
    parent.append(form);
  }
  function experimentControls(parent, data, api) {
    const config = data.experiment_config || {};
    add(parent, paragraph('Отдельный API-эксперимент. CLI-лимит исследования остаётся 3; '
      + 'до 20 API-запросов за 24 часа. Ключ API и модель задаются явно.'),
    paragraph(config.configured ? 'Ключ настроен · модель: ' + text(config.model) :
      'Ключ API не настроен. Запуск недоступен.'),
    paragraph('Endpoint: https://api.openai.com/v1/responses. Запроса для проверки ключа нет.'));
    const configForm = el('form', 'research-form');
    const key = field(configForm, 'Новый ключ API', '', {type: 'password', required: true});
    const model = field(configForm, 'Модель API', config.model || '',
      {required: true, maxLength: 100});
    const configStatus = paragraph('Ключ не включается в планы, результаты и выгрузки.');
    const saveConfig = el('button', 'button secondary', 'Сохранить конфигурацию API');
    saveConfig.type = 'submit';
    add(configForm, saveConfig, configStatus);
    configForm.addEventListener('submit', event => {
      event.preventDefault();
      action(saveConfig, configStatus, async () => {
        try {
          const result = await api('/api/research/experiments/config',
            {api_key: key.value, model: model.value});
          config.configured = result.configured;
          config.model = result.model;
          configStatus.textContent = 'Настройка сохранена локально. API-запросов не было.';
        } finally { key.value = ''; }
      });
    });
    parent.append(configForm);
    const template = {cases: [{id: 'case_1', input: 'Замените на свой пример',
      expected: 'Ваш критерий ожидаемого ответа'}],
    baseline: {label: 'Baseline', model: config.model || 'OWNER_EXPLICIT_MODEL',
      instructions: 'Answer concisely'},
    candidate: {label: 'Candidate', model: config.model || 'OWNER_EXPLICIT_MODEL',
      instructions: 'Answer concisely, then check the answer'},
    repetitions: 1, max_requests: 2, timeout_seconds: 60, max_output_tokens: 128,
    max_input_chars: 8000, metrics: ['latency_ms', 'exact_match'],
    stop_criteria: ['first_failure_or_uncertain'],
    pricing: {input_usd_per_million: null, output_usd_per_million: null,
      estimated_input_tokens_per_request: null}};
    const planForm = el('form', 'research-form');
    const planInput = field(planForm, 'Протокол: замените пример своими данными',
      JSON.stringify(template, null, 2), {rows: 14, required: true, maxLength: 50000});
    const planStatus = paragraph('Подготовка только фиксирует план. Внешних запросов нет.');
    const freeze = el('button', 'button secondary', 'Подготовить точный план эксперимента');
    freeze.type = 'submit';
    const approval = el('div', 'research-experiment-approval');
    add(planForm, freeze, planStatus);
    planForm.addEventListener('submit', event => {
      event.preventDefault();
      action(freeze, planStatus, async () => {
        const plan = await api('/api/research/experiments/plan', parse(planInput));
        approval.replaceChildren();
        add(approval, el('h4', '', 'Отдельный апрув API-эксперимента'),
          detail('Точный замороженный план и пределы', plan.payload || plan),
          paragraph('Хеш плана: ' + text(plan.plan_hash)),
          paragraph('Число запросов ограничено. Фактические токены и сумма заранее неизвестны; '
            + 'цены — ваши предположения, денежный потолок не гарантируется.'));
        const accepted = consent(approval,
          'Одобряю именно этот план и расход API по его пределам.');
        const runStatus = paragraph('Выполнение ещё не началось.');
        const planId = plan.plan_id || plan.id, commandId = identity();
        const start = button('Запустить одобренный API-эксперимент', () => {
          if (!accepted.checked || startedPlans.has(planId)) return;
          startedPlans.add(planId);
          action(start, runStatus, async () => {
            try {
              await api('/api/research/experiments/start', {plan_id: planId,
                plan_hash: plan.plan_hash, consent: true, command_id: commandId});
              runStatus.textContent = 'Апрув принят. Проверьте состояние ниже; повтора нет.';
            } catch (error) {
              runStatus.textContent = 'Исход запуска нужно проверить. Повтор этой кнопкой '
                + 'заблокирован. ' + text(error?.message);
            }
          }, false);
        });
        start.disabled = true;
        accepted.addEventListener('change', () => {
          start.disabled = !accepted.checked || !config.configured || startedPlans.has(planId);
        });
        add(approval, start, runStatus);
        planStatus.textContent = 'План заморожен. Для выполнения нужен отдельный апрув ниже.';
      });
    });
    add(parent, planForm, approval,
      detail('Состояние и сохранённые исходы', data.experiments || {}));
    const importForm = el('form', 'research-form');
    const observations = field(importForm, 'Импорт внешних наблюдений в JSON',
      '{"observations":[],"note":"Источник внешних наблюдений"}', {rows: 5});
    const importStatus = paragraph('Импорт не считается запуском лаборатории.');
    const importButton = el('button', 'button secondary', 'Сохранить импорт наблюдений');
    importButton.type = 'submit';
    add(importForm, importButton, importStatus);
    importForm.addEventListener('submit', event => {
      event.preventDefault();
      action(importButton, importStatus, async () => {
        await api('/api/research/experiments/import', parse(observations));
        importStatus.textContent = 'Импорт сохранён с хешем исходных данных; '
          + 'выполнения не заявлено.';
      });
    });
    parent.append(importForm);
  }
  function costControls(parent, api) {
    const form = el('form', 'research-form');
    const input = field(form, 'Исходные предположения расчёта в JSON',
      '{"input_usd_per_million":null,"output_usd_per_million":null}', {rows: 4});
    const status = paragraph('Неизвестные цены остаются неизвестными. Внешних запросов нет.');
    const calculate = el('button', 'button secondary', 'Рассчитать сценарий с предположениями');
    calculate.type = 'submit';
    const result = el('div');
    add(form, calculate, status, result);
    form.addEventListener('submit', event => {
      event.preventDefault();
      action(calculate, status, async () => {
        const data = await api('/api/research/cost', parse(input));
        result.replaceChildren(detail('Расчёт, предположения и чувствительность', data));
        status.textContent = 'Локальный расчёт. Это не счёт API и не гарантированный расход.';
      });
    });
    parent.append(form);
  }
  async function mountWorkspace(host, api) {
    if (host.dataset.researchMounted) return;
    host.dataset.researchMounted = 'true';
    host.classList.add('research-workbench');
    const status = paragraph('Загружаем сохранённые основания и наблюдения…');
    const content = el('div', 'research-workbench-content');
    const reload = async () => {
      try {
        const data = await api('/api/research');
        content.replaceChildren();
        for (const issue of arr(data.runtime?.errors || data.errors)) {
          content.append(paragraph(issue, 'research-warning'));
        }
        const sources = section('Источники и версии',
          'Оригинал, буквальная привязка и научный вывод — отдельные состояния.');
        sourceCards(sources, data.sources, api, reload);
        const measurements = section('Реестр измерений',
          'Без общего определения метрики и условий записи не ранжируются.');
        measurementCards(measurements, data.measurements);
        measurements.append(detail('Изменения источников и затронутые выводы', data.impacts || []));
        const evaluation = section('Качество исследований',
          'Поддержка фактами и понятность оцениваются отдельно; '
          + 'старые отчёты начинают без оценок.');
        quality(evaluation, data.evaluation, api);
        const experiments = section('Контролируемый API-эксперимент');
        experimentControls(experiments, data, api);
        const costs = section('Стоимость с явными предположениями');
        costControls(costs, api);
        add(content, sources, measurements, evaluation, experiments, costs);
        status.textContent = 'Локальные сохранённые данные. Просмотр не запускает исследования.';
      } catch (error) { status.textContent = 'Данные недоступны: ' + text(error?.message); }
    };
    host.replaceChildren(button('Обновить исследовательский реестр', reload), status, content);
    await reload();
  }
  function mountRun(host, run, data, api) {
    host.classList.add('research-run');
    host.replaceChildren();
    const sources = section('Сохранённые оригиналы этого апрува');
    sourceCards(sources, data.sources);
    const measurements = section('Наблюдения этого исследования');
    measurementCards(measurements, data.measurements);
    const recipe = section('Рецепт проверки решения',
      'Критерии приёмки — требования задачи. Они не становятся измеренным результатом.');
    recipe.append(detail('Задача, приёмка, условия, кандидаты и следующий шаг', data.recipe));
    const evaluation = section('Разметка качества');
    quality(evaluation, data.evaluation, api);
    add(host, sources, evidenceSection(data.evidence), measurements, recipe, evaluation);
    if (!data.public_preview) return;
    const preview = data.public_preview;
    const dossier = section('Публичное досье: отдельная локальная версия', preview.notice);
    add(dossier, paragraph('SHA-256 публичного содержимого: ' + text(preview.projection_hash)),
      detail('Точный публичный текст и поля этой версии', preview.payload));
    if (preview.payload?.english_abstract?.language === 'en') {
      add(dossier, el('h4', '', 'English abstract'),
        paragraph(preview.payload.english_abstract.text, 'research-english'));
    }
    const accepted = consent(dossier, 'Одобряю это точное публичное содержимое. '
      + 'Апрув исследования не заменяет этот выбор. Размещения и отправки в Telegram нет.');
    const status = paragraph('Публичная версия ещё не сохранена.');
    const save = button('Сохранить одобренную публичную версию локально', () => {
      if (!accepted.checked) return;
      action(save, status, async () => {
        const result = await api('/api/runs/' + encodeURIComponent(run.id) + '/dossier',
          {projection_hash: preview.projection_hash, consent: true});
        const assetId = result.id || result.asset_id;
        status.textContent = 'Одобренная неизменяемая версия сохранена локально.';
        if (/^[0-9a-f]{64}$/.test(assetId)) {
          for (const extension of ['html', 'json']) {
            const link = el('a', 'text-button', 'Скачать ' + extension.toUpperCase());
            link.href = '/api/research/dossiers/' + assetId + '.' + extension;
            link.download = 'research-dossier-' + assetId.slice(0, 12) + '.' + extension;
            link.rel = 'noopener noreferrer';
            dossier.append(link);
          }
        }
      });
    });
    save.disabled = true;
    accepted.addEventListener('change', () => { save.disabled = !accepted.checked; });
    add(dossier, save, status);
    host.append(dossier);
  }
  function mountPlan(host, run) {
    const plan = run.plan || {}, bundle = plan.evidence_bundle;
    if (!bundle) return;
    const sectionNode = section('Источники и реестр, зафиксированные до апрува',
      'Статус получения виден до запуска. Совпадение хеша не подтверждает научную истинность.');
    sourceCards(sectionNode, bundle.documents);
    sectionNode.append(detail('Выбранные наблюдения из релевантных прошлых запусков',
      plan.registry_context || {measurements: [], notice: 'Наблюдения не выбраны.'}));
    sectionNode.append(paragraph('Числовые выводы должны ссылаться на точные сохранённые '
      + 'цитаты. Отсутствующий оригинал не становится проверенным фактом.'));
    host.append(sectionNode);
  }
  window.LabResearch = {mountWorkspace, mountRun, mountPlan};
})();
