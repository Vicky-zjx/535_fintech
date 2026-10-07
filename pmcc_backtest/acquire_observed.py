"""Acquire exact observed/discovered RICs; apply source-labeled research terms.

The window is locked from data availability before any strategy P&L. No fresh
strike grid, selection from future completeness, or synthetic market prices.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import hashlib,json
from pathlib import Path
import time

from .calendar import Calendar
from .config import Config
from .contracts import resolve,parse_ric,APPLE_SOURCE,OCC_AAPL_2020,OCC_SOURCE,ADJUSTMENT_SOURCE
from .data import finite
from .fetch_lseg import request_daily,parse_daily,parse_dividends,FIELDS


def acquire(root,output):
    if output.exists(): raise ValueError('Choose a new output; existing prices are never overwritten')
    private=root/'pmcc_backtest/local_data';p=private/'probe'
    cfg=Config(start='2026-07-06',end='2026-09-30')
    cal=Calendar(cfg.start,cfg.end)
    reason=('Window locked before P&L: the existing observed expired-short universe begins July 2026; '
            'a 12-month weekly-chain study is unsupported. Start July 6 preserves the previous assignment overlap; '
            'end September 30 retains the requested endpoint and all missing late-September short opportunities. '
            'No date is chosen from subsequent strategy returns.')
    lock=dict(config=cfg.to_dict(),locked_at=datetime.now(timezone.utc).isoformat(),reason=reason)
    lockpath=private/'window_lock.json'
    if lockpath.exists():
        saved=json.loads(lockpath.read_text())
        if saved['config']!=lock['config']:raise ValueError('Research window already locked differently')
        lock=saved
    else:lockpath.write_text(json.dumps(lock,indent=2))
    oldpath=root/'covered_call/data/aapl_hourly_verified.json';old=json.loads(oldpath.read_text())
    descriptions=json.loads((p/'long_metadata.json').read_text())
    # These are actual previously observed/discovered identities, never a grid.
    ids={q['ric']:q for q in old['options']}
    desc={q['RIC']:q for q in descriptions}
    rawdir=private/'observed_daily_raw';rawdir.mkdir(exist_ok=True)
    import lseg.data as ld
    from lseg.data.content import historical_pricing as hp
    ld.open_session()
    try:
        capath=private/'corporate_actions.json'
        if capath.exists(): ca=json.loads(capath.read_text())
        else:
            try:
                df=ld.get_data('AAPL.O',fields=['TR.CAEffectiveDate','TR.CAAdjustmentFactor','TR.CAAdjustmentType','TR.CACorpActDesc'],parameters={'SDate':'2025-09-30','EDate':'2026-09-30'})
                ca=json.loads(df.to_json(orient='records',date_format='iso'))
            except Exception as exc: ca={'error':str(exc)}
            capath.write_text(json.dumps(ca,indent=2))
        print('CORPORATE_ACTION_REVIEW',str(ca)[:5000],flush=True)
        # Review actual nontrivial events before permitting a standard assumption.
        events=[] if isinstance(ca,dict) else [r for r in ca if any(v not in (None,'') and k!='Instrument' for k,v in r.items())]
        ambiguous=[]
        for event in events:
            factor=event.get('Adjustment Factor')
            desc_text=str(event.get('Corporate Action Description','')).lower()
            if finite(factor) and abs(factor-1)>1e-10:
                ambiguous.append(event)
            elif any(w in desc_text for w in ('split','spin','merger','rights','special')):
                ambiguous.append(event)
        review=dict(status='research screening, not a complete OCC memo search',provider_events=events,
                    provider_error=ca.get('error') if isinstance(ca,dict) else None,
                    provider_query_period=['2025-09-30','2026-09-30'],unresolved_adjustment_event=bool(ambiguous),
                    apple_split_history='Apple public FAQ lists its last split in August 2020, before this sample.',
                    sources=[APPLE_SOURCE,OCC_AAPL_2020,OCC_SOURCE,ADJUSTMENT_SOURCE],
                    limitation='No detected conflicting corporate-action evidence; absence is not a vendor guarantee of every historical deliverable.')
        if ambiguous:raise ValueError('Review actual adjustment events before proceeding: '+str(ambiguous))
        terms=[];excluded=[]
        for ident in sorted(set(ids)|set(desc)):
            try:
                c=resolve(ident,cal,description=desc.get(ident),existing=ids.get(ident),corporate_action_review=review)
                if ident in desc and c['expiry']<'2027-07-02':
                    excluded.append(dict(id=ident,reason='OUTSIDE_PREDECLARED_LONG_DTE_WINDOW',scope='data-acquisition filter, not a claim of invalid listing'));continue
                terms.append(c)
            except ValueError as exc:excluded.append(dict(id=ident,reason=str(exc),scope='contract identity/terms screening'))
        def get(c):
            key=hashlib.sha256(c['id'].encode()).hexdigest()[:20];path=rawdir/(key+'.json')
            if path.exists():saved=json.loads(path.read_text())
            else:
                saved=dict(ric=c['id'],start='2026-06-29',end=cfg.end)
                for attempt in range(2):
                    try:
                        saved['raw']=request_daily(hp,c['id'],'2026-06-29',cfg.end,FIELDS);break
                    except Exception as exc:
                        saved['error']=str(exc)
                        if attempt==0:time.sleep(.4)
                path.write_text(json.dumps(saved,allow_nan=False,indent=2))
            rows=parse_daily(saved['raw'],c['id']) if 'raw' in saved else []
            log=dict(id=c['id'],sha256=hashlib.sha256(path.read_bytes()).hexdigest(),error=saved.get('error'))
            for r in rows:r['source_snapshot_sha256']=log['sha256']
            prior=p/(c['id'].replace('^','_')+'.json')
            if prior.exists():
                prior_rows=parse_daily(json.loads(prior.read_text()),c['id']);by={r['date']:r for r in rows}
                phash=hashlib.sha256(prior.read_bytes()).hexdigest()
                for r in prior_rows:
                    if r['date'] in by:
                        newer=by[r['date']]
                        if (r['bid'],r['ask'])!=(newer['bid'],newer['ask']):
                            raise ValueError('CONFLICTING_REAL_SNAPSHOTS_REQUIRES_REVIEW: '+c['id']+' '+r['date'])
                    else:
                        r['source_snapshot_sha256']=phash
                        by[r['date']]=r
                rows=sorted(by.values(),key=lambda r:r['date'])
                log['earlier_real_snapshot_sha256']=phash
                log['merge_policy']='Preserve earlier real dates missing from new reply; overlapping BBO must agree; no interpolation.'
            return c,rows,log
        options=[];logs=[];kept=[]
        with ThreadPoolExecutor(max_workers=3) as pool:
            for i,(c,rows,log) in enumerate(pool.map(get,terms)):
                evidenced=[r for r in rows if any(finite(r.get(f)) for f in ('bid','ask','trade','vendor_mid'))]
                dates=sorted(r['date'] for r in evidenced)
                if dates:
                    c.update(known_from=dates[0],first_observed_quote_date=dates[0],last_observed_quote_date=dates[-1])
                    c['provenance']['historical_membership']=dict(status='actual historical observations; per-signal availability gating',first=dates[0],last=dates[-1],raw_sha256=log['sha256'])
                    kept.append(c);options.extend(rows)
                else:excluded.append(dict(id=c['id'],reason='NO_HISTORICAL_PRICE_EVIDENCE_IN_ACQUISITION_WINDOW',scope='observed membership; not proven unlisted'))
                logs.append(log)
                print(f'{i+1}/{len(terms)} {c["id"]} real daily rows={len(rows)}',flush=True)
    finally:ld.close_session()
    stock=parse_daily(json.loads((p/'stock_daily.json').read_text()),cfg.stock_ric,stock=True)
    stock=[r for r in stock if r['date']>='2026-06-29']
    dividends=parse_dividends(json.loads((p/'dividends.json').read_text()))
    md=dict(source='LSEG',synthetic=False,stock_unadjusted=True,source_precision='daily',config=cfg.to_dict(),
            research_window_locked=True,window_lock=lock,window_selection_reason=reason,
            terms_verified=False,standard_assumption_policy='source-supported standard AAPL contract assumption; not per-contract vendor historical verification',
            candidate_universe='Observed subset: 56 exact expired-call RICs from the prior real cache plus eligible ordinary OPRA long-call IDs from current LSEG discovery, admitted only with historical price evidence by each signal. No complete historical chain or globally minimal listed strike is claimed; long discovery has survivor bias.',
            availability_policy='previous_session_by_next_09_assumed',quote_basis='Real same-date daily closing BID/ASK; MID_PRICE cross-check; exact simultaneous quote times unknown.',
            dividend_coverage_verified=True,dividend_assignment_enabled=all(d['announced_at'] for d in dividends),
            corporate_action_review=review,exclusions=excluded,requests=logs,old_cache_sha256=hashlib.sha256(oldpath.read_bytes()).hexdigest(),
            field_definitions_source='https://developers.lseg.com/en/api-catalog/lseg-data-platform/lseg-data-library-for-python/tutorials/content-tutorials/historical-pricing',
            adjustments=['exchangeCorrection','manualCorrection'],sessions='normal',
            long_mode_note='75%-of-spot proxy predeclared before P&L; subsequently returned historical DELTA is used for exposure only, not a mode switch.',
            acquisition_strike_scope='Long discovery cap 255 is a request bound on actual returned strikes, not a listing grid; all sample signal stock closes ×0.75 are below it.',
            fetched_at=datetime.now(timezone.utc).isoformat())
    output.write_text(json.dumps(dict(metadata=md,contracts=kept,stock=stock,options=options,dividends=dividends),indent=2,allow_nan=False))
    print(json.dumps(dict(output=str(output),contracts=len(kept),options=len(options),exclusions=len(excluded),locked_config=cfg.to_dict()),indent=2))


if __name__=='__main__':
    from .repair_coverage import repair
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--base-input',type=Path,help='Retained real baseline; never overwritten')
    p.add_argument('--cache-dir',type=Path,help='Immutable repair request directory')
    p.add_argument('--offline',action='store_true',help='Use retained request responses only')
    args=p.parse_args();root=Path(__file__).resolve().parents[1]
    if args.output.exists():raise ValueError('Choose a new output snapshot')
    base=args.base_input or args.output.with_stem(args.output.stem+'_base')
    if not args.base_input:
        if args.offline:raise ValueError('Offline assembly requires --base-input')
        acquire(root,base)
    repair(base,args.output,args.cache_dir or args.output.parent/(args.output.stem+'_repair'),offline=args.offline)
