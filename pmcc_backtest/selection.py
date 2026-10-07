"""Lock choices using the previous session only; never inspect execution quotes."""
from datetime import date
from .data import finite, mid


def long_call(market, day):
    cal,cfg=market.calendar,market.config
    signal=cal.previous(day)
    spot=market.stock(signal)
    if spot is None or not market.signal_known(market.stocks.get(signal),day):
        return None,'SIGNAL_STOCK_MISSING'
    eligible=[]
    for c in market.contracts.values():
        dte=(date.fromisoformat(c['expiry'])-date.fromisoformat(signal)).days
        q=market.quote(c['id'],signal)
        if not (market.observed(c,signal) and cfg.long_dte_min<=dte<=cfg.long_dte_max
                and c['strike']<spot and mid(q) is not None and market.signal_known(q,day)):
            continue
        if cfg.long_mode=='historical delta':
            delta=q.get('delta')
            if not finite(delta) or not cfg.long_delta_min<=delta<=cfg.long_delta_max or q.get('delta_source') not in ('historical','estimated contemporaneous'):
                continue
            rank=(abs(delta-cfg.long_delta_target),c['strike'],c['id'])
        else:
            if c['strike']>cfg.long_proxy*spot+1e-10:
                continue
            rank=(-c['strike'],c['id'])
        eligible.append((abs(dte-cfg.long_dte_target),c['expiry'],rank,c))
    if not eligible:
        return None,'NO_ELIGIBLE_OBSERVED_LONG'
    return min(eligible,key=lambda x:x[:3])[3],None


def short_call(market, day, supporting_long=None):
    cal,cfg=market.calendar,market.config
    signal=cal.previous(day); week=cal.week(day)
    spot=market.stock(signal)
    if spot is None or not market.signal_known(market.stocks.get(signal),day):
        return None,'SIGNAL_STOCK_MISSING'
    # Contract metadata identifies Friday-series membership. The calendar alone
    # cannot turn a Thursday/other-weekday contract into a Friday series.
    choices=[]
    for c in market.contracts.values():
        if c.get('series_friday')!=week['friday'] or not market.observed(c,signal):
            continue
        if not day<c['last_trade_date'] or c['last_trade_date']!=week['friday_last_session']:
            continue
        if c['strike']<spot*(1+cfg.short_otm)-1e-10:
            continue
        if supporting_long and (c['strike']<supporting_long['strike'] or c['expiry']>=supporting_long['expiry']
                                or c['deliverable']!=supporting_long['deliverable']):
            continue
        choices.append(c)
    if choices:return min(choices,key=lambda c:(c['strike'],c['id'])),None
    coverage=market.short_coverage(week['friday'])
    if not coverage or coverage.get('historical_contracts',0)==0:
        return None,'CANDIDATE_DATA_NOT_COVERED'
    if coverage.get('signal_observed_contracts',0)==0:
        return None,'NO_SIGNAL_TIME_EVIDENCE_IN_QUERIED_CANDIDATES'
    return None,('NO_ELIGIBLE_CONTRACT_IN_VERIFIED_UNIVERSE' if coverage.get('complete')
                 else 'NO_ELIGIBLE_CONTRACT_IN_PARTIAL_OBSERVED_UNIVERSE')
