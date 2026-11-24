"""Fixed weekly, hypothetical European terminal-put scenarios. NOT option trades.

No quotes, delta models, strike discovery, orders or parameter optimization.
All actual prices stay in the caller's private input; output contains summaries.
"""
from datetime import timedelta
import math
import numpy as np
import pandas as pd
import exchange_calendars as xcals
from final_project.data_provider import digest
from .reference import history
from .reliability import TICKERS, block_indices, interval
from .extension_plan import PLAN

RATIOS=(1., .98, .95, .90)
DESIGN=dict(version='hypothetical-put-payoff-v1',specified_on='2026-11-24',
    strike_to_signal_spot=list(RATIOS),cost_per_100_share_scenario=3.30,
    signal='Previous completed XNYS close before scheduled entry; unchanged production indicators.',
    schedule='Entry is the last XNYS session of each calendar week, normally Friday. Hypothetical expiry is the last XNYS session on/before the following Friday.',
    selection='One fixed opportunity per week, not first-passing-day selection or the actual daily order engine.',
    strike='Ratio times previous completed signal close; not a listed strike, entry-time ATM or a 25-delta contract.',
    horizon='Normally 6–8 calendar days; require 3–10. Use actual holiday/early-close calendar; no invented holiday prices.',
    payoff='max(K - expiry stock close, 0) / K; normalized collateral, not option return.',
    costs='Research budget $3.30 per standard 100-share scenario, not a broker quote or production fee change.',
    idle='A rejected opportunity has zero incremental option payoff/cost, NOT a measured zero cash return. No cash yield, equity curve, compounding, reinvestment or portfolio allocation is assumed.',
    bootstrap='Joint non-circular moving blocks of weekly opportunity dates; same indices across all stocks, ratios and nested groups.',
    block_weeks=[2,4,8],primary_block_weeks=4,replicates=5000,seed=5353124,
    uncertainty='Approximate pointwise percentile intervals; no multiplicity correction, stationarity or causal guarantee.',
    limitation='Terminal intrinsic only: excludes early exercise, assignment-stock holding, dividends, contract adjustments, market premiums and implied volatility. As-retrieved prices and survivor selection remain limitations.')


def observations(e):
    start,end=PLAN['extended_start'],PLAN['extended_end']
    h=history(e,start,end)
    cal=xcals.get_calendar('XNYS',start=str(pd.Timestamp(start)-pd.Timedelta(days=180)),
                          end=str(pd.Timestamp(end)+pd.Timedelta(days=21)))
    sessions=[str(d.date()) for d in cal.sessions]
    ix={d:i for i,d in enumerate(sessions)}
    def friday(day):return (day+timedelta(days=4-day.weekday())).isoformat()
    weeks={}
    for s in sessions:weeks[friday(pd.Timestamp(s).date())]=s
    entries=[s for _,s in sorted(weeks.items()) if start<=s<=end]
    signals={t:{r['signal_date']:r for r in h['tickers'][t]['daily_rows']} for t in TICKERS}
    prices={t:{r['date']:r['close'] for r in e['tickers'][t]['history']} for t in TICKERS}
    rows=[]
    for entry in entries:
        signal=sessions[ix[entry]-1]
        next_friday=(pd.Timestamp(friday(pd.Timestamp(entry).date()))+pd.Timedelta(days=7)).date()
        expiry=str(cal.date_to_session(str(next_friday),direction='previous').date())
        dte=(pd.Timestamp(expiry)-pd.Timestamp(entry)).days
        for t in TICKERS:
            s=signals[t].get(signal)
            for ratio in RATIOS:
                r=dict(ticker=t,ratio=ratio,entry_date=entry,signal_date=signal,expiry_date=expiry,
                       dte=dte,passed=s['eligible'] if s and s['valid'] else None,
                       status='observed',loss=None,cost=None)
                if expiry>end:r['status']='unmatured'
                elif not 3<=dte<=10:r['status']='horizon_unavailable'
                elif not s or not s['valid']:r['status']='signal_unavailable'
                elif any(prices[t].get(d) is None for d in (signal,expiry)):r['status']='price_unavailable'
                else:
                    strike=ratio*prices[t][signal]
                    r.update(loss=max(strike-prices[t][expiry],0)/strike,cost=3.30/(100*strike))
                rows.append(r)
    return rows


def group_stats(loss,cost):
    n=len(loss);events=sum(x>0 for x in loss)
    mean=lambda values:float(np.mean(values)) if len(values) else None
    return dict(n=n,positive_loss_events=events,positive_loss_frequency=events/n if n else None,
                mean_loss=mean(loss),mean_positive_loss=mean([x for x in loss if x>0]),
                maximum_loss=max(loss,default=None),mean_cost=mean(cost),
                break_even_before_cost=mean(loss),break_even_after_cost=mean(np.asarray(loss)+np.asarray(cost)))


def analyze(e,replicates=5000):
    if not isinstance(replicates,int) or replicates<1:raise ValueError('Positive replicate count required')
    rows=observations(e);end=PLAN['extended_end']
    # Retain every matured calendar slot, even if an individual stock is missing.
    dates=sorted({r['entry_date'] for r in rows if r['expiry_date']<=end})
    dindex={d:i for i,d in enumerate(dates)}
    # eligible weight, selected weight, loss, selected loss, cost, selected cost
    a=np.zeros((len(dates),4,4,6));result={}
    for r in rows:
        if r['status']!='observed':continue
        i,j,k=dindex[r['entry_date']],TICKERS.index(r['ticker']),RATIOS.index(r['ratio'])
        p=int(r['passed']);a[i,j,k]=[1,p,r['loss'],p*r['loss'],r['cost'],p*r['cost']]
    def contrasts(s):
        with np.errstate(divide='ignore',invalid='ignore'):
            u=s[...,2]/s[...,0];f=s[...,3]/s[...,1]
            ub=(s[...,2]+s[...,4])/s[...,0];fb=(s[...,3]+s[...,5])/s[...,1]
            return np.stack([u-f,ub-fb,(s[...,2]-s[...,3])/s[...,0],
                             (s[...,2]+s[...,4]-s[...,3]-s[...,5])/s[...,0]],axis=-1)
    estimates=contrasts(a.sum(axis=0))
    metrics=['conditional_loss_reduction','conditional_break_even_reduction','weekly_loss_reduction','weekly_break_even_reduction']
    boot={}
    for block in DESIGN['block_weeks']:
        if len(dates)<block:continue
        rng=np.random.Generator(np.random.PCG64(DESIGN['seed']+block));draws=[]
        for offset in range(0,replicates,200):
            idx=block_indices(len(dates),block,min(200,replicates-offset),rng)
            draws.append(contrasts(a[idx].sum(axis=1)))
        boot[block]=np.concatenate(draws)
    for j,t in enumerate(TICKERS):
        result[t]={}
        for k,ratio in enumerate(RATIOS):
            selected=[r for r in rows if r['ticker']==t and r['ratio']==ratio]
            all_rows=[r for r in selected if r['status']=='observed'];f=[r for r in all_rows if r['passed']]
            ustat=group_stats([r['loss'] for r in all_rows],[r['cost'] for r in all_rows])
            fstat=group_stats([r['loss'] for r in f],[r['cost'] for r in f])
            n,q=len(all_rows),len(f)/len(all_rows) if all_rows else None
            ready=min(len(f),n-len(f))>=20
            estimates_dict={name:float(estimates[j,k,m]) if math.isfinite(estimates[j,k,m]) else None for m,name in enumerate(metrics)}
            sensitivity=[]
            for block,b in boot.items():
                sensitivity.append(dict(block_weeks=block,**{name:interval(b[:,j,k,m],ready,replicates,
                    degenerate=m in (0,2) and (not all_rows or len({r['loss'] for r in all_rows})<2)) for m,name in enumerate(metrics)}))
            budget=estimates_dict['weekly_break_even_reduction']
            result[t][str(ratio)]=dict(unfiltered=ustat,filtered=fstat,eligible_frequency=q,
                valid_weekly_opportunities=n,scheduled_mature_weeks=len(dates),
                exclusions={s:sum(r['status']==s for r in selected) for s in sorted({r['status'] for r in selected if r['status']!='observed'})},
                weekly_filtered_loss=q*fstat['mean_loss'] if f else 0. if n else None,
                weekly_filtered_break_even=q*fstat['break_even_after_cost'] if f else 0. if n else None,
                weekly_unfiltered_break_even=ustat['break_even_after_cost'],
                weekly_skipped_frequency=1-q if q is not None else None,
                **estimates_dict,sensitivity=sensitivity,
                equal_premium_crossover=budget/(1-q) if budget is not None and q<1 else None,
                sparse_loss_events=min(fstat['positive_loss_events'],ustat['positive_loss_events']-fstat['positive_loss_events'])<5)
    return dict(kind='hypothetical_put_payoff_not_option_backtest',design={**DESIGN,'replicates':replicates},
                window=dict(start=PLAN['extended_start'],end=end),evidence_sha256=digest(e),
                scheduled_mature_weeks=len(dates),dte_counts={str(d):len({r['entry_date'] for r in rows if r['dte']==d}) for d in sorted({r['dte'] for r in rows})},
                tickers=result,premium_observations=0,estimated_option_alpha=None,
                comparison='Positive differences mean less hypothetical liability/cost, NOT higher returns. Weekly results use matched valid weeks and zero incremental option activity in skipped weeks.',
                premium_budget='Let q be the selected-week share, B_U and B_F be all/selected conditional break-even rates after cost. Equal expected weekly net cashflow requires q*p_F - p_U = q*B_F - B_U. The allowable weekly forgone premium is B_U - q*B_F. At equal constant premium p in both groups, filtering helps only if p < (B_U - q*B_F)/(1-q), ignoring cash yield. No actual premium or alpha is inferred.')
