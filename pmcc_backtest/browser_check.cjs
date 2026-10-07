// Optional end-to-end verification; Node/Playwright are not a site build dependency.
const {chromium}=require(process.env.PMCC_PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const base=(process.argv[2]||'http://127.0.0.1:8768/535_fintech/').replace(/\/?$/,'/');
(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:process.env.PMCC_CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',args:['--enable-unsafe-swiftshader']});
  const context=await browser.newContext({viewport:{width:1440,height:1100}});
  const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
  const output=fs.mkdtempSync(path.join(os.tmpdir(),'pmcc-browser-'));
  const expected=['','covered-call/','covered-call/data.html','pmcc/'].map(p=>base+p);
  for(const route of ['','options_surface_preview.html','covered-call/','covered-call/data.html','pmcc/']){
    const response=await page.goto(base+route,{waitUntil:'networkidle'});assert.equal(response.status(),200,route);
    await page.waitForSelector('nav.course-navigation');
    const links=await page.locator('nav.course-navigation a').evaluateAll(as=>as.map(a=>a.href));
    assert.deepEqual(links,expected,route+' course navigation');
    for(const url of links){assert.equal((await context.request.get(url)).status(),200,url);}
    if(route==='covered-call/'){
      const result=await page.evaluate(()=>window.COVERED_CALL_BOOK);
      assert.ok(Math.abs(result.metrics.ending_nav-32260.99)<1e-8);
      assert.equal(result.blotter.length,19);
      assert.ok(await page.locator('#nav-chart .main-svg').count());
    }
    if(route==='covered-call/data.html')assert.match(await page.locator('#connection-status').innerText(),/Data connection required/);
  }
  await page.reload({waitUntil:'networkidle'});
  const book=await page.evaluate(()=>window.PMCC_BOOK);
  assert.equal(book.status,'incomplete');assert.equal(book.runs.length,6);
  assert.equal(book.contract_catalogue.length,306);assert.equal(book.audit.assumption_contracts,306);
  assert.equal(book.audit.individually_verified_contracts,0);assert.equal(book.audit.excluded_contracts.length,50);
  assert.equal(await page.locator('#nav-chart .main-svg').count()>0,true);
  assert.equal(await page.locator('#weekly tbody tr').count(),13);
  assert.equal(await page.locator('#gaps tbody tr').count(),1);
  assert.equal(await page.locator('#contract-table tbody tr').count(),306);
  const plotted=await page.locator('#nav-chart').evaluate(el=>el.data);
  assert.equal(plotted.length,3);assert.equal(plotted[0].y.filter(y=>y==null).length,1);
  assert.equal(plotted[0].connectgaps,false);assert.equal(plotted[2].y.filter(y=>y==null).length,0);
  assert.match(await page.locator('#metrics').innerText(),/1,841\.60/);
  assert.match(await page.locator('#metrics').innerText(),/1 missing NAV date\(s\): 2026-07-23/);
  assert.match(await page.locator('#dd-note').innerText(),/LOWER BOUND/);
  let dd=await page.locator('#dd-chart').evaluate(el=>el.data[0]);
  assert.equal(dd.y.filter(x=>x==null).length,1);assert.equal(dd.connectgaps,false);
  assert.match(await page.locator('#dd-title').innerText(),/Observed-NAV/);
  await page.selectOption('#drawdown-view','drawdown');
  await page.waitForFunction(()=>document.getElementById('dd-chart').data[0].y.at(-1)===null);
  dd=await page.locator('#dd-chart').evaluate(el=>el.data[0]);
  const firstGap=dd.x.indexOf('2026-07-23');assert.ok(dd.y.slice(firstGap).every(x=>x==null));
  await page.selectOption('#drawdown-view','observed_drawdown');
  assert.match(await page.locator('#coverage-note').innerText(),/All 4 September/);
  assert.match(await page.locator('#weekly').innerText(),/2026-10-02/);
  assert.equal(book.runs.every(r=>r.metrics.terminal_resolved&&r.audit.pnl_reconciled),true);
  assert.match(await page.locator('#assignment-example').textContent(),/No assignment occurred/);
  assert.match(await page.locator('#weekly').innerText(),/2026-09-08/);
  await page.selectOption('#model','quoted_side');
  assert.match(await page.locator('#metrics').innerText(),/1,437\.60/);
  await page.fill('#search','AAPLI172723000.U');assert.equal(await page.locator('#trades tbody tr').count(),2);
  await page.fill('#search','NO_SUCH_CONTRACT');assert.match(await page.locator('#trades').innerText(),/No events match/);
  await page.fill('#search','');await page.selectOption('#account','buy_hold');
  assert.match(await page.locator('#gaps').innerText(),/No valuation/);
  assert.equal(await page.locator('#trades tbody tr').count(),4);
  await page.selectOption('#account','pmcc');await page.selectOption('#model','midpoint');
  for(const name of ['trades.csv','daily_nav.csv','weekly_coverage.csv','results.json','config.json','data_audit.json','contracts.csv','exclusions.csv','candidate_coverage.csv','quote_rechecks.csv']){
    const res=await context.request.get(base+'pmcc/'+name);assert.equal(res.status(),200,name);
    const text=await res.text();assert.ok(text.length>20,name);
    if(name==='trades.csv')assert.equal(text.trim().split('\n').length,125);
    if(name==='daily_nav.csv')assert.equal(text.trim().split('\n').length,373);
    if(name==='results.json')assert.equal(JSON.parse(text).input_sha256,book.input_sha256);
  }
  await page.screenshot({path:path.join(output,'pmcc-desktop.png'),fullPage:true});
  await page.locator('#results').screenshot({path:path.join(output,'pmcc-results.png')});
  // UI-only complete-state fixture: verify the card note is not hardcoded.
  await page.evaluate(()=>{for(const r of window.PMCC_BOOK.runs){r.metrics.max_drawdown=-.05;r.metrics.valuation_path_complete=true;r.metrics.valuation_gap_sessions=0;r.metrics.valuation_gap_dates=[];}document.getElementById('model').dispatchEvent(new Event('change'));});
  assert.match(await page.locator('#metrics').innerText(),/Complete research window/);
  assert.doesNotMatch(await page.locator('#metrics').innerText(),/Unavailable/);
  assert.match(await page.locator('#dd-note').innerText(),/All daily NAVs are available/);
  await page.setViewportSize({width:390,height:844});await page.reload({waitUntil:'networkidle'});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'mobile page should not overflow');
  await page.screenshot({path:path.join(output,'pmcc-mobile.png'),fullPage:true});
  assert.deepEqual(errors,[],'browser exceptions');
  console.log(JSON.stringify({base,routes:5,navigationLinks:20,downloads:10,weeklyOpportunities:13,realScenarios:6,contracts:306,valuationGapsPreserved:1,oldResultPreserved:true,browserErrors:errors,screenshots:output},null,2));
  await browser.close();
})().catch(e=>{console.error(e);process.exit(1);});
