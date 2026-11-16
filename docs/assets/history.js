/* Observed-close evidence only. No returns, option fills or account balances inferred. */
(function (root) {
  'use strict';
  const names = ['BAC', 'KO', 'PFE', 'F'];
  const filters = ['trend', 'volatility', 'sudden_drop', 'combined'];
  const labels = ['Trend', 'HV20 ceiling', 'Five-day drop', 'All three'];
  const colors = ['#255b87', '#7796ad', '#acbdca', '#182b3a'];
  const pct = v => v === null ? 'Not evaluated' : (100 * v).toFixed(1) + '%';
  const countRate = (s, k) => `${s.pass_counts[k]} / ${s.evaluated_dates} (${pct(s.pass_rates[k])})`;
  function check(h) {
    if (h.kind !== 'historical_technical_signal_analysis' || h.source !== 'LSEG Data Platform') throw Error('Unverified historical provenance');
    for (const t of names) {
      const d = h.tickers[t];
      if (!d || !d.coverage || !Array.isArray(d.daily_rows)) throw Error('Missing stock evidence');
      for (const s of [d.daily, d.weekly, ...Object.values(d.by_year)]) {
        if (!Number.isInteger(s.evaluated_dates) || s.evaluated_dates < 0 || s.evaluated_dates + s.excluded_dates !== s.candidate_dates) throw Error('Invalid sample denominator');
        for (const k of filters) {
          const n = s.pass_counts[k], rate = s.pass_rates[k];
          if (!Number.isInteger(n) || n < 0 || n > s.evaluated_dates || (s.evaluated_dates ? !Number.isFinite(rate) || Math.abs(rate-n/s.evaluated_dates)>1e-10 : rate !== null)) throw Error('Invalid pass rate');
        }
      }
    }
    const j = h.joint_weekly;
    if (Object.values(j.distribution).reduce((a,b)=>a+b,0) !== j.evaluated_dates || j.evaluated_dates+j.excluded_dates !== j.candidate_dates) throw Error('Invalid joint denominator');
    return h;
  }
  function findings(h) {
    check(h);
    const n = names.reduce((a,t)=>a+h.tickers[t].weekly.evaluated_dates,0);
    if (!n) return ['Insufficient observed history for next-session eligibility. Missing dates are excluded, not counted as failed filters.'];
    const totals = filters.slice(0,3).map((k,i)=>({k,label:labels[i],fail:names.reduce((a,t)=>a+h.tickers[t].weekly.standalone_rejections[k],0),exclusive:names.reduce((a,t)=>a+h.tickers[t].weekly.exclusive_rejections[k],0)})).sort((a,b)=>b.fail-a.fail);
    const eligible = names.reduce((a,t)=>a+h.tickers[t].weekly.pass_counts.combined,0);
    const j = h.joint_weekly, top = totals[0];
    const years=Object.keys(h.tickers.BAC.by_year), earlier=years[1] || years[0], later=years.at(-1);
    return [
      `Across ${n} evaluable stock–entry-date pairs, ${eligible} (${pct(eligible/n)}) pass all three screens; ${n-eligible} otherwise possible stock-date opportunities are excluded before option or account checks. This measures reduced eligibility, not avoided losses or foregone dollar premiums.`,
      `${top.label} is the largest standalone restriction: ${top.fail} rejected stock-dates. It alone excludes ${top.exclusive}; removing only that filter, while leaving the others fixed, would restore those ${top.exclusive} opportunities. Standalone counts overlap and must not be added. ${totals.slice(1).map(x=>`${x.label}: ${x.fail} standalone / ${x.exclusive} exclusive rejections`).join('; ')}.`,
      `${j.multiple_eligible_dates} of ${j.evaluated_dates} fully observed next-session opportunities (${pct(j.evaluated_dates ? j.multiple_eligible_dates/j.evaluated_dates : null)}) have at least two eligible stocks. The engine can propose several names, subject to real option availability and account limits; lower HV20 wins only when cash or capacity is scarce. ${j.excluded_dates} dates lack a complete four-stock evaluation and are excluded from this comparison.`,
      `${names.map(t=>`${t}: ${countRate(h.tickers[t].weekly,'combined')}`).join('; ')}. Differences reflect this fixed universe and observed period, not proof that one company is a better investment. The year-by-year chart shows how often the current technical rules passed before weekly locks and capital allocation; partial calendar years are not full-year estimates.`,
      `From ${earlier} to the observed part of ${later}, combined next-session eligibility changed as follows: ${names.map(t=>`${t} ${pct(h.tickers[t].by_year[earlier].pass_rates.combined)} → ${pct(h.tickers[t].by_year[later].pass_rates.combined)}`).join('; ')}. Thus the rules do not impose a constant allocation across stocks or time. This is descriptive period variation, not evidence of forecasting skill or a comparison of equal-length investment returns.`
    ];
  }
  const api = {check, findings, countRate};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.WheelHistory = api;
  if (typeof document === 'undefined') return;
  const byId = id => document.getElementById(id);
  function paragraph(parent, text) { const p=document.createElement('p'); p.textContent=text; parent.append(p); }
  function rows(id, data) {
    const body=byId(id); body.replaceChildren();
    for (const values of data) { const tr=document.createElement('tr'); values.forEach((v,i)=>{const td=document.createElement(i===0?'th':'td');td.textContent=String(v);tr.append(td);});body.append(tr); }
  }
  function plot(id, traces, extra={}) {
    const target=byId(id);
    if (!root.Plotly) { target.textContent='Chart library unavailable. The observed counts remain available in the tables and downloads.'; return; }
    Promise.resolve(root.Plotly.react(target,traces,{autosize:true,height:340,margin:{l:48,r:15,t:25,b:70},paper_bgcolor:'#ffffff',plot_bgcolor:'#ffffff',font:{family:'system-ui',color:'#182b3a',size:12},colorway:colors,legend:{orientation:'h',y:-0.24},...extra},{responsive:true,displayModeBar:false})).then(()=>{
      if (target.offsetWidth && root.Plotly.Plots) root.Plotly.Plots.resize(target);
    });
  }
  function showHistory(h) {
    check(h);
    byId('history-status').textContent=`${h.status === 'complete' ? 'Complete observed-close coverage' : 'Partial observed-close coverage'} · ${h.window.analysis_start} to ${h.window.analysis_end}. ${h.window.warmup_sessions_requested} earlier exchange sessions requested for warm-up; excluded from reported sample counts. Retrieved ${h.market_retrieved_at}. ${h.matches_latest_market_attempt ? 'Matches the latest retained market evaluation.' : 'Retained evidence, not a successful update from the latest attempt.'}`;
    const gaps=names.filter(t=>h.tickers[t].coverage.missing_dates.length).map(t=>{const d=h.tickers[t].coverage.missing_dates;return `${t}: ${d.length} missing (${d.slice(0,3).join(', ')}${d.length>3?', …; all dates in JSON':''})`;});
    if(gaps.length)byId('history-status').textContent+=' No observed close on: '+gaps.join('; ')+'. Requested dates never replace the dates actually returned by LSEG.';
    rows('history-coverage',names.map(t=>{const d=h.tickers[t],c=d.coverage;return[t,`${c.first_observed ?? 'None'} → ${c.last_observed ?? 'None'}`,`${c.observed_sessions} / ${c.expected_sessions}`,`${c.observed_warmup_closes} / ${c.requested_warmup_closes}`,`${d.daily.evaluated_dates} / ${d.daily.candidate_dates}`,`${d.weekly.evaluated_dates} / ${d.weekly.candidate_dates}`];}));
    rows('history-weekly',names.map(t=>[t,...filters.map(k=>countRate(h.tickers[t].weekly,k)),h.tickers[t].weekly.excluded_dates]));
    rows('history-daily',names.map(t=>[t,...filters.map(k=>countRate(h.tickers[t].daily,k)),h.tickers[t].daily.excluded_dates]));
    rows('history-overlap',names.map(t=>{const s=h.tickers[t].weekly;return[t,...filters.slice(0,3).map(k=>`${s.standalone_rejections[k]} / ${s.exclusive_rejections[k]}`)];}));
    const years=Object.keys(h.tickers.BAC.by_year);
    rows('history-years',years.map(y=>[y,...names.map(t=>countRate(h.tickers[t].by_year[y],'combined'))]));
    const narrative=byId('history-findings'); narrative.replaceChildren();findings(h).forEach(s=>paragraph(narrative,s));
    plot('history-filter-chart',filters.map((k,i)=>({type:'bar',name:labels[i],x:names,y:names.map(t=>h.tickers[t].weekly.pass_rates[k]===null?null:h.tickers[t].weekly.pass_rates[k]*100),marker:{color:colors[i]},hovertemplate:'%{x}: %{y:.1f}%<extra>'+labels[i]+'</extra>'})),{barmode:'group',yaxis:{title:'Next-session pass rate (%)',range:[0,100]}});
    plot('history-year-chart',names.map((t,i)=>({type:'bar',name:t,x:years,y:years.map(y=>{const r=h.tickers[t].by_year[y].pass_rates.combined;return r===null?null:r*100;}),marker:{color:colors[i]},hovertemplate:'%{x}: %{y:.1f}%<extra>'+t+'</extra>'})),{barmode:'group',xaxis:{type:'category'},yaxis:{title:'Combined next-session pass rate (%)',range:[0,100]}});
    const drawSeries = () => {
      const t=byId('history-ticker').value,d=h.tickers[t].daily_rows,x=d.map(r=>r.signal_date);
      const trace=(key,name,axis,color)=>({type:'scatter',mode:'lines',name,x,y:d.map(r=>r[key]),yaxis:axis,connectgaps:false,line:{width:1.6,color},hovertemplate:'%{x}<br>%{y:.3f}<extra>'+name+'</extra>'});
      plot('history-series',[trace('close','Close','y',colors[0]),trace('sma20','SMA20','y',colors[1]),trace('sma50','SMA50','y',colors[3]),trace('hv20','HV20','y2',colors[0]),trace('r5','5-day return','y3',colors[0])],{height:640,hovermode:'x unified',margin:{l:58,r:15,t:20,b:70},legend:{orientation:'h',y:-0.1},xaxis:{anchor:'y3'},yaxis:{domain:[.70,1],title:'USD'},yaxis2:{domain:[.35,.60],title:'HV20',tickformat:'.0%'},yaxis3:{domain:[0,.25],title:'R5',tickformat:'.0%'},shapes:[{type:'line',xref:'paper',x0:0,x1:1,yref:'y2',y0:.45,y1:.45,line:{color:'#825d32',dash:'dot'}},{type:'line',xref:'paper',x0:0,x1:1,yref:'y3',y0:-.08,y1:-.08,line:{color:'#825d32',dash:'dot'}}]});
    };
    byId('history-ticker').addEventListener('change',drawSeries);drawSeries();
    const disclosure=byId('history-series').closest?.('details');
    disclosure?.addEventListener('toggle',()=>{if(disclosure.open)drawSeries();});
  }
  async function get(path) { const r=await fetch(path,{cache:'no-store'});if(!r.ok)throw Error(`HTTP ${r.status}`);return r.json(); }
  get('data/historical_signals.json').then(showHistory).catch(()=>{byId('history-status').textContent='Historical evidence unavailable or inconsistent. No counts or performance results are inferred.';});
  get('data/entry_demo_status.json').then(d=>{
    const box=byId('weekly-entry-demo');
    if(d.mode!=='demonstration'||d.production_orders_changed!==false||d.snapshot_file!=='entry_example_market.json'||d.calendar.first_session_of_week!==true)throw Error('Unverified example');
    box.replaceChildren();
    // Archive is a dated first-session example, never passed off as this evening's orders.
    paragraph(box,`Archived real LSEG snapshot: ${d.calendar.as_of}; target session ${d.calendar.target_session}. Independent hypothetical $40,000 cash-start account. These are historical demonstration proposals, not current orders or fills.`);
    const a=d.scenarios.find(s=>s.id==='cash_start');
    if(a.status!=='success'||!Array.isArray(a.proposed_orders)||a.order_count!==a.proposed_orders.length)throw Error('Invalid example');
    paragraph(box,`Cash-start example: ${a.order_count} proposals. ${a.decisions.map(r=>`${r.ticker}: ${r.decision} — ${r.reasons.join('; ')}`).join(' · ')}`);
  }).catch(()=>{byId('weekly-entry-demo').textContent='Archived example not verified; see its downloadable audit. No production orders are inferred.';});
})(typeof window !== 'undefined' ? window : globalThis);
