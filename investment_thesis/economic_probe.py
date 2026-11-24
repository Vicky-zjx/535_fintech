"""Small dated option-payoff illustrations, deliberately not estimated alpha."""
import math
from collections import Counter
from .research import cost_sensitivity


def analyze(evidence):
    results=evidence['option_probes']['results']
    cost=cost_sensitivity()['examples'][0]['assumed_cost']
    summaries=[]
    for ticker in ('BAC','KO','PFE','F'):
        selected=[r for r in results if r['ticker']==ticker]
        scenarios=[];exclusions=Counter()
        for r in selected:
            quote=next((p for p in r['dated_records'] if p['date']==r['observed_on']),None)
            spot=next((p['close'] for p in evidence['tickers'][ticker]['history'] if p['date']==r['observed_on']),None)
            end=next((p['close'] for p in evidence['tickers'][ticker]['history'] if p['date']==r['expiry']),None)
            if spot is None or not math.isclose(spot,r['selection_spot'],abs_tol=1e-8,rel_tol=0):
                exclusions['selection-date stock reference not reconciled']+=1;continue
            if not quote or quote['BID'] is None or quote['ASK'] is None or not 0<=quote['BID']<=quote['ASK'] or quote['ASK']<=0:
                exclusions['no valid entry-date bid/ask pair']+=1;continue
            if end is None:
                exclusions['no observed expiry-date stock close']+=1;continue
            intrinsic=max(r['strike']-end,0)
            mid=(quote['BID']+quote['ASK'])/2
            scenarios.append(dict(midpoint_premium_yield=mid/r['strike'],bid_premium_yield=quote['BID']/r['strike'],
                midpoint_net_payoff_yield=(100*(mid-intrinsic)-cost)/(100*r['strike']),
                bid_net_payoff_yield=(100*(quote['BID']-intrinsic)-cost)/(100*r['strike']),
                itm=intrinsic>0))
        ranges={k:[min(p[k] for p in scenarios),max(p[k] for p in scenarios)] if scenarios else None
                for k in ('midpoint_premium_yield','bid_premium_yield','midpoint_net_payoff_yield','bid_net_payoff_yield')}
        summaries.append(dict(ticker=ticker,probed_contracts=len(selected),usable_contracts=len(scenarios),
            excluded=dict(exclusions),itm_at_expiry=sum(p['itm'] for p in scenarios),**ranges))
    return dict(status='Dated option-price capability established; comparative alpha still not estimable',
        available_metrics=dict(illustrations=summaries),expected_alpha=None,
        entry_date='2026-11-13',expiry='2026-11-20',cost_per_contract=cost,
        valid_bid_ask_records=sum(r['valid_bid_ask_pairs'] for r in results),
        dated_delta_records=sum(r['non_null_counts']['DELTA_EXCH'] for r in results),
        probed_contracts=len(results),
        scope='Nearest observed puts, six per stock, one expiry. Availability sample only: not target-delta selections, actual trades, a matched filtered/unfiltered backtest or an independent sample of profits.',
        payoff_definition='Illustrative net short-put payoff = 100 × (assumed entry bid or midpoint − max(strike − observed expiry stock close, 0)) − $3.30 research cost. Divide by 100 × strike for the collateral yield. This marks an assigned stock purchase to the expiry close; it does not assume the stock was sold or a Wheel cycle completed.',
        assumptions='Ordinary 100-share deliverable research assumption consistent with retained standard-contract descriptions, not an individual historical OCC confirmation. Daily BBO fields do not certify a simultaneous executable closing NBBO. No execution or assignment is inferred.',
        missing='Full dated candidate history, usable historical delta or complete observed-strike fallback candidates, matched strategy arms and capital/idle-cash accounting remain missing. One week cannot estimate expected option alpha.')
