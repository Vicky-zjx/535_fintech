"""Thesis-level forward monitoring. No orders, fills, balances or execution calls."""
import math
import pandas as pd
import exchange_calendars as xcals
from .extension_plan import PLAN
from .reliability import TICKERS, kl, log_bound, nonoverlap_dates


def advisory(bound):
    if bound is None:return 'Awaiting Data'
    if not math.isfinite(bound) or not 0<=bound<=1:raise ValueError('Invalid probability bound')
    return ('Continue monitoring' if bound>.5 else 'Review' if bound>.25 else
            'Warning' if bound>.1 else 'Pause and investigate')


def classroom_example():
    bound=math.exp(log_bound(10,.6,.1,'lower'))
    return dict(source='November 24 classroom example as supplied by the student; not independently verified lecture text',
                expected_win_rate=.6,observed_win_rate=.5,completed_trades=10,adverse_deviation=.1,
                tail='lower',bound=bound,advisory=advisory(bound),own_trade_results=False)


def assessment(n,events,expected,acceptable=None,baseline_ready=True):
    if type(n) is not int or type(events) is not int or n<0 or not 0<=events<=n:raise ValueError('Invalid observed counts')
    if acceptable is not None and (not math.isfinite(acceptable) or not 0<acceptable<1):
        raise ValueError('Acceptable downside-risk limit must be chosen explicitly in (0,1)')
    observed=events/n if n else None
    ready=baseline_ready and expected is not None and 0<expected<1
    log_probability=None if not n or not ready else -n*kl(observed,expected) if observed>expected else 0.
    bound=math.exp(log_probability) if log_probability is not None else None
    enough=n>=PLAN['forward_reporting_floor']
    # A threshold left Pending must never be silently selected from bad outcomes.
    if not n:status='Awaiting matured prospective observations'
    elif not ready:status='Pending usable historical reference'
    elif not enough:status='Insufficient evidence: fewer than 20 matured observations'
    elif acceptable is None:status='Pending minimum acceptable performance'
    else:status='Conditional research monitoring'
    if not enough or not ready or acceptable is None:regime='Insufficient evidence'
    elif observed>expected and bound<=.1:regime='Performance worse than expected'
    elif observed<expected:regime='Performance better than expected'
    else:regime='Performance consistent with historical expectations'
    return dict(n=n,events=events,expected_decline_probability=expected,
                maximum_acceptable_decline_probability=acceptable,observed_decline_frequency=observed,
                deviation=observed-expected if observed is not None and expected is not None else None,
                upper_tail_bound=bound,log_upper_tail_bound=log_probability,
                acceptable_limit_breached=observed>acceptable if observed is not None and acceptable is not None else None,
                joint_deterioration_alert=(observed>expected and observed>acceptable and bound<=.1)
                    if enough and ready and acceptable is not None else None,
                conditional_advisory=advisory(bound),status=status,regime=regime,
                comparison='Pending' if observed is None or expected is None else
                           'Higher observed downside frequency' if observed>expected else
                           'Lower observed downside frequency' if observed<expected else 'Equal observed downside frequency')


def analyze(d,reference):
    e=reference['evidence'];cutoff=e['reference_end'];r=e['original_reliability']
    dates=[x['signal_date'] for x in d['rows']['BAC']];as_of=d['window']['analysis_end']
    # Never silently shorten a cumulative prospective study when retained history rolls off.
    cal=xcals.get_calendar('XNYS',start=cutoff,end=str((pd.Timestamp(cutoff)+pd.Timedelta(days=30)).date()))
    first_prospective=str(cal.date_to_session(pd.Timestamp(cutoff)+pd.Timedelta(days=1),direction='next').date())
    coverage_lost=d['window']['analysis_start']>first_prospective
    result=dict(kind='conditional_thesis_monitoring_not_trade_performance',as_of=as_of,
                frozen_reference_end=cutoff,reference_sha256=reference['evidence_sha256'],
                first_prospective_session=first_prospective,
                reference_start=e['window']['analysis_start'],plan=PLAN,classroom_example=classroom_example(),
                coverage_lost=coverage_lost,samples={})
    for mode in ('daily','nonoverlap'):
        chosen=set(dates if mode=='daily' else nonoverlap_dates(dates));stocks={}
        for t in TICKERS:
            groups={}
            for group in ('filtered','unfiltered'):
                b=r['samples'][mode]['tickers'][t]['groups'][group]
                expected=b['frequency'];acceptable=PLAN['maximum_acceptable_decline_probability'][t]
                candidates=[x for x in d['rows'][t] if x['signal_date']>cutoff and x['signal_date'] in chosen
                            and x['cohort'] is not None and (group=='unfiltered' or x['cohort']=='pass')]
                n=events=0;curve=[];missing=[];pending=[]
                for x in candidates:
                    if x['outcome_date']>as_of:pending.append(x['signal_date']);continue
                    if x['status']!='observed':
                        missing.append(x['signal_date'])
                        curve.append(dict(signal_date=x['signal_date'],outcome_date=x['outcome_date'],
                                          gap=True,n=n,observed_decline_frequency=None,upper_tail_bound=None,
                                          log_upper_tail_bound=None))
                        continue
                    n+=1;events+=int(x['tail_event'])
                    point=assessment(n,events,expected,acceptable,baseline_ready=b['n']>=20 and not coverage_lost)
                    curve.append(dict(signal_date=x['signal_date'],outcome_date=x['outcome_date'],**point))
                current=assessment(n,events,expected,acceptable,baseline_ready=b['n']>=20 and not coverage_lost)
                if coverage_lost:current.update(status='Pending: prospective source coverage has rolled off',regime='Insufficient evidence')
                groups[group]=dict(baseline_n=b['n'],baseline_events=b['events'],current=current,curve=curve,
                                   pending_signal_dates=pending,missing_path_signal_dates=missing,
                                   excluded_invalid_signals=sum(x['signal_date']>cutoff and x['signal_date'] in chosen and x['cohort'] is None for x in d['rows'][t]))
            stocks[t]=groups
        result['samples'][mode]=stocks
    return result
