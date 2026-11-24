const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const base=path.join(__dirname,'..');
const read=p=>fs.readFileSync(path.join(base,p),'utf8');
const d=JSON.parse(read('investment-thesis/data/thesis_tracker.json'));
const publicData=JSON.parse(read('investment-thesis/data/public_tracker.json'));
const h=JSON.parse(read('docs/data/historical_signals.json'));
const s=JSON.parse(read('docs/data/strategy_status.json'));
const refresh=JSON.parse(read('investment-thesis/data/refresh_status.json'));
const html=read('investment-thesis/index.html');
const script=read('investment-thesis/app.js');
const {check,charts,interpretation,review,alpha,cost,view,effect,difference,stability,chartAnalysis,stockAnalysis,overall,conditions,optionAudit,freshness}=require('../investment-thesis/app.js');
test('Source provenance, source dates and definition agree',()=>{
  check(d,h);
  for(const mutate of [x=>x.source='synthetic',x=>x.market_snapshot_sha256='different',
    x=>x.historical_generated_at='different',x=>x.design.holding_sessions=4,
    x=>x.rolling.pop(),x=>x.full_sample.aggregate.pass_mean_return+=.001]){
    const v=structuredClone(d);mutate(v);assert.throws(()=>check(v,h));
  }
});
test('All stock views plot exactly generated data and preserve null gaps',()=>{
  for(const ticker of ['ALL','BAC','KO','PFE','F']){
    const c=charts(d,ticker);
    assert.equal(c.length,2);
    for(const [i,key] of ['mean_adverse','tail_rate'].entries()){
      for(const [j,cohort] of ['pass','fail','all'].entries()){
        const expected=d.rolling.map(p=>ticker==='ALL'?p.aggregate[cohort+'_'+key]:p.tickers[ticker].sufficient?p.tickers[ticker][cohort][key]:null);
        assert.deepEqual(c[i].traces[j].y,expected);
        assert.equal(c[i].traces[j].connectgaps,false);
        assert.deepEqual(c[i].traces[j].x,d.rolling.map(p=>p.as_of));
      }
    }
  }
  assert.throws(()=>charts(d,'TSLA'));
});
test('Negative or inconclusive findings are not hidden behind profitability claims',()=>{
  for(const fn of [interpretation,review,alpha,cost])assert.doesNotMatch(fn(d),/undefined|NaN/);
  const v=structuredClone(d);v.full_sample.aggregate.baseline_return_spread=-.01;
  assert.match(alpha(v),/does not support/);
  v.full_sample.aggregate.downside_benefit=-.01;
  assert.match(interpretation(v),/does not support/);
  assert.match(cost(d),/not quotes, realized profits or a forecast/);
  assert.match(html,/not an estimate from these data/);
  assert.match(html,/research review conditions, not new order-engine switches/);
});
class Element{
  constructor(){this.children=[];this.value='ALL';this.content='';this.listeners={};}
  set textContent(v){this.content=String(v);this.children=[];}
  get textContent(){return this.content+this.children.map(x=>x.textContent).join(' ');}
  append(...c){this.children.push(...c);}
  replaceChildren(...c){this.children=c;this.content='';}
  addEventListener(name,fn){this.listeners[name]=fn;}
}
async function render({fail=false,plotly=true,mismatch=false,retained=false}={}){
  const nodes=new Map([...html.matchAll(/id="([^"]+)"/g)].map(m=>[m[1],new Element()]));
  const plotted=[],requested=[];
  const document={getElementById:id=>{assert.ok(nodes.has(id));return nodes.get(id);},createElement:()=>new Element()};
  const window=plotly?{Plotly:{react:(target,traces,layout)=>plotted.push({target,traces,layout})}}:{};
  const projected=structuredClone(publicData);if(mismatch)projected.projection.source_proof.market_snapshot_sha256='different';
  const recorded={...refresh,...retained?{status:'failed',evidence_generated_at:d.generated_at,market_snapshot_sha256:d.market_snapshot_sha256}:{}};
  const context=vm.createContext({document,window,fetch:async url=>{requested.push(url);return {ok:!fail,json:async()=>url.includes('public_tracker')?projected:recorded};}});
  vm.runInContext(script,context);await new Promise(resolve=>setImmediate(resolve));
  return {nodes,plotted,requested};
}
test('Real JSON loads into both charts, table and summary without writing orders',async()=>{
  const before=JSON.stringify(d);const r=await render();
  assert.equal(r.plotted.length,2);assert.equal(r.nodes.get('thesis-summary').children.length,4);
  assert.deepEqual(r.requested,['data/public_tracker.json','data/refresh_status.json']);
  assert.equal(r.nodes.get('thesis-reading').textContent,overall(d).join(' '));
  assert.equal(r.nodes.get('thesis-review').textContent,review(d));
  assert.equal(r.nodes.get('thesis-cost').textContent,cost(d));
  assert.ok(!r.nodes.has('order-rows'));
  for(const t of ['BAC','KO','PFE','F','ALL']){
    r.nodes.get('thesis-ticker').value=t;r.nodes.get('thesis-ticker').listeners.change();
    assert.deepEqual(Array.from(r.plotted.at(-2).traces[0].y),charts(d,t)[0].traces[0].y);
    assert.equal(r.nodes.get('thesis-loss-analysis').textContent,chartAnalysis(d,t,'mean_adverse').join(' '));
    assert.equal(r.nodes.get('thesis-tail-analysis').textContent,chartAnalysis(d,t,'tail_rate').join(' '));
    assert.equal(r.nodes.get('thesis-reading').textContent,overall(d,t).join(' '));
  }
  assert.equal(r.nodes.get('thesis-cost-table').children.length,5);
  assert.equal(r.nodes.get('thesis-conditions').children.length,3);
  assert.equal(r.nodes.get('thesis-stock-analysis').children.length,4);
  assert.equal(JSON.stringify(d),before);
});
test('Stale or inaccessible research fails honestly; missing Plotly retains table',async()=>{
  for(const options of [{fail:true},{mismatch:true}]){
    const r=await render(options);assert.equal(r.plotted.length,0);
    assert.match(r.nodes.get('thesis-status').textContent,/unavailable or inconsistent/);
  }
  const r=await render({plotly:false});assert.equal(r.nodes.get('thesis-summary').children.length,4);
  assert.match(r.nodes.get('thesis-loss-chart').textContent,/library unavailable/);
});
test('Every local anchor exists, English text and nightly integration preserved',()=>{
  const ids=[...html.matchAll(/id="([^"]+)"/g)].map(m=>m[1]);
  assert.equal(new Set(ids).size,ids.length);
  for(const m of html.matchAll(/href="#([^"]+)"/g))assert.ok(ids.includes(m[1]),m[1]);
  assert.doesNotMatch(script+html,/[\u4e00-\u9fff]/);
  const workflow=read('.github/workflows/investment-thesis.yaml');
  assert.match(workflow,/python -m investment_thesis.research/);
  assert.match(workflow,/Nightly risk-managed Wheel/);
  assert.match(workflow,/git add -- investment-thesis\/data\/public_tracker.json investment-thesis\/data\/refresh_status.json/);
  assert.match(workflow,/investment_thesis.publication --require-approval/);
  assert.doesNotMatch(html,/href="data\/(thesis_tracker.json|thesis_observations.csv)"/);
  assert.match(workflow,/investment_thesis.refresh --upstream/);
  assert.match(workflow,/refresh_status.json/);
});
test('Narratives reproduce cohort arithmetic and show contradictory results',()=>{
  for(const t of ['ALL','BAC','KO','PFE','F'])for(const k of ['mean_adverse','tail_rate']){
    const s=view(d.full_sample,t),e=effect(s,k);
    assert.ok(Math.abs(e.reduction-(s.all[k]-s.pass[k]))<1e-12);
    assert.ok(Math.abs(e.relative-e.reduction/s.all[k])<1e-12);
    const text=chartAnalysis(d,t,k).join(' ');
    for(const c of ['pass','fail','all'])assert.ok(text.includes((100*s[c][k]).toFixed(2)+'%'));
    assert.doesNotMatch(text,/undefined|NaN|Infinity/);
    const z=stability(d,t,k);
    assert.equal(z.evaluable+z.missing,d.rolling.length);
    assert.equal(z.better+z.worse+z.equal,z.evaluable);
    const actual=d.rolling.filter(p=>{const a=effect(view(p,t),k);return a&&a.reduction<0;});
    assert.equal(z.worse,actual.length);
    assert.equal(z.lastWorse,actual.at(-1)?.as_of||null);
  }
  const changed=structuredClone(d);
  changed.full_sample.tickers.BAC.pass.mean_adverse=.1;
  assert.notEqual(chartAnalysis(changed,'BAC','mean_adverse')[1],chartAnalysis(d,'BAC','mean_adverse')[1]);
  assert.match(chartAnalysis(changed,'BAC','mean_adverse')[1],/Relative change:.*increase/);
  assert.equal(stockAnalysis(d).length,4);
});
test('Zero denominator and insufficient cohorts never invent relative advantage',()=>{
  const s=structuredClone(d.full_sample.tickers.BAC);
  s.all.mean_adverse=0;s.pass.mean_adverse=0;
  assert.equal(effect(s,'mean_adverse').relative,null);
  assert.match(difference(s,'mean_adverse'),/undefined because the benchmark is zero/);
  s.sufficient=false;assert.equal(effect(s,'mean_adverse'),null);
  const changed=structuredClone(d);changed.full_sample.tickers.BAC=s;
  assert.match(chartAnalysis(changed,'BAC','mean_adverse')[1],/Insufficient evidence/);
  assert.doesNotMatch(chartAnalysis(changed,'BAC','mean_adverse')[1],/relative reduction/);
});
test('Freshness reflects actual next exchange close, not a new webpage timestamp',()=>{
  const fresh=new Date(new Date(d.next_market_close_at).getTime()-1);
  const stale=new Date(new Date(d.next_market_close_at).getTime()+1);
  assert.doesNotMatch(freshness(d,s,refresh,fresh),/STALE MARKET/);
  assert.match(freshness(d,s,refresh,stale),/STALE MARKET SNAPSHOT/);
  assert.match(freshness(d,s,{...refresh,status:'failed'},fresh),/STALE \/ FAILED UPDATE/);
  assert.match(freshness(d,s,{},fresh),/status unavailable/);
  assert.ok(freshness(d,s,refresh,stale).includes(d.latest_matured_outcome_date));
});
test('A recorded failure can show intact retained evidence beside a newer source',async()=>{
  const r=await render({mismatch:true,retained:true});
  assert.equal(r.plotted.length,2);
  assert.match(r.nodes.get('thesis-status').textContent,/STALE \/ FAILED UPDATE/);
  assert.equal(r.nodes.get('thesis-reading').textContent,overall(d).join(' '));
});
test('Option audit, economic extension and cost calculations do not claim alpha',()=>{
  assert.match(optionAudit(d),/not yet estimable/);
  assert.match(conditions(d)[2][3],/Not Yet Testable/);
  assert.match(conditions(d)[2][0],/new extension/);
  assert.equal(d.option_audit.economic_advantage,null);
  for(const e of d.cost_budget.examples)for(const c of e.scenarios){
    assert.ok(Math.abs(c.net_dollars-(c.gross_bps*e.collateral/10000-3.3))<1e-9);
  }
  const wrong=structuredClone(d);wrong.cost_budget.examples[0].scenarios[0].net_dollars+=1;
  assert.throws(()=>check(wrong,h),/cost scenario/);
});
