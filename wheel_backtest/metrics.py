"""Net-equity statistics; a missing mark is never a zero or bridged return."""
from datetime import date
import math
import statistics


def calculate(rows,initial,start,end,risk_free_rate):
    peak=initial;observed_peak=initial;broken=False;previous=initial;returns=[]
    for r in rows:
        nav=r['equity']
        r['daily_return']=nav/previous-1 if nav is not None and previous is not None and previous>0 else None
        previous=nav
        if nav is None:
            broken=True;r['drawdown']=r['observed_drawdown']=None;continue
        observed_peak=max(observed_peak,nav);r['observed_drawdown']=nav/observed_peak-1
        if broken:r['drawdown']=None
        else:peak=max(peak,nav);r['drawdown']=nav/peak-1
        if r['daily_return'] is not None:returns.append(r['daily_return'])
    gaps=[r['date'] for r in rows if r['equity'] is None];last=rows[-1]['equity'] if rows else None
    total=last/initial-1 if last is not None else None
    complete=bool(rows) and not gaps;span=(date.fromisoformat(end)-date.fromisoformat(start)).days+1
    vol=statistics.stdev(returns)*math.sqrt(252) if complete and len(returns)>1 else None
    rf=(1+risk_free_rate)**(1/252)-1
    sharpe=(statistics.mean(returns)-rf)*252/vol if vol and vol>0 else None
    cagr=(last/initial)**(365.25/span)-1 if complete and last>0 else None
    mdd=min([0]+[r['drawdown'] for r in rows]) if complete else None
    observed=min([0]+[r['observed_drawdown'] for r in rows if r['observed_drawdown'] is not None])
    return dict(ending_equity=last,net_pnl=last-initial if last is not None else None,total_return=total,
        cagr=cagr,annualized_volatility=vol,sharpe=sharpe,max_drawdown=mdd,observed_max_drawdown=observed,
        calmar=cagr/abs(mdd) if cagr is not None and mdd and span>=365 else None,
        sample_calendar_days=span,valuation_gap_dates=gaps,valid_daily_returns=len(returns),full_path_complete=complete,
        annualization_note='252 daily periods; risk-free rate configurable; cash earns 0%. Short-sample annualization is extrapolation, not a forecast. Calmar withheld below one year.')
