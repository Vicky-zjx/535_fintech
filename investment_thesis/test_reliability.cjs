const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const root=path.join(__dirname,'..');
const read=p=>fs.readFileSync(path.join(root,p),'utf8');
const d=JSON.parse(read('investment-thesis/data/thesis_tracker.json'));
const html=read('investment-thesis/index.html');
const script=read('investment-thesis/reliability.js');
const api=require('../investment-thesis/reliability.js');
test('Empirical rows agree with original tracker and reject mixed generations',()=>{
  api.check(d);
  for(const change of [x=>x.reliability.as_of='bad',x=>x.reliability.market_snapshot_sha256='bad',
    x=>x.reliability.samples.daily.tickers.BAC.groups.filtered.events++,
    x=>x.reliability.samples.daily.sensitivity[0].tickers.BAC.frequency_difference.ci95=[.1,-.1]]){
    const copy=structuredClone(d);change(copy);assert.throws(()=>api.check(copy));
  }
});
test('Incomplete numbers, impossible intervals and absent primary blocks are rejected',()=>{
  for(const change of [x=>delete x.reliability.samples.nonoverlap.tickers.BAC.groups.filtered.frequency,
    x=>x.reliability.samples.nonoverlap.tickers.BAC.groups.filtered.mean_adverse=null,
    x=>x.reliability.samples.daily.sensitivity[0].tickers.BAC.groups.filtered.ci95=[2,3],
    x=>x.reliability.design.primary_daily_block=8,
    x=>x.reliability.samples.daily.sensitivity.pop(),
    x=>x.reliability.samples.nonoverlap.tickers.BAC.downside_difference=null]){
    const v=structuredClone(d);change(v);assert.throws(()=>api.check(v));
  }
});
test('KL endpoints, complementary tails, monotonicity and invalid tolerance',()=>{
  assert.equal(api.kl(0,0),0);assert.equal(api.kl(1,1),0);
  assert.equal(api.kl(.1,0),Infinity);assert.ok(Math.abs(api.kl(0,.2)+Math.log(.8))<1e-12);
  assert.ok(Math.abs(api.logBound(100,.2,.05)-api.logBound(100,.8,.05,'upper'))<1e-12);
  assert.ok(api.logBound(200,.2,.05)<api.logBound(100,.2,.05));
  assert.ok(api.logBound(100,.2,.1)<api.logBound(100,.2,.05));
  assert.equal(api.logBound(100,.2,0),0);
  for(const args of [[0,.2,.1],[20,.2,.2],[20,.8,.3,'upper'],[20,NaN,.01],[20,.2,-.01]])assert.throws(()=>api.logBound(...args));
});
test('Both theoretical curves use the chosen actual n but never label it independent evidence',()=>{
  for(const t of ['BAC','KO','PFE','F'])for(const g of ['filtered','unfiltered'])for(const mode of ['daily','nonoverlap'])for(const tail of ['lower','upper']){
    const m=api.model(d.reliability,t,g,mode,.2,.05,tail),n=d.reliability.samples[mode].tickers[t].groups[g].n;
    assert.equal(m.plots[0].traces[1].x[0],n);
    assert.equal(m.plots[1].traces[1].x[0],.05);
    for(const c of m.plots){assert.equal(c.layout.yaxis.type,'log');assert.ok(c.traces[0].y.every(y=>y>0&&y<=1));}
    assert.match(m.nText.join(' '),/not a known truth|independent trials/);
    assert.match(m.tText.join(' '),/dependent observations|not evidence/);
    assert.doesNotMatch(m.nText.concat(m.tText).join(' '),/undefined|NaN/);
    assert.equal(m.plots[0].traces[1].y[0],Math.exp(api.logBound(n,.2,.05,tail)));
  }
});
test('Theory controls never mutate empirical statistics and underflow never masquerades as zero',()=>{
  const before=JSON.stringify(d),a=api.model(d.reliability,'BAC','filtered','daily',.2,.05),b=api.model(d.reliability,'BAC','filtered','daily',.8,.79);
  assert.notDeepEqual(a.plots[0].traces[0].y,b.plots[0].traces[0].y);
  assert.ok(b.plots[1].traces[0].y.every(y=>y>0));
  assert.equal(JSON.stringify(d),before);
  assert.match(html,/not claimed to reproduce/);assert.match(html,/independence sensitivity/);
});
test('Very small tolerances never produce probabilities above one',()=>{
  for(const mu of [.001,.1,.2,.5,.9,.999])for(const t of [1e-16,1e-12,1e-8]){
    assert.ok(api.kl(mu+t,mu)>=0);assert.ok(api.logBound(100,mu,t,'upper')<=0);
  }
});
test('Daily and non-overlap findings report uncertainty, alternate design, chance and limitations',()=>{
  for(const mode of ['daily','nonoverlap']){
    const text=api.findings(d.reliability,mode).join(' ');
    assert.match(text,/chance as a plausible explanation/);assert.match(text,/not a replacement result chosen/);
    assert.match(text,/H2 still requires/);assert.doesNotMatch(text,/undefined|NaN/);
    for(const t of ['BAC','KO','PFE','F'])assert.ok(text.includes(t+':'));
  }
});
class Element{
  constructor(value=''){this.value=value;this.children=[];this.listeners={};this.hidden=false;this.content='';}
  set textContent(v){this.content=String(v);this.children=[];}
  get textContent(){return this.content+this.children.map(x=>x.textContent).join(' ');}
  append(...c){this.children.push(...c);}replaceChildren(...c){this.children=c;this.content='';}
  addEventListener(event,fn){this.listeners[event]=fn;}
}
function render({plotly=true,data=d}={}){
  const nodes=new Map([...html.matchAll(/id="([^"]+)"/g)].map(m=>[m[1],new Element()]));
  for(const [id,value] of Object.entries({ticker:'BAC',group:'filtered',sampling:'daily',tail:'lower',mu:'0.20',tolerance:'0.05'}))nodes.get('reliability-'+id).value=value;
  const plots=[],window=plotly?{Plotly:{react:(node,traces,layout)=>plots.push({node,traces,layout}),purge:()=>{}}}:{};
  const document={getElementById:id=>nodes.get(id),createElement:()=>new Element()};
  vm.runInNewContext(script,{window,document});window.WheelReliability.show(data);
  return {nodes,plots};
}
test('Page renders eight empirical rows, twelve sensitivity rows, four stocks and both scenarios',()=>{
  const r=render();assert.equal(r.plots.length,2);
  assert.equal(r.nodes.get('reliability-samples').children.length,8);
  assert.equal(r.nodes.get('reliability-sensitivity').children.length,12);
  const before=r.nodes.get('reliability-samples').textContent;
  r.nodes.get('reliability-mu').value='.3';r.nodes.get('reliability-mu').listeners.input();
  assert.equal(r.nodes.get('reliability-samples').textContent,before);
  r.nodes.get('reliability-sampling').value='nonoverlap';r.nodes.get('reliability-sampling').listeners.change();
  assert.notEqual(r.nodes.get('reliability-samples').textContent,before);
  assert.match(r.nodes.get('reliability-n-analysis').textContent,/fixed non-overlapping/);
});
test('Invalid or blank hypotheses clear old graphs, retain actual evidence and recover',()=>{
  const r=render(),mu=r.nodes.get('reliability-mu'),t=r.nodes.get('reliability-tolerance');
  for(const bad of ['','.2','-.1','oops']){
    t.value=bad;t.listeners.input();assert.equal(r.nodes.get('reliability-error').hidden,false);
    assert.match(r.nodes.get('reliability-n-chart').textContent,/valid theory scenario/);
    assert.equal(r.nodes.get('reliability-samples').children.length,8);
  }
  t.value='.05';t.listeners.input();assert.equal(r.nodes.get('reliability-error').hidden,true);
  assert.doesNotMatch(r.nodes.get('reliability-n-chart').textContent,/Choose a valid theory scenario/);
  mu.value='';mu.listeners.input();assert.equal(r.nodes.get('reliability-error').hidden,false);
});
test('Missing chart library leaves empirical results; mixed data is not displayed',()=>{
  const r=render({plotly:false});assert.equal(r.nodes.get('reliability-samples').children.length,8);
  assert.match(r.nodes.get('reliability-n-chart').textContent,/Chart library unavailable/);
  const bad=structuredClone(d);bad.reliability.market_snapshot_sha256='wrong';
  const fail=render({data:bad});assert.equal(fail.plots.length,0);
  assert.match(fail.nodes.get('reliability-status').textContent,/unavailable or inconsistent/);
});

test('Five-year selector uses its actual n and intervals without mutating original evidence',()=>{
  const e=d.lecture_extension?.historical?.expanded;if(!e)return;
  const r=render(),before=JSON.stringify(d);
  r.nodes.get('reliability-window').value='expanded';r.nodes.get('reliability-window').listeners.change();
  assert.match(r.nodes.get('reliability-status').textContent,/Fixed five-year/);
  assert.match(r.nodes.get('reliability-status').textContent,/2021-11-24/);
  assert.ok(r.nodes.get('reliability-n-analysis').textContent.includes(String(e.full_sample.tickers.BAC.pass.n)));
  r.nodes.get('reliability-window').value='original';r.nodes.get('reliability-window').listeners.change();
  assert.match(r.nodes.get('reliability-status').textContent,/Original three-year/);
  assert.equal(JSON.stringify(d),before);
});
