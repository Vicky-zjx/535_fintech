/* Render the Python engine's baked result. No separate price or account series. */
"use strict";
(() => {
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? "—").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const money = value => value == null ? "—" : new Intl.NumberFormat("en-US", {style:"currency",currency:"USD",maximumFractionDigits:2}).format(value);
  const price = value => value == null ? "—" : Number(value).toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:4});
  const pct = value => value == null ? "—" : `${(100*value).toFixed(2)}%`;
  const stamp = value => value ? `${value.slice(0,10)} ${value.slice(11,16)} ET` : "—";
  const showFailure = message => { if ($("failure")) { $("failure").hidden=false; $("failure").textContent=message; } };
  const b=window.COVERED_CALL_BOOK;
  if (!b || !b.metadata || b.metadata.source!=="LSEG" || b.metadata.synthetic!==false) {
    showFailure("The real cached backtest could not be loaded. Rebuild book.js from the verified LSEG cache; this page does not substitute example data.");
    return;
  }
  const {metrics:m,config:c,ledger,blotter,validation:v}=b;

  function download(name,body,type) {
    const url=URL.createObjectURL(new Blob([body],{type}));
    const a=document.createElement("a"); a.href=url; a.download=name; a.click();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  function csv(name,rows) {
    if(!rows.length)return;
    const keys=[...new Set(rows.flatMap(row=>Object.keys(row)))];
    const cell=value=>'"'+String(value??"").replace(/"/g,'""')+'"';
    download(name,[keys.map(cell).join(","),...rows.map(row=>keys.map(k=>cell(row[k])).join(","))].join("\r\n"),"text/csv;charset=utf-8");
  }
  function table(rows,columns) {
    if(!rows.length)return '<div class="empty">No records for this selection.</div>';
    return `<table><thead><tr>${columns.map(col=>`<th scope="col" class="${col[3]||""}">${esc(col[1])}</th>`).join("")}</tr></thead><tbody>${rows.map(row=>`<tr>${columns.map(col=>`<td class="${col[3]||""}">${col[2]?col[2](row[col[0]],row):esc(row[col[0]])}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
  }
  const strikes = values => values?.length ? esc(values.map(price).join(', ')) : 'None observed';
  const decisionCols=[['timestamp','Entry timestamp',x=>esc(stamp(x))],['outcome','Outcome'],
    ['spot','Stock print',x=>esc(price(x)),'num'],['target','5% target',x=>esc(price(x)),'num'],
    ['observed_strikes','Observed strikes by entry',strikes,'note'],
    ['eligible_strikes','Observed strikes ≥ target',strikes,'note'],
    ['selected_strike','Selected strike',x=>esc(price(x)),'num'],['expiry','Expiry'],
    ['selected_first_observed_at','First evidence for selected RIC',x=>esc(stamp(x))],
    ['ric','Selected RIC'],['reason','Decision / skip reason',null,'note']];

  if ($("data-provenance")) {
    $("data-provenance").textContent=JSON.stringify({source:b.metadata.source,fetched_at:b.metadata.fetched_at,stock_bars:b.metadata.stock_bars,option_bars:b.metadata.option_bars,cache_sha256:b.metadata.cache_sha256,bar_minutes:c.bar_minutes,timestamp_normalization:b.metadata.timestamp_normalization,ric_day_convention:b.metadata.ric_day_convention},null,2);
    $("connection-status").textContent="Data connection required";
    $("connection-detail").textContent=location.hostname.endsWith("github.io") ? "GitHub Pages displays the cached backtest. A live LSEG pull runs locally with your own logged-in Workspace session." : "The published result is already available from book.js. Use the separate local Python utility below to fetch a new real dataset.";
    $("download-book").onclick=()=>download("covered-call-result.json",JSON.stringify(b,null,2),"application/json");
    $("universe-limit").textContent=b.universe.limitation;
    $("universe-acquisition").textContent=b.universe.acquisition_limitation;
    $("universe-count").textContent=`${b.universe.contract_count} distinct observed contracts in the retained LSEG cache. Each Monday uses only that Friday’s contracts with evidence available by entry.`;
    $("universe-weekly").innerHTML=table(b.decisions,decisionCols);
    $("universe-contracts").innerHTML=table(b.universe.contracts,[['ric','Observed RIC'],['expiry','Expiry'],['strike','Actual strike',x=>esc(price(x)),'num'],['first_observed_at','First observed bar end',x=>esc(stamp(x))]]);
    $("download-universe").onclick=()=>download('observed-option-universe.json',JSON.stringify(b.universe,null,2),'application/json');
    const probe=b.universe.discovery_probe;
    $("discovery-result").textContent=probe ? `LSEG Search probe ${probe.queried_at}: ${probe.opra_rows} OPRA call records; returned expiries: ${Object.entries(probe.opra_expiry_counts).map(([day,n])=>`${day} (${n})`).join(', ')}. This is not a historical chain snapshot and is not used to establish earlier Monday eligibility.` : 'No complete historical point-in-time chain is attached. The backtest uses only its documented observed cache.';
    return;
  }

  $("source-badge").textContent="REAL LSEG DATA · SIMULATED FILLS";
  $("period").textContent=`${c.start} — ${c.end}`;
  $("entry-summary").textContent=`${c.bar_minutes}-minute bars · Monday ${c.entry_time} New York`;
  if(b.status!=="complete")showFailure(`Incomplete run: ${b.status}. Results below stop at the last auditable state.`);

  const metricCards=[
    ["Starting NAV",money(m.starting_nav),"Configured initial cash"],
    ["Ending NAV",money(m.ending_nav),`${m.ending_shares} shares · ${Math.abs(m.ending_short_calls)} short calls`],
    ["Account return",pct(m.total_return),"Before dividends, fees & financing"],
    ["Premium collected",money(m.premium_collected),`${m.calls_sold} calls sold at quoted midpoints`]
  ];
  $("metrics").innerHTML=metricCards.map((x,i)=>`<article class="metric"><div class="metric-label">${esc(x[0])}</div><div class="metric-value ${i===2?(m.total_return>=0?'positive':'negative'):''}">${esc(x[1])}</div><div class="metric-note">${esc(x[2])}</div></article>`).join("");
  $("secondary-metrics").innerHTML=[["Expired OTM / ATM",m.expired],["Assigned ITM",m.assigned],["Skipped weeks",m.skipped_weeks],["Assignment rate",pct(m.assignment_rate)],["Max drawdown",pct(m.max_drawdown)]].map(x=>`<span>${esc(x[0])}<strong>${esc(x[1])}</strong></span>`).join("");
  $("result-note").textContent=`Ending cash ${money(m.ending_cash)}. Unrealized stock gains or losses remain in NAV; holding shares at the end is not a forced sale. ${m.ending_cash<0?'Negative cash is a margin debit. Financing interest is excluded, so this is a gross, price-only result.':''}`;
  $("audit-note").textContent=`${b.audit.passed?'Reconciled':'Audit failed'}: ${b.audit.booked_events} booked events · ${b.audit.ledger_rows} ledger states · ${m.margin_breach_rows} margin-breach states. Cash is reconciled to every blotter cash delta.`;

  const blotterCols=[
    ['timestamp','Timestamp',x=>esc(stamp(x))],['instrument','Instrument'],
    ['action','Action',x=>`<span class="action ${esc(x)}">${esc(x)}</span>`],['quantity','Qty',null,'num'],
    ['strike','Strike',x=>esc(price(x)),'num'],['expiry','Expiry'],
    ['limit_price','Limit',x=>esc(price(x)),'num'],['fill_price','Fill',x=>esc(price(x)),'num'],
    ['cash_delta','Cash Δ',x=>esc(money(x)),'num'],['cash_after','Cash after',x=>esc(money(x)),'num'],
    ['note','Rule / explanation',null,'note']
  ];
  function renderBlotter(){const f=$("action-filter").value;const rows=blotter.filter(r=>f==='ALL'||r.action===f);$("blotter-table").innerHTML=table(rows,blotterCols);$("blotter-count").textContent=`${rows.length} of ${blotter.length} booked events`;}
  $("action-filter").onchange=renderBlotter;renderBlotter();
  $("skips-summary").textContent=`Weekly decisions · ${m.skipped_weeks} skipped weeks`;
  $("decisions-table").innerHTML=table(b.decisions,decisionCols);

  const ledgerCols=[['timestamp','Timestamp',x=>esc(stamp(x))],['phase','State'],
    ['cash','Cash',x=>esc(money(x)),'num'],['shares','Shares',null,'num'],['stock_mark','Stock mark',x=>esc(price(x)),'num'],
    ['lmv','Stock MV / LMV',x=>esc(money(x)),'num'],['short_call_quantity','Short qty',null,'num'],
    ['call_ric','Call RIC'],['call_strike','Strike',x=>esc(price(x)),'num'],['call_expiry','Expiry'],
    ['option_mark','Option mark',x=>esc(price(x)),'num'],['option_mv','Option MV',x=>esc(money(x)),'num'],
    ['nav','NAV',x=>esc(money(x)),'num'],['initial_margin','Initial',x=>esc(money(x)),'num'],
    ['maintenance_margin','Maintenance',x=>esc(money(x)),'num'],['available_funds','Available',x=>esc(money(x)),'num'],
    ['excess','Excess',x=>esc(money(x)),'num'],['stock_mark_timestamp','Stock mark time',x=>esc(stamp(x))],
    ['option_mark_timestamp','Option mark time',x=>esc(stamp(x))],
    ['stock_mark_stale','Stale stock',x=>x?'Yes':'No'],['option_mark_stale','Stale call',x=>x?'Yes':'No'],['margin_breach','Margin breach',x=>x?'Yes':'No']];
  let page=0;
  function renderLedger(){let rows=ledger;const f=$("ledger-filter").value;if(f==='events')rows=rows.filter(r=>r.event_id);if(f==='stale')rows=rows.filter(r=>r.stock_mark_stale||r.option_mark_stale);if(f==='breaches')rows=rows.filter(r=>r.margin_breach);const pages=Math.max(1,Math.ceil(rows.length/25));page=Math.max(0,Math.min(page,pages-1));$("ledger-table").innerHTML=table(rows.slice(page*25,page*25+25),ledgerCols);$("ledger-page").textContent=`${page+1} / ${pages} · ${rows.length} states`;$("ledger-prev").disabled=page===0;$("ledger-next").disabled=page===pages-1;}
  $("ledger-filter").onchange=()=>{page=0;renderLedger();};$("ledger-prev").onclick=()=>{page--;renderLedger();};$("ledger-next").onclick=()=>{page++;renderLedger();};renderLedger();
  function inspect(index){const row=ledger[index];$("state-slider").value=index;$("state-time").textContent=`${stamp(row.timestamp)} · ${row.phase.replaceAll('_',' ')}`;$("state-values").innerHTML=[['Cash',money(row.cash)],['Shares',row.shares],['Short calls',row.short_call_quantity],['NAV',money(row.nav)],['Available funds',money(row.available_funds)],['Excess',money(row.excess)]].map(([k,v])=>`<div><small>${esc(k)}</small><strong>${esc(v)}</strong></div>`).join('');$("state-marks").textContent=`Stock mark ${price(row.stock_mark)} from ${stamp(row.stock_mark_timestamp)}${row.stock_mark_stale?' (STALE)':''}. ${row.call_ric?`Call ${row.call_ric}: mark ${price(row.option_mark)} from ${stamp(row.option_mark_timestamp)}${row.option_mark_stale?' (STALE)':''}.`:'No open short call.'}`;}
  $("state-slider").max=Math.max(0,ledger.length-1);$("state-slider").oninput=e=>inspect(Number(e.target.value));inspect(ledger.length-1);

  const fit=v.fit;
  $("fit-stats").innerHTML=`<strong class="r2">R² ${fit?fit.r2.toFixed(4):'unavailable'}</strong><span>${v.count.toLocaleString()} actual pairs</span><span>${fit?`Trade = ${fit.slope.toFixed(4)} × mid ${fit.intercept<0?'−':'+'} ${Math.abs(fit.intercept).toFixed(4)}`:'Insufficient variation for a regression'}</span>`;
  $("fit-note").textContent=fit?`Median |mid − print| is $${fit.median_abs_gap.toFixed(4)}. R² measures association across the sampled quotes and prints, not the probability of a fill at mid. The bar’s last trade and closing quote may occur at different instants; queue position and market impact are not observed.`:'There are insufficient valid paired observations to estimate a regression. A missing trade print has not been filled in.';
  $("analysis-cards").innerHTML=b.analysis.map(x=>`<article><h3>${esc(x.title)}</h3><p>${esc(x.text)}</p></article>`).join('');
  $("method-notes").innerHTML=b.methodology.map(x=>`<article><h3>${esc(x.title)}</h3><p>${esc(x.text)}</p></article>`).join('');
  $("download-book").onclick=()=>download('covered-call-result.json',JSON.stringify(b,null,2),'application/json');
  $("download-blotter").onclick=()=>csv('covered-call-blotter.csv',blotter);
  $("download-ledger").onclick=()=>csv('covered-call-ledger.csv',ledger);

  if(!window.Plotly){showFailure('Chart library did not load. The real ledger and blotter remain visible; reload the page or check assets/plotly.min.js.');return;}
  const small=window.innerWidth<600;
  const base={paper_bgcolor:'#ffffff',plot_bgcolor:'#ffffff',font:{family:'-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif',size:12,color:'#182c38'},margin:{l:small?58:74,r:22,t:55,b:64},height:small?405:470,hovermode:'x unified',legend:{orientation:'h',x:0,y:1.13,font:{size:11}},xaxis:{gridcolor:'#edf0f0',zeroline:false},yaxis:{gridcolor:'#e6ebeb',zeroline:false,tickprefix:'$',tickformat:',.0f'},hoverlabel:{bgcolor:'#fff',font:{color:'#182c38',size:12}}};
  const pc={responsive:true,displaylogo:false,scrollZoom:false,modeBarButtonsToRemove:['lasso2d','select2d']};
  const endStates=new Map();ledger.forEach((row,i)=>endStates.set(row.timestamp,{row,index:i}));
  const series=[...endStates.values()];
  const navTraces=[['nav','NAV','#167765',2.8],['initial_margin','Initial margin','#3973a3',1.6],['maintenance_margin','Maintenance','#b55037',1.6],['available_funds','Available funds','#8b6fa5',1.5],['excess','Excess','#b39849',1.5]].map(([key,name,color,width],i)=>({x:series.map(x=>x.row.timestamp.slice(0,19)),y:series.map(x=>x.row[key]),customdata:series.map(x=>x.index),type:'scatter',mode:'lines',name,line:{color,width},visible:i<3?true:'legendonly',connectgaps:false,hovertemplate:`${name}: $%{y:,.2f}<extra></extra>`}));
  const breaches=series.filter(x=>x.row.margin_breach);
  if(breaches.length)navTraces.push({type:'scatter',mode:'markers',name:'Margin breach',x:breaches.map(x=>x.row.timestamp.slice(0,19)),y:breaches.map(x=>x.row.nav),marker:{color:'#b55037',size:9,symbol:'x'},customdata:breaches.map(x=>x.index)});
  window.COVERED_CALL_READY=Promise.all([
    Plotly.newPlot('nav-chart',navTraces,{...base,xaxis:{...base.xaxis,title:{text:'New York time · completed hourly bars'},type:'date'}},pc).then(g=>g.on('plotly_click',event=>{const i=event.points[0].customdata;if(Number.isInteger(i))inspect(i);})),
    (()=>{const points=v.points;const traces=[{type:'scatter',mode:'markers',name:'Real paired observations',x:points.map(p=>p.mid),y:points.map(p=>p.trade),customdata:points.map(p=>[p.ric,stamp(p.timestamp)]),marker:{size:5,color:'#167765',opacity:.42},hovertemplate:'Mid: $%{x:.4f}<br>TRDPRC_1: $%{y:.4f}<br>%{customdata[0]}<br>%{customdata[1]}<extra></extra>'}];if(fit){const lo=Math.min(...points.map(p=>p.mid));const hi=Math.max(...points.map(p=>p.mid));traces.push({type:'scatter',mode:'lines',name:`OLS fit · R² ${fit.r2.toFixed(4)}`,x:[lo,hi],y:[fit.slope*lo+fit.intercept,fit.slope*hi+fit.intercept],line:{color:'#b55037',width:2},hovertemplate:'Fitted print: $%{y:.4f}<extra></extra>'});traces.push({type:'scatter',mode:'lines',name:'Parity: trade = mid',x:[lo,hi],y:[lo,hi],line:{color:'#9ba9ad',width:1,dash:'dot'},hoverinfo:'skip'});}return Plotly.newPlot('scatter-chart',traces,{...base,hovermode:'closest',xaxis:{...base.xaxis,title:{text:'(BID + ASK) / 2 · midpoint ($)'},tickprefix:'$'},yaxis:{...base.yaxis,title:{text:'TRDPRC_1 · last trade ($)'}}},pc);})()
  ]).catch(error=>{showFailure(`Chart rendering error: ${error.message}`);throw error;});
})();
