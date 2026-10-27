// Real publication checks; fixture branches are isolated in-memory and never exported.
const {chromium}=require(process.env.WHEEL_PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const base=(process.argv[2]||'http://127.0.0.1:8769/535_fintech/').replace(/\/?$/,'/');
(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:process.env.WHEEL_CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  const context=await browser.newContext({viewport:{width:1440,height:1050},acceptDownloads:true});
  const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  const out=fs.mkdtempSync(path.join(os.tmpdir(),'wheel-browser-'));
  for(const route of ['','covered-call/','covered-call/data.html','pmcc/','wheel/']){
    assert.equal((await page.goto(base+route,{waitUntil:'networkidle'})).status(),200);
    await page.waitForSelector('nav.course-navigation');
    assert.equal(await page.locator('nav.course-navigation a').count(),5);
    assert.equal(await page.locator('nav.course-navigation a').last().getAttribute('href'),base+'wheel/');
  }
  const book=await page.evaluate(()=>window.WHEEL_BOOK);assert.equal(book.synthetic,false);assert.equal(book.runs.length,3);
  const money=x=>new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(x);
  let checks=0;
  for(const model of ['quoted_side','midpoint']){
    await page.selectOption('#model',model);
    for(const strategy of ['wheel','buy_hold']){
      await page.selectOption('#account',strategy);
      const r=book.runs.find(r=>r.strategy===strategy&&(strategy==='buy_hold'||r.fill_model===model));
      for(const day of r.ledger.map(s=>s.date)){
        await page.selectOption('#date',day);
        const states=r.snapshots.filter(s=>s.date===day);
        assert.equal(await page.locator('#snapshot option').count(),states.length);
        for(const state of states){
          await page.selectOption('#snapshot',state.snapshot_id);
          const values=await page.locator('#portfolio-values strong').allTextContents();
          assert.equal(values[0],money(state.cash));assert.equal(values[1],money(state.reserved_cash));assert.equal(values[3],String(state.shares));
          assert.equal(values[6],state.option_liability==null?'N/A':money(state.option_liability));
          assert.equal(values[7],state.equity==null?'N/A':money(state.equity));
          if(state.option)assert.match(await page.locator('#open-option').innerText(),new RegExp(state.option.id.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')));
          checks++;
        }
      }
      await page.fill('#search','NO_MATCHING_CONTRACT');assert.match(await page.locator('#blotter').innerText(),/No recorded events/);
      await page.fill('#search','');assert.equal(await page.locator('#blotter tbody tr').count(),r.events.length);
      if(r.events.length){
        await page.locator('#blotter button[data-key="cash_after"]').click();
        const text=await page.locator('#blotter tbody tr').first().innerText();assert.ok(text.includes(money(Math.min(...r.events.map(e=>e.cash_after)))));
      }
    }
    const plotted=await page.locator('#equity-chart').evaluate(el=>el.data);
    for(const t of plotted){const r=book.runs.find(r=>(t.name==='Buy and hold'?r.strategy==='buy_hold':r.strategy==='wheel'&&r.fill_model===model));assert.deepEqual(t.y,r.ledger.map(x=>x.equity));assert.equal(t.connectgaps,false);}
  }
  for(const file of ['results.json','config.json','data_audit.json','blotter.csv','ledger.csv','snapshots.csv','decisions.csv','coverage.csv','quote_issues.csv'])assert.equal((await context.request.get(base+'wheel/'+file)).status(),200);
  await page.selectOption('#model','quoted_side');await page.selectOption('#account','wheel');
  const assignment=book.runs[0].events.find(e=>e.event_type==='PUT_ASSIGNMENT');
  if(assignment){await page.selectOption('#date',assignment.date);await page.selectOption('#snapshot',assignment.event_id+'-after');}
  await page.screenshot({path:path.join(out,'wheel-desktop.png'),fullPage:true});
  await page.locator('#portfolio').screenshot({path:path.join(out,'wheel-portfolio.png')});
  await page.locator('#performance').screenshot({path:path.join(out,'wheel-performance.png')});
  // Offline inputs / bad JSON must not silently replace market data or results.
  await page.getByText('Adjust parameters and reproduce',{exact:true}).click();
  await page.fill('#config-editor','not json');await page.click('#download-config');assert.match(await page.locator('#config-message').innerText(),/Invalid JSON/);
  await page.fill('#config-editor',JSON.stringify(book.config));const download=page.waitForEvent('download');await page.click('#download-config');assert.equal((await download).suggestedFilename(),'wheel-custom-config.json');
  assert.deepEqual(await page.evaluate(()=>window.WHEEL_BOOK),book,'UI must not mutate results');
  await page.setViewportSize({width:390,height:844});await page.reload({waitUntil:'networkidle'});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Mobile overflow');
  await page.screenshot({path:path.join(out,'wheel-mobile.png'),fullPage:true});
  await page.locator('#portfolio').screenshot({path:path.join(out,'wheel-portfolio-mobile.png')});
  assert.deepEqual(errors,[]);console.log(JSON.stringify({routes:5,navigationLinks:25,downloads:9,snapshotChecks:checks,browserErrors:errors,screenshots:out},null,2));
  await browser.close();
})().catch(e=>{console.error(e);process.exit(1);});
