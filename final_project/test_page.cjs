// Offline DOM harness; fixtures are not real prices and are never published.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'../docs/index.html'),'utf8');
const script=fs.readFileSync(path.join(__dirname,'../docs/assets/app.js'),'utf8');
class Element {
  constructor(tag='div'){this.tag=tag;this.children=[];this.attributes={};this.value='';this.hidden=false;this.classList={add(){}};}
  set textContent(v){this.value=String(v);this.children=[];}
  get textContent(){return this.value+this.children.map(c=>c.textContent).join(' ');}
  append(...children){this.children.push(...children);}
  replaceChildren(...children){this.value='';this.children=children;}
  get firstChild(){return this.children[0];}
  setAttribute(k,v){this.attributes[k]=v;}
}
async function render(status,orders=[],fail=false,demo=null){
  const elements=new Map([...html.matchAll(/id="([^"]+)"/g)].map(m=>[m[1],new Element()]));
  const document={getElementById:id=>{assert.ok(elements.has(id),'Real HTML ID '+id);return elements.get(id);},createElement:t=>new Element(t),createElementNS:(_,t)=>new Element(t),querySelector:()=>new Element()};
  vm.runInNewContext(script,{document,Intl,Date,fetch:async url=>({ok:!fail,json:async()=>url.includes('demo_status')?demo:url.includes('strategy_status')?status:orders})});
  await new Promise(resolve=>setImmediate(resolve));
  return elements;
}
const baseline={status:'not_run',decisions:[],errors:['Live data not yet available'],orders_updated:false};
test('Initial state is not a successful no-trade run',async()=>{
  const e=await render(baseline);assert.match(e.get('order-note').textContent,/not yet a successful/);assert.equal(e.get('decision-rows').children.length,4);
});
test('Validated empty array is explicitly a legitimate no-trade result',async()=>{
  const e=await render({...baseline,status:'success',errors:[]});assert.match(e.get('order-note').textContent,/Valid no-trade/);
});
test('Blocked attempt labels retained prior orders',async()=>{
  const o={id:'TEST-only',for:'2026-11-16',underlying:90000001,action:'SHT',contract:'put',expiry:'2026-11-20',strike:48.5,qty:1};
  const e=await render({...baseline,status:'blocked'},[o]);assert.match(e.get('order-note').textContent,/not changed/);assert.match(e.get('order-rows').textContent,/TEST-only/);
});
test('Network error is not an empty success state',async()=>{
  const e=await render(baseline,[],true);assert.match(e.get('issues').textContent,/Do not interpret this as a no-trade/);
});
test('Returned provider text is rendered as text, never HTML',async()=>{
  const e=await render({...baseline,errors:['<script>not executable</script>']});assert.equal(e.get('issues').textContent,'<script>not executable</script>');assert.equal(e.get('issues').children.length,0);
});
test('Real-shaped validated observations populate labels and charts',async()=>{
  const d={ticker:'BAC',close:50,sma20:49,sma50:48,hv20:.3,r5:.01,price_date:'2026-11-13',filters:{trend:true},decision:'No Trade',eligible:false,reasons:['TEST ONLY']};
  const e=await render({...baseline,status:'blocked',calendar:{as_of:'2026-11-13',target_session:'2026-11-16'},market_data_retrieved_at:'2026-11-16T03:00:00Z',decisions:[d]});
  assert.match(e.get('decision-rows').textContent,/\$50\.00/);assert.match(e.get('decision-rows').textContent,/30\.00%/);assert.equal(e.get('signal-chart').children[0].tag,'svg');
});
test('Negative signal deviations draw left of zero, not positive bars',async()=>{
  const d={ticker:'BAC',close:45,sma20:46,sma50:48,hv20:.3,r5:-.1,filters:{trend:false},decision:'No Trade',reasons:[]};
  const e=await render({...baseline,decisions:[d]});
  const svg=e.get('signal-chart').children[0];
  const zero=svg.children.find(n=>n.tag==='line').attributes.x1;
  for(const bar of svg.children.filter(n=>n.tag==='rect'))assert.ok(Number(bar.attributes.x)<Number(zero));
});
test('Demonstration is explicitly labeled and cannot populate production orders',async()=>{
  const demo=JSON.parse(fs.readFileSync(path.join(__dirname,'../docs/data/demo_status.json'),'utf8'));
  const e=await render({...baseline,status:'blocked'},[],false,demo);
  assert.match(e.get('demo-summary').textContent,/DEMONSTRATION ONLY/);
  assert.match(e.get('demo-results').textContent,/Hypothetical/);
  assert.doesNotMatch(e.get('order-rows').textContent,/fin535-demo-/);
  assert.match(e.get('order-note').textContent,/not changed/);
});
test('Malformed demonstration cannot change production rendering',async()=>{
  const e=await render({...baseline,status:'success',errors:[]},[],false,{mode:'live'});
  assert.match(e.get('demo-summary').textContent,/unavailable/);
  assert.match(e.get('order-note').textContent,/Valid no-trade/);
});
