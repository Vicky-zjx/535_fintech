/* Observed-close evidence only. No returns, option fills or account balances inferred. */
(function (root) {
  'use strict';
  const names = ['BAC', 'KO', 'PFE', 'F'];
  const filters = ['trend', 'volatility', 'sudden_drop', 'combined'];
  const labels = ['Trend', 'HV20 ceiling', 'Five-day drop', 'All three'];
  const colors = ['#255b87', '#7796ad', '#acbdca', '#182b3a'];
  const ranges = { '1M': 1, '3M': 3, '1Y': 12, '3Y': 36 };
  const datePattern = /^\d{4}-\d{2}-\d{2}$/;
  const pct = v => v === null ? 'Not evaluated' : (100 * v).toFixed(1) + '%';
  const countRate = (s, k) => `${s.pass_counts[k]} / ${s.evaluated_dates} (${pct(s.pass_rates[k])})`;
  function check(h) {
    if (h.kind !== 'historical_technical_signal_analysis' || h.source !== 'LSEG Data Platform') throw Error('Unverified historical provenance');
    if (!datePattern.test(h.window?.analysis_start) || !datePattern.test(h.window?.analysis_end) || h.window.analysis_start > h.window.analysis_end) throw Error('Invalid historical window');
    for (const t of names) {
      const d = h.tickers[t];
      if (!d || !d.coverage || !Array.isArray(d.daily_rows)) throw Error('Missing stock evidence');
      if (d.daily_rows.length !== d.coverage.expected_sessions) throw Error('Missing session rows; do not connect across absent observations');
      let previous = '';
      for (const r of d.daily_rows) {
        if (!datePattern.test(r.signal_date) || r.signal_date <= previous || r.signal_date < h.window.analysis_start || r.signal_date > h.window.analysis_end) throw Error('Invalid/unsorted observation date');
        previous = r.signal_date;
        for (const k of ['close','sma20','sma50','hv20','r5']) {
          if (r[k] !== null && (!Number.isFinite(r[k]) || (['close','sma20','sma50'].includes(k) && r[k] <= 0) || (k === 'hv20' && r[k] < 0))) throw Error('Invalid observed value');
        }
      }
      for (const s of [d.daily, d.weekly, ...Object.values(d.by_year)]) {
        if (!Number.isInteger(s.evaluated_dates) || s.evaluated_dates < 0 || s.evaluated_dates + s.excluded_dates !== s.candidate_dates) throw Error('Invalid sample denominator');
        for (const k of filters) {
          const n = s.pass_counts[k], rate = s.pass_rates[k];
          if (!Number.isInteger(n) || n < 0 || n > s.evaluated_dates || (s.evaluated_dates ? !Number.isFinite(rate) || Math.abs(rate-n/s.evaluated_dates)>1e-10 : rate !== null)) throw Error('Invalid pass rate');
        }
      }
      // Cross-check displayed pass counts against the saved evaluated rows.
      for (const [s, rows] of [[d.daily,d.daily_rows],[d.weekly,d.weekly_rows]]) {
        if (!Array.isArray(rows) || rows.length !== s.candidate_dates) throw Error('Missing eligibility observations');
        const valid = rows.filter(r=>r.valid === true);
        if (valid.length !== s.evaluated_dates) throw Error('Evaluated count differs from saved rows');
        for (const k of filters) {
          if (valid.some(r=>typeof r[k === 'combined' ? 'eligible' : k] !== 'boolean') ||
              valid.filter(r=>r[k === 'combined' ? 'eligible' : k]).length !== s.pass_counts[k]) throw Error('Pass counts differ from saved rows');
        }
        for (const k of filters.slice(0,3)) {
          if (valid.filter(r=>!r[k]).length !== s.standalone_rejections[k] ||
              valid.filter(r=>!r[k] && filters.slice(0,3).every(other=>other === k || r[other])).length !== s.exclusive_rejections[k]) throw Error('Rejection counts differ from saved rows');
        }
      }
    }
    const j = h.joint_weekly;
    if (Object.values(j.distribution).reduce((a,b)=>a+b,0) !== j.evaluated_dates || j.evaluated_dates+j.excluded_dates !== j.candidate_dates) throw Error('Invalid joint denominator');
    return h;
  }
  function restrictionStats(h) {
    const n = names.reduce((a,t)=>a+h.tickers[t].weekly.evaluated_dates,0);
    return filters.slice(0,3).map((k,i)=>({key:k,label:labels[i],evaluated:n,
      standalone:names.reduce((a,t)=>a+h.tickers[t].weekly.standalone_rejections[k],0),
      exclusive:names.reduce((a,t)=>a+h.tickers[t].weekly.exclusive_rejections[k],0)}));
  }
  function selectRange(h, ticker, range) {
    if (!names.includes(ticker) || !Object.hasOwn(ranges,range)) throw Error('Unknown stock/date range');
    const end = h.window.analysis_end, anchor = new Date(end+'T00:00:00Z');
    const cutoff = new Date(Date.UTC(anchor.getUTCFullYear(),anchor.getUTCMonth()-ranges[range],1));
    cutoff.setUTCDate(Math.min(anchor.getUTCDate(),new Date(Date.UTC(cutoff.getUTCFullYear(),cutoff.getUTCMonth()+1,0)).getUTCDate()));
    const start = range === '3Y' ? h.window.analysis_start : [h.window.analysis_start,cutoff.toISOString().slice(0,10)].sort().at(-1);
    return {start,end,rows:h.tickers[ticker].daily_rows.filter(r=>r.signal_date >= start && r.signal_date <= end)};
  }
  function seriesCharts(h, ticker, range) {
    const selected=selectRange(h,ticker,range), x=selected.rows.map(r=>r.signal_date);
    const trace=(key,name,color,dash='solid')=>({type:'scatter',mode:'lines',name,x:[...x],
      y:selected.rows.map(r=>r[key]),connectgaps:false,line:{width:2,color,dash},
      hovertemplate:'%{x|%b %d, %Y}<br>'+name+': '+(key==='hv20'||key==='r5'?'%{y:.2%}':'$%{y:.2f}')+'<extra></extra>'});
    const xaxis={type:'date',range:[selected.start,selected.end],nticks:5,tickformat:range==='1M'||range==='3M'?'%b %d':'%b %Y',automargin:true};
    const layout={hovermode:'x unified',xaxis,margin:{l:55,r:18,t:28,b:75},
      legend:{orientation:'h',x:0,y:-.22,font:{size:12}},uirevision:ticker+'-'+range};
    const threshold=(value,label)=>({shapes:[{type:'line',xref:'paper',x0:0,x1:1,yref:'y',y0:value,y1:value,line:{color:'#825d32',width:1.6,dash:'dash'}}],
      annotations:[{xref:'paper',x:1,yref:'y',y:value,text:label,showarrow:false,xanchor:'right',yanchor:'bottom',bgcolor:'rgba(255,255,255,0.9)',font:{color:'#825d32',size:11}}]});
    const hv=selected.rows.map(r=>r.hv20).filter(Number.isFinite), r5=selected.rows.map(r=>r.r5).filter(Number.isFinite);
    return {selected,charts:[
      {id:'history-price-chart',traces:[trace('close','Close',colors[0]),trace('sma20','SMA20','#38756c','dot'),trace('sma50','SMA50','#946d38','dash')],
       layout:{...layout,height:380,yaxis:{title:{text:'Price (USD)'},tickprefix:'$',automargin:true}}},
      {id:'history-hv-chart',traces:[trace('hv20','HV20',colors[0])],layout:{...layout,showlegend:false,
       yaxis:{title:{text:'Annualized HV20'},tickformat:'.0%',range:[0,Math.max(.50,...hv.map(v=>v*1.08))],automargin:true},...threshold(.45,'45% ceiling')}},
      {id:'history-r5-chart',traces:[trace('r5','Five-day return',colors[0])],layout:{...layout,showlegend:false,
       yaxis:{title:{text:'Five-day return'},tickformat:'.0%',range:[Math.min(-.10,...r5.map(v=>v*1.12)),Math.max(.02,...r5.map(v=>v*1.12))],zeroline:true,zerolinecolor:'#b5c4cf',automargin:true},...threshold(-.08,'−8% floor')}}
    ]};
  }
  function alignment(h,s) {
    if (!s || s.status !== 'success' || h.market_snapshot_sha256 !== s.market_snapshot_sha256 || h.market_retrieved_at !== s.market_data_retrieved_at || h.strategy_revision !== s.strategy_revision || h.window.analysis_end !== s.calendar?.as_of)
      return 'Historical evidence retained with its own dates; it does not match a verified latest successful evaluation. No newer values are inferred.';
    for (const ticker of names) {
      const row=h.tickers[ticker].daily_rows.at(-1), d=s.decisions?.find(r=>r.ticker===ticker);
      if (!row || row.signal_date !== h.window.analysis_end || !d || d.price_date !== row.signal_date || ['close','sma20','sma50','hv20','r5'].some(k=>!Number.isFinite(d[k]) || !Number.isFinite(row[k]) || Math.abs(d[k]-row[k])>1e-10*Math.max(1,Math.abs(row[k]))))
        return 'Source snapshot agrees, but at least one latest indicator is unavailable or inconsistent. Historical charts are not a complete current-signal reconciliation.';
    }
    return `Verified against the latest successful run: same market snapshot hash, retrieval time (${h.market_retrieved_at}), strategy revision and ${h.window.analysis_end} closing indicators for all four stocks. Historical file generated ${h.generated_at}; next order session ${s.calendar.target_session}.`;
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
  const api = {check, findings, countRate, restrictionStats, selectRange, seriesCharts, alignment};
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
    try {
      Promise.resolve(root.Plotly.react(target,traces,{autosize:true,height:340,margin:{l:48,r:15,t:25,b:80},paper_bgcolor:'#ffffff',plot_bgcolor:'#ffffff',font:{family:'system-ui',color:'#182b3a',size:12},colorway:colors,legend:{orientation:'h',y:-0.24},...extra},{responsive:true,displayModeBar:false})).catch(()=>{
        target.textContent='Chart could not render. The validated observations remain in the tables and downloadable JSON/CSV.';
      });
    } catch (_) {target.textContent='Chart could not render. See the validated JSON/CSV; no values are substituted.';}
  }
  function showHistory(h) {
    check(h);
    byId('history-status').textContent=`${h.status === 'complete' ? 'Complete observed-close coverage' : 'Partial observed-close coverage'} · ${h.window.analysis_start} to ${h.window.analysis_end}. ${h.window.warmup_sessions_requested} earlier exchange sessions requested for warm-up; excluded from reported sample counts. LSEG retrieved ${h.market_retrieved_at}.`;
    get('data/strategy_status.json').then(s=>{byId('history-alignment').textContent=alignment(h,s);}).catch(()=>{
      byId('history-alignment').textContent='Latest-run status unavailable; historical evidence retains its own source timestamp. Alignment is not assumed.';
    });
    const gaps=names.filter(t=>h.tickers[t].coverage.missing_dates.length).map(t=>{const d=h.tickers[t].coverage.missing_dates;return `${t}: ${d.length} missing (${d.slice(0,3).join(', ')}${d.length>3?', …; all dates in JSON':''})`;});
    if(gaps.length)byId('history-status').textContent+=' No observed close on: '+gaps.join('; ')+'. Requested dates never replace the dates actually returned by LSEG.';
    rows('history-coverage',names.map(t=>{const d=h.tickers[t],c=d.coverage;return[t,`${c.first_observed ?? 'None'} → ${c.last_observed ?? 'None'}`,`${c.observed_sessions} / ${c.expected_sessions}`,`${c.observed_warmup_closes} / ${c.requested_warmup_closes}`,`${d.daily.evaluated_dates} / ${d.daily.candidate_dates}`,`${d.weekly.evaluated_dates} / ${d.weekly.candidate_dates}`];}));
    rows('history-weekly',names.map(t=>[t,...filters.map(k=>countRate(h.tickers[t].weekly,k)),h.tickers[t].weekly.excluded_dates]));
    rows('history-daily',names.map(t=>[t,...filters.map(k=>countRate(h.tickers[t].daily,k)),h.tickers[t].daily.excluded_dates]));
    rows('history-overlap',names.map(t=>{const s=h.tickers[t].weekly;return[t,...filters.slice(0,3).map(k=>`${s.standalone_rejections[k]} / ${s.exclusive_rejections[k]}`)];}));
    rows('history-restrictions',restrictionStats(h).map(r=>[r.label,`${r.standalone} / ${r.evaluated} (${pct(r.evaluated?r.standalone/r.evaluated:null)})`,r.exclusive]));
    const entry=h.tickers.BAC.weekly_rows;
    byId('history-comparison-note').textContent=`Full sample: ${h.window.analysis_start} to ${h.window.analysis_end}, independent of the controls above. Pass rates use next-session opportunity dates; their prior-close signals run from ${entry[0]?.signal_date || 'unavailable'} to ${entry.at(-1)?.signal_date || 'unavailable'}. The time-series charts instead use closing-observation dates, including ${h.window.analysis_end}. Neither count represents filled option trades.`;
    const years=Object.keys(h.tickers.BAC.by_year);
    rows('history-years',years.map(y=>[y,...names.map(t=>countRate(h.tickers[t].by_year[y],'combined'))]));
    const narrative=byId('history-findings'); narrative.replaceChildren();findings(h).forEach(s=>paragraph(narrative,s));
    plot('history-filter-chart',filters.map((k,i)=>({type:'bar',name:labels[i],x:names,y:names.map(t=>h.tickers[t].weekly.pass_rates[k]===null?null:h.tickers[t].weekly.pass_rates[k]*100),customdata:names.map(t=>[h.tickers[t].weekly.pass_counts[k],h.tickers[t].weekly.evaluated_dates]),marker:{color:colors[i]},hovertemplate:'%{x}: %{y:.1f}%<br>%{customdata[0]} / %{customdata[1]} opportunities<extra>'+labels[i]+'</extra>'})),{barmode:'group',yaxis:{title:{text:'Technical pass rate (%)'},range:[0,100],automargin:true}});
    plot('history-year-chart',names.map((t,i)=>({type:'bar',name:t,x:years,y:years.map(y=>{const r=h.tickers[t].by_year[y].pass_rates.combined;return r===null?null:r*100;}),marker:{color:colors[i]},hovertemplate:'%{x}: %{y:.1f}%<extra>'+t+'</extra>'})),{barmode:'group',xaxis:{type:'category'},yaxis:{title:{text:'All three pass (%)'},range:[0,100],automargin:true}});
    const drawSeries = () => {
      const t=byId('history-ticker').value, range=byId('history-range').value;
      const {selected,charts}=seriesCharts(h,t,range), r=selected.rows;
      byId('history-price-title').textContent=`${t} · Close, SMA20 and SMA50`;
      byId('history-hv-title').textContent=`${t} · HV20 realized volatility`;
      byId('history-r5-title').textContent=`${t} · Five-day stock return`;
      byId('history-range-note').textContent=`${t} · ${range} · ${r[0]?.signal_date || selected.start} to ${r.at(-1)?.signal_date || selected.end} · ${r.length} session rows. Missing close / HV20 / R5: ${['close','hv20','r5'].map(k=>r.filter(v=>v[k]===null).length).join(' / ')}. Range ends at the dataset's last completed session, not today's date. No interpolation or forward fill.`;
      charts.forEach(c=>plot(c.id,c.traces,c.layout));
    };
    byId('history-ticker').addEventListener('change',drawSeries);
    byId('history-range').addEventListener('change',drawSeries);drawSeries();
    if (root.ResizeObserver && root.Plotly?.Plots) {
      const observer=new root.ResizeObserver(entries=>{entries.forEach(({target})=>{if(target.offsetWidth)root.Plotly.Plots.resize(target);});});
      for (const id of ['history-price-chart','history-hv-chart','history-r5-chart','history-filter-chart','history-year-chart']) observer.observe(byId(id));
    }
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
