const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const base=path.join(__dirname,'..');
const read=p=>fs.readFileSync(path.join(base,p),'utf8');
const d=JSON.parse(read('investment-thesis/data/thesis_tracker.json'));
const h=JSON.parse(read('docs/data/historical_signals.json'));
const s=JSON.parse(read('docs/data/strategy_status.json'));
const html=read('investment-thesis/index.html');
const script=read('investment-thesis/app.js');
const {check,charts,interpretation,review,alpha,cost}=require('../investment-thesis/app.js');
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
async function render({fail=false,plotly=true,mismatch=false}={}){
  const nodes=new Map([...html.matchAll(/id="([^"]+)"/g)].map(m=>[m[1],new Element()]));
  const plotted=[],requested=[];
  const document={getElementById:id=>{assert.ok(nodes.has(id));return nodes.get(id);},createElement:()=>new Element()};
  const window=plotly?{Plotly:{react:(target,traces,layout)=>plotted.push({target,traces,layout})}}:{};
  const historical=structuredClone(h);if(mismatch)historical.market_snapshot_sha256='different';
  const context=vm.createContext({document,window,fetch:async url=>{requested.push(url);return {ok:!fail,json:async()=>url.includes('thesis_tracker')?d:url.includes('historical_signals')?historical:s};}});
  vm.runInContext(script,context);await new Promise(resolve=>setImmediate(resolve));
  return {nodes,plotted,requested};
}
test('Real JSON loads into both charts, table and summary without writing orders',async()=>{
  const before=JSON.stringify(d);const r=await render();
  assert.equal(r.plotted.length,2);assert.equal(r.nodes.get('thesis-summary').children.length,4);
  assert.deepEqual(r.requested,['data/thesis_tracker.json','../docs/data/historical_signals.json','../docs/data/strategy_status.json']);
  assert.equal(r.nodes.get('thesis-reading').textContent,interpretation(d));
  assert.equal(r.nodes.get('thesis-review').textContent,review(d));
  assert.equal(r.nodes.get('thesis-cost').textContent,cost(d));
  assert.ok(!r.nodes.has('order-rows'));
  r.nodes.get('thesis-ticker').value='PFE';r.nodes.get('thesis-ticker').listeners.change();
  assert.deepEqual(Array.from(r.plotted.at(-2).traces[0].y),charts(d,'PFE')[0].traces[0].y);
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
  assert.match(workflow,/investment-thesis\/data\/thesis_tracker.json investment-thesis\/data\/thesis_observations.csv/);
});
