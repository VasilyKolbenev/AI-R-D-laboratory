/* TEST_ONLY: inline motion player with an in-memory API. No server, provider, research or Telegram. */
const assert = require('assert/strict'), fs = require('fs'), path = require('path');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..'), out = path.join(__dirname, 'qa-motion');
const base = 'http://127.0.0.1:8812', checks = [], errors = [], unexpected = [], requests = [];
let browser, page;
const baselineNote = 'TEST_ONLY: baseline не задан; ускорение и экономия неизвестны.';
const hostileNote = '<img src="https://TEST_ONLY.invalid/note" onerror="window.__motionExecuted=true"><script>window.__motionExecuted=true</script><svg onload="window.__motionExecuted=true">TEST_ONLY</svg>';
const variants = {
  motion: {version: 'dataflow-v1', video: true, note: baselineNote},
  legacy: {version: null, video: true},
  wrongversion: {version: 'TEST_ONLY-unsupported', video: true},
  unavailable: {version: 'dataflow-v1', video: false},
  hostile: {version: 'dataflow-v1', video: true, note: hostileNote},
};
const runs = Object.keys(variants).map(key => ({id: 'TEST_ONLY-' + key, status: 'completed', created_at: '2026-10-21T09:00:00Z', finished_at: '2026-10-21T09:01:00Z', output: 'TEST_ONLY: сохранённый отчёт без нового исследования.', plan: {question: 'TEST_ONLY: ' + key, provider: 'codex', web_search: false, sources: []}}));
const boot = {csrf: 'TEST_ONLY_csrf', version: 'TEST_ONLY', settings: {provider: 'codex', model: '', timeout_seconds: 180, daily_run_limit: 3, web_search: false}, providers: [], telegram: {configured: false}, counts: {sources: 0, runs: runs.length, knowledge: 0}};
const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="960" height="600" viewBox="0 0 960 600"><rect width="960" height="600" fill="#152c39"/><text x="45" y="85" fill="#d8e9e3" font-size="36">TEST_ONLY motion UI fixture</text><path d="M100 290H830" stroke="#82d4bd" stroke-width="12"/></svg>';
function presentation(run) {
  const item = variants[run.id.replace('TEST_ONLY-', '')];
  const data = {title: 'TEST_ONLY: движение компонентов', story: [{id: 'takeaway', title: 'Практический вывод', text: 'TEST_ONLY: схематическое движение без измерения скорости.'}], next_step: 'TEST_ONLY: проверить применимость.', post_text: 'TEST_ONLY: без отправки.', visual: {png_available: false, video_available: item.video}, provenance: {editorial_version: 12}};
  if (item.version) data.motion_story = {version: item.version, baseline: {note: item.note || baselineNote}};
  return data;
}
async function check(name, work) {await work(); checks.push({name, status: 'pass'});}
async function openRun(key) {
  await page.locator('.run-row').filter({hasText: 'TEST_ONLY: ' + key}).click();
  const image = page.locator('.infographic-image[src^="/api/runs/TEST_ONLY-' + key + '/card."]');
  await image.waitFor(); await image.scrollIntoViewIfNeeded();
  await page.waitForFunction(key => {const image = document.querySelector('.infographic-image'); return image?.getAttribute('src')?.startsWith('/api/runs/TEST_ONLY-' + key + '/') && image.complete && image.naturalWidth > 0;}, key);
}
async function assertFits() {
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true, 'Horizontal page overflow');
  assert.equal(await page.locator('.motion-preview video').evaluate(video => {const box = video.getBoundingClientRect(); return box.width > 0 && box.left >= -1 && box.right <= innerWidth + 1;}), true, 'Motion player outside viewport');
}
async function routeRequest(route) {
  const request = route.request(), url = new URL(request.url()), p = url.pathname;
  requests.push({method: request.method(), path: p});
  if (url.origin !== base || request.method() !== 'GET') {unexpected.push(request.method() + ' ' + request.url()); return route.abort();}
  const file = p === '/' ? 'index.html' : p === '/assets/app.js' ? 'app.js' : p === '/assets/style.css' ? 'style.css' : null;
  if (file) return route.fulfill({contentType: file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html', body: fs.readFileSync(path.join(root, 'laboratory/web', file))});
  if (p === '/favicon.ico') return route.fulfill({status: 204, body: ''});
  let data;
  if (p === '/api/bootstrap') data = boot;
  else if (p === '/api/sources' || p === '/api/tasks') data = {items: []};
  else if (p === '/api/runs') data = {items: runs};
  else if (p === '/api/memory') data = {profile: {version: 1, review_days: 30}, corrections: []};
  else if (p === '/api/study/schema') data = {task_types: [], evidence_levels: [], template: {}};
  else if (p === '/api/review/schema') data = {criteria: [], template: {}};
  else {
    const match = p.match(/^\/api\/runs\/(TEST_ONLY-(?:motion|legacy|wrongversion|unavailable|hostile))(?:\/(presentation|review|card\.svg|animation\.mp4))?$/);
    const run = match && runs.find(item => item.id === match[1]);
    if (run) {
      if (!match[2]) data = run;
      else if (match[2] === 'presentation') data = presentation(run);
      else if (match[2] === 'review') data = {current: null, history: [], costs: {}};
      else if (match[2] === 'card.svg') return route.fulfill({contentType: 'image/svg+xml', body: svg});
      // Metadata-only response: the fixture tests player wiring and layout, not media decoding.
      else return route.fulfill({status: 204, contentType: 'video/mp4', body: ''});
    }
  }
  if (data !== undefined) return route.fulfill({contentType: 'application/json', body: JSON.stringify(data)});
  unexpected.push(request.method() + ' ' + request.url());
  return route.fulfill({status: 400, contentType: 'application/json', body: '{"error":"TEST_ONLY unexpected request"}'});
}
(async () => {try {
  fs.mkdirSync(out, {recursive: true});
  browser = await chromium.launch({headless: true, channel: 'chrome'});
  const context = await browser.newContext({viewport: {width: 1440, height: 1100}, locale: 'ru-RU', timezoneId: 'Europe/Moscow', reducedMotion: 'reduce', serviceWorkers: 'block'});
  await context.route('**/*', routeRequest); page = await context.newPage(); page.setDefaultTimeout(9000);
  page.on('pageerror', error => errors.push('pageerror: ' + error.message));
  page.on('console', message => {if (message.type() === 'error') errors.push('console: ' + message.text());});
  await page.goto(base, {waitUntil: 'networkidle'}); await page.locator('.nav-button[data-view="runs"]').click();
  await check('Valid motion story renders one local MP4 player with controls, muted loop, inline metadata and no autoplay', async () => {
    await openRun('motion'); assert.equal(await page.locator('.motion-preview').count(), 1);
    const state = await page.locator('.motion-preview video').evaluate(video => ({src: video.getAttribute('src'), controls: video.controls, loop: video.loop, muted: video.muted, playsInline: video.playsInline, preload: video.preload, autoplay: video.autoplay, autoplayAttribute: video.hasAttribute('autoplay'), paused: video.paused, label: video.getAttribute('aria-label')}));
    assert.deepEqual(state, {src: '/api/runs/TEST_ONLY-motion/animation.mp4?v=12', controls: true, loop: true, muted: true, playsInline: true, preload: 'metadata', autoplay: false, autoplayAttribute: false, paused: true, label: 'Движение данных и работа компонентов: TEST_ONLY: движение компонентов'});
  });
  await check('Caption preserves the unknown baseline and makes schematic speed explicit', async () => {
    assert.equal(await page.locator('.motion-preview figcaption').textContent(), 'Условное движение данных: порядок и связи, без измерения скорости. ' + baselineNote);
    assert.equal(await page.locator('.infographic-image').getAttribute('src'), '/api/runs/TEST_ONLY-motion/card.svg?v=12');
  });
  await check('Desktop and mobile layouts keep the motion player inside the viewport', async () => {
    await assertFits(); await page.screenshot({path: path.join(out, 'TEST_ONLY-motion-desktop.png'), fullPage: true});
    await page.setViewportSize({width: 390, height: 844}); await assertFits();
    await page.screenshot({path: path.join(out, 'TEST_ONLY-motion-mobile.png'), fullPage: true});
  });
  await check('Missing story, unknown story version and unavailable video retain old cover with no inline player or MP4 request', async () => {
    for (const key of ['legacy', 'wrongversion', 'unavailable']) {
      await openRun(key); assert.equal(await page.locator('.motion-preview, .motion-preview video').count(), 0);
      assert.equal(await page.locator('.infographic-cover>h3').innerText(), 'Сравнение · применение · границы');
      assert.equal(await page.locator('.infographic-image').getAttribute('src'), '/api/runs/TEST_ONLY-' + key + '/card.svg?v=12');
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
      assert.equal(requests.some(item => item.path === '/api/runs/TEST_ONLY-' + key + '/animation.mp4'), false);
    }
  });
  await check('Untrusted baseline note is literal text and executes no markup or external request', async () => {
    await openRun('hostile'); assert.equal(await page.locator('.motion-preview figcaption').textContent(), 'Условное движение данных: порядок и связи, без измерения скорости. ' + hostileNote);
    assert.equal(await page.locator('.motion-preview figcaption img,.motion-preview figcaption script,.motion-preview figcaption svg').count(), 0);
    assert.equal(await page.evaluate(() => window.__motionExecuted), undefined); await assertFits();
    await page.setViewportSize({width: 1440, height: 1100}); await assertFits();
    await page.screenshot({path: path.join(out, 'TEST_ONLY-motion-untrusted-desktop.png'), fullPage: true});
  });
  await check('Browsing makes no unexpected requests, mutations, provider calls, Telegram calls or browser errors', async () => {
    assert.deepEqual(errors, []); assert.deepEqual(unexpected, []);
    assert.equal(requests.some(item => item.method !== 'GET'), false);
    assert.equal(requests.some(item => /telegram|provider|\/start|\/save|\/cancel/.test(item.path)), false);
  });
  const result = {test_only: true, media_fixture: '204 metadata response; playback decoding not tested', checks, errors, unexpected, request_count: requests.length, mutations: 0, provider_calls: 0, telegram_calls: 0};
  fs.writeFileSync(path.join(out, 'TEST_ONLY-ui-motion-v012.json'), JSON.stringify(result, null, 2));
  const failure = path.join(out, 'TEST_ONLY-ui-motion-v012-failure.json'); if (fs.existsSync(failure)) fs.unlinkSync(failure);
  console.log(JSON.stringify(result, null, 2));
} finally {if (browser) await browser.close();}})().catch(error => {
  fs.mkdirSync(out, {recursive: true}); fs.writeFileSync(path.join(out, 'TEST_ONLY-ui-motion-v012-failure.json'), JSON.stringify({test_only: true, checks, errors, unexpected, error: error.stack}, null, 2)); console.error(error.stack); process.exitCode = 1;
});
