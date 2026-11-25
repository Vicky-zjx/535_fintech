/* Existing five-year payoff summaries + explicit premium scenarios. No fetch,
   prices, fills, strategy edits, new bootstrap draws or estimated market alpha. */
(function(root){
  'use strict';
  const tickers=['BAC','KO','PFE','F'];
  const premiums=[10,25,50,75,100,150];
  const ratios=['1.0','0.98','0.95','0.9'];
  const bp=x=>x===null?'No excluded opportunities':(x*10000).toFixed(2);
  const pct=x=>(x*100).toFixed(1)+'%';
  const mean=a=>a.reduce((s,x)=>s+x,0)/a.length;
  const close=(a,b)=>Number.isFinite(a)&&Number.isFinite(b)&&Math.abs(a-b)<1e-10;
  function coefficients(d,ratio){
    const p=d.lecture_extension?.hypothetical_put_payoff;
    if(!ratios.includes(ratio)||p?.kind!=='hypothetical_put_payoff_not_option_backtest'||
       p.estimated_option_alpha!==null||p.premium_observations!==0)throw Error('Invalid hypothetical study');
    return tickers.map(t=>{
      const z=p.tickers?.[t]?.[ratio],u=z?.unfiltered,f=z?.filtered;
      if(!u||!f||!Number.isInteger(u.n)||u.n<=0||!Number.isInteger(f.n)||f.n<0||f.n>u.n||
         u.n!==p.scheduled_mature_weeks||u.n!==z.valid_weekly_opportunities)
        throw Error('Incomplete weekly coverage: no missing week is treated as zero');
      for(const g of [u,f]){
        if(!g.n)continue;
        for(const k of ['mean_loss','mean_cost','break_even_after_cost'])
          if(!Number.isFinite(g[k])||g[k]<0)throw Error('Missing or invalid payoff summary');
        if(!close(g.break_even_after_cost,g.mean_loss+g.mean_cost))throw Error('Inconsistent cost accounting');
      }
      const q=f.n/u.n,filteredLoss=f.n?q*f.mean_loss:0,filteredCost=f.n?q*f.mean_cost:0;
      if(!Number.isFinite(z.eligible_frequency)||!close(q,z.eligible_frequency))throw Error('Inconsistent frequency');
      const lossAvoided=u.mean_loss-filteredLoss,costSaved=u.mean_cost-filteredCost;
      if(lossAvoided< -1e-10||costSaved< -1e-10||
         (!close(z.weekly_break_even_reduction,lossAvoided+costSaved)))throw Error('Invalid nested cohort accounting');
      if(q===1&&(!close(lossAvoided,0)||!close(costSaved,0)))throw Error('No excluded cohort but different liability');
      return {ticker:t,n:u.n,selected:f.n,q,unfilteredLoss:u.mean_loss,unfilteredCost:u.mean_cost,
              filteredLoss,filteredCost,lossAvoided,costSaved};
    });
  }
  function scenario(c,premiumBp){
    const p=premiumBp/10000;
    const unfiltered=p-c.unfilteredLoss-c.unfilteredCost;
    const filtered=c.q*p-c.filteredLoss-c.filteredCost;
    const excluded=1-c.q;
    return {...c,premiumBp,unfiltered,filtered,advantage:filtered-unfiltered,
      premiumForgone:excluded*p,
      excludedBreakEvenBefore:excluded?c.lossAvoided/excluded:null,
      excludedBreakEvenAfter:excluded?(c.lossAvoided+c.costSaved)/excluded:null};
  }
  function model(d,ratio='0.95',premiumBp=50){
    if(!premiums.includes(premiumBp))throw Error('Unregistered premium scenario');
    const stocks=coefficients(d,ratio);
    // Equal-weight normalized sleeves, NOT q_bar times a mean conditional cost.
    const equal={ticker:'Equal-weight average',n:stocks[0].n,selected:null};
    for(const k of ['q','unfilteredLoss','unfilteredCost','filteredLoss','filteredCost','lossAvoided','costSaved'])
      equal[k]=mean(stocks.map(c=>c[k]));
    const series=[...stocks,equal].map(c=>({ticker:c.ticker,points:premiums.map(p=>scenario(c,p))}));
    const rows=series.map(s=>s.points.find(r=>r.premiumBp===premiumBp));
    const colors=['#255b87','#37806b','#b06a2c','#865a88','#182b3a'];
    const avg=rows[4],sign=x=>x<0?'negative':x>0?'positive':'zero';
    const analysis=[
      `At the assumed ${premiumBp} bp premium and ${Number(ratio)*100}% strike-to-signal-spot ratio, the equal-weight weekly result is ${bp(avg.filtered)} bp with filters versus ${bp(avg.unfiltered)} bp without filters: a ${sign(avg.advantage)} advantage of ${bp(avg.advantage)} bp. These are sample-average scenario calculations, not a forecast, a funded portfolio or risk-adjusted alpha.`,
      ...rows.slice(0,4).map(r=>`${r.ticker}: ${r.selected}/${r.n} weeks qualify (${pct(r.q)}). Filtering gives up ${bp(r.premiumForgone)} bp of premium per weekly opportunity, avoids ${bp(r.lossAvoided)} bp of expiry liability and saves ${bp(r.costSaved)} bp of assumed costs. The net advantage is ${bp(r.advantage)} bp. ${r.advantage>0&&r.filtered<0?`Both scenarios still lose money here (${bp(r.filtered)} bp filtered versus ${bp(r.unfiltered)} bp unfiltered): the positive advantage means a smaller loss, not a profit. `:''}${r.excludedBreakEvenAfter===null?'No weeks are excluded.':`The excluded opportunities break even at ${bp(r.excludedBreakEvenAfter)} bp of premium after costs.`}`),
      `Lines slope downward when opportunities are excluded because a higher assumed premium makes skipped trades more costly. Under the same-premium assumption, filtering helps only below the excluded opportunities' after-cost break-even premium; above it, lost premium exceeds the saved liability and costs. ${avg.excludedBreakEvenAfter===null?'No opportunities are excluded, so there is no crossover premium.':`The equal-weight crossover is ${bp(avg.excludedBreakEvenAfter)} bp, weighted by excluded opportunity shares, not the simple mean of four crossover premiums.`}`,
      'Actual premiums may be higher precisely in risky weeks, and the historical loss means are uncertain. These lines do not resolve either issue. No new confidence claim is made: the earlier block-bootstrap findings and adverse results remain relevant. Skipped weeks contribute zero incremental option P&L, not a measured zero return on cash.'
    ];
    return {rows,series,analysis,traces:series.map((s,i)=>({type:'scatter',mode:'lines+markers',name:s.ticker,
      x:premiums,y:s.points.map(p=>p.advantage*10000),connectgaps:false,
      customdata:s.points.map(p=>[p.unfiltered*10000,p.filtered*10000,p.q*100]),
      line:{color:colors[i],width:i===4?3:2,dash:i===4?'dash':'solid'},marker:{size:i===4?7:5},
      hovertemplate:'Premium: %{x} bp<br>Unfiltered: %{customdata[0]:.2f} bp/week<br>Filtered: %{customdata[1]:.2f} bp/week<br>Advantage: %{y:.2f} bp/week<br>Eligible weeks: %{customdata[2]:.1f}%<extra>%{fullData.name}</extra>'})),
      layout:{height:470,margin:{l:65,r:16,t:115,b:65},paper_bgcolor:'#fff',plot_bgcolor:'#fff',
        font:{family:'system-ui',color:'#182b3a'},hovermode:'closest',
        legend:{orientation:'h',x:0,y:1,yanchor:'bottom',font:{size:12}},
        xaxis:{title:{text:'Assumed premium / collateral (bp)'},tickmode:'array',tickvals:premiums},
        yaxis:{title:{text:'Net advantage (bp / week)'},zeroline:true,zerolinecolor:'#506575',zerolinewidth:2},
        shapes:[{type:'line',xref:'x',x0:premiumBp,x1:premiumBp,yref:'paper',y0:0,y1:1,line:{color:'#a7b9c8',width:1,dash:'dot'}}]}};
  }
  function show(d){
    const el=id=>document.getElementById(id);
    const plot=el('rough-alpha-chart');let generation=0;
    const draw=()=>{
      const version=++generation;
      try{
        const m=model(d,el('rough-alpha-ratio').value,Number(el('rough-alpha-premium').value));
        const window=d.lecture_extension.hypothetical_put_payoff.window;
        el('rough-alpha-status').textContent=`Fixed five-year study (${window.start} to ${window.end}): ${m.rows[0].n} mature weekly opportunities per stock. Table premium: ${m.rows[0].premiumBp} bp. All six assumptions appear in the chart; toggle lines in the legend or hover for both strategy returns.`;
        const rows=el('rough-alpha-results');rows.replaceChildren();
        for(const r of m.rows){
          const tr=document.createElement('tr');
          [r.ticker,r.selected===null?pct(r.q)+ ' mean':`${r.selected}/${r.n} (${pct(r.q)})`,bp(r.unfiltered),bp(r.filtered),bp(r.advantage),bp(r.excludedBreakEvenBefore)+' / '+bp(r.excludedBreakEvenAfter)].forEach((v,i)=>{
            const cell=document.createElement(i?'td':'th');cell.textContent=v;tr.append(cell);
          });rows.append(tr);
        }
        const text=el('rough-alpha-analysis');text.replaceChildren();
        for(const sentence of m.analysis){const p=document.createElement('p');p.textContent=sentence;text.append(p);}
        const fallback=()=>{if(version===generation)plot.textContent='Chart library unavailable; the complete calculated table and analysis remain available.';};
        if(root.Plotly)Promise.resolve(root.Plotly.react(plot,m.traces,m.layout,{responsive:true,displayModeBar:false})).catch(fallback);
        else fallback();
      }catch(_){
        el('rough-alpha-status').textContent='Sensitivity unavailable: incomplete or inconsistent fixed-study summaries. No missing week is replaced with zero.';
        el('rough-alpha-results').replaceChildren();el('rough-alpha-analysis').replaceChildren();
        if(root.Plotly?.purge)root.Plotly.purge(plot);
        plot.textContent='No sensitivity result substituted. Other research results are unchanged.';
      }
    };
    el('rough-alpha-ratio').addEventListener('change',draw);
    el('rough-alpha-premium').addEventListener('change',draw);draw();
  }
  const api={premiums,coefficients,scenario,model,show};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  root.WheelRoughAlpha=api;
})(typeof window!=='undefined'?window:globalThis);
