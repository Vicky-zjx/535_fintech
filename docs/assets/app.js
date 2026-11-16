'use strict';
(() => {
  const tickers=['BAC','KO','PFE','F'];
  const $=id=>document.getElementById(id);
  const fmt=(v,percent=false)=>typeof v==='number'&&Number.isFinite(v)?(percent?(v*100).toFixed(2)+'%':new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(v)):'Unavailable';
  const text=(id,value)=>{$(id).textContent=value;};
  function cell(tr,value,detail){const td=document.createElement('td');td.textContent=value;if(detail){const small=document.createElement('small');small.textContent=detail;td.append(small);}tr.append(td);}
  function empty(tbody,columns,message){const tr=document.createElement('tr');cell(tr,message);tr.firstChild.colSpan=columns;tbody.replaceChildren(tr);}
  function svgNode(tag,attrs,textValue){const n=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [k,v] of Object.entries(attrs))n.setAttribute(k,String(v));if(textValue!==undefined)n.textContent=textValue;return n;}
  function barChart(container,series,label){const el=$(container);if(!series.length)return;el.replaceChildren();const svg=svgNode('svg',{viewBox:'0 0 520 250',role:'img','aria-label':label});const max=Math.max(...series.map(d=>Math.abs(d.value)),1);let y=28;for(const d of series){svg.append(svgNode('text',{x:0,y:y+16,fill:'#526b7d','font-size':13},d.label));const x=132,w=280*Math.abs(d.value)/max;svg.append(svgNode('rect',{x,y:y+2,width:w,height:20,fill:d.color||'#32668f',rx:2}));svg.append(svgNode('text',{x:x+w+8,y:y+17,fill:'#182b3a','font-size':12},d.display));y+=Math.min(43,210/series.length);}el.append(svg);}
  function charts(s){const valid=s.decisions.filter(d=>Number.isFinite(d.close)&&Number.isFinite(d.sma50));barChart('signal-chart',valid.flatMap(d=>[{label:d.ticker+' close − SMA50',value:(d.close/d.sma50-1)*100,display:((d.close/d.sma50-1)*100).toFixed(1)+'%',color:'#32668f'},{label:d.ticker+' SMA20 − SMA50',value:(d.sma20/d.sma50-1)*100,display:((d.sma20/d.sma50-1)*100).toFixed(1)+'%',color:'#91adbf'}]),'Close and SMA20 deviation from SMA50, percent, by ticker');if(s.capital){const c=s.capital;barChart('capital-chart',[{label:'Exposure',value:c.exposure,display:fmt(c.exposure)},{label:'Put collateral',value:c.put_collateral,display:fmt(c.put_collateral),color:'#91adbf'},{label:'Free cash',value:c.uncommitted_cash,display:fmt(c.uncommitted_cash),color:'#4f766e'},{label:'Minimum reserve',value:c.equity*.3,display:fmt(c.equity*.3),color:'#a8b5be'}],'Account exposure, put collateral and uncommitted cash in USD. Collateral is included in exposure, not added again.');}}
  function render(s,orders){
    const good=s.status==='success';const observed=s.market_data_retrieved_at;
    text('run-state',good?'Validated evaluation':observed?'Market data retrieved · orders blocked':'Live data not yet available');
    if(good)document.querySelector('.run-strip').classList.add('success');
    text('run-time',s.attempted_at?'Latest attempt: '+s.attempted_at.replace('T',' ').replace('+00:00',' UTC'):'No verified live evaluation yet');
    text('target-session','Target session: '+(s.calendar?.target_session||'not yet evaluated'));
    text('decision-note',observed?'Signals use completed session '+s.calendar.as_of+'. Orders require a fresh, reconciled account and verified identifiers.':'Only validated inputs appear here. Missing data is not a no-trade signal.');
    const issues=[...(s.errors||[])];if(s.account_status&&s.account_status!=='Available')issues.push(s.account_status);
    if(s.conid_status){const missing=tickers.filter(t=>!s.conid_status[t]);if(missing.length)issues.push('Course conid mappings missing: '+missing.join(', '));}
    text('issues',issues.join(' · '));
    const rows=$('decision-rows');rows.replaceChildren();
    for(const ticker of tickers){const d=(s.decisions||[]).find(x=>x.ticker===ticker)||{ticker,reasons:['Live data not yet available']};const tr=document.createElement('tr');cell(tr,ticker,d.price_date||'No validated close');for(const k of ['close','sma20','sma50','hv20','r5'])cell(tr,fmt(d[k],k==='hv20'||k==='r5'));const p=d.position;cell(tr,p?`${p.shares} shares / ${p.put} put / ${p.call} call`:'Account unavailable');cell(tr,d.filters?Object.entries(d.filters).map(([k,v])=>k+': '+(v?'pass':'fail')).join(' · '):'Not evaluated',d.eligible?'Eligible':'Not eligible');cell(tr,d.decision||'Not evaluated',(d.reasons||[]).join('; '));rows.append(tr);}
    text('order-note',good?(orders.length?'Proposed simulated orders; not verified fills.':'Valid no-trade evaluation: no qualifying new or pending orders.'):(s.status==='not_run'?'Initial empty queue; not yet a successful no-trade evaluation.':'Order files were not changed by this attempt. Any displayed orders are retained from an earlier run; their dated sessions govern eligibility.'));
    const orderRows=$('order-rows');orderRows.replaceChildren();
    for(const o of orders){const tr=document.createElement('tr');const t=Object.entries(s.conid_status||{}).find(([,v])=>v===o.underlying)?.[0]||'Unmapped';[o.for,t+' / '+o.underlying,o.action,o.contract,o.expiry,fmt(o.strike),String(o.qty),o.id].forEach(v=>cell(tr,v));orderRows.append(tr);}
    if(!orders.length)empty(orderRows,8,good?'No proposed orders for this valid evaluation.':'Empty queue; no successful order-generation run is asserted.');
    const q=$('data-quality');q.replaceChildren();const stamp=document.createElement('p');stamp.textContent='Last successful evaluation: '+(s.successful_at||'None verified')+'. Latest market response: '+(s.market_data_retrieved_at||'None verified')+'.';q.append(stamp);for(const [t,d] of Object.entries(s.data_quality||{})){const p=document.createElement('p');p.textContent=t+': '+(d.candidate_count??0)+' accepted candidates; '+(d.options_status||'unavailable')+'. '+(d.delta_status||'Greeks unavailable')+'. Earnings: '+(d.earnings?.reliable?'confirmed next reported event':'unknown/provisional; blocks puts')+'. '+(d.errors||[]).join('; ');q.append(p);}
    $('snapshot-link').hidden=!s.market_snapshot_sha256;charts({...s,decisions:s.decisions||[]});
  }
  async function get(url){const r=await fetch(url,{cache:'no-store'});if(!r.ok)throw Error('HTTP '+r.status);return r.json();}
  Promise.all([get('data/strategy_status.json'),get('../open_orders.json')]).then(([s,o])=>{if(!Array.isArray(o))throw Error('Invalid orders');render(s,o);}).catch(()=>{text('run-state','Live data not yet available');text('issues','Published diagnostics or order files could not be loaded. Do not interpret this as a no-trade decision.');});
})();
