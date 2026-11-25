const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const root=path.join(__dirname,'..');
const d=JSON.parse(fs.readFileSync(path.join(root,'investment-thesis/data/public_tracker.json')));
const html=fs.readFileSync(path.join(root,'investment-thesis/index.html'),'utf8');
const script=fs.readFileSync(path.join(root,'investment-thesis/rough-alpha.js'),'utf8');
const {model,coefficients,scenario,premiums}=require('../investment-thesis/rough-alpha.js');
const near=(a,b)=>assert.ok(Math.abs(a-b)<1e-11,`${a} != ${b}`);
const ratios=['1.0','0.98','0.95','0.9'];
const tickers=['BAC','KO','PFE','F'];

test('All registered premiums and strike scenarios include skipped weeks and unchanged costs',()=>{
  const before=JSON.stringify(d);
  assert.deepEqual(premiums,[10,25,50,75,100,150]);
  for(const ratio of ratios)for(const p of premiums){
    const m=model(d,ratio,p);assert.equal(m.traces.length,5);assert.equal(m.rows.length,5);
    for(let i=0;i<4;i++){
      const z=d.lecture_extension.hypothetical_put_payoff.tickers[tickers[i]][ratio];
      const r=m.rows[i],q=z.filtered.n/z.unfiltered.n;
      near(r.unfiltered,p/10000-z.unfiltered.mean_loss-z.unfiltered.mean_cost);
      near(r.filtered,q*(p/10000-z.filtered.mean_loss-z.filtered.mean_cost));
      near(r.advantage,r.filtered-r.unfiltered);
      near(r.advantage,r.lossAvoided+r.costSaved-r.premiumForgone);
      const excludedN=z.unfiltered.n-z.filtered.n;
      near(r.excludedBreakEvenAfter,
        (z.unfiltered.n*z.unfiltered.break_even_after_cost-z.filtered.n*z.filtered.break_even_after_cost)/excludedN);
      near(r.excludedBreakEvenBefore,
        (z.unfiltered.n*z.unfiltered.mean_loss-z.filtered.n*z.filtered.mean_loss)/excludedN);
    }
    const avg=key=>m.rows.slice(0,4).reduce((s,r)=>s+r[key],0)/4;
    for(const k of ['unfiltered','filtered','advantage','q','premiumForgone','lossAvoided','costSaved'])near(m.rows[4][k],avg(k));
    near(m.rows[4].excludedBreakEvenAfter,(avg('lossAvoided')+avg('costSaved'))/(1-avg('q')));
    assert.doesNotMatch(m.analysis.join(' '),/NaN|Infinity|undefined/);
  }
  assert.equal(JSON.stringify(d),before);
});

test('Slope and zero crossing reflect lost premiums, not a selected-trades-only comparison',()=>{
  for(const ratio of ratios){
    const m=model(d,ratio);
    for(const s of m.series){
      for(let i=1;i<s.points.length;i++){
        const a=s.points[i-1],b=s.points[i];
        near((b.advantage-a.advantage)/((b.premiumBp-a.premiumBp)/10000),-(1-a.q));
        assert.ok(b.advantage<a.advantage);
      }
      const c=s.points[0];near(scenario(c,c.excludedBreakEvenAfter*10000).advantage,0);
    }
  }
});

test('95 percent real-summary results retain negative findings',()=>{
  const m=model(d,'0.95',50);
  const expected=[-1.735336984465082,-21.56007407373303,-17.959611195710814,33.97143127346025];
  m.rows.slice(0,4).forEach((r,i)=>near(r.advantage*10000,expected[i]));
  assert.ok(m.rows[4].advantage<0);
  assert.match(m.analysis[0],/negative advantage/);
  assert.match(m.analysis[4],/Both scenarios still lose money.*smaller loss, not a profit/);
  for(const r of model(d,'0.95',150).rows)assert.ok(r.advantage<0);
  assert.ok(model(d,'0.95',25).rows[4].advantage>0);
});

test('Missing coverage and inconsistent or nonfinite summaries never become zero returns',()=>{
  for(const mutate of [
    z=>z.unfiltered.n--,z=>z.filtered.n++,z=>z.eligible_frequency=0,
    z=>z.unfiltered.mean_loss=null,z=>z.filtered.mean_cost=NaN,
    z=>z.unfiltered.break_even_after_cost+=.1,z=>z.weekly_break_even_reduction=null
  ]){
    const x=structuredClone(d);mutate(x.lecture_extension.hypothetical_put_payoff.tickers.BAC['0.95']);
    assert.throws(()=>model(x));
  }
  assert.throws(()=>model(d,'0.25'));assert.throws(()=>model(d,'0.95',40));
});

test('All-selected and none-selected boundaries are distinct from missing data',()=>{
  for(const q of [0,1]){
    const x=structuredClone(d),z=x.lecture_extension.hypothetical_put_payoff.tickers.BAC['0.95'];
    z.filtered=q?structuredClone(z.unfiltered):{n:0,mean_loss:null,mean_cost:null,break_even_after_cost:null};
    z.eligible_frequency=q;z.weekly_break_even_reduction=q?0:z.unfiltered.break_even_after_cost;
    const r=model(x).rows[0];
    if(q){near(r.advantage,0);assert.equal(r.excludedBreakEvenAfter,null);}
    else {near(r.filtered,0);near(r.advantage,-r.unfiltered);near(r.excludedBreakEvenAfter,z.unfiltered.break_even_after_cost);}
    z.weekly_break_even_reduction=null;
    assert.throws(()=>model(x));
  }
});

class Element{
  constructor(){this.children=[];this.value='';this.listeners={};this.content='';}
  set textContent(v){this.content=String(v);this.children=[];}
  get textContent(){return this.content+this.children.map(x=>x.textContent).join(' ');}
  append(...c){this.children.push(...c);}
  replaceChildren(...c){this.content='';this.children=c;}
  addEventListener(k,fn){this.listeners[k]=fn;}
}
function render(data=d,plotly=true){
  const nodes=new Map([...html.matchAll(/id="([^"]+)"/g)].map(m=>[m[1],new Element()]));
  nodes.get('rough-alpha-ratio').value='0.95';nodes.get('rough-alpha-premium').value='50';
  const plotted=[],window=plotly?{Plotly:{react:(target,traces,layout)=>plotted.push({target,traces,layout}),purge:()=>{}}}:{};
  const context=vm.createContext({window,document:{getElementById:id=>nodes.get(id),createElement:()=>new Element()}});
  vm.runInContext(script,context);window.WheelRoughAlpha.show(data);
  return {nodes,plotted};
}
test('DOM controls update the five lines, table and dated-study analysis without new data requests',()=>{
  const r=render();assert.equal(r.plotted.length,1);assert.equal(r.nodes.get('rough-alpha-results').children.length,5);
  for(const ratio of ratios)for(const p of premiums){
    r.nodes.get('rough-alpha-ratio').value=ratio;r.nodes.get('rough-alpha-premium').value=String(p);
    r.nodes.get('rough-alpha-ratio').listeners.change();
    assert.equal(r.plotted.at(-1).traces.length,5);
    assert.match(r.nodes.get('rough-alpha-status').textContent,new RegExp(`Table premium: ${p} bp`));
    assert.ok(r.nodes.get('rough-alpha-analysis').textContent.includes(model(d,ratio,p).analysis[0]));
  }
  assert.doesNotMatch(script,/\bfetch\s*\(|localStorage|open_orders|workflow_dispatch/);
  assert.match(fs.readFileSync(path.join(root,'investment-thesis/app.js'),'utf8'),/WheelRoughAlpha\.show\(d\)/);
});
test('Failure is isolated to sensitivity; lack of Plotly preserves the results table',()=>{
  const r=render(d,false);assert.match(r.nodes.get('rough-alpha-chart').textContent,/library unavailable/);
  assert.equal(r.nodes.get('rough-alpha-results').children.length,5);
  const x=structuredClone(d);const v=render(x);
  x.lecture_extension.hypothetical_put_payoff.tickers.BAC['0.95'].unfiltered.mean_loss=null;
  v.nodes.get('rough-alpha-premium').listeners.change();
  assert.equal(v.nodes.get('rough-alpha-results').children.length,0);
  assert.match(v.nodes.get('rough-alpha-status').textContent,/No missing week is replaced with zero/);
  assert.match(v.nodes.get('rough-alpha-chart').textContent,/Other research results are unchanged/);
});
test('English disclaimers, source study, legacy costs and anchors are retained',()=>{
  assert.match(html,/preliminary economic edge estimate/);
  assert.match(html,/not real market Alpha/);
  assert.match(html,/not.*capital-constrained portfolio backtest/);
  assert.match(html,/excluded-opportunity break-even/i);
  assert.match(html,/Existing cost sensitivity/);
  assert.doesNotMatch(script,/[\u4e00-\u9fff]/);
  const ids=[...html.matchAll(/id="([^"]+)"/g)].map(m=>m[1]);
  assert.equal(new Set(ids).size,ids.length);
  for(const a of html.matchAll(/href="#([^"]+)"/g))assert.ok(ids.includes(a[1]));
});
