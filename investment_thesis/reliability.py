"""Dependence-aware research extension; no price, strategy or order mutations.

Design fixed on 2026-11-24 before calculating this extension's results. Windows
and seed are not optimized to produce favorable evidence. The independent KL
calculation is a classroom counterfactual, NOT coverage for financial samples.
"""
from collections import Counter
from datetime import date, timedelta
import math
import numpy as np
import exchange_calendars as xcals

TICKERS = ('BAC', 'KO', 'PFE', 'F')
DESIGN = dict(version='reliability-v1', specified_on='2026-11-24',
              nonoverlap_anchor='2023-11-24', stride_sessions=7,
              bootstrap_replicates=5000, seed=5351124,
              daily_block_lengths=[7, 14, 28], nonoverlap_block_lengths=[1, 2, 4],
              primary_daily_block=14, primary_nonoverlap_block=2,
              minimum_per_cohort=20, confidence_level=.95,
              minimum_valid_replicate_fraction=.95,
              difference='unfiltered minus filtered; positive means lower risk after filtering',
              bootstrap='joint-date moving-block percentile bootstrap; non-circular; PCG64; linear quantiles',
              inference='approximate pointwise intervals, not simultaneous or sequential guarantees',
              theorem_source_status='standard KL form; original classroom Theorem 1.1 not yet verified')


def kl(q, p):
    """Bernoulli D(q || p), including continuous endpoint limits."""
    if not (math.isfinite(q) and math.isfinite(p) and 0 <= q <= 1 and 0 <= p <= 1):
        raise ValueError('Probabilities must be finite and in [0,1]')
    if q == p:
        return 0.
    if p in (0, 1):
        return math.inf
    # log1p preserves small deviations; clamp roundoff, never a negative KL.
    return max(0., (q*math.log1p((q-p)/p) if q else 0.) +
               ((1-q)*math.log1p((p-q)/(1-p)) if q < 1 else 0.))


def log_bound(n, mu, t, tail='lower'):
    """Natural log of theoretical one-sided bound; strict interior tolerance."""
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise ValueError('Positive integer n required')
    if tail not in ('upper', 'lower') or not 0 < mu < 1:
        raise ValueError('Interior hypothesized mean and valid tail required')
    if not math.isfinite(t) or not 0 <= t < (1-mu if tail == 'upper' else mu):
        raise ValueError('Tolerance outside the selected tail domain')
    return -n*kl(mu+t if tail == 'upper' else mu-t, mu)


def iid_kl_interval(events, n, alpha=.05):
    """Invert both one-sided bounds at alpha/2. Only an independence scenario."""
    if n < 1 or not 0 <= events <= n or not 0 < alpha < 1:
        raise ValueError('Invalid sample or confidence level')
    q = events/n
    threshold = math.log(2/alpha)/n
    lo, hi = 0., q
    if events:
        for _ in range(70):
            mid = (lo+hi)/2
            if kl(q, mid) > threshold: lo = mid
            else: hi = mid
    lower = (lo+hi)/2 if events else 0.
    lo, hi = q, 1.
    if events < n:
        for _ in range(70):
            mid = (lo+hi)/2
            if kl(q, mid) > threshold: hi = mid
            else: lo = mid
    return [lower, (lo+hi)/2 if events < n else 1.]


def nonoverlap_dates(dates):
    """Absolute calendar phase stays fixed as the rolling source window moves."""
    if not dates: return []
    anchor = DESIGN['nonoverlap_anchor']
    start = min(anchor, dates[0]); end = max(anchor, dates[-1])
    cal = xcals.get_calendar('XNYS', start=str(date.fromisoformat(start)-timedelta(days=7)),
                            end=str(date.fromisoformat(end)+timedelta(days=7)))
    sessions = [str(x.date()) for x in cal.sessions_in_range(start, end)]
    ordinal = {d:i for i,d in enumerate(sessions)}
    return [d for d in dates if (ordinal[d]-ordinal[anchor]) % DESIGN['stride_sessions'] == 0]


def block_indices(n, length, draws, rng):
    """One shared index vector per draw, never a separate vector per stock/cohort."""
    if not 1 <= length <= n: raise ValueError('Block length exceeds panel')
    starts = rng.integers(0, n-length+1, size=(draws, math.ceil(n/length)))
    return (starts[..., None]+np.arange(length)).reshape(draws, -1)[:, :n]


def panel(rows, dates):
    # Columns: all count, pass count, all events, pass events, all loss, pass loss.
    # Missing dates occupy a slot with zero *weight*, never a zero observation.
    a = np.zeros((len(dates), 4, 6), dtype=float)
    mapped = {t:{r['signal_date']:r for r in rows[t]} for t in TICKERS}
    for i,d in enumerate(dates):
        for j,t in enumerate(TICKERS):
            r = mapped[t][d]
            if r['status'] != 'observed': continue
            passed = r['cohort'] == 'pass'
            loss = r['adverse_move']; event = r['tail_event']
            if not isinstance(event, bool) or not 0 <= loss <= 1:
                raise ValueError('Invalid observed outcome')
            a[i,j] = [1, passed, event, event*passed, loss, loss*passed]
    return a


def ratios(sums):
    """All frequency, filtered frequency, all loss, filtered loss; NaN if absent."""
    with np.errstate(divide='ignore', invalid='ignore'):
        return np.stack([sums[...,2]/sums[...,0], sums[...,3]/sums[...,1],
                         sums[...,4]/sums[...,0], sums[...,5]/sums[...,1]], axis=-1)


def interval(values, eligible, reps, degenerate=False):
    finite = values[np.isfinite(values)]
    bounds = [float(x) for x in np.quantile(finite, [.025,.975], method='linear')] if len(finite) else None
    reason = ('insufficient_original_cohort' if not eligible else
              'no_observed_outcome_variation' if degenerate else
              'too_many_empty_resampled_cohorts' if len(finite) < math.ceil(.95*reps) else
              'degenerate_resampling_interval' if bounds[1]-bounds[0] <= 1e-14 else None)
    return dict(ci95=bounds if reason is None else None,
                valid_replicates=int(len(finite)), reason=reason)


def bootstrap(a, lengths, reps, seed):
    observed = a.sum(axis=0)
    out = []
    for length in lengths:
        if len(a) < length:
            out.append(dict(block_length=length, status='insufficient_dates', tickers={})); continue
        rng = np.random.Generator(np.random.PCG64(seed+length))
        draws = []
        for start in range(0, reps, 200):
            idx = block_indices(len(a), length, min(200, reps-start), rng)
            draws.append(ratios(a[idx].sum(axis=1)))
        draws = np.concatenate(draws)
        stocks = {}
        for j,t in enumerate(TICKERS):
            all_n, pass_n, all_events, pass_events = observed[j,:4]
            ready = min(pass_n, all_n-pass_n) >= DESIGN['minimum_per_cohort']
            groups = {}
            for group, n, events, col in [('filtered', pass_n, pass_events, 1), ('unfiltered', all_n, all_events, 0)]:
                groups[group] = interval(draws[:,j,col], n >= 20, reps, events in (0,n))
            # A sample with no variation cannot provide a useful resampled tail CI.
            stocks[t] = dict(groups=groups,
                frequency_difference=interval(draws[:,j,0]-draws[:,j,1], ready, reps,
                                              pass_events in (0,pass_n) or
                                              all_events-pass_events in (0,all_n-pass_n)),
                downside_difference=interval(draws[:,j,2]-draws[:,j,3], ready, reps,
                                            len(a[a[:,j,0]>0,j,4]) == 0 or
                                            bool(np.ptp(a[a[:,j,0]>0,j,4]) == 0)))
        out.append(dict(block_length=length, status='computed', tickers=stocks))
    return out


def analyze(d, replicates=None):
    """Only validated tracker outcomes enter the empirical analysis."""
    reps = DESIGN['bootstrap_replicates'] if replicates is None else replicates
    if isinstance(reps, bool) or not isinstance(reps, int) or reps < 100:
        raise ValueError('At least 100 replicates required')
    rows = d['rows']; dates = [r['signal_date'] for r in rows['BAC']]
    if any([r['signal_date'] for r in rows[t]] != dates for t in TICKERS):
        raise ValueError('Shared session grid required; do not compress missing dates')
    result = dict(design={**DESIGN, 'bootstrap_replicates':reps},
                  market_snapshot_sha256=d['market_snapshot_sha256'],
                  as_of=d['window']['analysis_end'], samples={})
    for k, chosen, lengths, seed in [
            ('daily', dates, DESIGN['daily_block_lengths'], DESIGN['seed']),
            ('nonoverlap', nonoverlap_dates(dates), DESIGN['nonoverlap_block_lengths'], DESIGN['seed']+1000)]:
        by_t = {t:[r for r in rows[t] if r['signal_date'] in set(chosen)] for t in TICKERS}
        # Keep every calendar slot with a matured horizon, even if all stocks lack data.
        mature = [r['signal_date'] for r in by_t['BAC'] if r['outcome_date'] <= result['as_of']]
        a = panel(rows, mature)
        sums = a.sum(axis=0); estimates = ratios(sums)
        stocks = {}
        for j,t in enumerate(TICKERS):
            groups = {}
            for group,col,n,events in [('filtered',1,sums[j,1],sums[j,3]), ('unfiltered',0,sums[j,0],sums[j,2])]:
                groups[group] = dict(n=int(n), events=int(events), frequency=float(estimates[j,col]) if n else None,
                                     mean_adverse=float(estimates[j,col+2]) if n else None,
                                     iid_kl95_scenario=iid_kl_interval(int(events),int(n)) if n else None)
            stocks[t] = dict(groups=groups, excluded=dict(Counter(r['status'] for r in by_t[t] if r['status']!='observed')),
                             frequency_difference=float(estimates[j,0]-estimates[j,1]) if sums[j,1] else None,
                             downside_difference=float(estimates[j,2]-estimates[j,3]) if sums[j,1] else None,
                             sparse_event_warning=bool(min(sums[j,3],sums[j,1]-sums[j,3],
                                                      sums[j,2]-sums[j,3],sums[j,0]-sums[j,1]-sums[j,2]+sums[j,3]) < 5))
        result['samples'][k] = dict(scheduled_dates=chosen, matured_dates=mature, tickers=stocks,
                                   sensitivity=bootstrap(a,lengths,reps,seed))
    return result
