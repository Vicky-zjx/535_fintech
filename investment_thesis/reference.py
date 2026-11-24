"""One-time, explicit preservation of original real evidence. Never overwrite."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import exchange_calendars as xcals
import pandas as pd
from final_project.data_provider import digest
from final_project.sanji_orders import atomic_json
from final_project.strategy_config import UNIVERSE, STRATEGY_REVISION
from final_project.indicators import compute, IndicatorUnavailable, valid_close
from .extension_plan import PLAN, REFERENCE_NAME


def freeze(root, now):
    root=Path(root); target=root/'investment-thesis/data'/REFERENCE_NAME
    if target.exists(): raise FileExistsError('Frozen reference already exists; no overwrite allowed')
    h=json.loads((root/'docs/data/historical_signals.json').read_text())
    m=json.loads((root/'docs/data/market_snapshot.json').read_text())
    d=json.loads((root/'investment-thesis/data/thesis_tracker.json').read_text())
    if (m['source']!='LSEG Data Platform' or m['mode']!='live' or h['market_snapshot_sha256']!=digest(m)
            or d['market_snapshot_sha256']!=digest(m) or h['window']['analysis_end']!=PLAN['reference_end']
            or h['window']['analysis_start']!=PLAN['original_start']):
        raise ValueError('The declared original reference does not match retained real evidence')
    evidence=dict(schema_version=1, frozen_at=now.isoformat(), reference_end=PLAN['reference_end'],
                  source=m['source'], strategy_revision=STRATEGY_REVISION,
                  market_snapshot_sha256=digest(m), historical_signals_sha256=digest(h),
                  original_tracker_sha256=digest(d), retrieved_at=m['retrieved_at'],
                  window=h['window'], field='TR.PriceClose', currency='USD',
                  adjustment='As retrieved by the original connector; adjustment parameter was not explicitly set.',
                  tickers={t:{k:m['tickers'][t][k] for k in ('ric','identity_verified','history')} for t in UNIVERSE},
                  original_full_sample=d['full_sample'], original_reliability=d['reliability'])
    atomic_json(target, dict(evidence=evidence,evidence_sha256=digest(evidence)))
    return target


def load(root):
    p=Path(root)/'investment-thesis/data'/REFERENCE_NAME
    if not p.exists(): raise ValueError('Frozen original reference missing; do not auto-rebase monitoring')
    obj=json.loads(p.read_text());e=obj['evidence']
    if obj['evidence_sha256']!=digest(e) or e['reference_end']!=PLAN['reference_end'] or e['strategy_revision']!=STRATEGY_REVISION:
        raise ValueError('Frozen reference integrity or strategy revision changed')
    return obj


def history(source, start, end):
    """Reuse exact production indicator computation, without touching its module."""
    if source.get('source')!='LSEG Data Platform':raise ValueError('Real LSEG source required')
    cal=xcals.get_calendar('XNYS',start=str((pd.Timestamp(start)-pd.Timedelta(days=180)).date()),
                          end=str((pd.Timestamp(end)+pd.Timedelta(days=30)).date()))
    sample=cal.sessions_in_range(start,end)
    if str(sample[-1].date())!=end:raise ValueError('Completed exchange-session endpoint required')
    query_start=str(cal.sessions[cal.sessions.get_loc(sample[0])-55].date())
    sessions=[str(d.date()) for d in cal.sessions_in_range(query_start,end)]
    outputs={}
    for t in UNIVERSE:
        item=source['tickers'][t]
        if item['identity_verified'] is not True:raise ValueError('Unverified underlying')
        observed={}
        for r in item['history']:
            day=r['date'];v=r['close']
            if str(pd.Timestamp(day).date())!=day or (v is not None and not valid_close(v)):
                raise ValueError('Invalid price/date')
            if day in observed and observed[day]!=v:raise ValueError('Conflicting historical prices')
            observed[day]=v
        rows=[]
        for i,day in enumerate(sessions):
            if day<start:continue
            try:ind=compute(observed,sessions[max(0,i-54):i+1]);valid=True;error=None
            except IndicatorUnavailable as e:ind=e.diagnostics;valid=False;error=str(e)
            rows.append(dict(ticker=t,signal_date=day,close=observed.get(day),valid=valid,
                             eligible=all(ind['filters'].values()) if valid else None,exclusion=error,
                             **{k:ind.get(k) if valid else None for k in ('sma20','sma50','hv20','r5')},
                             **{k:ind['filters'][k] if valid else None for k in ('trend','volatility','sudden_drop')}))
        outputs[t]={'daily_rows':rows}
    return dict(kind='historical_technical_signal_analysis',source=source['source'],strategy_revision=STRATEGY_REVISION,
                market_retrieved_at=source['retrieved_at'],market_snapshot_sha256=source.get('market_snapshot_sha256',digest(source)),
                window=dict(analysis_start=start,analysis_end=end,query_start=query_start,warmup_sessions_requested=55,expected_sample_sessions=len(sample)),tickers=outputs)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--freeze',action='store_true',required=True);parser.parse_args()
    print(freeze(Path(__file__).resolve().parents[1],datetime.now(timezone.utc)))
