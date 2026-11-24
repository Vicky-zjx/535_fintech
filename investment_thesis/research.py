"""Forward stock-risk research, separate from orders, fills and Wheel returns.

Only reads validated historical_signals.json; never queries or edits prices/orders.
Design v1 fixed 2026-11-23, before inspecting its results. Earlier data are
retrospective. A signal at t uses the close at t+1 as reference and t+6 as exit.
All six closes must exist. Daily windows overlap: no independent-trade inference.
"""
from collections import Counter
from datetime import datetime, timezone
import csv
import io
import json
from pathlib import Path
import statistics

import exchange_calendars as xcals
import pandas as pd

from final_project.data_provider import digest
from final_project.indicators import valid_close
from final_project.sanji_orders import atomic_json
from final_project.strategy_config import UNIVERSE, STRATEGY_REVISION
from .option_audit import audit as option_audit

DESIGN = {
    'version': 'forward-stock-risk-v1.1', 'registered_on': '2026-11-23',
    'reference_lag_sessions': 1, 'holding_sessions': 5,
    'rolling_entry_sessions': 126, 'minimum_per_cohort_per_ticker': 20,
    'adverse_move_threshold': .03,
    'comparison': 'Primary: equal-weight within-ticker pass versus all (unfiltered); fail cohort is diagnostic. All four required.',
    'sampling': 'Every signal session; overlapping five-session paths, not independent trades.',
    'purpose': 'Test a necessary downside-risk premise, not option pricing, realized alpha or Wheel returns.',
}


def outcomes(h):
    if (h.get('kind') != 'historical_technical_signal_analysis'
            or h.get('source') != 'LSEG Data Platform'
            or h.get('strategy_revision') != STRATEGY_REVISION):
        raise ValueError('Thesis requires validated real LSEG historical signals')
    start, end = h['window']['analysis_start'], h['window']['analysis_end']
    # The rolling three-year boundary can be a holiday/weekend. Include prior
    # calendar context so sessions_in_range accepts it without changing the
    # requested sample boundaries or adding a non-trading-day observation.
    cal = xcals.get_calendar('XNYS', start=str((pd.Timestamp(start)-pd.Timedelta(days=7)).date()),
                             end=str((pd.Timestamp(end)+pd.Timedelta(days=25)).date()))
    dates = [str(d.date()) for d in cal.sessions_in_range(start, end)]
    all_dates = [str(d.date()) for d in cal.sessions if str(d.date()) >= dates[0]]
    result = {}
    for ticker in UNIVERSE:
        source = h['tickers'][ticker]['daily_rows']
        if [r['signal_date'] for r in source] != dates:
            raise ValueError('History must retain every exchange-session row, including missing closes')
        for r in source:
            if r['close'] is not None and not valid_close(r['close']):
                raise ValueError('Invalid observed price')
            if type(r['valid']) is not bool or (r['valid'] and type(r['eligible']) is not bool):
                raise ValueError('Invalid signal eligibility')
        rows = []
        for i, r in enumerate(source):
            first, last = i+1, i+6
            row = dict(ticker=ticker, signal_date=r['signal_date'],
                       reference_date=all_dates[first], outcome_date=all_dates[last],
                       reference_index=first, outcome_index=last,
                       cohort=('pass' if r['eligible'] else 'fail') if r['valid'] else None,
                       status=None, reason=None, reference_close=None, end_close=None,
                       stock_return=None, adverse_move=None, tail_event=None,
                       missing_dates=[], prospective=r['signal_date'] >= DESIGN['registered_on'])
            if not r['valid']:
                row.update(status='signal_unavailable', reason=r.get('exclusion'))
            elif last >= len(source):
                row.update(status='unmatured', reason='Five-session forward path not yet complete')
            else:
                path = source[first:last+1]
                row['missing_dates'] = [x['signal_date'] for x in path if not valid_close(x['close'])]
                if row['missing_dates']:
                    row.update(status='missing_path', reason='At least one actual path close is missing; no filling')
                else:
                    prices = [x['close'] for x in path]
                    adverse = max(0., 1.-min(prices)/prices[0])
                    row.update(status='observed', reference_close=prices[0], end_close=prices[-1],
                               stock_return=prices[-1]/prices[0]-1., adverse_move=adverse,
                               tail_event=adverse >= DESIGN['adverse_move_threshold'])
            rows.append(row)
        result[ticker] = rows
    return dates, result


def cohort_stats(rows):
    n = len(rows)
    return dict(n=n, mean_return=statistics.mean(r['stock_return'] for r in rows) if n else None,
                return_sd=statistics.stdev(r['stock_return'] for r in rows) if n > 1 else None,
                mean_adverse=statistics.mean(r['adverse_move'] for r in rows) if n else None,
                tail_rate=statistics.mean(int(r['tail_event']) for r in rows) if n else None)


def comparison(rows_by_ticker):
    tickers = {}
    for ticker, rows in rows_by_ticker.items():
        observed = [r for r in rows if r['status'] == 'observed']
        stats = {c: cohort_stats([r for r in observed if r['cohort'] == c]) for c in ('pass', 'fail')}
        stats['all'] = cohort_stats(observed)
        stats['sufficient'] = min(stats[c]['n'] for c in ('pass', 'fail')) >= DESIGN['minimum_per_cohort_per_ticker']
        tickers[ticker] = stats
    ready = len(tickers) == 4 and all(s['sufficient'] for s in tickers.values())
    aggregate = dict(sufficient=ready, insufficient_tickers=[t for t,s in tickers.items() if not s['sufficient']],
                     pass_n=sum(s['pass']['n'] for s in tickers.values()),
                     fail_n=sum(s['fail']['n'] for s in tickers.values()))
    for metric in ('mean_return', 'mean_adverse', 'tail_rate'):
        for cohort in ('pass', 'fail', 'all'):
            aggregate[f'{cohort}_{metric}'] = statistics.mean(s[cohort][metric] for s in tickers.values()) if ready else None
    aggregate['downside_benefit'] = aggregate['fail_mean_adverse']-aggregate['pass_mean_adverse'] if ready else None
    aggregate['return_spread'] = aggregate['pass_mean_return']-aggregate['fail_mean_return'] if ready else None
    aggregate['tail_benefit'] = aggregate['fail_tail_rate']-aggregate['pass_tail_rate'] if ready else None
    aggregate['baseline_downside_benefit'] = aggregate['all_mean_adverse']-aggregate['pass_mean_adverse'] if ready else None
    aggregate['baseline_return_spread'] = aggregate['pass_mean_return']-aggregate['all_mean_return'] if ready else None
    aggregate['baseline_tail_benefit'] = aggregate['all_tail_rate']-aggregate['pass_tail_rate'] if ready else None
    return {'tickers': tickers, 'aggregate': aggregate}


def wrong_if(stats):
    a = stats['aggregate']
    return {name: ('insufficient' if not a['sufficient'] else 'triggered' if a[key] <= 0 else 'not_triggered')
            for name, key in [('no_downside_benefit', 'baseline_downside_benefit'), ('no_tail_benefit', 'baseline_tail_benefit')]}


def cost_sensitivity():
    # Research-only budget, not broker quotes, option premiums or engine fees.
    examples = []
    for ticker, strike in [('KO', 96.), ('PFE', 28.)]:
        collateral = strike*100
        cost = .65*2 + .02*100
        gross = .002*collateral
        examples.append(dict(ticker=ticker, strike=strike, collateral=collateral,
                             assumed_cost=cost, break_even_bps=cost/collateral*1e4,
                             assumed_gross_surplus_bps=20., assumed_gross_surplus=gross,
                             illustrative_net_surplus=gross-cost,
                             illustrative_net_bps=(gross-cost)/collateral*1e4,
                             scenarios=[dict(gross_bps=b, gross_dollars=collateral*b/1e4,
                                             net_dollars=collateral*b/1e4-cost,
                                             net_bps=b-cost/collateral*1e4)
                                        for b in (5, 10, 20, 30, 50)]))
    return dict(kind='hypothetical_cost_budget_not_estimated_alpha', commission_per_contract_side=.65,
                assumed_round_trip_slippage_per_share=.02, commission_sides=2, multiplier=100,
                maximum_cycles_per_ticker_per_year=52, examples=examples)


def analyze(h):
    dates, rows = outcomes(h)
    full = comparison(rows)
    rolling = []
    for i, date in enumerate(dates):
        last_entry = i-DESIGN['holding_sessions']
        first_entry = max(1, last_entry-DESIGN['rolling_entry_sessions']+1)
        selected = {t: [r for r in values if r['outcome_index'] <= i and r['reference_index'] >= first_entry]
                    for t, values in rows.items()}
        stats = comparison(selected)
        rolling.append(dict(as_of=date, first_reference_date=dates[first_entry] if last_entry >= 1 else None,
                            last_reference_date=dates[last_entry] if last_entry >= 1 else None,
                            **stats, wrong_if=wrong_if(stats)))
    calendar = xcals.get_calendar('XNYS', start=dates[0], end=str((pd.Timestamp(dates[-1])+pd.Timedelta(days=25)).date()))
    next_session = calendar.next_session(pd.Timestamp(dates[-1]))
    return dict(schema_version=1, kind='forward_stock_risk_research', source=h['source'],
                strategy_revision=STRATEGY_REVISION, design=DESIGN, window=h['window'],
                market_retrieved_at=h['market_retrieved_at'], market_snapshot_sha256=h['market_snapshot_sha256'],
                historical_signals_sha256=digest(h), historical_generated_at=h.get('generated_at'),
                coverage={t: dict(Counter(r['status'] for r in values)) for t,values in rows.items()},
                latest_matured_outcome_date=max((r['outcome_date'] for v in rows.values() for r in v
                                                if r['status']=='observed'), default=None),
                next_market_session=str(next_session.date()),
                next_market_close_at=calendar.session_close(next_session).isoformat(),
                full_sample=full, rolling=rolling, rows=rows,
                prospective=comparison({t: [r for r in values if r['prospective']] for t,values in rows.items()}),
                cost_budget=cost_sensitivity())


def csv_text(result):
    rows = [dict(r, missing_dates='|'.join(r['missing_dates'])) for values in result['rows'].values() for r in values]
    out = io.StringIO(newline='')
    writer = csv.DictWriter(out, fieldnames=list(rows[0]), lineterminator='\n')
    writer.writeheader(); writer.writerows(rows)
    return out.getvalue()


def build(root, now):
    source = Path(root)/'docs/data'
    data = Path(root)/'investment-thesis/data'
    h = json.loads((source/'historical_signals.json').read_text())
    # Standalone builds must not silently publish analytics on a stale/mixed file.
    market = json.loads((source/'market_snapshot.json').read_text())
    if h['market_snapshot_sha256'] != digest(market):
        raise ValueError('History does not match retained real market snapshot')
    result = analyze(h)
    result['option_audit'] = option_audit(root)
    result['generated_at'] = now.isoformat()
    atomic_json(data/'thesis_tracker.json', result)
    (data/'thesis_observations.csv').write_text(csv_text(result))
    print(json.dumps({'window': result['window'], 'full_sample': result['full_sample']['aggregate'],
                      'latest_review': result['rolling'][-1]['wrong_if'], 'coverage': result['coverage']}, indent=2))
    return result


if __name__ == '__main__':
    build(Path(__file__).resolve().parents[1], datetime.now(timezone.utc))
