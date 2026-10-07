// Render only newly authored project documents in a fresh isolated test browser.
// No file navigation, user profile, existing tabs, CDP or local server.
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const assert = require('assert/strict');
const playwright = require('playwright');
const origin = 'http://alpha-docs-test.invalid';
const inputs = ['implementation-plan', 'claude-task-001'];
const documents = Object.fromEntries(inputs.map(name => [name, fs.readFileSync(path.join(__dirname, '../docs', name + '.html'), 'utf8')]));
const revisions = Object.fromEntries(Object.entries(documents).map(([name, source]) => [name, crypto.createHash('sha256').update(source).digest('hex')]));
const errors = [], blocked = [], results = [], screenshots = [];
let browser, context;
(async () => {
  browser = await playwright.chromium.launch({headless:true, ...(process.env.PLAYWRIGHT_CHANNEL ? {channel:process.env.PLAYWRIGHT_CHANNEL} : {})});
  context = await browser.newContext({locale:'ru-RU', timezoneId:'Europe/Moscow', reducedMotion:'reduce', serviceWorkers:'block'});
  await context.route('**/*', async route => {
    const match = inputs.find(name => route.request().url() === `${origin}/${name}`);
    if (match && route.request().isNavigationRequest()) return route.fulfill({status:200, contentType:'text/html; charset=utf-8', body:documents[match], headers:{'Content-Security-Policy':"default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'none'; img-src 'none'; font-src 'none'; object-src 'none'; form-action 'none'; base-uri 'none'"}});
    blocked.push(route.request().url());
    return route.abort('blockedbyclient');
  });
  const page = await context.newPage();
  page.setDefaultTimeout(5000);
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if(message.type()==='error') errors.push(message.text()); });
  for (const name of inputs) {
    await page.goto(`${origin}/${name}`, {waitUntil:'domcontentloaded'});
    for (const width of [1440,390]) {
      await page.setViewportSize({width,height:width===1440?1000:844});
      await page.evaluate(() => window.scrollTo(0,0));
      const layout = await page.evaluate(() => ({viewport:innerWidth, document:document.documentElement.scrollWidth}));
      assert(layout.document<=layout.viewport+1, `${name} overflow at ${width}`);
      const screenshot=`${name}-${width===1440?'desktop':'mobile'}-alpha.png`;
      await page.screenshot({path:path.join(__dirname,screenshot)});
      screenshots.push(screenshot);
      results.push({name:`${name}: layout ${width}`,status:'pass',detail:layout});
    }
    if(name==='implementation-plan') {
      assert.match(await page.locator('#schedule').innerText(),/4–5 недель/);
      assert.equal(await page.locator('#schedule table tbody tr').count(),5);
      assert.match(await page.locator('#team').innerText(),/Claude Code/);
      await page.setViewportSize({width:1440,height:1000});
      await page.locator('#schedule').scrollIntoViewIfNeeded();
      const screenshot='alpha-schedule-desktop.png';
      await page.screenshot({path:path.join(__dirname,screenshot)}); screenshots.push(screenshot);
      results.push({name:'Five weekly stages and assigned roles',status:'pass'});
    } else {
      await page.locator('#copyPrompt').click();
      assert.match(await page.locator('#copyStatus').innerText(),/скопировано|выделен/);
      assert.match(await page.locator('#handoffPrompt').inputValue(),/TASK-001/);
      results.push({name:'Manual handoff copy or selection fallback',status:'pass'});
    }
  }
  assert.deepEqual(errors,[]); assert.deepEqual(blocked,[]);
  results.push({name:'No JavaScript errors or external requests',status:'pass'});
})().catch(error=>results.push({name:'Document QA',status:'fail',error:error.stack})).finally(async()=>{
  if(context)await context.close(); if(browser)await browser.close();
  const report={testedAt:new Date().toISOString(),revisions,isolation:{freshBrowser:true,freshContext:true,fileNavigation:false,userProfile:false,existingTabAccess:false,externalNetwork:false},results,screenshots,errors,blocked};
  fs.writeFileSync(path.join(__dirname,'alpha-plan-results.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify(report,null,2));
  if(results.some(r=>r.status==='fail'))process.exitCode=1;
});
