"""Separate immutable Wheel acquisition. No original cache is modified."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime,timezone,timedelta,date
import hashlib,json
from pathlib import Path
from .config import Config
from .data import Calendar,candidate_ric,parse_ric,resolve,finite
from pmcc_backtest.fetch_lseg import request_daily,parse_daily,FIELDS


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_config(path):return Config(**json.loads(Path(path).read_text())) if path else Config()


def acquire(base,output,cache,cfg,*,discovery=None,offline=False):
    if output.exists():raise ValueError('Use a NEW output snapshot; old market data is never overwritten')
    data=json.loads(base.read_text());md=data['metadata'];cal=Calendar(cfg.start,cfg.end)
    if md.get('source')!='LSEG' or md.get('synthetic') is not False:raise ValueError('Real source required')
    if md.get('config',{}).get('stock_ric')!=cfg.stock_ric:raise ValueError('Supply a matching real base for a different underlying')
    if cfg.start<md['config']['start'] or cfg.end>md['config']['end']:raise ValueError('Requested dates extend beyond validated equity/dividend/corporate-action base')
    strikes={c['strike'] for c in data['contracts']};discovery_sha=None
    if discovery:
        discovery_sha=digest(discovery)
        for record in json.loads(discovery.read_text()):
            try:c=parse_ric(record['RIC'],cfg.stock_ric)
            except (KeyError,ValueError):continue
            if c['strike']==record.get('StrikePrice'):strikes.add(c['strike'])
    stock={r['date']:r['price'] for r in data['stock']};planrows=[];ids=set()
    for w in cal.weekly():
        spot=stock.get(w['previous_session']);expiries=[]
        if not finite(spot):continue
        for offset in range(cfg.dte_min,cfg.dte_max+1):
            expiry=str(date.fromisoformat(w['date'])+timedelta(days=offset))
            if date.fromisoformat(expiry).weekday()==4:expiries.append(expiry)
        leads=sorted(k for k in strikes if .85*spot<=k<=1.15*spot)
        for expiry in expiries:
            # Both types: reuse existing exact IDs, query only missing ones.
            probes=[candidate_ric(cfg.stock_ric,expiry,k,cp) for cp in ('P','C') for k in leads]
            planrows.append(dict(entry_date=w['date'],signal_date=w['previous_session'],expiry=expiry,strike_leads=leads,probe_ids=probes))
            ids.update(probes)
    original={c['id']:c for c in data['contracts']};needed=sorted(ids-set(original))
    plan=dict(base_sha256=digest(base),config=cfg.to_dict(),discovery_sha256=discovery_sha,requests=needed,weeks=planrows,
        scope='85%-115% prior spot; strike leads from retained real RICs/discovery, never a synthetic strike grid. Reconstructed IDs are unverified probes until actual historical prices establish membership. Current/retained discovery is NOT a complete historical chain. Plans locked before Wheel P&L.')
    cache.mkdir(parents=True,exist_ok=True);lock=cache/'plan.json'
    if lock.exists():
        if json.loads(lock.read_text())!=plan:raise ValueError('Acquisition plan changed; use a new cache directory')
    else:lock.write_text(json.dumps(plan,sort_keys=True,indent=2)+'\n')
    ld=hp=None;connection_error=None
    if not offline:
        try:
            import lseg.data as ld
            from lseg.data.content import historical_pricing as hp
            session=ld.open_session()
            # Small actual price request tests functionality before a large batch.
            request_daily(hp,cfg.stock_ric,cal.previous(cal.sessions[0]),cfg.end,['TRDPRC_1'])
        except Exception as exc:connection_error=f'{type(exc).__name__}: {exc}'
    logs=[];newrows=[];newcontracts=[];exclusions=[]
    def get(ric):
        path=cache/(hashlib.sha256(ric.encode()).hexdigest()[:24]+'.json')
        if path.exists():saved=json.loads(path.read_text())
        elif offline or connection_error:return ric,{'error':connection_error or 'NOT_IN_RETAINED_WHEEL_CACHE'},None
        else:
            saved=dict(id=ric,start=cal.previous(cal.sessions[0]),end=cfg.end,fields=FIELDS,requested_at=datetime.now(timezone.utc).isoformat())
            try:saved['raw']=request_daily(hp,ric,saved['start'],cfg.end,FIELDS)
            except Exception as exc:saved['error']=f'{type(exc).__name__}: {exc}'
            path.write_text(json.dumps(saved,indent=2,allow_nan=False)+'\n')
        return ric,saved,digest(path)
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            for n,(ric,saved,sha) in enumerate(pool.map(get,needed)):
                rows=parse_daily(saved['raw'],ric) if 'raw' in saved else []
                logs.append(dict(id=ric,raw_sha256=sha,rows=len(rows),error=saved.get('error')))
                try:c=resolve(ric,cfg.stock_ric,cal,rows,md['corporate_action_review'])
                except ValueError as exc:exclusions.append(dict(id=ric,reason=str(exc)));continue
                for q in rows:q['source_snapshot_sha256']=sha
                newcontracts.append(c);newrows.extend(rows)
                if n%20==0:print('WHEEL_HISTORY',n+1,'/',len(needed),flush=True)
    finally:
        if ld:ld.close_session()
    # Preserve every original quote and term verbatim; build a separate superset.
    data['contracts']+=newcontracts;data['options']+=newrows
    data['metadata']=deepcopy(md)|dict(wheel_config=cfg.to_dict(),wheel_acquisition=dict(plan=plan,requests=logs,exclusions=exclusions,
        connection_error=connection_error,offline=offline,acquired_contracts=len(newcontracts),acquired_rows=len(newrows)),
        candidate_universe=plan['scope'],wheel_base_sha256=plan['base_sha256'])
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(data,sort_keys=True,indent=2,allow_nan=False)+'\n')
    print(json.dumps(dict(output=str(output),requested=len(needed),new_contracts=len(newcontracts),new_rows=len(newrows),connection_error=connection_error),indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--cache-dir',type=Path,required=True);p.add_argument('--config',type=Path);p.add_argument('--discovery',type=Path);p.add_argument('--offline',action='store_true')
    a=p.parse_args();acquire(a.base,a.output,a.cache_dir,read_config(a.config),discovery=a.discovery,offline=a.offline)
