(function(root){
  'use strict';
  const tickers=['BAC','KO','PFE','F'];
  const bp=x=>Number.isFinite(x)?(x*10000).toFixed(2):'Not estimable';
  const pct=x=>Number.isFinite(x)?(x*100).toFixed(2)+'%':'Not estimable';
  const pp=x=>Number.isFinite(x)?(x*100).toFixed(3):'Not estimable';
  const ci=(x,format=bp)=>x?.ci95?x.ci95.map(format).join(' to '):'Withheld: no loss variation or insufficient sample';
  function check(d){
    const p=d.lecture_extension?.hypothetical_put_payoff;
    if(p?.kind!=='hypothetical_put_payoff_not_option_backtest'||p.estimated_option_alpha!==null||p.premium_observations!==0)throw Error('Invalid economic study');
    for(const t of tickers)for(const r of ['1.0','0.98','0.95','0.9']){
      const z=p.tickers[t][r],u=z.unfiltered,f=z.filtered,q=z.eligible_frequency;
      if(u.n!==z.valid_weekly_opportunities||f.n>u.n||Math.abs(q-f.n/u.n)>1e-12)throw Error('Invalid opportunity counts');
      for(const g of [u,f])if(Math.abs(g.break_even_after_cost-g.mean_loss-g.mean_cost)>1e-12||
        Math.abs(g.positive_loss_frequency-g.positive_loss_events/g.n)>1e-12)throw Error('Invalid payoff accounting');
      if(Math.abs(z.weekly_filtered_break_even-q*f.break_even_after_cost)>1e-12||
        Math.abs(z.weekly_break_even_reduction-(u.break_even_after_cost-q*f.break_even_after_cost))>1e-12)throw Error('Ignored idle weeks');
    }
    return p;
  }
  function model(d,ratio='0.95',block=4){
    const p=check(d);if(!['1.0','0.98','0.95','0.9'].includes(ratio)||![2,4,8].includes(block))throw Error('Invalid scenario');
    const conditional=[],weekly=[],analysis=[],budget=[];
    const texts=['The fixed five-year sample has '+p.scheduled_mature_weeks+' mature weekly opportunities per stock and one not-yet-matured final opportunity. No price is substituted for the latter. The chart shows '+pct(Number(ratio))+' of the prior signal close, not observed market contracts.'];
    for(const t of tickers){
      const z=p.tickers[t][ratio],u=z.unfiltered,f=z.filtered,c=z.sensitivity.find(b=>b.block_weeks===block);
      for(const [name,g] of [['Filtered',f],['Unfiltered',u]])conditional.push([t+' / '+name,g.n,pct(g.positive_loss_frequency),bp(g.mean_loss),bp(g.mean_positive_loss)+' / '+bp(g.maximum_loss),bp(g.break_even_before_cost)+' / '+bp(g.break_even_after_cost)]);
      weekly.push([t,pct(z.eligible_frequency)+' / '+pct(z.weekly_skipped_frequency),bp(z.weekly_filtered_loss)+' / '+bp(u.mean_loss),bp(z.weekly_filtered_break_even)+' / '+bp(u.break_even_after_cost),bp(z.weekly_break_even_reduction)+' / '+ci(c.weekly_break_even_reduction)]);
      const range=c.conditional_loss_reduction.ci95;
      analysis.push(`${t}: the mean terminal liability is ${bp(f.mean_loss)} bp with filters versus ${bp(u.mean_loss)} bp without them. The reduction is ${bp(z.conditional_loss_reduction)} bp (95% interval ${ci(c.conditional_loss_reduction)}, ${block}-week blocks). ${range?(range[0]>0?'This pointwise interval favors lower liability, not higher returns.':range[1]<0?'This pointwise interval favors higher liability after filtering.':'Zero is included: lower per-opportunity liability has not been established.'):'No uncertainty guarantee can be drawn from a degenerate or inadequate sample.'} ${z.sparse_loss_events?'There are fewer than five positive losses in at least one disjoint cohort; the interval can seriously understate unseen tail risk.':''}`);
      budget.push(`${t}: ${f.n}/${u.n} weeks qualify (${pct(z.eligible_frequency)}). Covering historical mean liability and the assumed cost requires ${bp(f.break_even_after_cost)} bp per selected opportunity, versus ${bp(u.break_even_after_cost)} bp without filtering. Across all weeks, the loss-and-cost saving is ${bp(z.weekly_break_even_reduction)} bp: this is the maximum average weekly premium I could give up before losing that arithmetic advantage, ignoring cash yield. It is not an observed premium discount. If every eligible and excluded week instead offered the same premium, the break-even comparison would cross at ${bp(z.equal_premium_crossover)} bp; actual premiums vary with risk and are unknown here.`);
    }
    texts.push(...analysis,'The weekly liability falls partly because the strategy takes less exposure. Skipping most weeks can reduce gross losses even if the selected weeks are no safer. Without the premiums on both selected and rejected opportunities, these data cannot measure economic value or option alpha.');
    return {conditional,weekly,analysis:texts,budget,
      traces:['filtered','unfiltered'].map((g,i)=>({type:'bar',name:i?'Unfiltered':'Filtered',x:tickers,y:tickers.map(t=>p.tickers[t][ratio][g].mean_loss*10000),marker:{color:i?'#a7b9c8':'#255b87'},hovertemplate:'%{x}: %{y:.2f} bp terminal liability<extra>%{fullData.name}</extra>'})),
      layout:{barmode:'group',height:360,margin:{l:65,r:18,t:15,b:50},paper_bgcolor:'#fff',plot_bgcolor:'#fff',font:{family:'system-ui',color:'#182b3a'},yaxis:{title:{text:'Loss / collateral (bp)'},rangemode:'tozero'},legend:{orientation:'h',y:1.16}}};
  }
  function findings(d){
    const x=d.lecture_extension,a=x.historical.expanded.ablation,stocks=a.samples.daily.tickers;
    const rows=tickers.map(t=>{const z=stocks[t].combined,c=z.sensitivity.find(b=>b.block_length===14);return [t,`${z.n} / ${z.benchmark_n}`,`${pp(z.downside_difference)} / ${ci(c.downside_difference,pp)}`,`${pp(z.frequency_difference)} / ${ci(c.frequency_difference,pp)}`];});
    const bac=a.samples.nonoverlap.tickers.BAC.combined;
    const text=[`Five years, ${x.historical.expanded.window.analysis_start}–${x.historical.expanded.window.analysis_end}: all four primary 95% intervals for the combined screen include zero for both mean downside and decline frequency. Lower risk is not statistically established. BAC's decline-frequency reduction reverses from ${pp(stocks.BAC.combined.frequency_difference)} pp on daily windows to ${pp(bac.frequency_difference)} pp on the predetermined non-overlapping schedule. Removing shared paths does not remove serial dependence.`,
      'Trend is the largest exclusion screen for all four stocks. Beyond trend, the other two filters exclude '+tickers.map(t=>`${stocks[t].trend.n-stocks[t].combined.n} additional ${t} paths`).join(', ')+'. PFE and F therefore retain incremental screening, but fewer trades do not prove an economic benefit. The combined screen excludes '+tickers.map(t=>`${pct(stocks[t].combined.exclusion_rate)} of ${t} daily opportunities`).join(', ')+'.',
      'The hypothetical put study below estimates a liability hurdle, not returns. BAC generally has lower conditional liability in these scenarios; KO, PFE and F do not show the same improvement. The actual option audit retains 137 dated bid/ask pairs and 23 contracts with an entry-to-expiry illustration, but lacks verified historical candidate membership and usable historical deltas. Actual option alpha remains unestimated.',
      'Registered review now: '+root.WheelThesis.conditions(d).map(c=>c[0]+': '+c[3].replace(/\.$/,'')).join('; ')+'. Insufficient evidence is not a passed test. H2 still needs comparable historical premiums, candidate availability and execution costs; confirmed trading performance also needs the professor’s filled-trade and account records.'];
    return {rows,text};
  }
  function interpretation(d){
    const a=d.lecture_extension.historical.expanded.ablation.samples.daily.tickers.F.combined;
    const z=check(d).tickers.F['0.95'],f=z.filtered,u=z.unfiltered;
    const uncertainty=z.sensitivity.find(b=>b.block_weeks===4).conditional_loss_reduction;
    return [
      `F illustrates the distinction. In the five-year daily study, the observed 3% decline frequency is ${pct(a.frequency)} with filters versus ${pct(a.frequency+a.frequency_difference)} without them. That favorable point estimate is uncertain. In the weekly 95% hypothetical-strike scenario, however, mean expiry liability rises from ${bp(u.mean_loss)} to ${bp(f.mean_loss)} bp of collateral after filtering. The dates, samples and outcomes differ: a daily path reaching a 3% decline is not the same event as a weekly put finishing in the money.`,
      `Within that weekly scenario, F's positive-loss frequency is ${pct(f.positive_loss_frequency)} (${f.positive_loss_events}/${f.n}) after filtering versus ${pct(u.positive_loss_frequency)} (${u.positive_loss_events}/${u.n}) without filtering. Mean loss conditional on a positive loss is also higher: ${bp(f.mean_positive_loss)} versus ${bp(u.mean_positive_loss)} bp. Thus both frequency and severity contribute to the higher weekly point estimate; the daily frequency result cannot be carried over to this payoff. The loss-reduction interval is ${ci(uncertainty)} bp at the primary four-week block length, so the difference remains uncertain.`,
      `Only ${f.n} of ${u.n} F weeks qualify (${pct(z.eligible_frequency)}). The break-even premium after assumed costs is ${bp(f.break_even_after_cost)} bp per selected opportunity versus ${bp(u.break_even_after_cost)} bp without filters. Skipping the other weeks avoids liabilities but also gives up unknown premiums. Without those premiums and a cash-return comparison, I cannot establish the filters' economic value. This is a hurdle calculation, not estimated alpha.`
    ];
  }
  function show(d){
    const el=id=>document.getElementById(id);
    function paragraphs(id,texts){el(id).replaceChildren();for(const text of texts){const p=document.createElement('p');p.textContent=text;el(id).append(p);}}
    function table(id,rows){el(id).replaceChildren();for(const r of rows){const tr=document.createElement('tr');r.forEach((v,i)=>{const td=document.createElement(i?'td':'th');td.textContent=String(v);tr.append(td);});el(id).append(tr);}}
    const f=findings(d);table('fixed-findings-table',f.rows);paragraphs('fixed-findings-text',f.text);
    paragraphs('payoff-interpretation',interpretation(d));
    const draw=()=>{const m=model(d,el('payoff-ratio').value,Number(el('payoff-block').value));
      table('payoff-conditional',m.conditional);table('payoff-weekly',m.weekly);paragraphs('payoff-analysis',m.analysis);paragraphs('payoff-budget',m.budget);
      if(root.Plotly)Promise.resolve(root.Plotly.react(el('payoff-chart'),m.traces,m.layout,{responsive:true,displayModeBar:false})).catch(()=>{el('payoff-chart').textContent='Chart unavailable; see the tables.';});
      else el('payoff-chart').textContent='Chart library unavailable; see the tables.';
    };el('payoff-ratio').addEventListener('change',draw);el('payoff-block').addEventListener('change',draw);draw();
  }
  const api={check,model,findings,interpretation,show};if(typeof module!=='undefined'&&module.exports)module.exports=api;root.WheelPayoff=api;
})(typeof window!=='undefined'?window:globalThis);
