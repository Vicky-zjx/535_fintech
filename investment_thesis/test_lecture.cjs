const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const base=path.join(__dirname,'..');
const d=JSON.parse(fs.readFileSync(path.join(base,'investment-thesis/data/thesis_tracker.json'),'utf8'));
const html=fs.readFileSync(path.join(base,'investment-thesis/index.html'),'utf8');
const script=fs.readFileSync(path.join(base,'investment-thesis/lecture.js'),'utf8');
const api=require('../investment-thesis/lecture.js');
const x=api.check(d);
test('Extension source, counts and forward eligibility are validated',()=>{
  for(const change of [v=>v.lecture_extension.source_sha256='bad',v=>v.lecture_extension.as_of='bad',
    v=>v.lecture_extension.historical.original_ablation.samples.daily.tickers.BAC.combined.events++,
    v=>v.lecture_extension.monitoring.samples.daily.BAC.filtered.current.events=-1,
    v=>v.lecture_extension.monitoring.samples.daily.BAC.filtered.curve.push({signal_date:'2026-11-23',outcome_date:'2026-11-23'})]){
    const copy=structuredClone(d);change(copy);assert.throws(()=>api.check(copy));
  }
});
test('All five arms and block lengths display actual values without changing originals',()=>{
  const before=JSON.stringify(x);
  for(const mode of ['daily','nonoverlap'])for(const length of mode==='daily'?[7,14,28]:[1,2,4]){
    const rows=api.ablationRows(x,'original',mode,length),text=api.ablationText(x,'original',mode,length).join(' ');
    assert.equal(rows.length,20);assert.equal(rows[0][1],mode==='daily'?'746 / 145':'107 / 16');
    assert.match(text,/chance remains a plausible explanation/);assert.match(text,/not tested causes/);
    assert.match(text,/H2 remains untested|matched option economics/);assert.doesNotMatch(text,/undefined|NaN/);
    for(const t of ['BAC','KO','PFE','F'])assert.match(text,new RegExp(t+':'));
    assert.equal(api.comparisonRows(x,mode).length,4);
  }
  assert.equal(before,JSON.stringify(x));assert.throws(()=>api.ablationRows(x,'original','daily',2));
});
test('Pending history is not rendered as an extended result',()=>{
  const z=structuredClone(x);z.historical.expanded=null;
  assert.throws(()=>api.ablationRows(z,'expanded'));
  assert.ok(api.comparisonRows(z).every(r=>r[3]==='Pending'));
  assert.match(api.ablationText(z).join(' '),/cannot yet say whether five years stabilizes/);
});
test('Classroom example is calculated, not live strategy performance',()=>{
  const c=x.monitoring.classroom_example;
  assert.ok(Math.abs(c.bound-.8153726976)<1e-12);assert.equal(c.tail,'lower');assert.equal(c.own_trade_results,false);
  assert.match(html,/not verified the complete original lecture notes/);
  assert.match(html,/not confidence sequences/);assert.match(html,/No advisory pauses trading/);
});
test('Empty prospective data produce no fake chart, zero loss or filled trades',()=>{
  const z=structuredClone(x);
  for(const mode of ['daily','nonoverlap'])for(const t of ['BAC','KO','PFE','F'])for(const group of ['filtered','unfiltered']){
    const g=z.monitoring.samples[mode][t][group];g.current.n=0;g.current.events=0;
    g.current.observed_decline_frequency=null;g.current.upper_tail_bound=null;g.current.log_upper_tail_bound=null;g.curve=[];
    const m=api.monitorModel(z,t,group,mode);
    assert.equal(m.ready,false);assert.match(m.placeholder,/0 matured/);
    assert.match(m.riskText.join(' '),/zero observations is not a measured zero risk/);
    assert.doesNotMatch(m.riskText.concat(m.boundText).join(' '),/undefined|NaN/);
    assert.ok(m.plots.every(p=>p.traces.every(s=>s.y.length===0)));
  }
});
test('Future rendering branch preserves missing points and log underflow',()=>{
  const z=structuredClone(x),g=z.monitoring.samples.daily.BAC.filtered;
  // Isolated future-rendering fixture, not real observations. The source may
  // correctly withhold monitoring when private storage is unavailable.
  z.monitoring.coverage_lost=false;
  Object.assign(g.current,{n:22,events:20,observed_decline_frequency:20/22,upper_tail_bound:.01,log_upper_tail_bound:Math.log(.01)});
  g.curve=[{n:20,outcome_date:'2026-12-30',observed_decline_frequency:.9,log_upper_tail_bound:-800},
    {n:20,outcome_date:'2026-12-31',gap:true,observed_decline_frequency:null,log_upper_tail_bound:null},
    {n:22,outcome_date:'2027-01-04',observed_decline_frequency:20/22,log_upper_tail_bound:Math.log(.01)}];
  const m=api.monitorModel(z);assert.equal(m.ready,true);
  assert.equal(m.plots[0].traces[0].y[1],null);assert.equal(m.plots[1].traces[0].y[1],null);
  assert.ok(m.plots[1].traces[0].y[0]>0);assert.equal(m.plots[1].layout.yaxis.type,'log');
  assert.ok(m.plots.every(p=>p.traces.every(s=>s.connectgaps===false)));
  assert.equal(m.plots[0].traces.length,2); // no invented acceptable-risk line
  z.monitoring.coverage_lost=true;assert.equal(api.monitorModel(z).ready,false);
  assert.match(api.monitorModel(z).placeholder,/incomplete or unavailable/);
});
class Element{
  constructor(value=''){this.value=value;this.children=[];this.listeners={};this.content='';this.disabled=false;}
  set textContent(x){this.content=String(x);this.children=[];}get textContent(){return this.content+this.children.map(x=>x.textContent).join(' ');}
  append(...c){this.children.push(...c);}replaceChildren(...c){this.children=c;this.content='';}
  get options(){return this.children;}addEventListener(name,fn){this.listeners[name]=fn;}
}
test('DOM controls render both sections, switch designs, keep links and no new fetch',()=>{
  const elements={};for(const m of html.matchAll(/id="([^"]+)"/g))elements[m[1]]=new Element();
  for(const [k,v] of Object.entries({'ablation-window':'original','ablation-sampling':'daily','ablation-block':'14','monitor-ticker':'BAC','monitor-group':'filtered','monitor-sampling':'daily'}))elements[k].value=v;
  elements['ablation-window'].append(new Element('original'),new Element('expanded'));
  const drawn=[];const context={console,document:{getElementById:id=>elements[id],createElement:()=>new Element()},Plotly:{react:async(...a)=>drawn.push(a),purge:()=>{}}};
  vm.runInNewContext(script,context);context.WheelLecture.show(d);
  assert.equal(elements['ablation-results'].children.length,20);assert.equal(elements['monitor-results'].children.length,8);
  assert.match(elements['lecture-example'].textContent,/81.54%/);assert.match(elements['monitor-inventory'].textContent,/Awaiting/);
  elements['ablation-sampling'].value='nonoverlap';elements['ablation-sampling'].listeners.change();
  assert.equal(elements['ablation-block'].value,'2');assert.equal(elements['ablation-block'].children.length,3);
  assert.match(elements['ablation-analysis'].textContent,/fixed non-overlapping/);
  elements['monitor-ticker'].value='PFE';elements['monitor-ticker'].listeners.change();
  assert.match(elements['monitor-risk-analysis'].textContent,/PFE/);
  if(d.window.analysis_end==='2026-11-23')assert.equal(drawn.length,0);
  assert.doesNotMatch(script,/fetch\(|open_orders|POST/);
  for(const id of ['ablation','monitoring']){assert.match(html,new RegExp('href="#'+id+'"'));assert.ok(elements[id]);}
});
