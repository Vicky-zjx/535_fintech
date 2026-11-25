(function(root){
  'use strict';
  const tickers=['BAC','KO','PFE','F'],arms=['none','trend','volatility','sudden_drop','combined'];
  const pct=x=>Number.isFinite(x)?`${(100*x).toFixed(2)}%`:'Pending';
  const pp=x=>Number.isFinite(x)?`${(100*x).toFixed(3)} pp`:'Pending';
  const interval=c=>c?.ci95?`${pp(c.ci95[0])} to ${pp(c.ci95[1])}`:
    c?.reason==='benchmark_identity'?'Same benchmark · no inference':
    c?.reason==='insufficient_original_cohort'?'Withheld: fewer than 20 in a cohort':
    'Withheld: inadequate variation or resampling';
  const uncertainty=c=>!c?.ci95?'the comparison cannot support an uncertainty claim':
    c.ci95[0]>0?'the pointwise interval favors lower risk':c.ci95[1]<0?'the pointwise interval favors higher risk':
    'the interval includes zero, so chance remains a plausible explanation';
  function check(d){
    const x=d.lecture_extension;
    if(x?.kind!=='lecture_research_extension'||x.as_of!==d.window.analysis_end||x.source_sha256!==d.market_snapshot_sha256||
       x.monitoring.as_of!==x.as_of||x.monitoring.reference_sha256!==x.historical.reference_sha256||
       x.monitoring.frozen_reference_end!==x.historical.plan.reference_end)throw Error('Mixed research generations');
    for(const a of [x.historical.original_ablation,x.historical.expanded?.ablation].filter(Boolean)){
      if(a.replicates!==5000)throw Error('Unvalidated bootstrap count');
      for(const mode of ['daily','nonoverlap'])for(const t of tickers)for(const arm of arms){
        const s=a.samples[mode].tickers[t][arm];
        if(!Number.isInteger(s.n)||s.n<0||s.n>s.benchmark_n||s.events<0||s.events>s.n||
           (s.n>0&&Math.abs(s.frequency-s.events/s.n)>1e-12)||(s.n===0&&s.frequency!==null)||
           (s.benchmark_n>0?Math.abs(s.pass_rate+s.exclusion_rate-1)>1e-12:s.pass_rate!==null||s.exclusion_rate!==null)||
           s.opportunities_excluded!==s.benchmark_n-s.n)throw Error('Invalid ablation counts');
      }
    }
    for(const mode of ['daily','nonoverlap'])for(const t of tickers)for(const group of ['filtered','unfiltered']){
      const g=x.monitoring.samples[mode][t][group],z=g.current;
      if(!Number.isInteger(z.n)||z.events<0||z.events>z.n||
         (z.n===0&&z.observed_decline_frequency!==null)||
         (z.n>0&&Math.abs(z.observed_decline_frequency-z.events/z.n)>1e-12))throw Error('Invalid prospective counts');
      for(const p of g.curve)if(p.signal_date<=x.monitoring.frozen_reference_end||p.outcome_date>x.as_of)throw Error('Retrospective or unmatured point in monitor');
    }
    return x;
  }
  function selected(x,window,mode){
    if(!['original','expanded'].includes(window)||!['daily','nonoverlap'].includes(mode))throw Error('Invalid sample');
    const a=window==='original'?x.historical.original_ablation:x.historical.expanded?.ablation;
    if(!a)throw Error('Historical extension is Pending');return a;
  }
  function ablationRows(x,window='original',mode='daily',block=14){
    const a=selected(x,window,mode);
    return tickers.flatMap(t=>arms.map(arm=>{const s=a.samples[mode].tickers[t][arm],c=s.sensitivity.find(z=>z.block_length===block);
      if(!c)throw Error('Invalid block length');
      return [`${t} / ${s.label}${s.sparse_event_warning?' · Sparse-event caution':''}`,`${s.n} / ${s.events}`,`${pct(s.pass_rate)} / ${pct(s.exclusion_rate)}`,pct(s.mean_adverse),pct(s.frequency),
        `${pp(s.downside_difference)} / ${interval(c.downside_difference)}`,`${pp(s.frequency_difference)} / ${interval(c.frequency_difference)}`];
    }));
  }
  function ablationText(x,window='original',mode='daily',block=14){
    const a=selected(x,window,mode),s=a.samples[mode].tickers;
    const text=[`This ${mode==='daily'?'daily overlapping':'fixed non-overlapping'} sample covers ${a.window.analysis_start} to ${a.window.analysis_end}. I compare outcomes on a common set of valid, mature paths, not executed trades. Blocks contain ${block} ${mode==='daily'?'exchange dates':'seven-session-spaced slots'}. A screen can exclude fewer opportunities yet still leave higher risk; the sign and uncertainty matter as well as the count.`];
    for(const t of tickers){
      const z=s[t],c=z.combined.sensitivity.find(v=>v.block_length===block),same=z.trend.n===z.combined.n;
      text.push(`${t}: trend alone excludes ${z.trend.opportunities_excluded}/${z.none.n} paths (${pct(z.trend.exclusion_rate)}), HV20 excludes ${z.volatility.opportunities_excluded} (${pct(z.volatility.exclusion_rate)}), and the five-day-return screen excludes ${z.sudden_drop.opportunities_excluded} (${pct(z.sudden_drop.exclusion_rate)}). All filters leave ${z.combined.n} paths and a ${pct(z.combined.frequency)} decline frequency, against ${pct(z.none.frequency)} without filters. The frequency reduction is ${pp(z.combined.frequency_difference)} (95% interval ${interval(c.frequency_difference)}); ${uncertainty(c.frequency_difference)}. Mean downside changes by ${pp(z.combined.downside_difference)} (95% interval ${interval(c.downside_difference)}). ${same?'The combined set equals the trend-only set, so the other screens add no exclusions conditional on trend in this sample.':'The combined screen excludes '+(z.trend.n-z.combined.n)+' additional paths beyond trend; this is an interaction, not a separately estimated causal benefit.'}`);
      text.push(`For ${t}, HV20 alone changes decline frequency by ${pp(z.volatility.frequency_difference)} and mean downside by ${pp(z.volatility.downside_difference)}; the return-only screen changes them by ${pp(z.sudden_drop.frequency_difference)} and ${pp(z.sudden_drop.downside_difference)}. ${z.volatility.n===z.none.n||z.sudden_drop.n===z.none.n?'At least one of these screens never excludes a mature path, leaving no comparison group from which to infer its added value.':'The table reports their intervals rather than assuming a small difference is reliable.'} Fewer exclusions do not tell me how much option premium was forgone.`);
      const overlap=a.diagnostics?.filter_overlap?.[t];
      if(overlap&&mode==='daily')text.push(`${t}: ${overlap.price_below_sma50} mature signals have Close below SMA50, and ${overlap.sma20_below_sma50} have SMA20 below SMA50 (these counts overlap). Of the volatility exclusions, ${overlap.hv_fail_already_trend_fail} already fail trend; ${overlap.return_fail_already_trend_fail} return-screen exclusions also fail trend. This nesting explains why extra screens may change little after trend. Trend has two relative-price conditions, while 45% HV and an 8% weekly fall are high absolute cutoffs. This explains observed selectivity, not a proven causal return benefit.`);
      const sparse=arms.filter(a=>z[a].sparse_event_warning);
      if(sparse.length)text.push(`${t} sparse-event caution: `+sparse.map(a=>`${z[a].label} has ${z[a].events} events among ${z[a].n} selected paths and ${z.none.events-z[a].events} among ${z[a].opportunities_excluded} excluded paths`).join('; ')+'. At least one cohort has fewer than five events or non-events; percentile-bootstrap coverage can be unreliable even when an interval is displayed.');
    }
    const bac=a.samples.daily.tickers.BAC.combined,non=a.samples.nonoverlap.tickers.BAC.combined;
    text.push(`BAC illustrates the sampling problem: its daily frequency reduction is ${pp(bac.frequency_difference)} versus ${pp(non.frequency_difference)} on the fixed non-overlapping schedule (${non.n} selected paths). That schedule changes which dates and events appear, not just the denominator. A few clustered declines or different market phases could explain the shift; I have not established either explanation. I keep the predetermined schedule rather than choosing a favorable phase.`);
    const dominant=tickers.filter(t=>s[t].trend.opportunities_excluded>=Math.max(s[t].volatility.opportunities_excluded,s[t].sudden_drop.opportunities_excluded));
    const zero=tickers.filter(t=>{const c=s[t].combined.sensitivity.find(v=>v.block_length===block).frequency_difference.ci95;return c&&c[0]<=0&&c[1]>=0;});
    text.push(`Trend excludes at least as many paths as either other individual screen for ${dominant.join(', ')||'none of the four stocks'} in this selected sample. The combined frequency intervals include zero for ${zero.join(', ')||'none of the stocks with an available interval'}. Rejecting many opportunities does not establish an advantage. Sector exposure, differing volatility and ex-dividend dates could produce heterogeneous results; those are possible explanations, not tested causes. Few events, overlapping paths and persistent regimes can limit effective information and make intervals wide. Multiple screens and stocks also create selection risk. I do not change the production rules from these exploratory results.`);
    text.push(x.historical.expanded?'The expanded comparison below uses a fixed earlier start with the same endpoint. More observations can narrow uncertainty without removing dependence, provider revisions or regime sensitivity. I report both periods rather than select whichever supports my thesis. H2 remains untested without matched option economics; a one-expiry quote sample does not establish alpha.':
      'I cannot yet say whether five years stabilizes these results: that separate real-data pull has not been imported and validated. The current evidence is provisional support at best for H1, not proof of a stable reduction. H2 remains untested without matched option economics.');
    if(x.historical.expanded){
      const width=z=>{const c=z.sensitivity.find(v=>v.block_length===block).frequency_difference.ci95;return c?c[1]-c[0]:null;};
      text.push('Frequency-difference interval widths, original versus five years on this sampling schedule: '+tickers.map(t=>`${t} ${pp(width(x.historical.original_ablation.samples[mode].tickers[t].combined))} versus ${pp(width(x.historical.expanded.ablation.samples[mode].tickers[t].combined))}`).join('; ')+'. More calendar history does not guarantee a narrower interval: cohort composition, clustered events and the proportion passing trend also change. The fixed earlier start is retained even when evidence becomes less favorable.');
    }
    if(a.diagnostics?.calendar_partitions)text.push('Across all fixed calendar partitions, including partial endpoint years: '+tickers.map(t=>{const y=a.diagnostics.calendar_partitions[t],hv=y.map(v=>v.maximum_hv20).filter(Number.isFinite);return `${t} has ${y.filter(v=>v.endpoint_price_return>0).length} positive and ${y.filter(v=>v.endpoint_price_return<0).length} negative price-return intervals, with maximum HV20 ranging from ${pct(Math.min(...hv))} to ${pct(Math.max(...hv))}`;}).join('; ')+'. These observed contrasts show some variation in market conditions, not complete coverage of every crisis or a separately identified macro cause.');
    return text;
  }
  function comparisonRows(x,mode='daily'){
    const block=mode==='daily'?14:2;
    return tickers.map(t=>{const o=x.historical.original_ablation.samples[mode].tickers[t].combined,e=x.historical.expanded?.ablation.samples[mode].tickers[t].combined;
      const value=z=>`${pp(z.frequency_difference)} / ${interval(z.sensitivity.find(b=>b.block_length===block).frequency_difference)}`;
      return [t,`${o.n} / ${o.benchmark_n}`,value(o),e?`${e.n} / ${e.benchmark_n}`:'Pending',e?value(e):'Pending validated historical download'];});
  }
  function monitorRows(x,mode='daily'){
    return tickers.flatMap(t=>['filtered','unfiltered'].map(group=>{const g=x.monitoring.samples[mode][t][group],z=g.current;
      return [`${t} / ${group}`,`${g.baseline_events} / ${g.baseline_n}`,pct(z.expected_decline_probability),pct(z.maximum_acceptable_decline_probability),`${z.events} / ${z.n}`,
        `${pct(z.observed_decline_frequency)} / ${pp(z.deviation)}`,`${g.pending_signal_dates.length} / ${g.missing_path_signal_dates.length}`,z.status];}));
  }
  function monitorModel(x,t='BAC',group='filtered',mode='daily'){
    if(!tickers.includes(t)||!['filtered','unfiltered'].includes(group)||!['daily','nonoverlap'].includes(mode))throw Error('Invalid monitor selection');
    const m=x.monitoring,g=m.samples[mode][t][group],z=g.current,floor=m.plan.forward_reporting_floor;
    const ready=z.n>=floor&&!m.coverage_lost&&z.log_upper_tail_bound!==null;
    const points=g.curve.filter(p=>p.n>=floor),dates=points.map(p=>p.outcome_date);
    const series=(y,name,color)=>({type:'scatter',mode:'lines+markers',x:dates,y,name,connectgaps:false,
      line:{color,width:2},marker:{size:4},hovertemplate:'%{x}<br>%{y:.3g}<extra>%{fullData.name}</extra>'});
    const layout=(title,log=false)=>({height:340,paper_bgcolor:'#fff',plot_bgcolor:'#fff',font:{family:'system-ui',color:'#182b3a',size:11},margin:{l:62,r:18,t:20,b:90},
      xaxis:{title:{text:'Matured outcome date'},type:'date',gridcolor:'#eaf0f4'},yaxis:{title:{text:title},type:log?'log':'linear',gridcolor:'#eaf0f4',...(!log?{tickformat:'.0%'}:{})},legend:{orientation:'h',y:-.3,x:0}});
    const risk=[series(points.map(p=>p.observed_decline_frequency),'Observed decline frequency','#255b87'),series(points.map(p=>p.gap?null:z.expected_decline_probability),'Frozen estimated baseline','#946d38')];
    if(z.maximum_acceptable_decline_probability!==null)risk.push(series(points.map(p=>p.gap?null:z.maximum_acceptable_decline_probability),'Prechosen acceptable limit','#7c5551'));
    const bound=series(points.map(p=>p.log_upper_tail_bound===null?null:Math.exp(Math.max(-300*Math.LN10,p.log_upper_tail_bound))),'Conditional upper-tail bound','#255b87');
    const bl=layout('Probability upper bound (log)',true);
    bl.shapes=[.5,.25,.1].map(v=>({type:'line',xref:'paper',x0:0,x1:1,y0:v,y1:v,line:{color:'#9bb0bf',dash:'dot',width:1}}));
    const placeholder=`${t} ${group}: ${z.n} matured prospective observations; ${g.pending_signal_dates.length} unfinished; ${g.missing_path_signal_dates.length} missing paths. ${m.coverage_lost?'Forward-history coverage is incomplete or unavailable; monitoring withheld.':z.n<floor?`Waiting for at least ${floor} observations before drawing a curve.`:'Usable fixed baseline unavailable; monitoring withheld.'}`;
    const riskText=[`${t}, ${group}, ${mode==='daily'?'daily':'fixed non-overlapping'}: the frozen reference has ${g.baseline_events} events in ${g.baseline_n} paths (${pct(z.expected_decline_probability)}). New signals must be strictly after ${m.frozen_reference_end}; the latest available market date is ${m.as_of}. There are ${z.events} new events in ${z.n} matured paths, ${g.pending_signal_dates.length} unfinished paths and ${g.missing_path_signal_dates.length} missing-price paths. ${z.n?`The observed frequency is ${pct(z.observed_decline_frequency)}, a deviation of ${pp(z.deviation)} from the baseline.`:'There is no observed prospective frequency yet; zero observations is not a measured zero risk.'}`,
      `The maximum acceptable downside probability is ${pct(z.maximum_acceptable_decline_probability)}. Current assessment: ${z.status}; ${z.regime}. The historical mean is an estimate and is not the acceptable-risk limit. The graph would show cumulative completed observations, not stock returns, option returns or account NAV.`,
      `I need independent future evidence before treating the historical comparison as a repeatable pattern. ${ready?'The reporting floor is met, but it does not establish adequate power or independence.':z.n<floor?'The reporting floor is not met, so there is no curve to interpret.':'The source coverage or baseline is not usable; the curve is withheld.'} Missing windows are excluded and leave visible gaps; the cumulative estimate then describes complete cases, not all outcomes. Invalid signal inputs are excluded separately (${g.excluded_invalid_signals} in this selection).`];
    const boundText=[`Deterioration means more decline events, so I use exp[−n D(observed frequency ∥ frozen expected frequency)] only above the baseline; otherwise the upper-tail bound is 1. ${z.upper_tail_bound===null?'No bound is calculated for the current empty or unusable sample.':`The current conditional bound is ${z.upper_tail_bound<1e-300?'below 10⁻³⁰⁰':pct(z.upper_tail_bound)}, giving the classroom advisory “${z.conditional_advisory}”.`} This is a conditional calculation against an estimated hypothesis, not a test with verified financial-data coverage.`,
      'A high bound can simply mean too little evidence, not that my strategy is working. A low bound warrants investigation, not a claim that failure has that probability. Serial dependence, uncertainty in the baseline and repeated testing can invalidate an independence-based alarm. I would inspect data quality and market conditions before changing my belief.',
      `This research monitor never changes orders. ${z.maximum_acceptable_decline_probability===null?'The acceptable-risk limit is still Pending, so no formal regime decision is made.':'The stated regime rule is an advisory interpretation, not an independently validated state model.'} Actual win-rate monitoring and portfolio drawdown remain separate until authoritative fills and NAV exist.`];
    return {ready,placeholder,plots:[{id:'monitor-risk-chart',traces:risk,layout:layout('Decline frequency')},{id:'monitor-bound-chart',traces:[bound],layout:bl}],riskText,boundText};
  }
  function show(d){
    const el=id=>document.getElementById(id),paragraphs=(id,texts)=>{el(id).replaceChildren();for(const text of texts){const p=document.createElement('p');p.textContent=text;el(id).append(p);}},
      table=(id,rows)=>{el(id).replaceChildren();for(const row of rows){const tr=document.createElement('tr');row.forEach((value,i)=>{const c=document.createElement(i?'td':'th');c.textContent=value;tr.append(c);});el(id).append(tr);}};
    let x;try{x=check(d);}catch(_){el('extension-status').textContent='Lecture extension unavailable or inconsistent; existing research is retained.';return;}
    const h=x.historical,m=x.monitoring;
    el('extension-status').textContent=`${h.status}. Original evidence: ${h.original_window.analysis_start}–${h.original_window.analysis_end}. Fixed requested extension: ${h.plan.extended_start}–${h.plan.extended_end}. Current tracker through ${x.as_of}, built ${d.generated_at}.`;
    const expanded=el('ablation-window').options[1];expanded.disabled=!h.expanded;
    const complete=h.expanded&&tickers.every(t=>h.download_audit?.price_coverage?.[t]?.complete===true);
    expanded.textContent=h.expanded?`Fixed five-year window · ${complete?'complete closes':'partial coverage'}`:'Fixed five-year extension · Pending';
    el('extension-audit').textContent=`${h.comparison_status} ${h.adjustment_status} `+(h.expanded?
      `Downloaded ${h.expanded.retrieved_at}. `+tickers.map(t=>`${t}: ${h.expanded.added_mature_paths[t]} added mature paths; ${h.expanded.coverage[t].missing_path||0} missing-price paths and ${h.expanded.coverage[t].signal_unavailable||0} unavailable signals in the requested window`).join('; ')+'.':'');
    if(h.download_audit?.adjustment_audit){const p=h.download_audit.adjustment_audit;
      el('extension-audit').textContent+=' '+tickers.map(t=>`${t} adjusted/unadjusted probe checks: `+p.tickers[t].price_comparisons.map(c=>`${c.compared} compared, ${c.differences} different`).join(' / ')).join('; ')+'. '+p.policy;}
    const c=m.classroom_example;
    el('lecture-example').textContent=`With expected win probability ${pct(c.expected_win_rate)}, observed win frequency ${pct(c.observed_win_rate)} in ${c.completed_trades} completed trades, the adverse deviation is ${pp(c.adverse_deviation)}. The lower-tail calculation exp[−10 D(0.50 ∥ 0.60)] gives ${pct(c.bound)} (approximately 82%). This upper bound is too loose to establish deterioration: the classroom advisory is “${c.advisory}”. It is not the probability that the strategy has failed and these are not my trades.`;
    el('monitor-status').textContent=`Frozen reference ends ${m.frozen_reference_end}; market data ends ${m.as_of}. Only later signals with completed outcomes qualify. This is a research monitor, separate from Sanji.`;
    el('monitor-inventory').textContent=Object.values(x.monitoring_inventory).join(' ');
    const candidates=x.acceptable_risk_candidates;
    if(candidates){paragraphs('risk-candidate-analysis',[candidates.status+'. '+candidates.calibration+' '+candidates.definition,candidates.limitation,'The 25/50/75 bp budgets correspond to $30/$60/$90 on a hypothetical $12,000 stock exposure. Each probability candidate is budget divided by the historical conditional severity, not a threshold chosen to make the observed frequency pass. All active maximum-risk thresholds remain Pending.']);
      table('risk-candidate-results',tickers.map(t=>{const z=candidates.tickers[t];return [t,pct(z.conditional_mean_closing_decline),...z.scenarios.map(s=>pct(s.probability_candidate))];}));}
    const economics=x.option_economics;
    if(economics.available_metrics){
      paragraphs('fresh-option-economics',[`The independent private pull now has ${economics.valid_bid_ask_records} valid dated bid/ask pairs across ${economics.probed_contracts} contracts, but ${economics.dated_delta_records} usable historical delta observations: the delta requests failed, which is not a measured delta of zero. The historical discovery probe did not establish chain membership. Entry ${economics.entry_date}; expiry ${economics.expiry}. ${economics.scope}`,economics.payoff_definition,economics.assumptions,economics.missing]);
      const range=v=>v?`${pct(v[0])} to ${pct(v[1])}`:'No valid observation';
      table('option-probe-results',economics.available_metrics.illustrations.map(z=>[z.ticker,`${z.usable_contracts} / ${z.probed_contracts}`,range(z.midpoint_premium_yield),range(z.midpoint_net_payoff_yield),range(z.bid_net_payoff_yield),String(z.itm_at_expiry)]));
    }else paragraphs('fresh-option-economics',[economics.reason]);
    const drawA=()=>{const mode=el('ablation-sampling').value,window=el('ablation-window').value,block=Number(el('ablation-block').value);
      table('ablation-results',ablationRows(x,window,mode,block));paragraphs('ablation-analysis',ablationText(x,window,mode,block));table('extension-comparison',comparisonRows(x,mode));
      const bins=selected(x,window,mode).diagnostics?.calendar_partitions;
      if(bins)table('calendar-partitions',tickers.flatMap(t=>bins[t].map(y=>[`${t}: ${y.first_date}–${y.last_date}`,String(y.valid_signals),pct(y.endpoint_price_return),`${pct(y.median_hv20)} / ${pct(y.maximum_hv20)}`,pct(y.trend_exclusion_rate),pct(y.decline_frequency)])));};
    el('ablation-sampling').addEventListener('change',()=>{const daily=el('ablation-sampling').value==='daily',b=el('ablation-block');b.replaceChildren();for(const length of daily?[7,14,28]:[1,2,4]){const o=document.createElement('option');o.value=String(length);o.textContent=`${length} ${daily?'dates':'slots'}${length===(daily?14:2)?' · primary':''}`;b.append(o);}b.value=daily?'14':'2';drawA();});
    el('ablation-window').addEventListener('change',drawA);el('ablation-block').addEventListener('change',drawA);drawA();
    const messages=new Set();
    const drawM=()=>{const mode=el('monitor-sampling').value,z=monitorModel(x,el('monitor-ticker').value,el('monitor-group').value,mode);
      table('monitor-results',monitorRows(x,mode));paragraphs('monitor-risk-analysis',z.riskText);paragraphs('monitor-bound-analysis',z.boundText);
      for(const p of z.plots){const node=el(p.id);if(!z.ready||!root.Plotly){if(root.Plotly?.purge)root.Plotly.purge(node);node.textContent=z.ready?'Chart library unavailable; see the actual results table.':z.placeholder;messages.add(p.id);continue;}
        if(messages.has(p.id)){node.replaceChildren();messages.delete(p.id);}
        Promise.resolve(root.Plotly.react(node,p.traces,p.layout,{responsive:true,displayModeBar:false})).catch(()=>{node.textContent='Monitor chart unavailable; see the actual results table.';messages.add(p.id);});}};
    for(const id of ['monitor-ticker','monitor-group','monitor-sampling'])el(id).addEventListener('change',drawM);drawM();
  }
  const api={check,ablationRows,ablationText,comparisonRows,monitorRows,monitorModel,show};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;root.WheelLecture=api;
})(typeof window!=='undefined'?window:globalThis);
