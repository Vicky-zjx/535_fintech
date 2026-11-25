"""Reconcile downloaded adjustment probes without changing a single price."""
import math
import pandas as pd


def analyze(e):
    out={}
    for ticker,probe in e['probes']['adjustments'].items():
        stock=e['tickers'][ticker];primary={r['date']:r['close'] for r in stock['history']}
        comparisons=[]
        for q in probe['price_comparisons']:
            raw=e['raw_records'].get(q['query_id'])
            result=dict(adjusted=q['adjusted'],status='unavailable',compared=0,differences=0,missing_dates=[])
            if raw and [c.casefold() for c in raw['columns']]==['instrument','date','tr.closeprice']:
                values={};valid=True
                for ric,day,price in raw['data']:
                    if ric!=stock['ric'] or day is None:valid=False;break
                    parsed=pd.to_datetime(day,errors='coerce')
                    if pd.isna(parsed):valid=False;break
                    day=str(parsed.date())
                    if day not in primary or (price is not None and (type(price) not in (float,int) or not math.isfinite(price) or price<=0)):
                        valid=False;break
                    if day in values and values[day]!=price:valid=False;break
                    values[day]=price
                if valid:
                    matched=[day for day,v in primary.items() if v is not None and values.get(day) is not None]
                    result.update(status='compared',compared=len(matched),
                        differences=sum(not math.isclose(primary[day],values[day],rel_tol=0,abs_tol=1e-8) for day in matched),
                        missing_dates=[day for day,v in primary.items() if v is not None and values.get(day) is None])
            comparisons.append(result)
        raw=e['raw_records'].get(probe['corporate_actions']['query_id'])
        ca=dict(returned_rows=len(raw['data']) if raw else 0,dated_rows_in_window=0,
                dated_rows_outside_window=0,non_unit_factors_in_window=0)
        if raw and [c.casefold() for c in raw['columns']]==['instrument','tr.caeffectivedate','tr.caadjustmentfactor','tr.caadjustmenttype']:
            for ric,day,factor,_ in raw['data']:
                if ric!=stock['ric'] or day is None:continue
                parsed=pd.to_datetime(day,errors='coerce')
                if pd.isna(parsed):continue
                if e['window']['query_start']<=str(parsed.date())<=e['window']['analysis_end']:
                    ca['dated_rows_in_window']+=1
                    if type(factor) in (int,float) and math.isfinite(factor) and factor!=1:ca['non_unit_factors_in_window']+=1
                else:ca['dated_rows_outside_window']+=1
        out[ticker]=dict(price_comparisons=comparisons,corporate_action_probe=ca)
    return dict(tickers=out,policy='No additional price adjustment; comparison is not complete corporate-action or total-return validation. Empty or out-of-window corporate-action records do not establish absence of events.')
