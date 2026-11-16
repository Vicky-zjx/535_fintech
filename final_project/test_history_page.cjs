const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const base=path.join(__dirname,'..');
const h=JSON.parse(fs.readFileSync(path.join(base,'docs/data/historical_signals.json')));
const archive=JSON.parse(fs.readFileSync(path.join(base,'docs/data/entry_demo_status.json')));
const {check,findings}=require('../docs/assets/history.js');
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
  const charts=[];
  const document={getElementById:id=>{assert.ok(nodes.has(id),id);return nodes.get(id);},createElement:()=>new Element()};
  const window=plotly?{Plotly:{react:(node,traces,layout)=>charts.push({node,traces,layout})}}:{};
  const context=vm.createContext({document,window,fetch:async url=>({ok:!fail,status:503,json:async()=>url.includes('entry_demo')?archive:h})});
  vm.runInContext(script,context);await new Promise(resolve=>setImmediate(resolve));
  return {nodes,charts};
}
test('Historical tables, plotted arrays and archived demo use actual saved evidence',async()=>{
  const {nodes,charts}=await render();assert.equal(nodes.get('history-weekly').children.length,4);
  assert.equal(charts.length,3);assert.equal(charts[2].traces.length,5);
  assert.deepEqual(Array.from(charts[2].traces[0].y),h.tickers.BAC.daily_rows.map(r=>r.close));
  assert.ok(charts[2].traces.every(t=>t.connectgaps===false));
  assert.match(nodes.get('weekly-entry-demo').textContent,/2026-11-13/);
  assert.match(nodes.get('weekly-entry-demo').textContent,/2 proposals/);
  assert.equal(nodes.get('order-rows').children.length,0);
  nodes.get('history-ticker').value='KO';nodes.get('history-ticker').listeners.change();
  assert.deepEqual(Array.from(charts.at(-1).traces[0].y),h.tickers.KO.daily_rows.map(r=>r.close));
});
test('Unavailable analysis or chart library does not imply a successful zero result',async()=>{
  const {nodes}=await render(true);assert.match(nodes.get('history-status').textContent,/unavailable or inconsistent/);
  assert.match(nodes.get('weekly-entry-demo').textContent,/not verified/);
  const good=await render(false,false);assert.match(good.nodes.get('history-filter-chart').textContent,/library unavailable/);
  assert.equal(good.nodes.get('history-weekly').children.length,4);
});
