// Offline DOM harness; fixtures are not real prices and are never published.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'../docs/index.html'),'utf8');
const script=fs.readFileSync(path.join(__dirname,'../docs/assets/app.js'),'utf8');
const analysisScript=fs.readFileSync(path.join(__dirname,'../docs/assets/analysis.js'),'utf8');
const analysis=require('../docs/assets/analysis.js');
const currentStatus=JSON.parse(fs.readFileSync(path.join(__dirname,'../docs/data/strategy_status.json'),'utf8'));
const currentDemo=JSON.parse(fs.readFileSync(path.join(__dirname,'../docs/data/demo_status.json'),'utf8'));
// Stable dated real evidence for complete-input UI cases, even when today's feed is incomplete.
// This in-memory test fixture is never written or presented as current production state.
const realDemo=JSON.parse(fs.readFileSync(path.join(__dirname,'../docs/data/entry_demo_status.json'),'utf8'));
const realStatus={...currentStatus,calendar:realDemo.calendar,decisions:realDemo.scenarios[0].decisions,
  market_data_retrieved_at:realDemo.market_retrieved_at,market_snapshot_sha256:realDemo.market_snapshot_sha256,capital:null};
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
  const context=vm.createContext({document,Intl,Date,window:{},fetch:async url=>({ok:typeof fail==='function'?!fail(url):!fail,json:async()=>url.includes('demo_status')?demo:url.includes('strategy_status')?status:orders})});
  vm.runInContext(analysisScript,context);vm.runInContext(script,context);
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
test('Partial-data success names unavailable stocks rather than claiming no opportunities',async()=>{
  const e=await render({...baseline,status:'success',errors:[],warnings:['BAC latest close unavailable'],outcome:'partial_data_no_proposals',decisions:[{ticker:'BAC',category:'Data unavailable',technical_status:'Data unavailable',reasons:['Latest completed close missing']}]});
  assert.match(e.get('issues').textContent,/BAC latest close unavailable/);
  assert.match(e.get('decision-rows').textContent,/Data unavailable/);
  assert.match(e.get('order-note').textContent,/not evidence.*whole universe/);
});
test('Observation-window gaps and actual adjacent-return span are disclosed',async()=>{
  const d={ticker:'KO',category:'Already proposed',technical_status:'Technical filter passed',reasons:['Weekly cap'],observation_window:{valid_closes:54,expected_sessions:55,missing_dates:['2026-10-20'],hv20_return_pairs:[['2026-10-15','2026-10-16'],['2026-11-12','2026-11-13']]}};
  const e=await render({...baseline,status:'success',decisions:[d]});
  assert.match(e.get('decision-rows').textContent,/54 valid closes \/ 55 sessions/);
  assert.match(e.get('decision-rows').textContent,/missing: 2026-10-20/);
  assert.match(e.get('decision-rows').textContent,/adjacent-session returns from 2026-10-15 to 2026-11-13/);
  assert.match(e.get('decision-rows').textContent,/Already proposed/);
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

test('Published live evidence produces dated commentary, not realized performance',async()=>{
  const e=await render(realStatus,[],false,realDemo);
  const evidence=analysis.signalEvidence(realStatus);
  assert.match(e.get('analysis-source').textContent,new RegExp(evidence.asOf));
  assert.equal(e.get('signal-discussion').children.length,6);
  assert.match(e.get('signal-discussion').textContent,/not approved orders/);
  assert.match(e.get('signal-discussion').textContent,/cannot show.*redundant/);
  assert.match(e.get('availability-rows').textContent,/Pending verified Sanji execution and NAV histories/);
  if(!realStatus.capital)assert.match(e.get('capital-chart').textContent,/No cash balance or zero exposure is assumed/);
  else assert.equal(e.get('capital-chart').children[0].tag,'svg');
  assert.equal(e.get('demo-capital-chart').children.length,2);
  assert.equal(e.get('demo-capital-chart').children[0].children[1].attributes.role,'img');
  assert.match(e.get('demo-capital-note').textContent,/neither actual Sanji capital nor a period-average/);
  assert.doesNotMatch(e.get('signal-discussion').textContent,/NaN|undefined|N\/A/);
});
test('Missing order download does not erase a successful market response',async()=>{
  const e=await render(realStatus,[],url=>url.includes('open_orders'));
  assert.match(e.get('run-state').textContent,/Market data retrieved|Validated evaluation/);
  assert.match(e.get('order-note').textContent,/queue contents are unknown/);
  assert.match(e.get('analysis-source').textContent,/Latest verified/);
});
test('Missing diagnostics do not masquerade as a zero portfolio or successful empty queue',async()=>{
  const e=await render(realStatus,[],url=>url.includes('strategy_status'),realDemo);
  assert.match(e.get('issues').textContent,/Do not interpret/);
  assert.equal(e.get('capital-chart').children.length,0);
  assert.equal(e.get('signal-discussion').children.length,0);
  assert.match(e.get('demo-summary').textContent,/DEMONSTRATION ONLY/);
});
test('New dated evidence changes interpretation; November findings are not hardcoded',()=>{
  const s=structuredClone(realStatus);
  s.calendar.as_of='2030-01-07';s.market_data_retrieved_at='2030-01-08T03:00:00Z';
  s.calendar.target_session='2030-01-08';
  // Explicit offline fixture, never published or supplied to the trading engine.
  for(const d of s.decisions){d.price_date=s.calendar.as_of;d.close=60;d.sma20=55;d.sma50=50;d.hv20=.46;d.r5=-.09;d.filters={trend:true,volatility:false,sudden_drop:false};}
  const result=analysis.signalParagraphs(analysis.signalEvidence(s)).join(' ');
  assert.match(result,/2030-01-07/);assert.match(result,/46\.00% \(failed/);
  assert.doesNotMatch(result,/All four stocks passed|Trend was the separating|2026-11-13/);
});
test('Missing, stale and inconsistent indicators withhold financial interpretation',()=>{
  for(const mutate of [s=>s.decisions[0].close=null,s=>s.decisions[0].price_date='2000-01-01',s=>s.decisions[0].filters.trend=!s.decisions[0].filters.trend,s=>s.mode='test',s=>s.market_snapshot_sha256=null]){
    const s=structuredClone(realStatus);mutate(s);assert.throws(()=>analysis.signalEvidence(s));
  }
});
test('Technical eligibility is not production order eligibility',()=>{
  const blocked=structuredClone(realStatus);blocked.status='blocked';
  blocked.decisions.forEach(d=>{d.eligible=false;d.decision='No Trade';});
  const e=analysis.signalEvidence(blocked);
  for(const d of e.rows)assert.equal(d.technical,Object.values(d.filters).every(Boolean));
  assert.ok(e.rows.every(d=>d.eligible===false));
});
test('Hypothetical capital reconciles and never computes a return',()=>{
  const c=analysis.hypotheticalCapital(realDemo);
  const account=realDemo.scenarios.find(s=>s.id==='covered_inventory').account;
  assert.ok(Math.abs(c.exposure+c.cash-account.equity)<1e-8);
  assert.equal(c.utilization,c.exposure/c.equity);
  assert.equal(c.cashFraction,c.cash/c.equity);
  for(const k of ['pnl','return','sharpe','nav_history','drawdown'])assert.equal(c[k],undefined);
  for(const mutate of [d=>d.mode='live',d=>d.production_orders_changed=true,d=>d.scenarios[1].capital.cash+=1,d=>d.scenarios[1].capital.exposure=null,d=>d.scenarios[1].account.positions[0].quantity=0]){
    const d=structuredClone(realDemo);mutate(d);assert.throws(()=>analysis.hypotheticalCapital(d));
  }
});
test('Interpretation leaves all source and example records unchanged',()=>{
  const before=JSON.stringify([realStatus,realDemo]);
  analysis.signalParagraphs(analysis.signalEvidence(realStatus));analysis.hypotheticalCapital(realDemo);
  assert.equal(JSON.stringify([realStatus,realDemo]),before);
});
test('Current incomplete market/demo evidence is explicitly withheld, not silently replaced',async()=>{
  const e=await render(currentStatus,[],false,currentDemo);
  assert.match(e.get('demo-summary').textContent,/DEMONSTRATION ONLY/);
  try {analysis.signalEvidence(currentStatus);} catch (_) {
    assert.match(e.get('signal-discussion').textContent,/withheld/);
    assert.match(e.get('analysis-source').textContent,/No complete/);
  }
  if(currentDemo.scenarios.some(s=>s.account===null)) {
    assert.match(e.get('demo-results').textContent,/No inventory or cash balance assumed/);
    assert.match(e.get('demo-results').textContent,/Blocked/);
  }
  assert.doesNotMatch(e.get('order-rows').textContent,/fin535-demo-/);
});
test('English methodology and formulas are visible without a fabricated performance chart',()=>{
  assert.match(html,/Capital Utilization and Return Measurement/);
  assert.match(html,/Account Return = Net Portfolio P&amp;L \/ Starting Portfolio Equity/);
  assert.match(html,/Return on Deployed Capital = Net Strategy P&amp;L \/ Average Deployed Capital/);
  assert.match(html,/Capital Utilization = Deployed Capital \/ Portfolio Equity/);
  assert.match(html,/Performance Evaluation Pending Sanji Data/);
  assert.match(html,/comparison has not run/);
  assert.match(html,/strategy-workflow\.svg/);
  assert.ok(html.indexOf('assets/analysis.js')<html.indexOf('assets/app.js'));
  assert.doesNotMatch(html+script+analysisScript,/[\u4e00-\u9fff]/);
});

test('Assignment scope separates proposed orders, schema and execution without inventing a balance',()=>{
  const scope=html.match(/<aside class="note" id="assignment-scope">([\s\S]*?)<\/aside>/)?.[1];
  assert.ok(scope);
  for(const role of ['My algorithm','Sanji specification','Sanji backend']) assert.ok(scope.includes(role));
  assert.match(scope,/does not require completed Sanji fills or positions/);
  assert.match(scope,/student-selected \$40,000 simulation budget/);
  assert.match(scope,/Pending proposals retain their collateral and weekly commitments/);
  assert.match(html,/Missing execution\s+records do not mean that the order-generation workflow failed/);
});

test('Dated automation audit distinguishes actual schedule evidence from manual success and punctuality',()=>{
  const evidence=html.match(/<div id="automation-evidence">([\s\S]*?)<\/div>/)?.[1];
  assert.ok(evidence);
  assert.match(evidence,/actions\/runs\/43981421173">Manual run/);
  assert.match(evidence,/actions\/runs\/44073688095">Scheduled run/);
  assert.match(evidence,/actual <code>schedule<\/code> event/);
  assert.match(evidence,/06:24:09 America\/New_York \(11:24:09 UTC\)/);
  assert.match(evidence,/not the configured 22:00/);
  assert.match(evidence,/historical run records, not a claim about every future run/);
});

test('Earnings policy is removed from current diagnostics, with an explicit gap-risk disclosure',async()=>{
  const e=await render(realStatus,[],false,realDemo);
  for(const id of ['availability-rows','data-quality','pipeline-discussion','demo-results'])
    assert.doesNotMatch(e.get(id).textContent,/earnings|blackout|calendar confirmation/i);
  assert.match(html,/does not screen around earnings announcements/);
  assert.match(html,/exposed to earnings-related price gaps/);
  assert.match(html,/intentionally removed/);
  assert.doesNotMatch(html,/Unknown earnings still block|earnings validation|No earnings from entry|earnings_investigation\.json|event filters/);
  const flow=fs.readFileSync(path.join(__dirname,'../docs/assets/strategy-workflow.svg'),'utf8');
  assert.doesNotMatch(flow,/earnings/i);
  assert.match(flow,/Five-day return ≥ −8%/);
});

test('A successful retained-data audit never labels an unchanged queue as new orders',async()=>{
  const s={...realStatus,status:'success',errors:[],evaluation_kind:'retained_market_replay',orders_updated:false,proposed_order_count:2};
  const e=await render(s,[],false,realDemo);
  assert.match(e.get('run-time').textContent,/Retained-data re-evaluation/);
  assert.match(e.get('decision-note').textContent,/not a new API query/);
  assert.match(e.get('order-note').textContent,/not changed/);
  assert.match(e.get('order-rows').textContent,/replay does not publish orders/);
  assert.doesNotMatch(e.get('order-note').textContent,/Valid no-trade/);
});

test('Course mode labels hypothetical budget separately from unavailable official account',async()=>{
  const s={...baseline,status:'success',errors:[],account_mode:'course_proposal',
    account_status:'Unavailable; course assumptions used',unconfirmed_proposal_count:2,
    capital:{equity:40000,cash:40000,exposure:12400,put_collateral:12400,uncommitted_cash:27600}};
  const e=await render(s,[{id:'fin535-course-test',for:'2026-11-16',underlying:8894,action:'SHT',contract:'put',expiry:'2026-11-20',strike:96,qty:1}]);
  assert.match(e.get('account-mode').textContent,/COURSE PROPOSAL MODE/);
  assert.match(e.get('capital-note').textContent,/Initial simulated capital: \$40,000/);
  assert.match(e.get('availability-rows').textContent,/authoritative Sanji book not yet available/);
  assert.match(e.get('order-note').textContent,/not actual Sanji account orders/);
  assert.equal(e.get('issues').textContent,'');
  assert.match(e.get('run-state').textContent,/Validated evaluation/);
});

test('Unconfirmed prior outcomes are not mislabeled as a no-opportunity result',async()=>{
  const e=await render({...baseline,status:'success',errors:[],account_mode:'course_proposal',
    outcome:'awaiting_order_confirmation',unconfirmed_proposal_count:2});
  assert.match(e.get('order-note').textContent,/unknown outcomes/);
  assert.doesNotMatch(e.get('order-note').textContent,/Valid no-trade/);
  assert.match(e.get('account-mode').textContent,/2 unconfirmed/);
});

test('Course market-input failure remains blocked and never clears retained queue in UI',async()=>{
  const e=await render({...baseline,status:'blocked',account_mode:'course_proposal',errors:['BAC: missing close']});
  assert.match(e.get('order-note').textContent,/not changed/);
  assert.match(e.get('issues').textContent,/missing close/);
  assert.match(e.get('account-mode').textContent,/not fills or actual balances/);
});

function initialAuditFixture(){
  const scenario=realDemo.scenarios.find(s=>s.id==='cash_start');
  return {...realStatus,status:'success',account_mode:'course_proposal',errors:[],
    initial_account_policy:{scope:'course_simulation_only',starting_cash:40000,
      professor_confirmed_cash_amount:false,official_sanji_balance:false,
      initial_positions_file_required:false,initial_inventory:{shares:0,open_puts:0,open_calls:0}},
    initial_cycle_review:{status:'validated',orders_written:false,fills_inferred:false,
      market_retrieved_at:realStatus.market_data_retrieved_at,signal_date:realStatus.calendar.as_of,
      target_session:realStatus.calendar.target_session,existing_proposals_match:true,
      proposals:scenario.proposed_orders,capital:scenario.capital,
      collateral_by_proposal:scenario.proposed_orders.map(o=>({id:o.id,underlying:o.underlying,strike:o.strike,qty:o.qty,collateral:100*o.strike*o.qty}))}};
}
test('Initial account copy is concise while retaining the simulation and fill distinction',async()=>{
  const e=await render(initialAuditFixture());
  assert.match(e.get('initial-account-summary').textContent,/Initial simulated capital: \$40,000/);
  assert.match(e.get('initial-account-summary').textContent,/Starting inventory: 0 shares, 0 open puts, 0 open calls/);
  assert.match(e.get('initial-account-summary').textContent,/subsequent holdings depend on confirmed order outcomes/);
  for (const id of ['initial-account-summary','account-mode','capital-note','availability-rows'])
    assert.doesNotMatch(e.get(id).textContent,/professor.confirmed|student.authorized|capital authority/i);
  assert.doesNotMatch(html,/not (?:a )?professor.confirmed|student.authorized|capital authority/i);
  assert.match(html,/<td>Initial simulated capital<\/td>\s*<td>\$40,000<\/td>/);
  assert.match(e.get('initial-account-summary').textContent,/positions.json is not required/);
  assert.match(e.get('initial-collateral-note').textContent,/\$12,400.00.*31.00%.*\$27,600.00/);
  assert.equal(e.get('initial-collateral-rows').children.length,2);
  assert.match(e.get('initial-collateral-rows').textContent,/\$9,600.00/);
  assert.match(e.get('initial-collateral-rows').textContent,/\$2,800.00/);
});
test('Initial audit with inconsistent collateral or dates makes no allocation claim',async()=>{
  for(const mutate of [s=>s.initial_cycle_review.capital.put_collateral+=1,s=>s.initial_cycle_review.signal_date='1900-01-01',s=>s.initial_cycle_review.fills_inferred=true]){
    const s=structuredClone(initialAuditFixture());mutate(s);
    const e=await render(s);
    assert.match(e.get('initial-collateral-note').textContent,/failed|unavailable or inconsistent/);
    assert.doesNotMatch(e.get('initial-collateral-note').textContent,/Total proposed collateral/);
  }
});
test('Earlier commitments withhold a new flat-start audit, without assuming zero later positions',async()=>{
  const s=initialAuditFixture();s.initial_cycle_review={status:'not_initial_cycle'};
  const e=await render(s);
  assert.match(e.get('initial-collateral-note').textContent,/Not an initial-cycle reset/);
  assert.match(e.get('initial-collateral-note').textContent,/stay reserved until reconciled/);
  assert.match(html,/Subsequent Wheel phases[\s\S]*require authoritative holdings/);
});
