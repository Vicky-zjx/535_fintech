'use strict';
(() => {
  const book=window.PMCC_BOOK;
  const $=id=>document.getElementById(id);
  const names={pmcc:'PMCC',covered_call:'Cash-funded covered call',buy_hold:'100-share buy and hold'};
  const colors={pmcc:'#167765',covered_call:'#3973a3',buy_hold:'#b55037'};
  const esc=x=>String(x??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const usd=x=>x==null?'—':new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',maximumFractionDigits:2}).format(x);
  const pct=x=>x==null?'—':(100*x).toFixed(2)+'%';
  const display=x=>typeof x==='number'?Number(x.toFixed(4)).toLocaleString('en-US'):x==null?'—':typeof x==='boolean'?(x?'Yes':'No'):x;
  const table=(target,rows,cols,empty='No recorded observations.')=>{
    $(target).innerHTML=rows.length?'<table><thead><tr>'+cols.map(([k,title])=>`<th>${esc(title)}</th>`).join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+cols.map(([k,title,format])=>`<td>${esc(format?format(r[k]):display(r[k]))}</td>`).join('')+'</tr>').join('')+'</tbody></table>':`<p class="empty">${esc(empty)}</p>`;
  };
  if(!book){$('run-finding').textContent='Published result file could not be loaded. No results are assumed.';return;}
  const blocked=book.status==='blocked';
  const pmccRun=book.runs.find(r=>r.strategy==='pmcc'&&r.fill_model==='midpoint');
  const gapCount=pmccRun?.metrics.valuation_gap_sessions??0;
  const endpointsClosed=book.runs.length>0&&book.runs.every(r=>r.metrics.terminal_resolved&&r.audit.pnl_reconciled);
  $('status').textContent=blocked?'DATA AUDIT BLOCKED':book.status==='complete'?'SIMULATED RUN COMPLETE':'INCOMPLETE · VALUATION / EXPOSURE GAPS';
  $('status').classList.toggle('blocked',book.status!=='complete');
  $('window').textContent=(blocked?'Target, not a completed sample: ':'Sample: ')+book.config.start+' — '+book.config.end;
  $('run-finding').textContent=blocked?'Input audit failed: no performance is published. See the unresolved issues below.':'Real LSEG prices · simulated fills. '+(endpointsClosed?'All accounts closed and reconciled. ':'Terminal exposure unresolved. ')+(gapCount?`${gapCount} PMCC NAV gap(s): ${pmccRun.metrics.valuation_gap_dates.join(', ')}; full-sample MDD unavailable.`:'Complete PMCC daily NAV path.');
  $('run-finding').classList.toggle('error',book.status!=='complete');
  if(book.config.long_mode!=='75%-of-spot strike proxy') $('long-rule').textContent='365–550 signal DTE; expiry nearest 450 then earlier. Historical delta target 0.80, eligible 0.70–0.90; ties lower strike, then identifier. Replace at weekly decision when remaining DTE ≤90.';
  const runs=()=>book.runs.filter(r=>r.fill_model===$('model').value);
  const selected=()=>runs().find(r=>r.strategy===$('account').value);
  if(book.runs.every(r=>r.metrics.valuation_path_complete))$('drawdown-view').value='drawdown';
  function renderDrawdown(){
    const field=$('drawdown-view').value,observed=field==='observed_drawdown';
    const incomplete=runs().filter(r=>!r.metrics.valuation_path_complete);
    const gaps=incomplete.map(r=>`${names[r.strategy]}: ${(r.metrics.valuation_gap_dates??[]).join(', ')||'unresolved exposure'}`).join('; ');
    $('dd-title').textContent=observed?'Observed-NAV drawdown':'Strict full-path drawdown';
    $('dd-note').textContent=blocked?'No empirical run.':incomplete.length?
      `Full-sample MDD is unavailable for ${gaps}. Strict drawdown stops at the FIRST missing NAV and stays blank afterward: later peaks may have been missed. Observed-NAV drawdown resumes using only observed peaks, keeps missing points blank, and its maximum magnitude is only a LOWER BOUND on full-sample MDD—not a replacement.`:
      'All daily NAVs are available. Full-sample MDD is computed over the entire research window, including initial equity; observed-NAV and strict drawdown agree.';
    chart('dd-chart',field,observed?'Observed NAV · lower bound if gaps':'Strict full-path','.1%');
  }
  function chart(id,field,title,format){
    const rows=runs();
    if(!rows.length){$(id).innerHTML='<div class="empty-plot"><strong>Not run</strong><span>Verified historical inputs are required.<br>No zero-return curve is substituted.</span></div>';return;}
    const traces=rows.map(r=>({name:names[r.strategy],x:r.ledger.map(x=>x.date),y:r.ledger.map(x=>x[field]),customdata:r.ledger.map(x=>pct(x.delta_to_nav)),type:'scatter',mode:'lines',connectgaps:false,line:{color:colors[r.strategy],width:2},hovertemplate:'%{x}<br>%{y:'+format+'}'+(field==='delta_dollar'?'<br>Exposure / NAV: %{customdata}':'')+'<extra>%{fullData.name}</extra>'}));
    if(typeof Plotly==='undefined'){$(id).textContent='Chart library unavailable; download the ledger CSV for exact values.';return;}
    Plotly.react(id,traces,{paper_bgcolor:'white',plot_bgcolor:'white',margin:{l:66,r:18,t:18,b:60},font:{family:'system-ui',color:'#182c38',size:11},yaxis:{title:{text:title},tickformat:format,gridcolor:'#e7ecea'},xaxis:{gridcolor:'#eef1ee'},legend:{orientation:'h',y:-.22},hovermode:'x unified'},{responsive:true,displaylogo:false});
  }
  function renderTrades(){
    const r=selected(),query=$('search').value.toLowerCase();
    const events=(r?.blotter??[]).filter(e=>['date','signal_date','signal_at','leg','contract','strike','expiry','action','reason','execution_reference'].map(k=>e[k]??'').join(' ').toLowerCase().includes(query));
    $('trade-count').textContent=blocked?'Not run':`${events.length} / ${r?.blotter.length??0} events`;
    table('trades',events,[['date','Date'],['signal_date','Signal input date'],['signal_at','Signal time'],['execution_reference','Modeled close'],['event_phase','Phase'],['leg','Leg'],['contract','Contract'],['strike','Strike',usd],['expiry','Expiry'],['action','Action'],['quantity','Qty'],['price','Price',usd],['commission','Option fee',usd],['stock_slippage_cost','Stock slippage',usd],['cash_delta','Cash Δ',usd],['source_date','Quote date'],['source_precision','Precision'],['source_timestamp','Actual source time'],['reason','Reason']],blocked?'No empirical trades: the input audit stopped the run.':'No events match this filter.');
    const weeks=blocked?book.weekly_coverage:r?.weekly_coverage??[];
    table('weekly',weeks,[['date','Scheduled session'],['signal_date','Prior session'],['closing_reference','Modeled close / ET'],['friday_series','Friday series'],['last_session','Scheduled last session'],['holiday_shifted','Holiday shift'],['signal_observed_contracts','Candidates evidenced by signal'],['candidate_coverage','Candidate scope'],['candidate_coverage_complete','Complete chain proven'],['signal_spot','Signal stock',usd],['execution_spot','Execution stock',usd],['selected_short','Chosen short'],['actual_entry_moneyness','Entry moneyness',pct],['time_to_last_trade_days','Days to last trade'],['outcome','Outcome'],['reason','Reason']]);
    const sept=weeks.filter(w=>w.date>='2026-09-01'&&w.date<='2026-09-30'),skips=sept.filter(w=>w.outcome==='skipped');
    $('coverage-note').textContent=blocked?'Calendar opportunities only; no empirical orders were run.':
      'Every weekly opportunity is retained. Candidate coverage is a historical-evidence subset, not the complete market chain; a cache/query gap is not evidence that no contract existed. '+
      (r?.strategy==='buy_hold'?'Buy and hold has no weekly overlay.':skips.length?'September weeks without a short: '+skips.map(w=>w.date+' — '+w.reason).join('; ')+'.':`All ${sept.length} September entry weeks have a short. The October 2 series is eligible for September 28 entry and September 30 terminal liquidation.`);
    table('gaps',r?.issues??[],[['date','Date'],['reason','Issue'],['details','Observed limitation'],['short_contract','Held short'],['affects','Affected results']],blocked?'Not run.':'No valuation or unresolved-exposure issues in this account.');
    const assigned=(r?.blotter??[]).find(e=>e.action==='ASSIGN');
    if(!assigned){$('assignment-example').textContent=blocked?'No empirical run was permitted, so assignment occurrence is unknown. Synthetic unit-test examples are not presented as historical evidence.':'No assignment occurred in this account and fill-model run. No synthetic worked example is included in the results.';}
    else{
      const surrounding=r.blotter.filter(e=>e.id>=assigned.id&&e.id<=assigned.id+5);
      $('assignment-example').innerHTML='<p class="caption">Real-input, modeled assignment; it is not evidence of actual historical exercise. Inspect cash, shares and the retained long, then the mandatory cover where applicable.</p><div id="assignment-table" class="table-wrap"></div>';
      table('assignment-table',surrounding,[['date','Date'],['action','Action'],['leg','Leg'],['cash_delta','Cash Δ',usd],['cash_after','Cash after',usd],['shares_after','Shares after'],['long_after','Long retained'],['reason','Reason']]);
    }
  }
  function render(){
    const r=runs().find(r=>r.strategy==='pmcc'),m=r?.metrics??{};
    const ddNote=m.max_drawdown!=null?'Complete research window; all daily NAVs available':m.valuation_gap_sessions?
      `Unavailable: ${m.valuation_gap_sessions} missing NAV date(s): ${(m.valuation_gap_dates??[]).join(', ')}`:'Unavailable: unresolved exposure or incomplete path';
    const cards=[['PMCC net P&L',usd(m.net_pnl),'After costs, not gross premiums'],['Account return',pct(m.account_return),'Same $50,000 denominator'],['Full-sample MDD',pct(m.max_drawdown),ddNote],['Initial capital outlay',usd(m.initial_capital_outlay),'Long paid in full, including entry fee']];
    $('metrics').innerHTML=cards.map(([label,value,note])=>`<div class="metric"><div class="metric-label">${label}</div><div class="metric-value">${value}</div><div class="metric-note">${blocked?'Unavailable: empirical run blocked':note}</div></div>`).join('');
    $('metrics-note').textContent=blocked?'Both fill scenarios are implemented, but neither has a publishable empirical result. Blank values are not zero.':'Displayed model: '+$('model').selectedOptions[0].text+'. '+(m.terminal_resolved?'Endpoint return reconciles after liquidation. ':'Endpoint unresolved. ')+(m.valuation_gap_sessions?`${m.valuation_gap_sessions} PMCC NAV gaps; full-sample MDD is withheld. `:'No PMCC NAV gaps; full-sample MDD is available. ')+'No headline annualized return or Sharpe ratio is reported.';
    const comparisons=Object.keys(names).map(s=>{const x=runs().find(v=>v.strategy===s);return {name:names[s],status:x?.status??'not run',...x?.metrics};});
    table('comparison',comparisons,[['name','Account'],['ending_nav','Ending NAV',usd],['net_pnl','Net P&L',usd],['account_return','Account return',pct],['max_drawdown','Full-sample MDD',pct],['max_observed_drawdown','Observed-NAV max DD*',pct]]);
    table('comparison-extra',comparisons,[['name','Account'],['status','Path status'],['terminal_resolved','Terminal closed'],['valuation_gap_sessions','NAV gaps'],['entry_capital_saved','Entry cash saved vs 100 shares',usd],['transaction_costs','All modeled costs',usd],['gross_premiums','Gross premiums',usd],['short_calls','Short calls'],['expiry_assignments','Expiry assignments'],['early_assignments','Dividend assignments'],['skipped_weeks','Skipped weeks'],['long_only_sessions','Long-only EOD states'],['valid_daily_returns','Valid daily returns']]);
    chart('nav-chart','nav','USD',',.2f');renderDrawdown();chart('capital-chart','capital_deployed_cost','Capital deployed at cost · USD',',.2f');
    chart('exposure-chart','delta_dollar','Delta × 100 × stock · USD',',.2f');
    const attrs=Object.keys(names).map(s=>{const x=runs().find(v=>v.strategy===s);return{name:names[s],...x?.attribution};});
    table('attribution',attrs,[['name','Account'],['long_realized','Long realized',usd],['long_unrealized','Long unrealized',usd],['short_realized','Short realized',usd],['short_unrealized','Short unrealized',usd],['stock_realized','Stock realized',usd],['stock_unrealized','Stock unrealized',usd],['dividends','Dividends',usd],['option_commissions','Option fees (subtract)',usd],['stock_slippage','Stock slippage (subtract)',usd],['borrow_cost','Borrow (subtract)',usd]]);
    renderTrades();
  }
  const a=book.audit;
  const quality=blocked?[['Stock daily observations',a.stock?.rows],['Long-call probe rows',a.long_probe?.rows],['Dividend records',a.dividends?.records],['Expired search records',a.expired_search_records],['Old observed short IDs',a.old_cache?.contracts]]:[['Stock rows',a.stock_observations],['Option rows',a.option_observations],['Contracts',a.contracts],['Valid daily marks (before repair)',a.valid_option_marks]];
  $('quality').innerHTML=quality.map(([k,v])=>`<span>${esc(k)}<strong>${esc(v)}</strong></span>`).join('');
  const issues=a.blocking_issues??[];
  $('blockers').hidden=!issues.length;
  $('blockers').innerHTML='<strong>Data audit — unresolved</strong><ul>'+issues.map(x=>'<li>'+esc(x)+'</li>').join('')+'</ul>';
  $('coverage-note').textContent=blocked?'These are calendar-generated opportunities, NOT executed or rejected orders. Each row is explicitly “not_run” because the common dataset failed the audit. Monday holidays are still shifted to the first real session. No losing or missing week has been dropped.':'Every weekly opportunity appears, including skips, long-only periods, holiday shifts and unresolved obligations. Signal-target moneyness may differ from execution moneyness.';
  $('audit-detail').textContent=JSON.stringify(a,null,2);
  $('repair-note').textContent=(a.valuation_policy??'No supplemental quote policy recorded.')+' '+(a.quote_recheck_summary?`${a.quote_recheck_summary.checked} candidate-panel quotes rechecked; ${a.quote_recheck_summary.recovered} recovered, ${a.quote_recheck_summary.unresolved} unresolved. These are NOT held-account NAV-gap counts.`:'');
  table('repair-targets',a.original_gap_investigation??[],[['date','Original gap'],['id','Contract'],['mark_available','Recovered mark'],['source_timestamp','Actual source time'],['explanation','Evidence / limitation']]);
  const contracts=book.contract_catalogue??[];
  $('contract-scope').textContent=`${contracts.length} retained contracts; ${a.individually_verified_contracts??0} individually verified historical deliverables; ${a.assumption_contracts??0} source-supported standard-term assumptions. ${a.excluded_contracts?.length??0} excluded from acquisition or use. `+(a.candidate_universe??'');
  table('contract-table',contracts,[['id','Observed RIC'],['underlying','Underlying · derived'],['cp','Type · derived'],['strike','Strike · derived',usd],['expiry','Expiry · derived'],['scheduled_last_trading_date','Scheduled last trade · calendar'],['first_observed_quote_date','First observed quote'],['last_observed_quote_date','Last observed quote'],['multiplier','Multiplier · assumed'],['deliverable','Deliverable · assumed'],['standard_verified','Historically vendor-verified'],['terms_status','Terms status']]);
  table('exclusions',a.excluded_contracts??[],[['id','Identifier'],['reason','Reason'],['scope','Scope']]);
  $('versions').textContent=JSON.stringify({versions:book.versions,python:book.python,input_sha256:book.input_sha256,code_hashes:book.code_hashes},null,2);
  $('model').addEventListener('change',render);$('account').addEventListener('change',renderTrades);$('search').addEventListener('input',renderTrades);$('drawdown-view').addEventListener('change',renderDrawdown);
  render();
})();
