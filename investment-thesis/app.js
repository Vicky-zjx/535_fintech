/* A descriptive stock-risk tracker. Never mutates the planner or its orders. */
(function (root) {
  'use strict';
  const names=['BAC','KO','PFE','F'];
  const pct=v=>v===null?'Insufficient evidence':(v*100).toFixed(2)+'%';
  const bps=v=>v===null?'Unmeasured':(v*10000).toFixed(2)+' bp';
  const money=v=>'$'+v.toFixed(2);
  const datePattern=/^\d{4}-\d{2}-\d{2}$/;
  function check(d,h) {
    if (d.kind!=='forward_stock_risk_research' || d.source!=='LSEG Data Platform' || h.source!==d.source ||
        d.strategy_revision!==h.strategy_revision || d.market_snapshot_sha256!==h.market_snapshot_sha256 ||
        d.market_retrieved_at!==h.market_retrieved_at || d.historical_generated_at!==h.generated_at ||
        d.window.analysis_start!==h.window.analysis_start || d.window.analysis_end!==h.window.analysis_end)
      throw Error('Research and historical source disagree');
    if (d.design.version!=='forward-stock-risk-v1.1' || d.design.minimum_per_cohort_per_ticker!==20 ||
        d.design.rolling_entry_sessions!==126 || d.design.holding_sessions!==5 || d.design.reference_lag_sessions!==1 ||
        d.design.adverse_move_threshold!==.03) throw Error('Unexpected research definition');
    if (d.rolling.length!==h.tickers.BAC.daily_rows.length) throw Error('Missing research dates');
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
  const api={check,charts,interpretation,review,alpha,cost};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  root.WheelThesis=api;
  if(typeof document==='undefined')return;
  const el=id=>document.getElementById(id);
  async function get(url){const r=await fetch(url,{cache:'no-store'});if(!r.ok)throw Error('Research data unavailable');return r.json();}
  function show(d,h,s) {
    check(d,h);
    const aligned=s.status==='success'&&s.market_snapshot_sha256===d.market_snapshot_sha256&&s.calendar?.as_of===d.window.analysis_end;
    el('thesis-status').textContent=`Observed sample ${d.window.analysis_start} to ${d.window.analysis_end}. LSEG retrieved ${d.market_retrieved_at}; tracker generated ${d.generated_at}. ${aligned?'Source snapshot matches the latest successful order evaluation.':'Retained historical snapshot; not a verified current order evaluation.'} Only completed paths contribute; the most recent six signal dates cannot yet mature.`;
    el('thesis-reading').textContent=interpretation(d);
    el('thesis-review').textContent=review(d);
    el('thesis-alpha').textContent=alpha(d);
    el('thesis-cost').textContent=cost(d);
    const body=el('thesis-summary');body.replaceChildren();
    for(const t of names){const z=d.full_sample.tickers[t];const tr=document.createElement('tr');
      [t,`${z.pass.n} / ${z.fail.n}`,...['mean_return','return_sd','mean_adverse','tail_rate'].map(k=>`${pct(z.pass[k])} / ${pct(z.fail[k])}`)].forEach((v,i)=>{const c=document.createElement(i?'td':'th');c.textContent=v;tr.append(c);});body.append(tr);}
    el('thesis-coverage').textContent=names.map(t=>{const c=d.coverage[t];return `${t}: ${c.observed||0} observed paths, ${c.unmatured||0} pending, ${c.missing_path||0} missing-price paths and ${c.signal_unavailable||0} unavailable signals`;}).join('; ')+'. Exclusions are not zero returns.';
    el('thesis-prospective').textContent=`Since design registration (${d.design.registered_on}): ${d.prospective.aggregate.pass_n} mature pass paths / ${d.prospective.aggregate.fail_n} mature fail paths. ${d.prospective.aggregate.sufficient?'The separately recorded prospective sample meets the minimum cohort sizes.':'Prospective validation is still accumulating; the retrospective sample is not relabeled as a live test.'}`;
    const draw=()=>charts(d,el('thesis-ticker').value).forEach(c=>{
      const target=el(c.id);
      if(!root.Plotly){target.textContent='Chart library unavailable. Validated results remain in the table and downloads.';return;}
      try{Promise.resolve(root.Plotly.react(target,c.traces,c.layout,{responsive:true,displayModeBar:false})).catch(()=>{target.textContent='Chart unavailable; see the data table and downloads.';});}
      catch(_){target.textContent='Chart unavailable; see the data table and downloads.';}
    });
    el('thesis-ticker').addEventListener('change',draw);draw();
  }
  Promise.all([get('data/thesis_tracker.json'),get('../docs/data/historical_signals.json'),get('../docs/data/strategy_status.json').catch(()=>({}))])
    .then(([d,h,s])=>show(d,h,s)).catch(()=>{
      el('thesis-status').textContent='Research data unavailable or inconsistent with the historical source. No result is substituted; reload after the nightly publication completes.';
    });
})(typeof window!=='undefined'?window:globalThis);
