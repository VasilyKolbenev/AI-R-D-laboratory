/* Development QA for newly authored Constellation v2 only.
 * Opens a fresh headless browser/context. No file:// navigation, existing tab,
 * user profile, CDP connection, local server, or external network is used.
 */
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const assert = require('assert/strict');
const playwright = require('playwright');

const APP_URL = 'http://constellation-test.invalid/';
const appPath = path.resolve(__dirname, '../ui/03-constellation.html');
const OLD_REVISION = 'f6823462c7dc992ddbc3390e07702222aeb6995b4034ead36ad9a67c121c3e1d';
const outPath = path.join(__dirname, 'constellation-v2-results.json');
const layoutOnly = process.argv.includes('--layout-only');
const source = fs.readFileSync(appPath, 'utf8');
const sourceHash = crypto.createHash('sha256').update(source).digest('hex');
if (!process.argv.includes('--revision-ready')) throw new Error('Await author readiness. Run with --revision-ready only after Constellation v2 is saved.');
if (sourceHash === OLD_REVISION) throw new Error('Refusing to exercise the old interface. Constellation v2 has not been authored yet.');

const results = [];
const screenshots = [];
const errors = [];
const blockedRequests = [];
const consoleErrors = [];
let browser, context, page;
async function check(name, fn) {
  try { const detail = await fn(); results.push({ name, status: 'pass', ...(detail === undefined ? {} : { detail }) }); }
  catch (error) {
    results.push({ name, status: 'fail', error: error.message });
    if (errors.length) throw new Error(`Application runtime error; aborting dependent tests: ${errors.join('; ')}`);
  }
}
async function screenshot(name) {
  const file = `constellation-v2-${name}.png`;
  await page.screenshot({ path: path.join(__dirname, file), fullPage: false });
  screenshots.push(file);
}
async function assertNoOverflow() {
  const size = await page.evaluate(() => ({ viewport: innerWidth, document: document.documentElement.scrollWidth, body: document.body.scrollWidth }));
  assert(size.document <= size.viewport + 1, `Document overflows: ${JSON.stringify(size)}`);
  assert(size.body <= size.viewport + 1, `Body overflows: ${JSON.stringify(size)}`);
  return size;
}
async function visibleText(selector) { return (await page.locator(selector).innerText()).trim(); }
async function downloadText(action) {
  const pending = page.waitForEvent('download');
  await action();
  const download = await pending;
  assert.equal(await download.failure(), null, 'Download failed');
  const downloadedPath = await download.path();
  assert(downloadedPath, 'Download has no temporary artifact');
  return { name: download.suggestedFilename(), text: fs.readFileSync(downloadedPath, 'utf8') };
}
async function persistentState() {
  return page.evaluate(() => Object.fromEntries(Object.keys(localStorage).map(key => [key, localStorage.getItem(key)])));
}
async function waitText(selector, pattern, timeout = 10000) {
  await page.waitForFunction(({ selector, source, flags }) => {
    const element = document.querySelector(selector);
    return element && new RegExp(source, flags).test(element.textContent);
  }, { selector, source: pattern.source, flags: pattern.flags }, { timeout });
}
async function navigate(view) {
  await page.locator(`button[data-view="${view}"]`).first().click();
  await page.locator(`#view-${view}`).waitFor({ state: 'visible' });
}
async function navigateAll(width, height, mobile) {
  await page.setViewportSize({ width, height });
  const ids = await page.locator('nav button[data-view]').evaluateAll(elements => [...new Set(elements.map(element => element.dataset.view))]);
  assert.equal(ids.length, 6, `Expected six navigation views; found ${ids.join(', ')}`);
  const sizes = [];
  for (const view of ids) {
    await navigate(view);
    const toplineY = await page.locator('.topline').evaluate(element => element.getBoundingClientRect().top);
    sizes.push({ view, ...(await assertNoOverflow()), toplineY });
    if (sizes.length > 1) assert(Math.abs(toplineY-sizes[0].toplineY)<=1, `Topbar shifts between views: ${JSON.stringify(sizes)}`);
    if (!mobile || ['map', 'study', 'runs'].includes(view)) await screenshot(`${mobile ? 'mobile' : 'desktop'}-${view === 'study' ? 'plan' : view}`);
  }
  return sizes;
}

async function exerciseAuthoredV2() {
  const readState = () => page.evaluate(() => JSON.parse(localStorage.getItem('constellation-v2-demo')));
  const openMemory = async () => {
    await navigate('map');
    await page.locator('[data-node="memory"]').click();
    await page.locator('#inspector-action').click();
    await page.locator('#view-study').waitFor({ state: 'visible' });
  };
  const approve = async () => {
    await page.locator('#approval-checkbox').check();
    await page.locator('#approve-button').click();
    assert(!(await page.locator('#launch-button').isDisabled()));
  };
  const exportJson = async () => JSON.parse((await downloadText(() => page.locator('#export-button').click())).text);
  let historicalFixture;

  await check('Chart, table and exported fixture agree numerically', async () => {
    await navigate('compare');
    const rows = await page.locator('#comparison-table tbody tr').evaluateAll(elements => elements.map(tr => [...tr.cells].map(cell => cell.textContent.trim())));
    assert.deepEqual(rows, [['Context only','68%','1,2','1,80'],['Vector memory','82%','2,0','2,60'],['Event memory','89%','2,6','3,10']]);
    const points = await page.locator('.scatter circle[data-candidate]').evaluateAll(elements => elements.map(e => ({ name:e.dataset.candidate, success:Number(e.dataset.success), cost:Number(e.dataset.cost), x:Number(e.getAttribute('cx')), y:Number(e.getAttribute('cy')) })));
    assert.deepEqual(points.map(({name,success,cost}) => ({name,success,cost})), [{name:'Context only',success:68,cost:1.8},{name:'Vector memory',success:82,cost:2.6},{name:'Event memory',success:89,cost:3.1}]);
    for (const point of points) { assert(Math.abs(point.x-(60+(point.cost-1.5)*280))<0.01); assert.equal(point.y,35+(100-point.success)*6); }
    const exported = await exportJson();
    historicalFixture = exported.aggregate_fixture;
    assert.equal(historicalFixture.total_attempts, 1080);
    assert.equal(historicalFixture.unique_cases * historicalFixture.repeats * historicalFixture.candidate_count, 1080);
    assert.equal(historicalFixture.cost_per_complete_hypothetical_run_usd, 27);
    assert.equal(exported.real_api_connected, false);
    assert.equal(exported.actual_cost_usd, 0);
    return { candidates: points.length, attempts: historicalFixture.total_attempts };
  });

  await check('Non-memory map node has its own context and no memory metrics', async () => {
    await navigate('map');
    await page.locator('[data-node="tools"]').click();
    assert.match(await visibleText('#inspector-title'), /Инструменты/);
    assert(await page.locator('#inspector-chart').isHidden());
    assert(await page.locator('#inspector-empty').isVisible());
    await page.locator('#inspector-action').click();
    assert.match(await visibleText('#study-title'), /инструментов/);
    assert(await page.locator('#memory-plan-content').isHidden());
    assert(await page.locator('#launch-button').isDisabled());
  });

  await check('Source import preserves literal safe text and survives reload', async () => {
    const payload='QA <img src=x onerror="window.__qaInjected=true"> & материал';
    await page.locator('#import-button').click();
    await page.locator('[data-import-mode="text"]').click();
    await page.locator('#source-title').fill(payload);
    await page.locator('#source-content').fill('Новый способ маршрутизации. <script>window.__qaInjected=true</script>');
    await page.locator('#source-claim').fill('Требуется проверить точность выбора инструмента.');
    await page.locator('#save-source-button').click();
    assert.equal(await visibleText('#source-detail-heading'), payload);
    assert.equal(await page.locator('#source-detail-dialog img, #source-detail-dialog script').count(), 0);
    assert.equal(await page.evaluate(() => window.__qaInjected), undefined);
    await page.locator('[data-close="source-detail-dialog"]').first().click();
    await page.reload({ waitUntil:'domcontentloaded' });
    await navigate('sources');
    const saved=(await readState()).sources.find(s=>s.title===payload);
    assert(saved, 'Imported source missing from local storage');
    await page.locator(`[data-source="${saved.id}"]`).click();
    assert.equal(await visibleText('#source-detail-heading'), payload);
    await page.locator('#source-create-study').click();
    assert((await visibleText('#study-title')).includes(payload));
    assert.equal((await readState()).plan.family,'models');
    assert(await page.locator('#launch-button').isDisabled());
    assert(await page.locator('#memory-plan-content').isHidden());
    assert.equal(await page.evaluate(() => window.__qaInjected), undefined);
  });

  await check('Fixed plan counts, consent gate and edit require new approval', async () => {
    await openMemory();
    assert.match(await visibleText('#memory-plan-content'), /120/);
    assert.match(await visibleText('#memory-plan-content'), /1\s*080/);
    assert.match(await visibleText('#budget-demo'), /27,00/);
    assert(await page.locator('#approve-button').isDisabled());
    assert(await page.locator('#launch-button').isDisabled());
    await screenshot('desktop-approval');
    await approve();
    const before=(await readState()).plan.version;
    await page.locator('#edit-plan-button').click();
    await page.locator('#plan-title-input').fill('QA · память при обновлении фактов');
    await page.locator('#save-plan-button').click();
    const after=(await readState()).plan;
    assert.equal(after.version,before+1);
    assert.equal(after.approvalVersion,null);
    assert(await page.locator('#launch-button').isDisabled());
    assert(!(await page.locator('#approval-checkbox').isChecked()));
    await page.reload({waitUntil:'domcontentloaded'});
    await navigate('study');
    assert.equal(await visibleText('#study-title'),'QA · память при обновлении фактов');
    assert(await page.locator('#launch-button').isDisabled());
  });

  await check('Unsupported plan cannot approve or launch a memory simulation', async () => {
    await page.locator('#edit-plan-button').click();
    await page.locator('#plan-mode-input').selectOption('reproduction');
    await page.locator('#save-plan-button').click();
    assert(await page.locator('#approval-checkbox').isDisabled());
    assert(await page.locator('#approve-button').isDisabled());
    assert(await page.locator('#launch-button').isDisabled());
    assert(await page.locator('#budget-demo').isHidden());
    assert.match(await visibleText('#approval-status'), /нет исполнимого/);
    await page.locator('#edit-plan-button').click();
    await page.locator('#plan-mode-input').selectOption('benchmark');
    await page.locator('#save-plan-button').click();
  });

  await check('Simulation can pause, resume and cancel with partial history', async () => {
    await approve();
    await page.locator('#launch-button').click();
    await page.waitForFunction(()=>Number(document.querySelector('#run-progress').getAttribute('aria-valuenow'))>0);
    await page.locator('#pause-run-button').click();
    assert.match(await visibleText('#active-run-badge'),/паузе/);
    const paused=(await readState()).runs[0];
    await page.waitForTimeout(700);
    assert.equal((await readState()).runs[0].tick,paused.tick);
    await page.locator('#pause-run-button').click();
    await page.waitForFunction(tick=>JSON.parse(localStorage.getItem('constellation-v2-demo')).runs[0].tick>tick,paused.tick);
    await page.locator('#cancel-run-button').click();
    const cancelled=(await readState()).runs[0];
    assert.equal(cancelled.status,'partial');
    assert(cancelled.tick>0&&cancelled.tick<25);
    assert.equal(cancelled.actualCost,0);
    assert.equal(cancelled.newModelMeasurements,0);
    assert.match(await visibleText('#run-history-body'),/частично/);
  });

  await check('Repeat needs fresh consent, completes and preserves 1080 historical aggregates', async () => {
    await page.locator('#repeat-button').click();
    assert(await page.locator('#launch-button').isDisabled());
    await approve();
    await page.locator('#launch-button').click();
    await waitText('#active-run-badge',/завершено/,16000);
    const saved=(await readState());
    assert.equal(saved.runs.length,2);
    assert.equal(saved.runs[0].status,'completed');
    assert.equal(saved.runs[0].tick,25);
    assert.equal(saved.runs[1].status,'partial');
    assert(saved.runs.every(r=>r.actualCost===0&&r.newModelMeasurements===0));
    await page.locator('#run-report-button').click();
    assert(await page.locator('#view-compare').isVisible());
    const exported=await exportJson();
    assert.deepEqual(exported.aggregate_fixture,historicalFixture);
    assert.equal(exported.aggregate_fixture.total_attempts,1080);
    assert.equal(exported.local_state.runs.length,2);
    return { localRuns:2, newMeasuredAttempts:0, preservedHistoricalAttempts:1080 };
  });

  await check('Evidence opens, switches failed case and exports provenance', async () => {
    await navigate('runs');
    await page.locator('#evidence-button').click();
    assert(await page.locator('#evidence-dialog').isVisible());
    assert.match(await visibleText('#sample-status'),/пройдено/);
    await page.locator('[data-sample="quote"]').click();
    assert.match(await visibleText('#sample-status'),/ошибка/);
    assert.match(await visibleText('#sample-target'),/12 октября/);
    assert.match(await visibleText('#sample-output'),/10 октября/);
    const json=JSON.parse((await downloadText(()=>page.locator('#evidence-export').click())).text);
    assert.equal(json.synthetic,true);
    assert.equal(json.illustrative_samples.length,2);
    assert.equal(json.aggregate_fixture.total_attempts,1080);
    await page.locator('[data-close="evidence-dialog"]').first().click();
    await navigate('compare');
    const csv=(await downloadText(()=>page.locator('#csv-button').click())).text.replace(/^\uFEFF/,'').trim().split(/\r?\n/);
    assert.equal(csv.length,4);
    assert.equal(csv[1],'synthetic_demo,Context only,68,1.2,1.8,360');
    assert.equal(csv[3],'synthetic_demo,Event memory,89,2.6,3.1,360');
  });

  await check('Incompatible cohort suppresses winner claim and saved conclusion', async () => {
    await page.locator('#comparison-condition').selectOption('changed');
    assert(await page.locator('#compatibility-warning').isVisible());
    assert(await page.locator('#comparison-insight').isHidden());
    assert(await page.locator('#save-finding-button').isDisabled());
    assert.match(await visibleText('#compatibility-status'),/Несопоставимые/);
    await page.locator('#comparison-condition').selectOption('same');
    assert(await page.locator('#comparison-insight').isVisible());
    assert(!(await page.locator('#save-finding-button').isDisabled()));
  });

  await check('Saved decision identifies fixed evidence rather than unrelated plan version', async () => {
    await page.locator('#save-finding-button').click();
    await page.locator('#finding-text').fill('QA: проверить ошибки при цитировании старого события.');
    await page.locator('#finding-form button[type="submit"]').click();
    const decision=(await readState()).decisions[0];
    assert.equal(decision.evidence,'memory-demo-v1');
    assert.equal(decision.fixtureRecipeVersion,'memory-fixture-v1');
    await navigate('knowledge');
    assert.match(await visibleText('#decision-list'),/QA: проверить ошибки/);
  });

  await check('Provider roles persist while remaining explicitly disconnected', async () => {
    await page.locator('#settings-button').click();
    assert.match(await visibleText('#settings-dialog'),/Подключения не настроены/);
    await page.locator('#role-researcher').selectOption('Anthropic · макет');
    await page.locator('#role-subject').selectOption('Будущий API-кандидат · не подключён');
    await page.locator('#role-judge').selectOption('LLM-судья · не подключён');
    await page.locator('#save-settings-button').click();
    await navigate('study');
    assert(await page.locator('#launch-button').isDisabled());
    await page.reload({waitUntil:'domcontentloaded'});
    await page.locator('#settings-button').click();
    assert.equal(await page.locator('#role-researcher').inputValue(),'Anthropic · макет');
    assert.match(await visibleText('#settings-dialog'),/Подключения не настроены/);
    await page.locator('[data-close="settings-dialog"]').first().click();
    const exported=await exportJson();
    assert.equal(exported.real_api_connected,false);
    assert.equal(exported.actual_cost_usd,0);
  });

  await check('Historical repeat restores frozen roles and still requires approval', async () => {
    await navigate('runs');
    const previous=(await readState()).runs[0];
    await page.locator('#repeat-button').click();
    const state=await readState();
    assert.deepEqual(state.roles,previous.plan.roles);
    assert.equal(state.plan.approvalVersion,null);
    assert(!(await page.locator('#approval-checkbox').isDisabled()));
    assert(await page.locator('#launch-button').isDisabled());
    assert.deepEqual(state.runs[0],previous);
  });

  await check('Memory draft and archived source plans persist locally', async () => {
    const before=await readState();
    assert(before.draftArchive.length>=2);
    const title=before.plan.title;
    await page.reload({waitUntil:'domcontentloaded'});
    await navigate('study');
    assert.equal(await visibleText('#study-title'),title);
    const after=await readState();
    assert.deepEqual(after.draftArchive,before.draftArchive);
    assert.deepEqual(after.runs,before.runs);
    assert(after.sources.some(source=>source.title.startsWith('QA <img')));
  });
}

(async () => {
  browser = await playwright.chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? {channel:process.env.PLAYWRIGHT_CHANNEL} : {}) });
  context = await browser.newContext({
    viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1,
    locale: 'ru-RU', timezoneId: 'Europe/Moscow', reducedMotion: 'reduce',
    acceptDownloads: true, serviceWorkers: 'block', javaScriptEnabled: !layoutOnly
  });
  await context.route('**/*', async route => {
    const request = route.request();
    if (request.url() === APP_URL && request.isNavigationRequest() && request.method() === 'GET') {
      return route.fulfill({
        status: 200, contentType: 'text/html; charset=utf-8', body: source,
        headers: {
          'Cache-Control': 'no-store',
          'Content-Security-Policy': "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; connect-src 'none'; font-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-src 'none'"
        }
      });
    }
    blockedRequests.push({ url: request.url(), method: request.method(), type: request.resourceType() });
    return route.abort('blockedbyclient');
  });
  page = await context.newPage();
  page.setDefaultTimeout(5000);
  page.on('pageerror', error => { errors.push(error.message); console.error('APP_RUNTIME_ERROR: '+error.message); });
  page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()); });
  await page.goto(APP_URL, { waitUntil: 'domcontentloaded' });
  if (layoutOnly) {
    await page.screenshot({ path: path.join(__dirname, 'constell-v2-first-layout.png'), fullPage: false });
    screenshots.push('constell-v2-first-layout.png');
    await check('Static initial layout has no document overflow (application JavaScript disabled)', assertNoOverflow);
    return;
  }
  await page.waitForTimeout(100);
  assert.deepEqual(errors, [], 'Initial application render failed');
  assert((await page.locator('#study-title').textContent()).trim().length > 0, 'Study title was not rendered');
  await check('Authored application is a standalone inline artifact', async () => {
    assert.equal(await page.locator('script[src],link[rel="stylesheet"],iframe,object,embed').count(), 0);
    assert.match(await page.locator('body').innerText(), /синтетическ/i);
    assert.equal(await page.evaluate(() => location.origin), APP_URL.slice(0, -1));
  });
  await check('All six desktop views render without document overflow', () => navigateAll(1440, 1000, false));
  await check('All six mobile views render without document overflow', () => navigateAll(390, 844, true));
  await page.setViewportSize({ width: 1440, height: 1000 });
  await check('V2 behavioural contract', exerciseAuthoredV2);
  await check('No unhandled JavaScript errors', () => assert.deepEqual(errors, []));
  await check('No console error or CSP violation', () => assert.deepEqual(consoleErrors, []));
  await check('No external request attempted', () => assert.deepEqual(blockedRequests, []));
})().catch(error => {
  results.push({ name: 'Harness execution', status: 'fail', error: error.stack || error.message });
}).finally(async () => {
  if (context) await context.close();
  if (browser) await browser.close();
  const report = {
    testedAt: new Date().toISOString(), appRevisionSha256: sourceHash,
    isolation: { freshHeadlessBrowser: true, freshContext: true, syntheticOrigin: APP_URL, allOtherNetworkBlocked: true, fileNavigation: false, userProfile: false, existingTabAccess: false },
    results, screenshots, errors, consoleErrors, blockedRequests
  };
  if (!layoutOnly) fs.writeFileSync(outPath, JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
  if (results.some(result => result.status === 'fail')) process.exitCode = 1;
});
