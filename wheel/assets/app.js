'use strict';
(() => {
  const b=window.WHEEL_BOOK,$=id=>document.getElementById(id),esc=x=>String(x??'N/A').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const money=x=>x==null?'N/A':new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(x),pct=x=>x==null?'N/A':(x*100).toFixed(2)+'%',num=x=>x==null?'N/A':Number(x).toLocaleString('en-US',{maximumFractionDigits:4});
  if(!b){$('finding').textContent='Results could not be loaded; no performance assumed.';return;}
  const title={wheel:'Cash-secured Wheel',buy_hold:'Buy and hold'},color={wheel:'#167765',buy_hold:'#3973a3'},sorts={};
  const selected=()=>b.runs.find(r=>r.strategy===$('account').value&&(r.strategy==='buy_hold'||r.fill_model===$('model').value));
  const wheel=()=>b.runs.find(r=>r.strategy==='wheel'&&r.fill_model===$('model').value),benchmark=()=>b.runs.find(r=>r.strategy==='buy_hold');
  function table(id,rows,cols,empty='No recorded events.'){
    const order=sorts[id],sorted=[...rows];if(order)sorted.sort((a,b)=>{const x=a[order.key],y=b[order.key];if(x==null)return y==null?0:1;if(y==null)return -1;return (typeof x==='number'&&typeof y==='number'?x-y:String(x).localeCompare(String(y)))*order.direction;});
    $(id).innerHTML=sorted.length?'<table><thead><tr>'+cols.map(([k,t])=>`<th><button class="sort" data-key="${esc(k)}">${esc(t)}${order?.key===k?(order.direction===1?' ↑':' ↓'):''}</button></th>`).join('')+'</tr></thead><tbody>'+sorted.map(r=>'<tr>'+cols.map(([k,t,f])=>'<td>'+esc(f?f(r[k]):typeof r[k]==='object'&&r[k]!==null?JSON.stringify(r[k]):r[k])+'</td>').join('')+'</tr>').join('')+'</tbody></table>':`<p class="empty">${esc(empty)}</p>`;
    $(id).querySelectorAll('button.sort').forEach(button=>button.onclick=()=>{sorts[id]={key:button.dataset.key,direction:order?.key===button.dataset.key?-order.direction:1};table(id,rows,cols,empty);});
  }
  function plot(id,traces,ytitle,format=',.0f'){
    if(!traces.length){$(id).innerHTML='<p class="empty">Unsupported: no empirical curve substituted.</p>';return;}
    if(typeof Plotly==='undefined'){$(id).textContent='Chart library unavailable; exact values are in the CSV downloads.';return;}
    Plotly.react(id,traces,{paper_bgcolor:'white',plot_bgcolor:'white',margin:{l:66,r:18,t:20,b:80},font:{family:'system-ui',size:11,color:'#182c38'},yaxis:{title:{text:ytitle},tickformat:format,gridcolor:'#e7ecea'},xaxis:{gridcolor:'#eef1ee'},legend:{orientation:'h',y:-.23},hovermode:'x unified'},{responsive:true,displaylogo:false});
  }
  const trace=(r,field,name,color)=>({name,x:r.ledger.map(x=>x.date),y:r.ledger.map(x=>x[field]),mode:'lines',type:'scatter',connectgaps:false,line:{color,width:2}});
  function snapshot(){
    const r=selected(),s=r.snapshots.find(s=>s.snapshot_id===$('snapshot').value);if(!s)return;
    $('snapshot-note').textContent=`${title[r.strategy]} · ${s.timestamp} · ${s.phase} · marks from ${s.mark_date}. `+(!r.metrics.empirical_strategy_supported?'Cash-only diagnostic state; NOT a validated Wheel performance path.':'Event snapshots use only marks available at that modeled event; EOD states use that day’s close.');
    const values=[['Cash',money(s.cash)],['Reserved for puts',money(s.reserved_cash)],['Buying power',money(s.buying_power)],['Shares',num(s.shares)],['Stock value',money(s.stock_value)],['Dividend receivable',money(s.dividend_receivable)],['Short-option liability',money(s.option_liability)],['Portfolio equity',money(s.equity)]];
    $('portfolio-values').innerHTML=values.map(([k,v])=>`<span>${esc(k)}<strong>${esc(v)}</strong></span>`).join('');
    table('open-option',s.option?[{...s.option,mark:s.option_mark,liability:s.option_liability}]:[],[['id','Exact RIC'],['cp','Put/call'],['strike','Strike',money],['expiry','Expiry'],['last_trade_date','Scheduled last trade'],['quantity','Qty'],['entry_date','Entry date'],['entry_premium','Entry premium/share',money],['mark','Mark/share',money],['liability','Short liability',money]],'No open option. Liability = $0; this is not a missing quote substituted with zero.');
  }
  function dateChange(){
    const items=selected().snapshots.filter(s=>s.date===$('date').value);
    $('snapshot').innerHTML=items.map(s=>`<option value="${esc(s.snapshot_id)}">${esc(s.phase+' · '+s.timestamp+(s.event_id?' · '+s.event_id:''))}</option>`).join('');
    $('snapshot').value=items.at(-1)?.snapshot_id??'';snapshot();
  }
  function events(){
    const r=selected(),query=$('search').value.toLowerCase(),type=$('event-type').value;
    const rows=r.events.filter(e=>(!type||e.event_type===type)&&JSON.stringify(e).toLowerCase().includes(query));
    $('event-count').textContent=`${rows.length} / ${r.events.length} events · 0 rolls`;
    table('blotter',rows,[['event_id','Event'],['timestamp','Modeled time'],['event_type','Type'],['underlying','Underlying'],['contract','RIC'],['cp','P/C'],['strike','Strike',money],['expiry','Expiry'],['quantity','Qty'],['multiplier','Multiplier'],['fill_price','Fill',money],['bid','Bid',money],['ask','Ask',money],['midpoint','Mid',money],['quote_date','Quote date'],['quote_timestamp','Actual source time'],['gross_cash_flow','Gross cash Δ',money],['commission','Commission',money],['assignment_fee','Assign fee',money],['stock_execution_cost','Stock cost',money],['net_cash_flow','Net cash Δ',money],['cash_before','Cash before',money],['cash_after','Cash after',money],['shares_before','Shares before'],['shares_after','Shares after'],['stock_action','Stock transfer'],['realized_pnl_gross','Realized gross P&L',money],['reason','Reason'],['source','Source'],['assumption_flags','Assumptions']]);
  }
  function account(){
    const r=selected(),old=$('date').value;
    $('date').innerHTML=r.ledger.map(s=>`<option>${s.date}</option>`).join('');$('date').value=r.ledger.some(s=>s.date===old)?old:r.ledger.at(-1)?.date??'';dateChange();
    $('event-type').innerHTML='<option value="">All types</option>'+[...new Set(r.events.map(e=>e.event_type))].map(t=>`<option>${t}</option>`).join('');events();
    table('ledger',r.ledger,[['date','Date'],['cash','Cash',money],['reserved_cash','Reserved',money],['buying_power','Buying power',money],['shares','Shares'],['share_acquisition_cost','Share basis',money],['stock_value','Stock value',money],['short_put','Put'],['covered_call','Call'],['option_liability','Option liability',money],['dividend_receivable','Dividend receivable',money],['equity','Equity',money],['realized_pnl_net','Realized net P&L',money],['unrealized_stock_pnl','Unrealized stock',money],['unrealized_option_pnl','Unrealized option',money]]);
    table('decisions',r.decisions,[['date','Entry session'],['signal_date','Signal input date'],['cp','Side'],['known_contracts','Known candidates'],['eligible_contracts','Eligible'],['selected','Selected RIC'],['outcome','Outcome']],'Buy-and-hold has no weekly option decisions.');
    table('issues',r.issues,[['date','Date'],['contract','Contract'],['reason','Issue']],'No held-position valuation issues. Candidate-coverage gaps are reported separately above.');
    plot('composition-chart',[trace(r,'cash','Cash','#167765'),trace(r,'stock_value','Stock value','#3973a3'),{...trace(r,'option_liability','Short-option liability','#b55037'),y:r.ledger.map(s=>s.option_liability==null?null:-s.option_liability)},trace(r,'dividend_receivable','Dividend receivable','#988138')],'Components · USD');
  }
  function performance(){
    const w=wheel(),bm=benchmark(),m=w.metrics;
    const cards=[['Wheel total return',pct(m.total_return),m.empirical_strategy_supported?'Net equity, including open positions':'Unavailable: no supported option fills'],['Wheel Sharpe',num(m.sharpe),m.valuation_gap_dates.length?'Withheld across '+m.valuation_gap_dates.length+' NAV gap(s)':'Daily returns; annual RF '+pct(b.config.risk_free_rate)],['Full-sample MDD',pct(m.max_drawdown),m.valuation_gap_dates.length?'Missing NAV: '+m.valuation_gap_dates.join(', '):m.empirical_strategy_supported?'Complete observed-account path':'Unavailable, not a zero-loss result'],['Gross premiums',money(m.gross_premiums),'Cash receipts, NOT profit']];
    $('metrics').innerHTML=cards.map(([k,v,n])=>`<div class="metric"><div class="metric-label">${esc(k)}</div><div class="metric-value">${esc(v)}</div><div class="metric-note">${esc(n)}</div></div>`).join('');
    table('comparison',[w,bm].map(r=>({account:title[r.strategy],...r.metrics})),[['account','Account'],['net_pnl','Net P&L',money],['total_return','Return',pct],['cagr','Annualized return',pct],['annualized_volatility','Ann. volatility',pct],['sharpe','Sharpe',num],['max_drawdown','Full MDD',pct],['benchmark_excess_return','Excess return',pct],['option_entries','Options sold'],['put_assignments','Put assigns'],['call_assignments','Call assigns'],['total_costs','Costs',money],['net_premiums_after_option_costs','Net premium cash',money],['days_with_shares','Sessions with shares'],['days_without_shares','Without shares']]);
    const supported=[w,bm].filter(r=>r.metrics.empirical_strategy_supported);
    plot('equity-chart',supported.map(r=>trace(r,'equity',title[r.strategy],color[r.strategy])),'Equity · USD');
    plot('drawdown-chart',supported.map(r=>trace(r,'drawdown',title[r.strategy],color[r.strategy])),'Drawdown','.1%');
    $('drawdown-note').textContent=!m.empirical_strategy_supported?'No supported Wheel fills: no flat cash curve is substituted for empirical performance.':m.valuation_gap_dates.length?'Wheel strict drawdown stops at the first missing NAV ('+m.valuation_gap_dates[0]+'); full-path MDD/Sharpe/volatility are withheld. Observed drawdown in the downloads retains gaps and is only a magnitude lower bound.':'Complete observed-account NAV paths; drawdown uses each account’s running equity peak, including initial cash.';
    account();
  }
  $('status').textContent=b.status==='unsupported_missing_wheel_fills'?'WHEEL NOT YET EMPIRICALLY SUPPORTED':'OBSERVED-UNIVERSE RESEARCH';$('status').classList.toggle('blocked',b.status==='unsupported_missing_wheel_fills');
  $('sample').textContent=`${b.config.stock_ric} · ${b.config.start} — ${b.config.end} · ${money(b.config.initial_cash)} each`;
  $('finding').textContent=b.conclusion;$('thesis').textContent=b.thesis;$('conclusion').textContent=b.conclusion;
  const a=b.audit,missing=a.missing_candidate_weeks.filter(w=>w.cp==='P');
  $('coverage-summary').textContent=`Short-dated historical contracts: ${a.contract_counts.P} puts / ${a.contract_counts.C} calls. ${missing.length} weekly put-candidate gaps; the historical chain is still incomplete. Missing cache coverage is NOT evidence that the market had no contracts. `+(a.acquisition?.connection_error?'LSEG acquisition: '+a.acquisition.connection_error:'')+(a.mark_repair?.requests?.length?' Closing-mark recheck: '+a.mark_repair.requests.map(x=>`${x.date} ${x.id} — ${x.recovered?'recovered from real closing quote':'no eligible final-minute BBO; missing mark retained'}`).join('; ')+'.':'');
  $('quote-quality').innerHTML=[['Observed BBOs',num(a.quoted_observations)],['Median spread/share',money(a.median_spread)],['Median relative spread',pct(a.median_relative_spread)],['Historical delta rows',num(a.historical_delta_rows)]].map(([k,v])=>`<span>${esc(k)}<strong>${esc(v)}</strong></span>`).join('');
  $('spread-note').textContent=a.spread_population+' Baseline sells at observed bid and buys back at ask; midpoint is a separate optimistic sensitivity, not an asserted execution. Actual fills, available size and intraday quote synchrony are unobserved.';
  table('coverage',a.weeks,[['date','Entry session'],['signal_date','Known by input date'],['cp','P/C'],['known_contracts','Observed candidates'],['valid_signal_quotes','Valid signal BBO'],['eligible_contracts','Eligible'],['reason','Coverage outcome']]);
  table('quote-issues',a.quote_issues,[['date','Date'],['contract','Contract'],['missing_fields','Missing fields'],['closing_fallback_available','Validated closing fallback'],['reason','Reason']]);
  table('contracts',a.contracts,[['id','Observed RIC'],['cp','P/C'],['strike','Strike',money],['expiry','Expiry'],['last_trade_date','Scheduled last trade'],['first_observed_quote_date','First observed'],['last_observed_quote_date','Last observed'],['multiplier','Multiplier'],['terms_status','Term verification']]);
  $('candidate-note').textContent=a.candidate_universe;$('timing').textContent=b.timing;$('capital-note').textContent=b.capital_note;
  table('parameters',Object.entries(b.config).map(([parameter,value])=>({parameter,value})),[['parameter','Parameter'],['value','Fixed value']]);
  $('cost-note').textContent=`Option commission ${money(b.config.option_commission)} per executed contract/side; stock execution cost ${b.config.stock_slippage_bps} bp per executed share-side; assignment fee ${money(b.config.assignment_fee)} per event. Strike transfers incur no stock-market spread. Bid/ask cost is already in fills and is not deducted a second time. No financing or borrow; idle cash earns 0%.`;
  $('accounting-note').textContent=b.accounting;$('assignment-note').textContent=b.assignment;$('limitations').innerHTML=b.limitations.map(t=>'<li>'+esc(t)+'</li>').join('');
  $('config-editor').value=JSON.stringify(b.config,null,2);$('provenance').textContent=JSON.stringify({input_sha256:b.input_sha256,python:b.python,code_hashes:b.code_hashes},null,2);
  $('download-config').onclick=()=>{try{const cfg=JSON.parse($('config-editor').value);if(!cfg||Array.isArray(cfg)||typeof cfg!=='object')throw Error('Expected an object');const url=URL.createObjectURL(new Blob([JSON.stringify(cfg,null,2)+'\n'],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='wheel-custom-config.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);$('config-message').textContent='Downloaded; Python validates settings before rerunning. Published results unchanged.';}catch(e){$('config-message').textContent='Invalid JSON: '+e.message;}};
  $('date').onchange=dateChange;$('snapshot').onchange=snapshot;$('account').onchange=account;$('model').onchange=performance;$('search').oninput=events;$('event-type').onchange=events;
  performance();
})();
