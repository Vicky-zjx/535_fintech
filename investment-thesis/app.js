/* A descriptive stock-risk tracker. Never mutates the planner or its orders. */
(function (root) {
  'use strict';
  const names=['BAC','KO','PFE','F'];
  const pct=v=>v===null?'Insufficient evidence':(v*100).toFixed(2)+'%';
  const bps=v=>v===null?'Unmeasured':(v*10000).toFixed(2)+' bp';
  const money=v=>(v<0?'−$':'$')+Math.abs(v).toFixed(2);
  const datePattern=/^\d{4}-\d{2}-\d{2}$/;
  function check(d,h,retained=false) {
    const projected=d.projection?.version===1;
    if(projected){
      if('rows' in d||d.projection.raw_price_paths_included!==false)throw Error('Private paths in browser payload');
      h={...d.projection.source_proof,generated_at:d.projection.source_proof.historical_generated_at};
    }
    if(d.kind!=='forward_stock_risk_research'||d.source!=='LSEG Data Platform')throw Error('Invalid research source');
    if (!retained&&(!h || h.source!==d.source ||
        d.strategy_revision!==h.strategy_revision || d.market_snapshot_sha256!==h.market_snapshot_sha256 ||
        d.market_retrieved_at!==h.market_retrieved_at || d.historical_generated_at!==h.generated_at ||
        d.window.analysis_start!==h.window.analysis_start || d.window.analysis_end!==h.window.analysis_end))
      throw Error('Research and historical source disagree');
    if (d.design.version!=='forward-stock-risk-v1.1' || d.design.minimum_per_cohort_per_ticker!==20 ||
        d.design.rolling_entry_sessions!==126 || d.design.holding_sessions!==5 || d.design.reference_lag_sessions!==1 ||
        d.design.adverse_move_threshold!==.03) throw Error('Unexpected research definition');
    if(projected?names.some(t=>d.projection.row_counts[t]!==d.rolling.length):
      ((!retained&&d.rolling.length!==h.tickers.BAC.daily_rows.length)||d.rolling.length!==d.rows.BAC.length)) throw Error('Missing research dates');
    let previous='';
    for(const point of d.rolling) {
      if(!datePattern.test(point.as_of)||point.as_of<=previous||point.as_of>d.window.analysis_end) throw Error('Invalid tracker dates');
      previous=point.as_of;
    }
    if(previous!==d.window.analysis_end) throw Error('Tracker ends before source');
    for(const sample of [d.full_sample,d.prospective,...d.rolling]) {
      for(const ticker of names) {
        const s=sample.tickers[ticker];
        if(!s || s.sufficient!==(s.pass.n>=20 && s.fail.n>=20)) throw Error('Invalid cohort sufficiency');
        for(const c of ['pass','fail','all']) {
          const z=s[c];
          if(!Number.isInteger(z.n)||z.n<0) throw Error('Invalid sample count');
          for(const k of ['mean_return','return_sd','mean_adverse','tail_rate']) {
            if(z[k]!==null&&!Number.isFinite(z[k])) throw Error('Invalid statistic');
            if(z.n===0&&z[k]!==null) throw Error('Empty cohort cannot be zero');
          }
        }
        if(s.all.n!==s.pass.n+s.fail.n) throw Error('Cohort total mismatch');
      }
      if(sample.aggregate.sufficient!==names.every(t=>sample.tickers[t].sufficient)) throw Error('Aggregate minimum not met');
      for(const c of ['pass','fail','all'])for(const k of ['mean_return','mean_adverse','tail_rate']) {
        const actual=sample.aggregate[c+'_'+k];
        if(sample.aggregate.sufficient) {
          const expected=names.reduce((a,t)=>a+sample.tickers[t][c][k],0)/4;
          if(!Number.isFinite(actual)||Math.abs(actual-expected)>1e-12) throw Error('Unequal aggregate weights');
        } else if(actual!==null) throw Error('Insufficient aggregate must remain missing');
      }
    }
    const matured=projected?d.latest_matured_outcome_date:Object.values(d.rows).flat().filter(x=>x.status==='observed').map(x=>x.outcome_date).sort().at(-1)||null;
    if(d.latest_matured_outcome_date!==matured||matured>d.window.analysis_end)throw Error('Invalid maturity timestamp');
    for(const e of d.cost_budget.examples){
      if(Math.abs(e.assumed_cost-3.3)>1e-12||e.scenarios.map(s=>s.gross_bps).join(',')!=='5,10,20,30,50')throw Error('Invalid cost assumption');
      for(const s of e.scenarios)if(Math.abs(s.net_dollars-(s.gross_bps*e.collateral/10000-e.assumed_cost))>1e-9||Math.abs(s.net_bps-s.net_dollars/e.collateral*10000)>1e-9)throw Error('Invalid cost scenario');
    }
    return d;
  }
  function charts(d,ticker='ALL') {
    if(ticker!=='ALL'&&!names.includes(ticker))throw Error('Unknown ticker');
    const cohorts=['pass','fail','all'],labels=['Pass filters','Fail filters','Unfiltered'],colors=['#255b87','#946d38','#7e8f9a'];
    const value=(p,c,k)=>ticker==='ALL'?p.aggregate[c+'_'+k]:p.tickers[ticker].sufficient?p.tickers[ticker][c][k]:null;
    return ['mean_adverse','tail_rate'].map((key,i)=>({
      id:i?'thesis-tail-chart':'thesis-loss-chart',
      traces:cohorts.map((c,j)=>({type:'scatter',mode:'lines',name:labels[j],connectgaps:false,
        x:d.rolling.map(p=>p.as_of),y:d.rolling.map(p=>value(p,c,key)),
        customdata:d.rolling.map(p=>[p.first_reference_date,p.last_reference_date,
          ticker==='ALL'?p.aggregate.pass_n:p.tickers[ticker].pass.n,
          ticker==='ALL'?p.aggregate.fail_n:p.tickers[ticker].fail.n]),
        line:{color:colors[j],width:2,dash:j===2?'dot':'solid'},
        hovertemplate:'Known by %{x|%b %d, %Y}<br>'+labels[j]+': %{y:.2%}<br>Reference window: %{customdata[0]} to %{customdata[1]}<br>Pass / fail paths: %{customdata[2]} / %{customdata[3]}<extra></extra>'})),
      layout:{autosize:true,height:340,margin:{l:55,r:12,t:15,b:90},hovermode:'x unified',
        xaxis:{type:'date',nticks:4,tickformat:'%b %Y',automargin:true},
        yaxis:{title:{text:i?'Frequency':'Mean closing loss'},tickformat:i?'.0%':'.1%',rangemode:'tozero',automargin:true},
        legend:{orientation:'h',x:0,y:-.25,font:{size:12}},paper_bgcolor:'#ffffff',plot_bgcolor:'#ffffff',
        font:{family:'system-ui',size:12,color:'#182b3a'},uirevision:ticker}
    }));
  }
  function interpretation(d) {
    const s=d.full_sample.aggregate;
    if(!s.sufficient)return 'The full sample lacks enough pass/fail paths in every stock; no aggregate benefit is inferred.';
    return `Full sample, equal stock weights: mean maximum closing loss is ${pct(s.pass_mean_adverse)} after pass signals, ${pct(s.fail_mean_adverse)} after fail signals and ${pct(s.all_mean_adverse)} unfiltered. The pass-minus-fail loss difference is ${bps(-s.downside_benefit)} (negative favors the premise); 3% decline frequencies are ${pct(s.pass_tail_rate)} versus ${pct(s.fail_tail_rate)}. ${s.pass_mean_adverse>=s.all_mean_adverse?'The pass group does not improve mean loss relative to the unfiltered baseline. ':''}${s.downside_benefit>0?'A smaller loss than the fail group is descriptive evidence, not proof of a persistent or priced advantage.':'The observed loss comparison does not support the risk premise.'} Neither comparison establishes option alpha.`;
  }
  function review(d) {
    const p=d.rolling.at(-1),a=p.aggregate;
    if(!a.sufficient)return `Review as of ${p.as_of}: insufficient evidence for the four-stock conditions. ${a.insufficient_tickers.map(t=>`${t}: ${p.tickers[t].pass.n} pass / ${p.tickers[t].fail.n} fail paths`).join('; ')} (minimum 20 of each). Individual stock charts remain selectable. No success is inferred from an unavailable review.`;
    const label=v=>v==='triggered'?'triggered — review the thesis':'not triggered';
    return `Review as of ${p.as_of}: condition 1 ${label(p.wrong_if.no_downside_benefit)} (${bps(a.baseline_downside_benefit)} loss reduction versus unfiltered); condition 2 ${label(p.wrong_if.no_tail_benefit)} (${(100*a.baseline_tail_benefit).toFixed(2)} percentage-point frequency reduction versus unfiltered). These are descriptive review flags, not evidence of statistical significance or changes to live order rules.`;
  }
  function alpha(d) {
    const a=d.full_sample.aggregate;
    return `The full-sample five-session stock-return contrast versus the unfiltered baseline is ${bps(a.baseline_return_spread)}: ${pct(a.pass_mean_return)} after pass signals versus ${pct(a.all_mean_return)} unfiltered, using equal stock weights. The diagnostic pass-minus-fail contrast is ${bps(a.return_spread)}. ${a.baseline_return_spread!==null&&a.baseline_return_spread<=0?'This does not support a positive directional return advantage.':''} It is neither beta-adjusted alpha nor a tradable long/short spread. The return dispersions in the evidence table show uncertainty; overlapping paths must not be compounded into a strategy return.`;
  }
  function cost(d) {
    return d.cost_budget.examples.map(e=>`${e.ticker} at the recorded $${e.strike.toFixed(0)} strike: ${money(e.collateral)} collateral, ${e.break_even_bps.toFixed(2)} bp to cover the assumed ${money(e.assumed_cost)} cost; a hypothetical 20 bp gross surplus would leave ${money(e.illustrative_net_surplus)} (${e.illustrative_net_bps.toFixed(2)} bp)`).join('. ')+'. These are sensitivity examples, not quotes, realized profits or a forecast. The economic edge is not established by the stock tracker.';
  }
  // All narrative arithmetic comes from the same cohorts used by the plots.
  // A positive reduction is favorable; do not confuse pp with relative percent.
  function view(sample,ticker) {
    if(ticker!=='ALL'&&!names.includes(ticker))throw Error('Unknown ticker');
    if(ticker!=='ALL')return sample.tickers[ticker];
    const a=sample.aggregate;
    return {sufficient:a.sufficient,...Object.fromEntries(['pass','fail','all'].map(c=>[c,{
      n:c==='all'?a.pass_n+a.fail_n:a[c+'_n'],
      ...Object.fromEntries(['mean_adverse','tail_rate','mean_return'].map(k=>[k,a[c+'_'+k]]))}]))};
  }
  const label=t=>t==='ALL'?'All four stocks, equally weighted':t;
  const counts=s=>`${s.pass.n} pass / ${s.fail.n} fail / ${s.all.n} unfiltered paths`;
  function effect(s,key) {
    const pass=s.pass[key],baseline=s.all[key];
    if(!s.sufficient||pass===null||baseline===null)return null;
    const reduction=baseline-pass;
    return {reduction,relative:baseline>0?reduction/baseline:null};
  }
  function difference(s,key) {
    const e=effect(s,key);if(!e)return 'The minimum sample requirement is not met; no comparison is inferred.';
    const unit=key==='tail_rate'?' percentage points':' bp';
    const scale=key==='tail_rate'?100:10000;
    const direction=e.reduction>0?'lower':e.reduction<0?'higher':'unchanged';
    return `Pass is ${Math.abs(e.reduction*scale).toFixed(2)}${unit} ${direction} than unfiltered. `+
      (e.relative===null?'Relative reduction is undefined because the benchmark is zero.':
      `Relative change: a ${Math.abs(e.relative*100).toFixed(2)}% ${e.relative>=0?'reduction':'increase'}, not a percentage-point change.`);
  }
  function stability(d,ticker,key) {
    let better=0,worse=0,equal=0,missing=0,lastWorse=null,latestRun=null;
    const runs=[];
    for(const p of d.rolling){const e=effect(view(p,ticker),key);
      if(!e){missing++;latestRun=null;continue;}
      if(e.reduction>0){better++;latestRun=null;}
      else if(e.reduction<0){worse++;lastWorse=p.as_of;
        if(!latestRun){latestRun={start:p.as_of,end:p.as_of,dates:0};runs.push(latestRun);}
        latestRun.end=p.as_of;latestRun.dates++;
      }else{equal++;latestRun=null;}
    }
    return {better,worse,equal,missing,evaluable:better+worse+equal,lastWorse,lastWorseRun:runs.at(-1)||null};
  }
  function stabilityText(d,ticker,key) {
    const s=stability(d,ticker,key),r=s.lastWorseRun;
    return `Across ${s.evaluable} evaluable rolling dates, pass is lower than unfiltered on ${s.better} (${s.evaluable?(100*s.better/s.evaluable).toFixed(1):'0.0'}%), higher on ${s.worse}, and equal on ${s.equal}; ${s.missing} dates lack the required sample. `+
      (r?`The most recent continuous higher-risk interval is ${r.start} to ${r.end} (${r.dates} plotted ${r.dates===1?'date':'dates'}). `:'There is no observed higher-risk interval among the evaluable dates. ')+
      'These strongly overlapping windows describe stability, not independent trials or a significance test.';
  }
  function summary(sample,ticker,key) {
    const s=view(sample,ticker);
    if(!s.sufficient)return `${counts(s)}. Insufficient evidence: `+(ticker==='ALL'?
      sample.aggregate.insufficient_tickers.map(t=>`${t} has ${sample.tickers[t].pass.n} pass / ${sample.tickers[t].fail.n} fail`).join('; '):
      `${ticker} needs at least 20 paths in both pass and fail groups`)+'. Values remain missing in the chart; no reduced-stock aggregate is substituted.';
    return `Pass ${pct(s.pass[key])}; unfiltered ${pct(s.all[key])}; fail ${pct(s.fail[key])}. ${difference(s,key)} Sample: ${counts(s)}.`;
  }
  function chartAnalysis(d,ticker,key) {
    const tail=key==='tail_rate',latest=d.rolling.at(-1);
    return [
      `${label(ticker)}. ${tail?'I count paths with at least one closing price 3% or more below the next-session reference close during the following five sessions.':'I measure the largest closing-price loss from the next-session reference close over the following five sessions, then average it. A path that never closes below its reference contributes zero observed loss.'}`,
      `Full sample (${d.window.analysis_start} to ${d.window.analysis_end}): ${summary(d.full_sample,ticker,key)}`,
      `Latest rolling window, known by ${latest.as_of}; reference dates ${latest.first_reference_date} to ${latest.last_reference_date}: ${summary(latest,ticker,key)}`,
      stabilityText(d,ticker,key),
      tail?'Fewer large declines would be relevant to a put seller because losses can increase as the stock falls toward or through the strike. One possible explanation for a reduction is that the screens avoid persistent selloffs. Rebounds, sector shocks and different regimes can produce the opposite result; the chart does not identify a causal mechanism. A 3% close-to-close-path event is neither option assignment probability nor option loss probability.':
        'A smaller loss could mean less adverse stock exposure when I write puts. One possible explanation is that trend and volatility screens avoid continuing declines. They can also select a calm period just before a reversal or miss a recovery. This comparison cannot separate those explanations from market-regime differences. It is not portfolio maximum drawdown and excludes intraday losses.',
      'For my Wheel, this is a risk diagnostic, not a premium or profit result. Even a favorable comparison would need option prices, costs and the return on weeks without a trade before I could claim an economic benefit.'
    ];
  }
  function stockAnalysis(d) {
    const ready=names.filter(t=>d.full_sample.tickers[t].sufficient);
    const ranked=[...ready].sort((a,b)=>effect(view(d.full_sample,b),'mean_adverse').reduction-effect(view(d.full_sample,a),'mean_adverse').reduction);
    return names.map(t=>{const s=d.full_sample.tickers[t],e=effect(s,'mean_adverse'),f=effect(s,'tail_rate'),r=d.rolling.at(-1).tickers[t];
      if(!e||!f)return `${t}: ${counts(s)}; insufficient full-sample evidence. I do not rank this stock.`;
      const conclusion=e.reduction>0&&f.reduction>0?'Both measures favor the risk premise.':e.reduction<=0&&f.reduction<=0?'Neither measure favors the risk premise.':'The two measures point in different directions.';
      return `${t}: pass mean loss ${pct(s.pass.mean_adverse)} versus ${pct(s.all.mean_adverse)} unfiltered (${Math.abs(e.reduction*10000).toFixed(2)} bp ${e.reduction>0?'lower':'higher'}); 3% event frequency ${pct(s.pass.tail_rate)} versus ${pct(s.all.tail_rate)} (${Math.abs(f.reduction*100).toFixed(2)} pp ${f.reduction>0?'lower':'higher'}). ${conclusion} Its mean-loss reduction ranks ${ranked.indexOf(t)+1} of ${ranked.length} evaluable stocks (largest first). Full sample: ${counts(s)}, sufficient. Latest window: ${r.pass.n} pass / ${r.fail.n} fail, ${r.sufficient?'sufficient':'insufficient'} under the unchanged 20-per-cohort rule.`;
    });
  }
  function overall(d,ticker='ALL') {
    const s=view(d.full_sample,ticker),loss=effect(s,'mean_adverse'),tail=effect(s,'tail_rate');
    const favorable=names.filter(t=>{const a=view(d.full_sample,t);return a.sufficient&&effect(a,'mean_adverse').reduction>0&&effect(a,'tail_rate').reduction>0;});
    const contrary=names.filter(t=>{const a=view(d.full_sample,t);return a.sufficient&&effect(a,'mean_adverse').reduction<=0&&effect(a,'tail_rate').reduction<=0;});
    const p=view(d.prospective,ticker);
    return [
      `${label(ticker)}: ${loss&&tail?`mean closing loss is ${pct(s.pass.mean_adverse)} after pass signals versus ${pct(s.all.mean_adverse)} unfiltered; 3% event frequencies are ${pct(s.pass.tail_rate)} and ${pct(s.all.tail_rate)}. ${loss.reduction>0&&tail.reduction>0?'Both full-sample risk comparisons favor H1, descriptively.':loss.reduction<=0&&tail.reduction<=0?'Neither full-sample risk comparison supports H1.':'The evidence is mixed: one measure favors H1, while the other does not.'}`:'The full sample does not meet the minimum counts, so I cannot infer a risk advantage.'} I do not treat this as evidence of option profitability.`,
      `The four stocks do not have to tell the same story. Both full-sample measures favor the premise for ${favorable.join(', ')||'none of the stocks'}; neither favors it for ${contrary.join(', ')||'none of the stocks'}. The remaining evaluable stocks have mixed signs. This is why the aggregate is not enough. Differences in sectors or market regimes are possible explanations, not findings established by this comparison.`,
      `${stabilityText(d,ticker,'mean_adverse')} ${view(d.rolling.at(-1),ticker).sufficient?'The latest selected view meets the count rule, but a single window cannot establish persistence.':'The latest selected view is insufficient; I do not carry an older valid value forward.'} The unchanged four-stock review below is separate from these selected-stock diagnostics.`,
      `Signals through ${d.design.retrospective_cutoff||d.design.registered_on} are retrospective. Only later signals with completed outcomes count as prospective; this view has ${p.pass.n} matured pass and ${p.fail.n} matured fail paths. ${p.sufficient?'The prospective counts now meet the minimum, but still require a separate performance comparison.':'Prospective validation is still accumulating; no earlier result is relabeled as a live test.'} H2 needs matched historical option quotes, payoffs and costs, including forgone trades and idle cash. Until then I cannot conclude that the risk changes improve net returns.`
    ];
  }
  function conditions(d) {
    const p=d.rolling.at(-1),a=p.aggregate;
    const sample=names.map(t=>`${t} ${p.tickers[t].pass.n}/${p.tickers[t].fail.n}`).join('; ')+' pass/fail';
    return [['1. Mean downside (registered)','mean_adverse','no_downside_benefit'],['2. Large-downside frequency (registered)','tail_rate','no_tail_benefit']].map(([title,key,flag])=>[
      title,`${pct(a['pass_'+key])} / ${pct(a['all_'+key])} unfiltered; as of ${p.as_of}`,sample,
      p.wrong_if[flag]==='insufficient'?'Insufficient Evidence — at least one stock lacks 20 observations per cohort.':
      p.wrong_if[flag]==='triggered'?'Triggered — pass is no safer on this measure; review H1.':'Not Triggered — lower observed risk, not proof of the thesis.'
    ]).concat([['3. Net economic benefit (new extension)','Not measured / matched unfiltered CSP net return required','No validated weekly option comparison','Not Yet Testable — Insufficient Option Data; no alpha is assumed.']]);
  }
  function optionAudit(d) {
    const a=d.option_audit;
    if(!a||a.status!=='insufficient_option_data')return 'Option evidence needs a separately validated historical comparison; no economic return is inferred.';
    const snapshots=a.snapshots.filter(s=>s.status==='inventoried');
    const stats=snapshots.flatMap(s=>Object.values(s.tickers));
    const sum=k=>stats.reduce((v,x)=>v+x[k],0);
    return `The retained discovery snapshots dated ${snapshots.map(s=>s.market_date).join(' and ')} contain ${sum('contracts')} contract records (${sum('puts')} puts), ${sum('bid_ask_pairs')} populated bid/ask pairs and ${sum('dated_deltas')} populated dated deltas across BAC, KO, PFE and F. These are snapshot records, not a complete historical weekly universe. ${a.capability} ${a.legacy_scope} Option-level economic advantage is not yet estimable; it is not assumed to be zero.`;
  }
  function freshness(d,s={},r={},now=new Date()) {
    const aligned=s.status==='success'&&s.market_snapshot_sha256===d.market_snapshot_sha256&&s.calendar?.as_of===d.window.analysis_end;
    const lag=d.next_market_close_at&&now.getTime()>=new Date(d.next_market_close_at).getTime();
    const failed=r.status==='failed'||(s.status&&s.status!=='success');
    return `Latest market data: ${d.window.analysis_end}. Latest matured outcome: ${d.latest_matured_outcome_date||'none'}. LSEG retrieval: ${d.market_retrieved_at}. Tracker generation: ${d.generated_at}. Sample: ${d.window.analysis_start} to ${d.window.analysis_end}. `+
      (failed?'STALE / FAILED UPDATE: last validated evidence is retained; no fresh observation is substituted. ':lag?`STALE MARKET SNAPSHOT: session ${d.next_market_session} has already closed, but is not reflected here. A newer build timestamp is not newer market data. `:'The next scheduled market close has not yet passed. ')+
      (aligned?'The retained source matches the successful order evaluation. ':'The source is not verified against the latest successful order evaluation. ')+
      (r.attempted_at?`Last recorded thesis refresh: ${r.status} at ${r.attempted_at} (${r.context||'unspecified context'}). `:'Refresh status unavailable; latest workflow success is not verified. ')+
      'Only fully matured paths contribute; recent signal dates remain pending.';
  }
  const api={check,charts,interpretation,review,alpha,cost,view,effect,difference,stability,chartAnalysis,stockAnalysis,overall,conditions,optionAudit,freshness};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  root.WheelThesis=api;
  if(typeof document==='undefined')return;
  const el=id=>document.getElementById(id);
  async function get(url){const r=await fetch(url,{cache:'no-store'});if(!r.ok)throw Error('Research data unavailable');return r.json();}
  function paragraphs(id,texts) {const target=el(id);target.replaceChildren();for(const text of texts){const p=document.createElement('p');p.textContent=text;target.append(p);}}
  function table(id,rows){const target=el(id);target.replaceChildren();for(const row of rows){const tr=document.createElement('tr');row.forEach((value,i)=>{const td=document.createElement(i?'td':'th');td.textContent=value;tr.append(td);});target.append(tr);}}
  function show(d,h,s,r) {
    const retained=r.status==='failed'&&r.evidence_generated_at===d.generated_at&&r.market_snapshot_sha256===d.market_snapshot_sha256;
    check(d,h,retained);
    el('thesis-status').textContent=freshness(d,s,r);
    el('thesis-review').textContent=review(d);
    el('thesis-alpha').textContent=alpha(d);
    el('thesis-cost').textContent=cost(d);
    el('thesis-option-audit').textContent=optionAudit(d);
    table('thesis-conditions',conditions(d));
    paragraphs('thesis-stock-analysis',stockAnalysis(d));
    table('thesis-cost-table',d.cost_budget.examples[0].scenarios.map((v,i)=>[
      `${v.gross_bps} bp`,...d.cost_budget.examples.map(e=>`${e.scenarios[i].net_bps.toFixed(2)} bp / ${money(e.scenarios[i].net_dollars)}`)]));
    const body=el('thesis-summary');body.replaceChildren();
    for(const t of names){const z=d.full_sample.tickers[t];const tr=document.createElement('tr');
      [t,`${z.pass.n} / ${z.fail.n} / ${z.all.n}`,...['mean_return','return_sd','mean_adverse','tail_rate'].map(k=>`${pct(z.pass[k])} / ${pct(z.all[k])} / ${pct(z.fail[k])}`)].forEach((v,i)=>{const c=document.createElement(i?'td':'th');c.textContent=v;tr.append(c);});body.append(tr);}
    el('thesis-coverage').textContent=names.map(t=>{const c=d.coverage[t];return `${t}: ${c.observed||0} observed paths, ${c.unmatured||0} pending, ${c.missing_path||0} missing-price paths and ${c.signal_unavailable||0} unavailable signals`;}).join('; ')+'. Exclusions are not zero returns.';
    el('thesis-prospective').textContent=d.prospective_unavailable_reason||`Prospective evidence uses signals strictly after ${d.design.retrospective_cutoff||d.design.registered_on}, with outcomes completed by the current market date: ${d.prospective.aggregate.pass_n} mature pass paths / ${d.prospective.aggregate.fail_n} mature fail paths. The same cutoff applies to the frozen-baseline monitor. Historical outcomes that had not matured at the cutoff do not enter the frozen baseline.`;
    const draw=()=>{const ticker=el('thesis-ticker').value;
      paragraphs('thesis-loss-analysis',chartAnalysis(d,ticker,'mean_adverse'));
      paragraphs('thesis-tail-analysis',chartAnalysis(d,ticker,'tail_rate'));
      paragraphs('thesis-reading',overall(d,ticker));
      charts(d,ticker).forEach(c=>{
      const target=el(c.id);
      if(!root.Plotly){target.textContent='Chart library unavailable. Validated results remain in the table and downloads.';return;}
      try{Promise.resolve(root.Plotly.react(target,c.traces,c.layout,{responsive:true,displayModeBar:false})).catch(()=>{target.textContent='Chart unavailable; see the data table and downloads.';});}
      catch(_){target.textContent='Chart unavailable; see the data table and downloads.';}
    });};
    el('thesis-ticker').addEventListener('change',draw);draw();
    if(root.WheelReliability)root.WheelReliability.show(d);
    if(root.WheelLecture)root.WheelLecture.show(d);
    if(root.WheelPayoff)root.WheelPayoff.show(d);
  }
  Promise.all([get('data/public_tracker.json'),get('data/refresh_status.json').catch(()=>({}))])
    .then(([d,r])=>show(d,null,{},r)).catch(()=>{
      el('thesis-status').textContent='Research data unavailable or inconsistent with the historical source. No result is substituted; reload after the nightly publication completes.';
    });
})(typeof window!=='undefined'?window:globalThis);
