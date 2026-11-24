(function(root){
  'use strict';
  const tickers=['BAC','KO','PFE','F'];
  const pct=x=>Number.isFinite(x)?`${(100*x).toFixed(2)}%`:'Unavailable';
  const pp=x=>Number.isFinite(x)?`${(100*x).toFixed(2)} pp`:'Unavailable';
  const interval=(x,points=false)=>x?`[${(points?pp:pct)(x[0])}, ${(points?pp:pct)(x[1])}]`:'Unavailable';
  const probability=log=>log < -690?`${(log/Math.LN10).toFixed(1)} log₁₀ probability`:
    Math.exp(log)<.0001?Math.exp(log).toExponential(2):pct(Math.exp(log));
  const reason=x=>x.ci95?interval(x.ci95):({insufficient_original_cohort:'Insufficient cohort',no_observed_outcome_variation:'No observed variation; interval withheld',too_many_empty_resampled_cohorts:'Too many empty resamples',degenerate_resampling_interval:'Degenerate resampling; interval withheld'}[x.reason]||'Unavailable');
  function kl(q,p){
    if(!Number.isFinite(q)||!Number.isFinite(p)||q<0||q>1||p<0||p>1)throw Error('Invalid probabilities');
    if(q===p)return 0;if(p===0||p===1)return Infinity;
    return Math.max(0,(q?q*Math.log1p((q-p)/p):0)+(q<1?(1-q)*Math.log1p((p-q)/(1-p)):0));
  }
  function logBound(n,mu,t,tail='lower'){
    if(!Number.isInteger(n)||n<1||!Number.isFinite(mu)||mu<=0||mu>=1||!['lower','upper'].includes(tail))throw Error('Positive sample size and 0 < μ < 1 required.');
    if(!Number.isFinite(t)||t<0||t>=(tail==='lower'?mu:1-mu))throw Error(tail==='lower'?'Lower tail requires 0 ≤ t < μ.':'Upper tail requires 0 ≤ t < 1 − μ.');
    return t===0?0:-n*kl(tail==='lower'?mu-t:mu+t,mu);
  }
  function check(d){
    const r=d.reliability;
    if(!r||r.market_snapshot_sha256!==d.market_snapshot_sha256||r.as_of!==d.window.analysis_end||r.design.version!=='reliability-v1'||r.design.bootstrap_replicates!==5000)throw Error('Statistical evidence generation does not match tracker.');
    if(r.design.primary_daily_block!==14||r.design.primary_nonoverlap_block!==2||r.design.nonoverlap_anchor!=='2023-11-24'||r.design.stride_sessions!==7||r.design.confidence_level!==.95||r.design.minimum_per_cohort!==20||JSON.stringify(r.design.daily_block_lengths)!=='[7,14,28]'||JSON.stringify(r.design.nonoverlap_block_lengths)!=='[1,2,4]')throw Error('Statistical design mismatch.');
    const number=(x,lo,hi)=>Number.isFinite(x)&&x>=lo&&x<=hi;
    const bounds=(x,lo,hi)=>Array.isArray(x)&&x.length===2&&x.every(v=>number(v,lo,hi))&&x[0]<=x[1];
    for(const mode of ['daily','nonoverlap']){
      const sample=r.samples[mode];
      for(const t of tickers){
        const z=sample.tickers[t];
        for(const group of ['filtered','unfiltered']){
          const g=z.groups[group];
          if(!Number.isInteger(g.n)||!Number.isInteger(g.events)||g.n<0||g.events<0||g.events>g.n||(g.n?(!number(g.frequency,0,1)||!number(g.mean_adverse,0,1)||Math.abs(g.frequency-g.events/g.n)>1e-12||!bounds(g.iid_kl95_scenario,0,1)):(g.frequency!==null||g.mean_adverse!==null||g.iid_kl95_scenario!==null)))throw Error('Frequency/count mismatch.');
          if(mode==='daily'){
            const old=d.full_sample.tickers[t][group==='filtered'?'pass':'all'];
            if(g.n!==old.n||Math.abs(g.frequency-old.tail_rate)>1e-12||Math.abs(g.mean_adverse-old.mean_adverse)>1e-12)throw Error('Original tracker mismatch.');
          }
        }
        if(z.groups.filtered.n>z.groups.unfiltered.n)throw Error('Filtered is not a subset.');
        for(const [key,metric] of [['frequency_difference','frequency'],['downside_difference','mean_adverse']]){
          if(z.groups.filtered.n?(!number(z[key],-1,1)||Math.abs(z[key]-(z.groups.unfiltered[metric]-z.groups.filtered[metric]))>1e-12):z[key]!==null)throw Error('Difference sign mismatch.');
        }
      }
      const expected=mode==='daily'?r.design.daily_block_lengths:r.design.nonoverlap_block_lengths;
      if(JSON.stringify(sample.sensitivity.map(x=>x.block_length))!==JSON.stringify(expected))throw Error('Missing block sensitivity.');
      for(const b of sample.sensitivity){if(b.status!=='computed')continue;
        for(const t of tickers){const z=b.tickers[t];
          for(const [c,lo] of [[z.groups.filtered,0],[z.groups.unfiltered,0],[z.frequency_difference,-1],[z.downside_difference,-1]]){
            if(c.valid_replicates<0||c.valid_replicates>5000||!Number.isInteger(c.valid_replicates))throw Error('Invalid bootstrap count.');
            if(c.ci95===null){if(!['insufficient_original_cohort','no_observed_outcome_variation','too_many_empty_resampled_cohorts','degenerate_resampling_interval'].includes(c.reason))throw Error('Missing interval reason.');}
            else if(!bounds(c.ci95,lo,1)||c.ci95[1]-c.ci95[0]<=1e-14||c.reason!==null||c.valid_replicates<4750)throw Error('Invalid interval.');
          }
        }
      }
    }
    return r;
  }
  function primary(r,mode){return r.samples[mode].sensitivity.find(x=>x.block_length===(mode==='daily'?r.design.primary_daily_block:r.design.primary_nonoverlap_block));}
  function outcome(c){return !c?.ci95?'uncertainty could not be estimated':c.ci95[0]>0?'the pointwise interval favors lower risk after filtering':c.ci95[1]<0?'the pointwise interval favors higher risk after filtering':'the interval includes zero; an apparent improvement could be due to sampling variation';}
  function model(r,ticker='BAC',group='filtered',mode='daily',mu=.2,t=.05,tail='lower'){
    if(!tickers.includes(ticker)||!['filtered','unfiltered'].includes(group)||!['daily','nonoverlap'].includes(mode))throw Error('Invalid sample selection.');
    const g=r.samples[mode].tickers[ticker].groups[group];
    const n=g.n,log=logBound(n,mu,t,tail),q=tail==='lower'?mu-t:mu+t;
    const rawRequired=kl(q,mu)===0?null:Math.ceil(Math.log(20)/kl(q,mu));
    const required=Number.isSafeInteger(rawRequired)?rawRequired:null;
    const nx=Array.from({length:200},(_,i)=>1+Math.round(i*(Math.max(1000,2*n)-1)/199));
    const tx=Array.from({length:201},(_,i)=>i/200*(tail==='lower'?mu:1-mu)*.999);
    const line=(x,y,name)=>({type:'scatter',mode:'lines',x,y,name,line:{color:'#255b87',width:2.5},hovertemplate:'%{x:.4g}<br>Bound %{y:.4g}<extra>%{fullData.name}</extra>'});
    const marker=(x)=>({type:'scatter',mode:'markers',x:[x],y:[Math.exp(Math.max(-300*Math.LN10,log))],name:'Selected scenario',marker:{size:9,color:'#946d38'},hovertemplate:'%{x:.4g}<br>Bound %{y:.4g}<extra>Selected scenario</extra>'});
    const layout=(label)=>({height:340,paper_bgcolor:'#fff',plot_bgcolor:'#fff',font:{family:'system-ui',color:'#182b3a',size:11},margin:{l:65,r:16,t:15,b:85},xaxis:{title:{text:label},gridcolor:'#eaf0f4'},yaxis:{type:'log',title:{text:'Probability bound (log scale)'},gridcolor:'#eaf0f4',exponentformat:'power'},legend:{orientation:'h',y:-.30,x:0},hovermode:'closest'});
    const plots=[
      {id:'reliability-n-chart',traces:[line(nx,nx.map(x=>Math.exp(Math.max(-300*Math.LN10,logBound(x,mu,t,tail)))),'Independent-sample bound'),marker(n)],layout:layout('Number of observations n')},
      {id:'reliability-t-chart',traces:[line(tx,tx.map(x=>Math.exp(Math.max(-300*Math.LN10,logBound(n,mu,x,tail)))),'Independent-sample bound'),marker(t)],layout:layout('Error tolerance t (probability)')}
    ];
    const ci=primary(r,mode)?.tickers?.[ticker]?.groups[group];
    const non=r.samples.nonoverlap.tickers[ticker].groups[group];
    const hypothesis=g.frequency<mu?`The actual frequency is below the hypothetical μ: the correct tail at X̄ = ${pct(g.frequency)} would have theoretical bound ${probability(-n*kl(g.frequency,mu))}. This is not a valid p-value for these dependent observations.`:
      'The observed frequency is not below the hypothetical μ, so it is not evidence from the lower tail for a lower true probability.';
    const nText=[
      `${ticker}, ${group}, ${mode==='daily'?'daily overlapping':'fixed non-overlapping'} sample: ${g.events} declines in ${n} observed paths (${pct(g.frequency)}). With hypothetical μ = ${pct(mu)} and t = ${pp(t)}, the ${tail}-tail threshold is ${pct(q)} and the bound at n = ${n} is ${probability(log)}. The observed frequency ${tail==='lower'?g.frequency<=q?'falls':'does not fall':g.frequency>=q?'falls':'does not fall'} in that selected tail event. The marker is a hypothetical calculation; μ is an input, not a known truth or the sample mean.`,
      required===null?(t===0?'At t = 0 the bound is 1 regardless of n, so it gives no useful concentration information.':'This tolerance is below numerical resolution for a useful concentration calculation; no required sample size is inferred.'):`Under independence, this scenario first has a bound no greater than 5% at n = ${required}. The actual count is ${n}, but it cannot be used as ${n} independent trials. The fixed non-overlapping version has only ${non.n} observations; serial dependence can remain there too.`,
      ci?`The empirical block-bootstrap 95% interval for this group's decline frequency is ${reason(ci)}${ci.ci95?`, a width of ${pp(ci.ci95[1]-ci.ci95[0])}`:''}. This interval, the event count and the block sensitivity are more informative about adequacy than whether the raw count clears the theoretical sample-size line.`:'The empirical interval is unavailable; the theoretical curve does not replace it.',
      'A large sample reduces random error only under an appropriate model. These selected historical frequencies describe the sampled conditions and stocks; they do not establish a stable future risk or an option premium advantage.'
    ];
    const tText=[
      `This curve holds the actual sample count at ${n} and hypothetical μ at ${pct(mu)}. At t = ${pp(t)}, it bounds Pr(X̄ ${tail==='lower'?'≤':'≥'} ${pct(q)}) by ${probability(log)} under independence. Increasing t makes the event more extreme, which reduces its bound; it does not make the data more precise.`,
      hypothesis,
      `Observed frequency ${pct(g.frequency)} is based on ${g.events} events. Inverting the two one-sided KL bounds gives ${interval(g.iid_kl95_scenario)} only in an independent-Bernoulli scenario. The 95% level uses ln(40) and does not mean a 95% probability that the thesis is true.`,
      `For the actual ${ticker} filtered-versus-unfiltered frequency difference, ${outcome(primary(r,mode)?.tickers?.[ticker]?.frequency_difference)}. The comparison uses a paired bootstrap because the two groups overlap; the scenario slider is not a test of whether the strategy is profitable.`
    ];
    return {plots,nText,tText};
  }
  function findings(r,mode){
    const sample=r.samples[mode],base=primary(r,mode),other=mode==='daily'?'nonoverlap':'daily',alternative=primary(r,other);
    const text=[`As of ${r.as_of}, this ${mode==='daily'?'daily':'non-overlapping'} analysis has ${sample.matured_dates.length} matured scheduled date slots. Sample sizes below are per stock, never added into an independent four-stock sample. Primary bootstrap blocks contain ${base.block_length} ${mode==='daily'?'trading dates':'seven-session-spaced slots'}. Positive differences mean lower observed risk after filtering.`];
    for(const t of tickers){
      const z=sample.tickers[t],c=base.tickers?.[t],o=r.samples[other].tickers[t],oc=alternative.tickers?.[t];
      const excluded=Object.entries(z.excluded).map(([k,n])=>`${n} ${k.replaceAll('_',' ')}`).join(', ')||'none';
      text.push(`${t}: filtered ${z.groups.filtered.events}/${z.groups.filtered.n} (${pct(z.groups.filtered.frequency)}) versus unfiltered ${z.groups.unfiltered.events}/${z.groups.unfiltered.n} (${pct(z.groups.unfiltered.frequency)}). The frequency reduction is ${pp(z.frequency_difference)}, with 95% interval ${interval(c?.frequency_difference.ci95,true)}; ${outcome(c?.frequency_difference)}. Mean downside reduction is ${pp(z.downside_difference)}, interval ${interval(c?.downside_difference.ci95,true)}. Excluded or pending scheduled paths: ${excluded}.`);
      text.push(`In the ${other==='daily'?'daily':'fixed non-overlapping'} check, ${t} has ${o.groups.filtered.n} filtered and ${o.groups.unfiltered.n} unfiltered observations. Its frequency reduction is ${pp(o.frequency_difference)}, interval ${interval(oc?.frequency_difference.ci95,true)}; ${outcome(oc?.frequency_difference)}. Mean downside reduction is ${pp(o.downside_difference)}, interval ${interval(oc?.downside_difference.ci95,true)}. Removing overlap changes the sampled dates as well as the count; it is a robustness check, not a replacement result chosen after seeing which looks better.${z.sparse_event_warning||o.sparse_event_warning?' At least one design has fewer than five events or non-events in a pass/fail cohort: rare-event percentile coverage is particularly uncertain, even when the observation-count floor is met.':''}`);
    }
    const supported=tickers.filter(t=>base.tickers?.[t]?.frequency_difference.ci95?.[0]>0);
    const adverse=tickers.filter(t=>base.tickers?.[t]?.frequency_difference.ci95?.[1]<0);
    text.push(`Across the four stocks, the primary pointwise frequency interval is wholly favorable for ${supported.join(', ')||'none'} and wholly adverse for ${adverse.join(', ')||'none'}; the remaining intervals include zero or are unavailable. I do not interpret a favorable result in one stock as a general four-stock edge.`);
    const conclusions=b=>tickers.map(t=>outcome(b.tickers?.[t]?.frequency_difference)+' / '+outcome(b.tickers?.[t]?.downside_difference)).join('|');
    const stable=sample.sensitivity.every(b=>conclusions(b)===conclusions(base));
    text.push(stable?'The zero-inclusion classifications for both endpoints are unchanged across the three chosen block lengths. Their widths still differ, and agreement within this sensitivity set does not validate stationarity.':'At least one zero-inclusion classification changes with block length. That sensitivity weakens a firm statistical conclusion; I report all lengths rather than selecting the most favorable one.');
    text.push('My confidence remains provisional. Counts above 20 make estimation possible, not necessarily precise; non-overlapping counts are smaller and dependence can persist. Intervals containing zero leave chance as a plausible explanation for an apparent improvement. Even an interval excluding zero is exploratory, not causal evidence or a multiple-testing-adjusted finding. This assesses H1 only; H2 still requires matched option prices, payoffs, idle capital and costs.');
    return text;
  }
  function show(d){
    const el=id=>document.getElementById(id);
    const paragraphs=(id,texts)=>{const node=el(id);node.replaceChildren();for(const text of texts){const p=document.createElement('p');p.textContent=text;node.append(p);}};
    const table=(id,rows)=>{el(id).replaceChildren();for(const row of rows){const tr=document.createElement('tr');row.forEach((x,i)=>{const td=document.createElement(i?'td':'th');td.textContent=x;tr.append(td);});el(id).append(tr);}};
    let r;try{r=check(d);}catch(e){el('reliability-status').textContent='Statistical extension unavailable or inconsistent; no result substituted.';return;}
    const expanded=d.lecture_extension?.historical?.expanded;
    el('reliability-expanded-option').disabled=!expanded;
    const chartMessages=new Set();
    const purge=()=>{for(const id of ['reliability-n-chart','reliability-t-chart']){if(root.Plotly?.purge)root.Plotly.purge(el(id));el(id).textContent='Choose a valid theory scenario to draw this chart.';chartMessages.add(id);}};
    const draw=()=>{
      const five=el('reliability-window').value==='expanded';
      const context=five&&expanded?{...d,window:expanded.window,full_sample:expanded.full_sample,reliability:expanded.reliability,market_snapshot_sha256:expanded.market_snapshot_sha256}:d;
      r=check(context);
      const mode=el('reliability-sampling').value,base=primary(r,mode),sample=r.samples[mode];
      el('reliability-status').textContent=`${five?'Fixed five-year':'Original three-year'} LSEG sample: ${context.window.analysis_start}–${context.window.analysis_end}; tracker built ${d.generated_at}. ${r.design.bootstrap_replicates.toLocaleString('en-US')} joint-date draws per block length. Original classroom wording remains unverified. Empirical results below do not change when hypothetical μ or t changes.`;
      table('reliability-samples',tickers.flatMap(t=>['filtered','unfiltered'].map(g=>{const z=sample.tickers[t].groups[g],c=base.tickers?.[t]?.groups[g];return [t,g==='filtered'?'Filtered':'Unfiltered',`${z.events} / ${z.n}`,pct(z.frequency),c?reason(c):'Insufficient dates',c?.ci95?pp(c.ci95[1]-c.ci95[0]):'Unavailable',interval(z.iid_kl95_scenario)];})));
      table('reliability-sensitivity',tickers.flatMap(t=>sample.sensitivity.map(b=>{const z=sample.tickers[t],c=b.tickers?.[t];return [t,`${b.block_length}${b.block_length===base.block_length?' · primary':''}`,`${pp(z.downside_difference)} / ${interval(c?.downside_difference.ci95,true)}`,`${pp(z.frequency_difference)} / ${interval(c?.frequency_difference.ci95,true)}`,c?`${c.downside_difference.valid_replicates} / ${c.frequency_difference.valid_replicates}`:'Insufficient dates'];})));
      paragraphs('reliability-findings',findings(r,mode));
      try{
        const rawMu=el('reliability-mu').value,rawT=el('reliability-tolerance').value;
        if(!rawMu.trim()||!rawT.trim())throw Error('Enter both hypothetical μ and tolerance t.');
        const m=model(r,el('reliability-ticker').value,el('reliability-group').value,mode,Number(rawMu),Number(rawT),el('reliability-tail').value);
        el('reliability-error').hidden=true;el('reliability-error').textContent='';
        paragraphs('reliability-n-analysis',m.nText);paragraphs('reliability-t-analysis',m.tText);
        for(const c of m.plots){const node=el(c.id);if(!root.Plotly){node.textContent='Chart library unavailable. All sample statistics remain in the tables.';chartMessages.add(c.id);continue;}
          if(chartMessages.has(c.id)){node.replaceChildren();chartMessages.delete(c.id);}
          Promise.resolve(root.Plotly.react(node,c.traces,c.layout,{responsive:true,displayModeBar:false})).catch(()=>{node.textContent='Theory chart unavailable; the empirical tables remain valid.';chartMessages.add(c.id);});}
      }catch(e){el('reliability-error').hidden=false;el('reliability-error').textContent=e.message;purge();paragraphs('reliability-n-analysis',['No theoretical calculation is shown for this invalid or empty-sample scenario.']);paragraphs('reliability-t-analysis',['Empirical tables remain unchanged; an invalid tolerance is not clipped into a different hypothesis.']);}
    };
    for(const id of ['window','ticker','group','sampling','tail','mu','tolerance'])el('reliability-'+id).addEventListener(['mu','tolerance'].includes(id)?'input':'change',draw);
    draw();
  }
  const api={kl,logBound,check,primary,model,findings,show};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  root.WheelReliability=api;
})(typeof window!=='undefined'?window:globalThis);
