"""Three-year observed-close signal analysis, NOT an options return backtest."""
from collections import Counter
from datetime import datetime, timezone
import csv
import io
import json
import math
from pathlib import Path
import exchange_calendars as xcals
import pandas as pd
from .strategy_config import UNIVERSE, MAX_HV, MIN_R5, STRATEGY_REVISION

FILTERS = ('trend', 'volatility', 'sudden_drop')


def history_window(as_of):
    end = pd.Timestamp(as_of)
    start = end - pd.DateOffset(years=3)
    cal = xcals.get_calendar('XNYS', start=str((start-pd.Timedelta(days=180)).date()),
                             end=str((end+pd.Timedelta(days=14)).date()))
    sample = cal.sessions_in_range(start, end)
    if not len(sample) or sample[-1] != end:
        raise ValueError('Historical endpoint must be a completed XNYS session')
    first = cal.sessions.get_loc(sample[0])
    return {'analysis_start': str(start.date()), 'analysis_end': str(end.date()),
            'query_start': str(cal.sessions[first-50].date()),
            'warmup_sessions_requested': 50, 'expected_sample_sessions': len(sample)}


def summarize(rows):
    valid = [r for r in rows if r['valid']]
    counts = {k: sum(r[k] for r in valid) for k in FILTERS}
    counts['combined'] = sum(r['eligible'] for r in valid)
    patterns = Counter('+'.join(k for k in FILTERS if not r[k]) or 'pass_all' for r in valid)
    return {'candidate_dates': len(rows), 'evaluated_dates': len(valid),
            'excluded_dates': len(rows)-len(valid), 'pass_counts': counts,
            'pass_rates': {k: v/len(valid) if valid else None for k, v in counts.items()},
            'standalone_rejections': {k: len(valid)-counts[k] for k in FILTERS},
            'exclusive_rejections': {k: patterns[k] for k in FILTERS},
            'rejection_patterns': dict(patterns)}


def analyze(market):
    if market.get('mode') != 'live' or market.get('source') != 'LSEG Data Platform':
        raise ValueError('Historical analysis requires real LSEG provenance')
    window = history_window(market['calendar']['as_of'])
    cal = xcals.get_calendar('XNYS', start=str((pd.Timestamp(window['query_start'])-pd.Timedelta(days=14)).date()),
                             end=str((pd.Timestamp(window['analysis_end'])+pd.Timedelta(days=14)).date()))
    sessions = cal.sessions_in_range(window['query_start'], window['analysis_end'])
    sample = cal.sessions_in_range(window['analysis_start'], window['analysis_end'])
    outputs = {}; all_weekly = {}; prices = []
    for ticker in UNIVERSE:
        data = market['tickers'].get(ticker, {})
        if data.get('identity_verified') is not True:
            raise ValueError(ticker+': LSEG stock identity is not verified')
        observed = {}
        for row in data.get('history', []):
            day, value = row['date'], row['close']
            parsed = pd.Timestamp(day)
            if str(parsed.date()) != day or parsed > sessions[-1]:
                raise ValueError('Invalid/future price date')
            if value is not None and (type(value) not in (float, int) or not math.isfinite(value) or value <= 0):
                raise ValueError('Invalid observed close')
            if day in observed and observed[day] != value:
                raise ValueError('Conflicting duplicate observed prices')
            observed[day] = value
        extra = sorted(d for d in observed if pd.Timestamp(d) not in sessions)
        series = pd.Series([observed.get(str(d.date())) for d in sessions], index=sessions, dtype=float)
        sma20, sma50 = series.rolling(20).mean(), series.rolling(50).mean()
        log_returns = (series/series.shift()).map(lambda x: math.log(x) if pd.notna(x) else float('nan'))
        hv = log_returns.rolling(20).std(ddof=1)*math.sqrt(252)
        r5 = series/series.shift(5)-1
        rows = []; weekly = []
        for i, day in enumerate(sessions):
            target = cal.next_session(day)
            monday = target-pd.Timedelta(days=target.weekday())
            first = cal.date_to_session(monday, direction='next')
            valid = pd.notna(sma50.iloc[i])
            vals = [sma20.iloc[i], sma50.iloc[i], hv.iloc[i], r5.iloc[i]]
            valid = bool(valid and all(pd.notna(v) for v in vals))
            row = {'ticker': ticker, 'signal_date': str(day.date()), 'entry_session': str(target.date()),
                   'first_weekly_session': bool(target == first), 'valid': valid,
                   'exclusion': None if valid else ('warmup' if i < 49 else 'missing_50_session_window'),
                   'close': None if pd.isna(series.iloc[i]) else float(series.iloc[i]),
                   **{k: float(v) if valid else None for k, v in zip(('sma20', 'sma50', 'hv20', 'r5'), vals)}}
            row.update({k: None for k in FILTERS}); row['eligible'] = None
            if valid:
                row.update(trend=row['close'] >= row['sma50'] and row['sma20'] >= row['sma50'],
                           volatility=row['hv20'] <= MAX_HV, sudden_drop=row['r5'] >= MIN_R5)
                row['eligible'] = all(row[k] for k in FILTERS)
            if day in sample:
                rows.append(row)
                prices.append({'ticker': ticker, 'date': row['signal_date'], 'close': row['close']})
            # A Monday entry uses the preceding completed session (usually Friday),
            # never Monday's close. Holidays are determined by XNYS, not weekdays.
            if target == first and window['analysis_start'] <= row['entry_session'] <= window['analysis_end']:
                weekly.append(row)
        observed_sample = [r for r in rows if r['close'] is not None]
        missing = [r['signal_date'] for r in rows if r['close'] is None]
        before = series.loc[series.index < sample[0]]
        coverage = {'expected_sessions': len(sample), 'observed_sessions': len(observed_sample),
                    'first_observed': observed_sample[0]['signal_date'] if observed_sample else None,
                    'last_observed': observed_sample[-1]['signal_date'] if observed_sample else None,
                    'missing_dates': missing, 'observed_warmup_closes': int(before.notna().sum()),
                    'requested_warmup_closes': len(before), 'outside_requested_sessions': extra,
                    'complete': not missing and bool(before.notna().all())}
        outputs[ticker] = {'coverage': coverage, 'daily': summarize(rows), 'weekly': summarize(weekly),
            'by_year': {year: summarize([r for r in weekly if r['entry_session'][:4] == year])
                        for year in sorted({r['entry_session'][:4] for r in weekly})},
            'daily_rows': rows, 'weekly_rows': weekly}
        all_weekly[ticker] = {r['entry_session']: r for r in weekly}
    joint = []
    for day in sorted(set.union(*(set(d) for d in all_weekly.values()))):
        observations = {t: all_weekly[t].get(day) for t in UNIVERSE}
        complete = all(r is not None and r['valid'] for r in observations.values())
        joint.append({'entry_session': day, 'complete': complete,
                      'eligible_tickers': [t for t, r in observations.items() if r and r['valid'] and r['eligible']],
                      'eligible_count': sum(r['eligible'] for r in observations.values()) if complete else None})
    valid_joint = [r for r in joint if r['complete']]
    def joint_summary(rows):
        return {'evaluated_dates': len(rows), 'multiple_eligible_dates': sum(r['eligible_count'] >= 2 for r in rows),
                'distribution': {str(k): sum(r['eligible_count'] == k for r in rows) for k in range(5)}}
    return {'schema_version': 1, 'kind': 'historical_technical_signal_analysis',
            'strategy_revision': STRATEGY_REVISION, 'source': market['source'],
            'market_retrieved_at': market['retrieved_at'], 'window': window,
            'status': 'complete' if all(d['coverage']['complete'] for d in outputs.values()) else 'partial',
            'tickers': outputs, 'joint_weekly': {**joint_summary(valid_joint),
                'candidate_dates': len(joint), 'excluded_dates': len(joint)-len(valid_joint), 'rows': joint,
                'by_year': {year: joint_summary([r for r in valid_joint if r['entry_session'][:4] == year])
                            for year in sorted({r['entry_session'][:4] for r in joint})}},
            'scope': 'Technical eligibility only; no historical option selection, cash allocation, fills, NAV or returns. Current fixed universe; adjusted closes as retrieved, not vintage unrevised data.'}


def build(root, now):
    from .data_provider import digest
    from .sanji_orders import atomic_json
    root = Path(root); data = root/'docs/data'
    market = json.loads((data/'market_snapshot.json').read_text())
    result = analyze(market)
    result.update(generated_at=now.isoformat(), market_snapshot_sha256=digest(market))
    status = json.loads((data/'strategy_status.json').read_text())
    result['matches_latest_market_attempt'] = status.get('market_snapshot_sha256') == digest(market)
    atomic_json(data/'historical_signals.json', result)
    # A tidy CSV reproduces every computed daily indicator; nulls stay empty.
    rows = [r for d in result['tickers'].values() for r in d['daily_rows']]
    csv_text = io.StringIO(newline=''); writer = csv.DictWriter(csv_text, fieldnames=list(rows[0]), lineterminator='\n')
    writer.writeheader(); writer.writerows(rows)
    (data/'historical_signals.csv').write_text(csv_text.getvalue())
    print(json.dumps({'historical_status': result['status'], 'window': result['window'],
                      'coverage': {t: d['coverage']['observed_sessions'] for t,d in result['tickers'].items()},
                      'joint_weekly': {k:v for k,v in result['joint_weekly'].items() if k != 'rows'}}, indent=2))
    return result


if __name__ == '__main__':
    build(Path(__file__).resolve().parents[1], datetime.now(timezone.utc))
