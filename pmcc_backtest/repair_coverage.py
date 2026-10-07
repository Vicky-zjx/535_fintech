"""Immutable, real LSEG coverage repair; never run P&L to choose request scope."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime,timezone
import hashlib,json
from pathlib import Path
import pandas as pd

from .calendar import Calendar
from .config import Config
from .contracts import candidate_call_ric,parse_ric,resolve,RIC_SOURCE
from .data import finite,mid,Market
from .fetch_lseg import request_daily,parse_daily,FIELDS

SERIES=['2026-09-11','2026-09-18','2026-09-25','2026-10-02']
HISTORY_SOURCE='https://developers.lseg.com/en/api-catalog/lseg-data-platform/lseg-data-library-for-python/tutorials/content-tutorials/historical-pricing'
EVENT_SOURCE='https://community.developers.lseg.com/discussion/72431/historical-pricing-api-rdp'
CLOSE_POLICY=('Daily BBO first; when a daily leg is absent, use the LAST quote event in the final 60 seconds of the actual regular session only if its complete BBO, source timestamp and event timestamp pass validation. The same quote supports daily marking and the unchanged midpoint/quoted-side closing-fill formulas. Never treat it as an observed fill or relabel its timestamp as the exact close. No previous bar, forward fill, theoretical/trade substitution or null-to-zero conversion. Signal selection still uses the original prior-session data.')


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def event_mark(raw,day,close):
    """Only a complete quote event in the final 60s, never a previous bar."""
    header=[h['name'] for h in raw.get('headers',[])]
    events=[];closing=pd.Timestamp(close)
    for values in raw.get('data',[]):
        r=dict(zip(header,values))
        if r.get('EVENT_TYPE')!='quote' or not r.get('DATE_TIME'):continue
        stamp=pd.Timestamp(r['DATE_TIME'])
        if stamp.tzinfo is not None and 0<=(closing-stamp).total_seconds()<=60:events.append((stamp,r))
    if not events:return None
    # Validate the LAST update, not the last valid update: a later invalid BBO
    # must not cause an older quote to be carried forward.
    stamp,r=max(events,key=lambda v:v[0])
    if not r.get('SOURCE_DATETIME'):return None
    source=pd.Timestamp(r['SOURCE_DATETIME'])
    if source.tzinfo is None or str(source.tz_convert('America/New_York').date())!=day:return None
    age=max((closing-stamp).total_seconds(),(closing-source).total_seconds())
    if source>closing or not 0<=age<=60:return None
    q=dict(bid=r.get('BID'),ask=r.get('ASK'))
    if mid(q) is None:return None
    return q|dict(date=day,source_timestamp=source.isoformat(),event_timestamp=stamp.isoformat(),
                  age_seconds=age,method='same_event_bbo_final_60_seconds',source='LSEG quote event',
                  closing_reference=close,valuation_only=False,precision='quote_event',
                  closing_reference_only=True)


def repair(input_path,output,cache,*,offline=False):
    if output.exists():raise ValueError('Choose a new input snapshot; no overwrite')
    data=json.loads(input_path.read_text());cfg=Config(**data['metadata']['config'])
    assert (cfg.start,cfg.end,cfg.initial_equity)==('2026-07-06','2026-09-30',50000.)
    original_cfg=deepcopy(data['metadata']['config']);cal=Calendar(cfg.start,cfg.end)
    root=Path(__file__).resolve().parents[1]
    cache.mkdir(parents=True,exist_ok=True)
    discovery=root/'pmcc_backtest/local_data/probe/search_long.json'
    strikes={c['strike'] for c in data['contracts']}
    for c in json.loads(discovery.read_text()):
        try:parsed=parse_ric(c['RIC'])
        except ValueError:continue
        if parsed['cp']=='C' and parsed['strike']==c['StrikePrice']:strikes.add(parsed['strike'])
    stock={s['date']:s['price'] for s in data['stock']}
    plans=[]
    for w in cal.weekly():
        if w['friday'] not in SERIES:continue
        spot=stock[w['previous_session']]
        # Bounds only limit probing; no fabricated intermediate strike values.
        leads=sorted(k for k in strikes if .95*spot<=k<=1.20*spot)
        plans.append(dict(expiry=w['friday'],execution_day=w['date'],signal_day=w['previous_session'],
                          signal_spot=spot,probe_strikes=leads,
                          ids=[candidate_call_ric(w['friday'],k) for k in leads]))
    plan=dict(base_input_sha256=digest(input_path),config=original_cfg,series=plans,
              discovery_seed_sha256=digest(discovery),
              scope='Strike leads from actual ordinary AAPL OPRA identities in retained history/current discovery; reconstructed expiry RICs are probes only. Historical observations, not construction or current chain, determine signal-time membership. Bounds 95%-120% of prior-session stock price; no assumed strike grid or completeness claim.',
              valuation_policy='Daily BBO first. For missing daily BBO only, a complete same-event quote in the final 60 seconds of the actual regular session may supply a valuation-only midpoint. Never previous-session/earlier-bar fill-forward, trade/theoretical-price substitution, or null-to-zero conversion.')
    planpath=cache/'plan.json'
    if planpath.exists():assert json.loads(planpath.read_text())==plan,'Plan changed after acquisition'
    elif offline:raise ValueError('No retained acquisition plan')
    else:planpath.write_text(json.dumps(plan,sort_keys=True,indent=2))
    ld=hp=None
    if not offline:
        import lseg.data as ld
        from lseg.data.content import historical_pricing as hp
        ld.open_session()
    def cached(kind,ric,day=None):
        request=dict(kind=kind,ric=ric,day=day)
        key=hashlib.sha256(json.dumps(request,sort_keys=True).encode()).hexdigest()[:24]
        path=cache/(key+'.json')
        if path.exists():saved=json.loads(path.read_text())
        else:
            if offline:raise ValueError('Uncached request '+str(request))
            saved=dict(request=request,requested_at=datetime.now(timezone.utc).isoformat())
            try:
                if kind=='daily':
                    saved['raw']=request_daily(hp,ric,'2026-06-28',cfg.end,FIELDS)
                else:
                    end=pd.Timestamp(cal.close(day));start=end-pd.Timedelta(seconds=60)
                    response=hp.events.Definition(ric,eventTypes='quote',start=start.tz_convert('UTC').isoformat(),end=end.tz_convert('UTC').isoformat(),adjustments=[hp.Adjustments.EXCHANGE_CORRECTION,hp.Adjustments.MANUAL_CORRECTION]).get_data()
                    if not response.is_success:raise RuntimeError('LSEG quote-event response unsuccessful')
                    saved['raw']=response.data.raw
            except Exception as exc:saved['error']=str(exc)
            path.write_text(json.dumps(saved,indent=2,allow_nan=False))
        return saved,digest(path)
    try:
        contracts={c['id']:c for c in data['contracts']};quotes={(q['id'],q['date']):q for q in data['options']}
        logs=[];rejections=[]
        all_ids=sorted({i for p in plans for i in p['ids']})
        def query(ric):return ric,*cached('daily',ric)
        with ThreadPoolExecutor(max_workers=3) as pool:
            for index,(ric,saved,sha) in enumerate(pool.map(query,all_ids)):
                rows=parse_daily(saved['raw'],ric) if 'raw' in saved else []
                rows=[r for r in rows if r['date']<=cfg.end]
                evidence=[r for r in rows if any(finite(r.get(k)) and r[k]>0 for k in ('bid','ask','vendor_mid','trade'))]
                logs.append(dict(id=ric,raw_sha256=sha,rows=len(rows),error=saved.get('error')))
                if evidence:
                    c=resolve(ric,cal,corporate_action_review=data['metadata']['corporate_action_review'])
                    dates=sorted(r['date'] for r in evidence)
                    c.update(known_from=dates[0],first_observed_quote_date=dates[0],last_observed_quote_date=dates[-1])
                    c['provenance']['historical_membership']=dict(status='actual historical response; gated before each signal',first=dates[0],last=dates[-1],raw_sha256=sha)
                    c['provenance']['candidate_construction']=dict(status='RIC probe, not listing evidence',source=RIC_SOURCE)
                    contracts[ric]=c
                    for row in rows:
                        row['source_snapshot_sha256']=sha
                        key=(ric,row['date'])
                        if key in quotes and any(quotes[key].get(f)!=row.get(f) for f in ('bid','ask','trade','vendor_mid')):
                            raise ValueError('Conflicting preserved quote '+str(key))
                        quotes.setdefault(key,row)
                else:rejections.append(dict(id=ric,reason='NO_PRICE_EVIDENCE_RETURNED_BY_BOUNDED_HISTORY_REQUEST',scope='probe failed to establish membership; not evidence of never listed'))
                if index%10==0 or index==len(all_ids)-1:print('HISTORICAL_CANDIDATES',index+1,'/',len(all_ids),flush=True)
        data['contracts']=sorted(contracts.values(),key=lambda c:c['id'])
        data['options']=sorted(quotes.values(),key=lambda r:(r['id'],r['date']))
        # Apply the same valuation-only recovery rule to every missing daily BBO,
        # not just positions selected after looking at P&L.
        missing=[q for q in data['options'] if cfg.start<=q['date']<=cfg.end and cal.exchange.is_session(q['date']) and mid(q) is None and (q.get('bid') is None or q.get('ask') is None)]
        repairs=[]
        def quote_query(q):return q,*cached('quote_events',q['id'],q['date'])
        with ThreadPoolExecutor(max_workers=3) as pool:
            for index,(q,saved,sha) in enumerate(pool.map(quote_query,missing)):
                mark=event_mark(saved.get('raw',{}),q['date'],cal.close(q['date']))
                if mark:
                    mark['raw_sha256']=sha;q['valuation_quote']=mark
                repairs.append(dict(id=q['id'],date=q['date'],daily_bid_missing=q.get('bid') is None,
                                    status='recovered_closing_bbo' if mark else 'unresolved_no_valid_quote_in_final_60_seconds',
                                    source_timestamp=mark.get('source_timestamp') if mark else None,raw_sha256=sha,error=saved.get('error')))
                if index%20==0 or index==len(missing)-1:print('QUOTE_RECHECK',index+1,'/',len(missing),flush=True)
        data['metadata'].update(valuation_policy=CLOSE_POLICY,closing_execution_quote_policy='daily_bbo_then_last_event_final_60_seconds',
                                quote_policy_revision='Acquisition initially isolated events for valuation. The same bounded real BBO is now consumed by closing execution too, fixing an artificial daily-only terminal rejection. Midpoint/quoted-side formulas, timestamps, positive-bid entry gate, signal choices and all strategy parameters are unchanged.',
                                candidate_universe=plan['scope']+' Existing long-call discovery has survivor bias; earlier short expiries retain their observed subset.',
                                coverage_repair=dict(plan=plan,requests=logs,quote_checks=repairs,probe_rejections=rejections,sources=[RIC_SOURCE,HISTORY_SOURCE,EVENT_SOURCE]))
        m=Market(data,cfg,cal);coverage=[]
        for w in cal.weekly():
            cs=[c for c in data['contracts'] if c.get('series_friday')==w['friday']]
            known=[c for c in cs if m.observed(c,w['previous_session'])]
            planweek=next((p for p in plans if p['expiry']==w['friday']),None)
            coverage.append(dict(expiry=w['friday'],execution_day=w['date'],signal_day=w['previous_session'],
                                 scope='reconstructed_and_historically_validated_subset' if planweek else 'previously_observed_subset',
                                 complete=False,queried_candidates=len(planweek['ids']) if planweek else None,
                                 historical_contracts=len(cs),signal_observed_contracts=len(known),
                                 signal_observed_strikes=sorted({c['strike'] for c in known}),
                                 provider_errors=sum(bool(r['error']) for r in logs if r['id'] in planweek['ids']) if planweek else None))
        data['metadata']['short_universe_coverage']=coverage
        assert data['metadata']['config']==original_cfg
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(data,sort_keys=True,indent=2,allow_nan=False)+'\n')
        print(json.dumps(dict(output=str(output),contracts=len(contracts),option_rows=len(quotes),quote_recovered=sum(r['status']=='recovered_closing_bbo' for r in repairs),quote_unresolved=sum(r['status']!='recovered_closing_bbo' for r in repairs),series=coverage[-4:]),indent=2))
    finally:
        if ld:ld.close_session()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',required=True,type=Path);p.add_argument('--output',required=True,type=Path);p.add_argument('--cache-dir',required=True,type=Path);p.add_argument('--offline',action='store_true')
    a=p.parse_args();repair(a.input,a.output,a.cache_dir,offline=a.offline)
