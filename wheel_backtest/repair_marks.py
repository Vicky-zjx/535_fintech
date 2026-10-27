"""Recover all held-account missing marks using the same final-minute event rule.

Produces a NEW input. Original daily nulls, strategy selection and fills remain
unchanged. These additional events are valuation-only, never signal inputs.
"""
import argparse,json,hashlib
from datetime import datetime,timezone
from pathlib import Path
import pandas as pd
from .acquire import digest,read_config
from .engine import run
from .data import Calendar
from pmcc_backtest.repair_coverage import event_mark


def repair(source,output,cache,cfg,offline=False):
    if output.exists():raise ValueError('Use a new input file; no overwrite')
    data=json.loads(source.read_text());targets=set()
    for model in ('quoted_side','midpoint'):
        for row in run(data,cfg,'wheel',model)['ledger']:
            if row['option'] and row['option_mark'] is None:targets.add((row['date'],row['option']['id']))
    plan={'input_sha256':digest(source),'config':cfg.to_dict(),'targets':sorted([list(t) for t in targets]),
          'rule':'All held-option missing daily marks in both fill models; last same-event BBO in final 60 seconds only. Both source/event timestamps validated, no earlier valid quote through an invalid later update. Valuation only; no change to original daily fields, selection or fills.'}
    cache.mkdir(parents=True,exist_ok=True);p=cache/'plan.json'
    if p.exists():assert json.loads(p.read_text())==plan,'Immutable repair plan changed'
    else:p.write_text(json.dumps(plan,sort_keys=True,indent=2)+'\n')
    cal=Calendar(cfg.start,cfg.end);ld=hp=None;logs=[]
    if not offline:
        import lseg.data as ld
        from lseg.data.content import historical_pricing as hp
        ld.open_session()
    quotes={(q['date'],q['id']):q for q in data['options']}
    try:
        for day,ric in sorted(targets):
            file=cache/(hashlib.sha256((day+ric).encode()).hexdigest()[:24]+'.json')
            if file.exists():saved=json.loads(file.read_text())
            elif offline:raise ValueError('Missing cached response: '+ric+' '+day)
            else:
                end=pd.Timestamp(cal.close(day));start=end-pd.Timedelta(seconds=60)
                saved={'date':day,'ric':ric,'requested_at':datetime.now(timezone.utc).isoformat(),'start':start.isoformat(),'end':end.isoformat()}
                try:
                    r=hp.events.Definition(ric,eventTypes='quote',start=start.tz_convert('UTC').isoformat(),end=end.tz_convert('UTC').isoformat(),adjustments=[hp.Adjustments.EXCHANGE_CORRECTION,hp.Adjustments.MANUAL_CORRECTION]).get_data()
                    if not r.is_success:raise RuntimeError('Provider response unsuccessful')
                    saved['raw']=r.data.raw
                except Exception as exc:saved['error']=str(exc)
                file.write_text(json.dumps(saved,indent=2,allow_nan=False)+'\n')
            q=event_mark(saved.get('raw',{}),day,cal.close(day));sha=digest(file)
            if q:
                q.update(raw_sha256=sha,valuation_only=True)
                quotes[(day,ric)]['valuation_quote']=q
            logs.append(dict(date=day,id=ric,recovered=q is not None,raw_sha256=sha,source_timestamp=q.get('source_timestamp') if q else None,error=saved.get('error')))
    finally:
        if ld:ld.close_session()
    data['metadata']['wheel_mark_repair']={'plan':plan,'requests':logs}
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(data,sort_keys=True,indent=2,allow_nan=False)+'\n')
    print(json.dumps(logs,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--cache-dir',type=Path,required=True);p.add_argument('--config',type=Path);p.add_argument('--offline',action='store_true')
    a=p.parse_args();repair(a.input,a.output,a.cache_dir,read_config(a.config),a.offline)
