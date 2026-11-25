const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const d=JSON.parse(fs.readFileSync(require('node:path').join(__dirname,'../investment-thesis/data/public_tracker.json')));
const {check,model,findings,interpretation}=require('../investment-thesis/payoff.js');
require('../investment-thesis/app.js');
test('All ratios and blocks use computed conditional and opportunity data',()=>{
 for(const r of ['1.0','0.98','0.95','0.9'])for(const b of [2,4,8]){
  const m=model(d,r,b);assert.equal(m.conditional.length,8);assert.equal(m.weekly.length,4);
  assert.deepEqual(m.traces[0].y,['BAC','KO','PFE','F'].map(t=>d.lecture_extension.hypothetical_put_payoff.tickers[t][r].filtered.mean_loss*10000));
  assert.doesNotMatch([...m.analysis,...m.budget].join(' '),/undefined|NaN|Infinity/);
  assert.match(m.analysis.join(' '),/not observed market contracts/);
  assert.match(m.analysis.join(' '),/cannot measure economic value or option alpha/);
 }
 assert.throws(()=>model(d,'0.25'));assert.throws(()=>model(d,'0.95',7));
});
test('Idleness and costs cannot be silently dropped',()=>{
 const z=structuredClone(d);z.lecture_extension.hypothetical_put_payoff.tickers.BAC['0.95'].weekly_filtered_break_even+=1;
 assert.throws(()=>check(z),/Ignored idle/);
 const a=structuredClone(d);a.lecture_extension.hypothetical_put_payoff.estimated_option_alpha=.1;
 assert.throws(()=>check(a));
});
test('Prominent findings include contradictory sampling, risks and review status',()=>{
 const f=findings(d);assert.equal(f.rows.length,4);
 assert.match(f.text.join(' '),/reverses/);assert.match(f.text.join(' '),/Insufficient Evidence/);
 assert.match(f.text.join(' '),/23 contracts/);assert.match(f.text.join(' '),/alpha remains unestimated/);
});
test('Browser receives summaries and no raw stock paths',()=>{
 assert.equal(d.projection.raw_price_paths_included,false);assert.ok(!('rows' in d));
 for(const key of ['"reference_close":','"end_close":','"BID":','"ASK":','"dated_records":'])assert.ok(!JSON.stringify(d).includes(key));
});
test('F interpretation distinguishes daily path frequency from weekly terminal frequency and severity',()=>{
 const text=interpretation(d).join(' '),z=d.lecture_extension.hypothetical_put_payoff.tickers.F['0.95'];
 for(const g of [z.filtered,z.unfiltered]){
  assert.ok(text.includes((10000*g.mean_loss).toFixed(2)));
  assert.ok(text.includes((100*g.positive_loss_frequency).toFixed(2)+'%'));
  assert.ok(text.includes((10000*g.mean_positive_loss).toFixed(2)));
  assert.ok(Math.abs(g.mean_loss-g.positive_loss_frequency*g.mean_positive_loss)<1e-12);
 }
 assert.match(text,/dates, samples and outcomes differ/);
 assert.match(text,/not estimated alpha/);
 assert.match(text,/15\/82/);assert.match(text,/46\/260/);
 assert.doesNotMatch(text,/undefined|NaN/);
});
test('Final research reading order retains all six findings and lecture material',()=>{
 const html=fs.readFileSync(require('node:path').join(__dirname,'../investment-thesis/index.html'),'utf8');
 const list=html.match(/<ul[^>]+id="key-findings-list">([\s\S]*?)<\/ul>/)[1];
 assert.equal([...list.matchAll(/<li>/g)].length,6);
 for(const phrase of ['do not provide strong evidence','trend filter','PFE and F','sampling method','does not show consistent','alpha remains unestablished'])assert.ok(list.includes(phrase));
 const section=id=>html.indexOf('<section id="'+id+'"');
 assert.ok(section('findings')<section('thesis'));
 assert.ok(section('put-payoff')<section('conclusion'));
 assert.ok(section('conclusion')<section('reliability'));
 assert.ok(section('monitoring')<html.indexOf('<details id="theorem-details">'));
 for(const term of ['Theorem 1.1','50%','25%','10%','CUSUM','drawdown','percentile bands','Pending'])assert.ok(html.includes(term),term);
 assert.match(html,/not yet sufficiently support my original thesis/);
 assert.match(html,/Break-even premium is a cost-and-liability hurdle, not estimated alpha/);
 assert.match(html,/interval containing zero does not cause that label/);
 const ids=[...html.matchAll(/id="([^"]+)"/g)].map(m=>m[1]);
 assert.equal(new Set(ids).size,ids.length);
 for(const a of html.matchAll(/href="#([^"]+)"/g))assert.ok(ids.includes(a[1]));
});
