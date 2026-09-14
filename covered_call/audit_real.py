"""Independently reconcile published fills to raw LSEG replies and cash events."""

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd


def audit_real(cache, book_path):
    data=json.loads(cache.read_text())
    code=book_path.read_text()
    prefix='window.COVERED_CALL_BOOK = '
    if not code.startswith(prefix):
        raise ValueError('Unexpected baked result format')
    book=json.loads(code[len(prefix):].strip().removesuffix(';'))
    assert book['metadata']['cache_sha256']==hashlib.sha256(cache.read_bytes()).hexdigest()
    raw_index={}
    for req in data['metadata']['requests']:
        if not req['success']:
            continue
        saved=json.loads((cache.parent/'raw'/req['raw_file']).read_text())
        raw=saved['raw']
        assert raw['universe']['ric']==req['ric']
        assert raw['summaryTimestampLabel']=='startPeriod'
        headers=[x['name'] for x in raw['headers']]
        for values in raw['data']:
            row=dict(zip(headers,values))
            ts=pd.Timestamp(row['DATE_TIME']).as_unit('ns')+pd.Timedelta(hours=1)
            raw_index[(req['ric'],ts)]=row
    for row in data['stock']+data['options']:
        source=raw_index[(row['ric'],pd.Timestamp(row['timestamp']))]
        assert pd.Timestamp(row['source_timestamp'])==pd.Timestamp(source['DATE_TIME'])
        for key,field in [('print','TRDPRC_1'),('bid','BID'),('ask','ASK')]:
            if key in row:
                expected=source.get(field)
                if expected is None:
                    assert row[key] is None
                else:
                    assert math.isclose(row[key],expected,abs_tol=1e-10)

    stock={(r['ric'],pd.Timestamp(r['timestamp'])):r for r in data['stock']}
    options={(r['ric'],pd.Timestamp(r['timestamp'])):r for r in data['options']}
    # Independently reconstruct membership from actual raw-verified prices, not
    # from the production universe helper or any constructible identifier.
    first={}
    for r in sorted(data['options'],key=lambda row:pd.Timestamp(row['timestamp'])):
        if any(r.get(f) is not None and math.isfinite(r[f]) for f in ['bid','ask','print']):
            first.setdefault(r['ric'],r)
    assert set(first)=={r['ric'] for r in book['universe']['contracts']}
    assert book['universe']['complete_historical_chain'] is False
    for contract in book['universe']['contracts']:
        row=first[contract['ric']]
        assert contract['strike']==row['strike'] and contract['expiry']==row['expiry']
        assert pd.Timestamp(contract['first_observed_at'])==pd.Timestamp(row['timestamp'])
        assert contract['evidence']=={f:row.get(f) for f in ['source_timestamp','bid','ask','print']}
    for decision in book['decisions']:
        if 'expiry' not in decision:
            continue
        known=sorted({r['strike'] for r in first.values() if r['expiry']==decision['expiry']
                      and pd.Timestamp(r['timestamp'])<=pd.Timestamp(decision['timestamp'])})
        assert decision['observed_strikes']==known
        target=decision['target']
        eligible=[k for k in known if target is not None and k>=target-1e-10]
        assert decision['eligible_strikes']==eligible
        if decision['selected_strike'] is not None:
            assert decision['selected_strike']==min(eligible)
            assert pd.Timestamp(decision['selected_first_observed_at'])==pd.Timestamp(first[decision['ric']]['timestamp'])
    cash=book['config']['initial_cash']; shares=0; call=None
    for e in book['blotter']:
        ts=pd.Timestamp(e['timestamp'])
        if e['action']=='BUY':
            assert shares==0 and call is None
            source=stock[(e['instrument'],ts)]
            assert e['fill_price']==source['print']
            assert e['cash_delta']==-100*source['print']
            assert cash-0.5*100*source['print']>=0
            shares=100
        elif e['action']=='SELL':
            assert shares==100 and call is None
            source=options[(e['instrument'],ts)]
            assert source['bid'] is not None and source['ask'] is not None
            assert 0<=source['bid']<=source['ask'] and source['ask']>0
            mid=(source['bid']+source['ask'])/2
            assert e['limit_price']==e['fill_price']==mid
            assert e['cash_delta']==100*mid
            s=stock[(book['config']['stock_ric'],ts)]['print']
            known={r['strike'] for r in data['options'] if r['expiry']==e['expiry'] and pd.Timestamp(r['timestamp'])<=ts and any(r.get(f) is not None for f in ['bid','ask','print'])}
            eligible=[k for k in known if k>=s*1.05-1e-10]
            assert e['strike']==min(eligible)
            call=e
        else:
            assert call is not None and e['instrument']==call['instrument']
            assert ts.tz_convert(book['config']['timezone']).date().isoformat()==call['expiry']
            assert ts.tz_convert(book['config']['timezone']).strftime('%H:%M')==book['config']['expiry_time']
            s=stock[(book['config']['stock_ric'],ts)]['print']
            if e['action']=='ASSIGN':
                assert s>call['strike'] and e['cash_delta']==100*call['strike']
                shares=0
            else:
                assert e['action']=='EXPIRE' and s<=call['strike'] and e['cash_delta']==0
            call=None
        cash+=e['cash_delta']
        assert math.isclose(e['cash_after'],cash,abs_tol=1e-7)
    assert call is None
    final_stock=data['stock'][-1]['print']
    assert math.isclose(book['metrics']['ending_nav'],cash+shares*final_stock,abs_tol=1e-7)
    for p in book['validation']['points']:
        row=options[(p['ric'],pd.Timestamp(p['timestamp']))]
        assert p['trade']==row['print']
        assert p['mid']==(row['bid']+row['ask'])/2
    points=book['validation']['points']
    x=np.array([p['mid'] for p in points]);y=np.array([p['trade'] for p in points])
    design=np.column_stack([x,np.ones_like(x)])
    beta=np.linalg.lstsq(design,y,rcond=None)[0]
    independent_r2=1-np.sum((y-design@beta)**2)/np.sum((y-y.mean())**2)
    assert math.isclose(independent_r2,book['validation']['fit']['r2'],abs_tol=1e-10)
    print(json.dumps(dict(passed=True,source_rows_verified=len(data['stock'])+len(data['options']),
                          booked_events_verified=len(book['blotter']),regression_pairs_verified=len(points),
                          observed_contracts_verified=len(first),weekly_candidate_sets_verified=len(book['decisions']),
                          independently_computed_r2=float(independent_r2),ending_cash=cash,
                          ending_nav=cash+shares*final_stock),indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache',type=Path,default=Path('covered_call/data/aapl_hourly_verified.json'))
    parser.add_argument('--book',type=Path,default=Path('covered-call/book.js'))
    args=parser.parse_args()
    audit_real(args.cache,args.book)
