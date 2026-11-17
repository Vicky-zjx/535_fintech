const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const base=path.join(__dirname,'..');
const h=JSON.parse(fs.readFileSync(path.join(base,'docs/data/historical_signals.json')));
const archive=JSON.parse(fs.readFileSync(path.join(base,'docs/data/entry_demo_status.json')));
const status=JSON.parse(fs.readFileSync(path.join(base,'docs/data/strategy_status.json')));
const {check,findings,selectRange,seriesCharts,restrictionStats,alignment}=require('../docs/assets/history.js');
const html=fs.readFileSync(path.join(base,'docs/index.html'),'utf8');
const script=fs.readFileSync(path.join(base,'docs/assets/history.js'),'utf8');
test('Historical interpretation uses verified published counts and no fabricated returns',()=>{
  const before=JSON.stringify(h);check(h);const text=findings(h).join(' ');
  assert.match(text,/eligibility, not avoided losses/);
  assert.match(text,/multiple|at least two/);
  assert.doesNotMatch(text,/undefined|NaN|N\/A/);
  assert.equal(before,JSON.stringify(h));
});
test('Invalid provenance, counts and denominators fail rather than becoming zero',()=>{
  for(const change of [d=>d.source='synthetic',d=>d.tickers.BAC.weekly.pass_counts.trend++,d=>d.tickers.BAC.weekly.evaluated_dates++,d=>d.joint_weekly.distribution[0]++]) {
    const d=structuredClone(h);change(d);assert.throws(()=>check(d));
  }
});
test('Required section order, method and existing SVG/navigation remain intact',()=>{
  const actual=[...html.matchAll(/<section id="([^"]+)"/g)].map(m=>m[1]);
  assert.deepEqual(actual,['objective','workflow','universe','rules','risk','historical','decisions','orders','demonstration','measurement','analysis','evaluation','reproducibility']);
  assert.match(html,/IV–RV thesis is untested/);assert.match(html,/vintage prices/);
  assert.match(html,/risk-free series/);assert.match(html,/data-course-nav/);assert.match(html,/strategy-workflow.svg/);
  assert.doesNotMatch(html+script,/[\u4e00-\u9fff]/);
});
class Element {
  constructor(){this.children=[];this.value='BAC';this.content='';this.listeners={};}
  set textContent(v){this.content=String(v);this.children=[];}
  get textContent(){return this.content+this.children.map(c=>c.textContent).join(' ');}
  append(...c){this.children.push(...c);}
  replaceChildren(...c){this.content='';this.children=c;}
  addEventListener(name,fn){this.listeners[name]=fn;}
}
async function render(fail=false, plotly=true){
  const nodes=new Map([...html.matchAll(/id="([^"]+)"/g)].map(m=>[m[1],new Element()]));
  nodes.get('history-range').value='3Y';
  const charts=[];
  const document={getElementById:id=>{assert.ok(nodes.has(id),id);return nodes.get(id);},createElement:()=>new Element()};
  const window=plotly?{Plotly:{react:(node,traces,layout)=>charts.push({node,traces,layout})}}:{};
  const requests=[];
  const context=vm.createContext({document,window,fetch:async url=>{requests.push(url);return {ok:!fail,status:503,json:async()=>url.includes('entry_demo')?archive:url.includes('strategy_status')?status:h};}});
  vm.runInContext(script,context);await new Promise(resolve=>setImmediate(resolve));
  return {nodes,charts,requests};
}
test('Historical tables, plotted arrays and archived demo use actual saved evidence',async()=>{
  const {nodes,charts,requests}=await render();assert.equal(nodes.get('history-weekly').children.length,4);
  assert.equal(charts.length,5);assert.equal(charts[2].traces.length,3);
  assert.equal(charts[2].node,nodes.get('history-price-chart'));
  assert.deepEqual(requests.sort(),['data/entry_demo_status.json','data/historical_signals.json','data/strategy_status.json']);
  assert.deepEqual(Array.from(charts[2].traces[0].y),h.tickers.BAC.daily_rows.map(r=>r.close));
  assert.ok(charts.slice(2).every(c=>c.traces.every(t=>t.connectgaps===false)));
  assert.equal(charts[3].layout.shapes[0].y0,.45);assert.equal(charts[4].layout.shapes[0].y0,-.08);
  assert.equal(nodes.get('history-restrictions').children.length,3);
  assert.equal(nodes.get('history-alignment').textContent,alignment(h,status));
  assert.match(nodes.get('weekly-entry-demo').textContent,/2026-11-13/);
  assert.match(nodes.get('weekly-entry-demo').textContent,/2 proposals/);
  assert.equal(nodes.get('order-rows').children.length,0);
  nodes.get('history-ticker').value='KO';nodes.get('history-ticker').listeners.change();
  assert.deepEqual(Array.from(charts.at(-3).traces[0].y),h.tickers.KO.daily_rows.map(r=>r.close));
  const fullComparison=nodes.get('history-weekly').textContent;
  nodes.get('history-range').value='1M';nodes.get('history-range').listeners.change();
  assert.deepEqual(Array.from(charts.at(-3).traces[0].y),selectRange(h,'KO','1M').rows.map(r=>r.close));
  assert.equal(nodes.get('history-weekly').textContent,fullComparison);
  assert.match(nodes.get('history-range-note').textContent,/KO · 1M/);
});
test('Unavailable analysis or chart library does not imply a successful zero result',async()=>{
  const {nodes}=await render(true);assert.match(nodes.get('history-status').textContent,/unavailable or inconsistent/);
  assert.match(nodes.get('weekly-entry-demo').textContent,/not verified/);
  const good=await render(false,false);assert.match(good.nodes.get('history-filter-chart').textContent,/library unavailable/);
  assert.equal(good.nodes.get('history-weekly').children.length,4);
});
test('All sixteen stock/range combinations preserve exact saved observations and SMA warmup',()=>{
  const before=JSON.stringify(h);
  for(const ticker of ['BAC','KO','PFE','F'])for(const range of ['1M','3M','1Y','3Y']){
    const {selected,charts}=seriesCharts(h,ticker,range);
    assert.equal(selected.end,h.window.analysis_end);
    assert.ok(selected.rows.length>0);
    assert.equal(selected.rows.at(-1).signal_date,h.window.analysis_end);
    const rows=h.tickers[ticker].daily_rows.filter(r=>r.signal_date>=selected.start);
    for(const [i,key] of ['close','sma20','sma50'].entries())assert.deepEqual(charts[0].traces[i].y,rows.map(r=>r[key]));
    assert.deepEqual(charts[1].traces[0].y,rows.map(r=>r.hv20));
    assert.deepEqual(charts[2].traces[0].y,rows.map(r=>r.r5));
    assert.ok(charts[1].layout.yaxis.range[1]>.45);
    assert.ok(charts[2].layout.yaxis.range[0]<-.08);
    assert.equal(charts[0].layout.xaxis.type,'date');
  }
  assert.equal(selectRange(h,'BAC','3Y').rows.length,h.tickers.BAC.daily_rows.length);
  const datedFixture={...h,window:{...h.window,analysis_end:'2026-11-16',analysis_start:'2023-11-16'}};
  assert.equal(selectRange(datedFixture,'BAC','1M').start,'2026-10-16');
  assert.equal(selectRange(datedFixture,'BAC','3M').start,'2026-08-16');
  assert.equal(selectRange(datedFixture,'BAC','1Y').start,'2025-11-16');
  assert.equal(JSON.stringify(h),before);
  assert.throws(()=>selectRange(h,'AAPL','1M'));assert.throws(()=>selectRange(h,'BAC','5Y'));
});
test('Calendar-month range clamps month end and never uses the browser clock',()=>{
  const copy=structuredClone(h);copy.window.analysis_end='2024-03-31';copy.window.analysis_start='2023-01-01';
  assert.equal(selectRange(copy,'BAC','1M').start,'2024-02-29');
});
test('Missing observations remain null gaps, including SMA and threshold panels',()=>{
  const copy=structuredClone(h), row=copy.tickers.BAC.daily_rows.at(-3);
  for(const k of ['close','sma20','sma50','hv20','r5'])row[k]=null;
  const {charts}=seriesCharts(copy,'BAC','1M');
  for(const c of charts)for(const t of c.traces){assert.equal(t.y.at(-3),null);assert.equal(t.connectgaps,false);}
});
test('Standalone and exclusive restrictions reproduce from individual entry rows',()=>{
  const rows=Object.values(h.tickers).flatMap(d=>d.weekly_rows).filter(r=>r.valid);
  for(const r of restrictionStats(h)){
    assert.equal(r.evaluated,rows.length);
    assert.equal(r.standalone,rows.filter(v=>!v[r.key]).length);
    assert.equal(r.exclusive,rows.filter(v=>!v[r.key]&&['trend','volatility','sudden_drop'].every(k=>k===r.key||v[k])).length);
  }
});
test('Latest successful run must agree in hash, dates, revision and each closing indicator',()=>{
  // An isolated metadata fixture stays stable when the nightly data advance or fail.
  // Its numeric rows are copied unchanged from real saved observations.
  const tickers=['BAC','KO','PFE','F'];
  const commonDate=h.tickers.BAC.daily_rows.find(r=>tickers.every(t=>h.tickers[t].daily_rows.some(v=>v.signal_date===r.signal_date&&v.valid))).signal_date;
  const observed=Object.fromEntries(tickers.map(t=>[t,h.tickers[t].daily_rows.find(r=>r.signal_date===commonDate)]));
  const fixtureH={...h,window:{...h.window,analysis_end:commonDate},tickers:Object.fromEntries(Object.entries(observed).map(([t,r])=>[t,{daily_rows:[r]}]))};
  const fixtureS={...status,status:'success',market_snapshot_sha256:h.market_snapshot_sha256,
    market_data_retrieved_at:h.market_retrieved_at,strategy_revision:h.strategy_revision,
    calendar:{as_of:commonDate,target_session:'TEST'},
    decisions:Object.entries(observed).map(([ticker,r])=>({...r,ticker,price_date:r.signal_date}))};
  assert.match(alignment(fixtureH,fixtureS),/Verified against/);
  for(const mutate of [s=>s.market_snapshot_sha256='wrong',s=>s.market_data_retrieved_at='wrong',s=>s.strategy_revision='wrong',s=>s.calendar.as_of='1900-01-01',s=>s.status='blocked']){
    const s=structuredClone(fixtureS);mutate(s);assert.match(alignment(fixtureH,s),/does not match/);
  }
  const s=structuredClone(fixtureS);s.decisions[0].close+=1;
  assert.match(alignment(fixtureH,s),/unavailable or inconsistent/);
  const stale=structuredClone(fixtureH);stale.tickers.BAC.daily_rows[0].signal_date='1900-01-01';
  assert.match(alignment(stale,fixtureS),/unavailable or inconsistent/);
});
test('Inconsistent series, duplicate dates or internally consistent but false summary counts fail closed',()=>{
  for(const mutate of [d=>d.tickers.BAC.daily_rows.pop(),d=>d.tickers.BAC.daily_rows[1].signal_date=d.tickers.BAC.daily_rows[0].signal_date,d=>d.tickers.BAC.daily_rows[0].close='50',d=>{const s=d.tickers.BAC.weekly;s.pass_counts.trend++;s.pass_rates.trend=s.pass_counts.trend/s.evaluated_dates;},d=>d.tickers.BAC.weekly.exclusive_rejections.trend++]){
    const copy=structuredClone(h);mutate(copy);assert.throws(()=>check(copy));
  }
});
