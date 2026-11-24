"""Persistent prospective evidence, never truncated to a rolling source window.

Private state, excluded from the publication bundle. Storage must survive runner
replacement; without it, reconstruction is allowed only from complete coverage.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import pandas as pd
import exchange_calendars as xcals
from final_project.data_provider import digest
from .reliability import TICKERS

KEEP=('ticker','signal_date','reference_date','outcome_date','cohort','status','reason',
      'stock_return','adverse_move','tail_event','missing_dates','prospective')


def path(root):
    base=Path(os.environ.get('THESIS_STATE_DIRECTORY',str(Path(root)/'.thesis-state'))).resolve()
    if base.is_relative_to((Path(root)/'investment-thesis').resolve()):
        raise ValueError('Forward state must not be in the website directory')
    return base/'forward_history.json'


def prepare(root,d,reference):
    cutoff=reference['evidence']['reference_end'];asof=d['window']['analysis_end']
    p=path(root);old=json.loads(p.read_text()) if p.exists() else None
    if old and (old.get('content_sha256')!=digest(old.get('content')) or
                old['content']['reference_sha256']!=reference['evidence_sha256']):
        raise ValueError('Prospective state/reference integrity conflict')
    b=deepcopy(old['content']) if old else dict(version=1,reference_sha256=reference['evidence_sha256'],
        cutoff=cutoff,as_of=cutoff,rows={t:[] for t in TICKERS},sources=[])
    if b['as_of']>asof:raise ValueError('Incoming source is older than retained forward history')
    cal=xcals.get_calendar('XNYS',start=str(pd.Timestamp(cutoff)-pd.Timedelta(days=10)),
                          end=str(pd.Timestamp(asof)+pd.Timedelta(days=25)))
    dates=[str(x.date()) for x in cal.sessions_in_range(cutoff,asof) if str(x.date())>cutoff]
    for t in TICKERS:
        existing={r['signal_date']:r for r in b['rows'][t]}
        for r in d['rows'][t]:
            if not cutoff<r['signal_date']<=asof:continue
            incoming={k:deepcopy(r[k]) for k in KEEP};prior=existing.get(r['signal_date'])
            if prior and any(incoming[k]!=prior[k] for k in ('cohort','reference_date','outcome_date')):
                raise ValueError('Previously classified signal was revised; review required')
            if prior and prior['status']!='unmatured':
                # Later rolling inputs may no longer have the start of an old
                # path. They cannot overwrite a previously observed outcome.
                if r['status']=='observed' and prior['status']=='observed' and incoming!=prior:
                    raise ValueError('Previously matured prospective evidence was revised; review required')
                continue
            existing[r['signal_date']]=incoming
        if sorted(existing)!=dates:
            raise ValueError('Prospective history incomplete; restore private state, never reset baseline')
        b['rows'][t]=[existing[day] for day in dates]
    b['as_of']=asof
    if d['market_snapshot_sha256'] not in b['sources']:b['sources'].append(d['market_snapshot_sha256'])
    obj=dict(content=b,content_sha256=digest(b))
    monitor=dict(rows=b['rows'],window={**d['window'],'analysis_start':dates[0] if dates else cutoff})
    return obj,monitor


def write(root,obj):
    from final_project.sanji_orders import atomic_json
    p=path(root);p.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    atomic_json(p,obj);p.chmod(0o600)
