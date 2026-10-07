"""Optional manifest-based extraction; acquire_observed needs no supplied manifest.

No strike grid, synthetic-price fallback, overwrite, credentials, or automatic
promotion of today's chain into a historical universe. See SCHEMA.md.
"""
import argparse
from datetime import datetime, timezone, timedelta, date
import hashlib
import json
from pathlib import Path

from .calendar import Calendar
from .config import Config
from .data import finite, mid, Market

FIELDS=['BID','ASK','MID_PRICE','TRDPRC_1','DELTA']
DIV_FIELDS=['TR.DivAnnouncementDate','TR.DivExDate','TR.DivPayDate','TR.DivUnAdjustedGross']


def parse_daily(raw,ident,stock=False):
    """A DATE is not an intraday quote timestamp. Do not manufacture one."""
    if raw.get('interval')!='P1D' or raw.get('summaryTimestampLabel')!='endPeriod':
        raise ValueError('Expected daily endPeriod response')
    headers=[h['name'] for h in raw['headers']]
    if 'DATE' not in headers:
        raise ValueError('Daily DATE header is required')
    rows=[]
    for values in raw.get('data',[]):
        item=dict(zip(headers,values));day=item['DATE'][:10]
        r=dict(date=day,precision='daily',source_timestamp=None,available_at=None)
        def val(key):
            v=item.get(key)
            if v is not None and not finite(v):
                raise ValueError(f'Non-finite {ident} {day} {key}')
            return v
        if stock:
            r.update(price=val('TRDPRC_1'),ric=ident)
        else:
            r.update(id=ident,bid=val('BID'),ask=val('ASK'),vendor_mid=val('MID_PRICE'),trade=val('TRDPRC_1'),
                     delta=val('DELTA'),delta_source='historical',quote_time_synchronization='unknown at daily precision')
            b,a,v=r['bid'],r['ask'],r['vendor_mid']
            if finite(b) and finite(a) and finite(v) and abs((b+a)/2-v)>1e-6:
                r['quote_inconsistent']=True
            # MID_PRICE alone is never automatically substituted for a missing BBO.
            r['vendor_mid_definition_verified']=False
        rows.append(r)
    return sorted(rows,key=lambda r:r['date'])


def parse_dividends(rows):
    result=[]
    for r in rows:
        ex=r.get('Dividend Ex Date');pay=r.get('Dividend Pay Date');announce=r.get('Dividend Announcement Date')
        amount=r.get('Gross Dividend Amount')
        if not ex or not finite(amount):
            continue
        # Date-only announcements become usable the following local day, not
        # at an invented earlier intraday publication time.
        known=(date.fromisoformat(announce[:10])+timedelta(days=1)).isoformat()+'T00:00:00' if announce else None
        if known:
            import pandas as pd
            known=pd.Timestamp(known,tz='America/New_York').isoformat()
        result.append(dict(ex_date=ex[:10],pay_date=pay[:10] if pay else None,amount=amount,
                           announced_at=known,announcement_precision='daily; next-day conservative availability',
                           source_announcement_date=announce[:10] if announce else None))
    return sorted(result,key=lambda d:d['ex_date'])


def request_daily(hp,ric,start,end,fields):
    response=hp.summaries.Definition(universe=ric,start=start,end=end,interval=hp.Intervals.DAILY,
        sessions=hp.MarketSession.NORMAL,adjustments=[hp.Adjustments.EXCHANGE_CORRECTION,hp.Adjustments.MANUAL_CORRECTION],fields=fields).get_data()
    if not response.is_success:
        raise RuntimeError(f'Unsuccessful LSEG response for {ric}')
    return response.data.raw


def extract(manifest_path,output):
    output=Path(output)
    if output.exists(): raise ValueError('Refusing to overwrite a real input snapshot')
    manifest=json.loads(Path(manifest_path).read_text());cfg=Config(**manifest['config'])
    terms=manifest['contracts']
    if not terms: raise ValueError('Empty optional manifest; use acquire_observed to assemble evidence automatically')
    gate=Market.__new__(Market);gate.config=cfg
    for c in terms:
        for field in ('id','strike','expiry','last_trade_date','known_from','multiplier','deliverable','underlying','currency','cp','terms_source','standard_verified'):
            if field not in c: raise ValueError(f'Missing {field}: {c.get("id")}')
        if not c['terms_source'] or not gate.standard(c):
            raise ValueError(f'Contract lacks verified or explicitly supported assumed terms: {c["id"]}')
    import lseg.data as ld
    from lseg.data.content import historical_pricing as hp
    output.parent.mkdir(parents=True,exist_ok=True)
    rawdir=output.parent/(output.stem+'_raw')
    rawdir.mkdir(exist_ok=True)
    start=Calendar(cfg.start,cfg.end).previous(Calendar(cfg.start,cfg.end).sessions[0])
    logs=[]
    def get(ric,fields):
        key=hashlib.sha256(json.dumps([ric,start,cfg.end,fields]).encode()).hexdigest()[:20]
        path=rawdir/(key+'.json')
        if path.exists():
            saved=json.loads(path.read_text())
        else:
            try: saved={'ric':ric,'raw':request_daily(hp,ric,start,cfg.end,fields)}
            except Exception as exc: saved={'ric':ric,'error':str(exc)}
            path.write_text(json.dumps(saved,allow_nan=False,indent=2))
        logs.append(dict(ric=ric,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),error=saved.get('error')))
        return saved.get('raw')
    ld.open_session()
    try:
        stockraw=get(cfg.stock_ric,['TRDPRC_1'])
        if stockraw is None: raise RuntimeError('Real stock history unavailable; no synthetic fallback')
        stock=parse_daily(stockraw,cfg.stock_ric,stock=True);options=[]
        for i,c in enumerate(terms):
            raw=get(c['id'],FIELDS)
            if raw is not None: options.extend(parse_daily(raw,c['id']))
            print(f'{i+1}/{len(terms)} {c["id"]}: {"received" if raw else "missing; logged"}',flush=True)
        df=ld.get_data(cfg.stock_ric,fields=DIV_FIELDS,parameters={'SDate':start,'EDate':cfg.end})
        divraw=json.loads(df.to_json(orient='records',date_format='iso'))
        divpath=rawdir/'dividends.json';divpath.write_text(json.dumps(divraw,indent=2))
        dividends=parse_dividends(divraw)
    finally: ld.close_session()
    md=dict(source='LSEG',synthetic=False,stock_unadjusted=True,source_precision='daily',
            fetched_at=datetime.now(timezone.utc).isoformat(),config=cfg.to_dict(),research_window_locked=True,
            window_selection_reason=manifest['window_selection_reason'],candidate_universe=manifest['candidate_universe'],
            availability_policy='previous_session_by_next_09_assumed',
            quote_basis='Daily endPeriod BID/ASK; exact synchronized quote timestamps are not supplied.',
            dividend_coverage_verified=manifest.get('dividend_coverage_verified',False),
            dividend_assignment_enabled=bool(dividends) and all(d['announced_at'] for d in dividends),
            field_definitions_source='https://developers.lseg.com/en/api-catalog/lseg-data-platform/lseg-data-library-for-python/tutorials/content-tutorials/historical-pricing',
            terms_verified=all(c['standard_verified'] for c in terms),requests=logs,
            adjustments=['exchangeCorrection','manualCorrection'],sessions='normal',
            contract_manifest_sha256=hashlib.sha256(Path(manifest_path).read_bytes()).hexdigest())
    output.write_text(json.dumps(dict(metadata=md,contracts=terms,stock=stock,options=options,dividends=dividends),allow_nan=False,indent=2))
    print(f'Saved private input {output}; audit before running performance.')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();extract(args.manifest,args.output)
