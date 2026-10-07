"""Strict observed-data schema and source-aware price access. No fill-forward."""
from datetime import date
import json
import math
from pathlib import Path
import pandas as pd


def finite(x):
    return isinstance(x,(float,int)) and not isinstance(x,bool) and math.isfinite(x)


def mid(q):
    if not q:
        return None
    if q.get('quote_inconsistent') or q.get('bid_timestamp') != q.get('ask_timestamp'):
        return None
    b,a=q.get('bid'),q.get('ask')
    if b is not None or a is not None:
        return (b+a)/2 if finite(b) and finite(a) and 0 <= b <= a and a > 0 else None
    m=q.get('vendor_mid')
    return m if q.get('vendor_mid_definition_verified') is True and finite(m) and m > 0 else None


def fill(q, side, model):
    m=mid(q)
    if m is None:
        return None
    if model=='midpoint':
        return m
    x=q.get('ask' if side=='BUY' else 'bid')
    return x if finite(x) and x >= 0 else None


class Market:
    def __init__(self, data, config, calendar, *, allow_test=False):
        self.data,self.config,self.calendar=data,config,calendar
        md=data.get('metadata',{})
        if not allow_test and (md.get('source')!='LSEG' or md.get('synthetic') is not False):
            raise ValueError('Only explicitly real LSEG data can enter a published run')
        if md.get('stock_unadjusted') is not True:
            raise ValueError('Stock must be unadjusted and consistent with option strikes')
        self.meta=md
        self.contracts={}
        for c in data.get('contracts',[]):
            if c['id'] in self.contracts:
                raise ValueError('Duplicate contract identity')
            for f in ('expiry','last_trade_date','known_from'):
                date.fromisoformat(c[f])
            if not finite(c.get('strike')) or c['strike']<=0:
                raise ValueError('Invalid contract strike')
            if c['last_trade_date']>c['expiry']:
                raise ValueError('Last trading date cannot follow expiry')
            self.contracts[c['id']]=c
        self.stocks=self._index(data.get('stock',[]),lambda r:r['date'])
        self.quotes=self._index(data.get('options',[]),lambda r:(r['id'],r['date']))
        self.quotes_by_contract={}
        self._signal_cutoffs={}
        self.first={}
        for q in data.get('options',[]):
            if q['id'] not in self.contracts:
                raise ValueError('Quote has unknown contract metadata')
            if any(finite(q.get(f)) for f in ('bid','ask','vendor_mid','trade')):
                self.first[q['id']]=min(q['date'],self.first.get(q['id'],q['date']))
            self.quotes_by_contract.setdefault(q['id'],[]).append(q)
        self.dividends=data.get('dividends',[])
        seen=set()
        for d in self.dividends:
            key=d['ex_date']
            if key in seen or not finite(d['amount']) or d['amount']<0:
                raise ValueError('Duplicate/invalid dividend')
            seen.add(key)
            if d.get('pay_date') and d['pay_date']<d['ex_date']:
                raise ValueError('Dividend payment before ex date')
            if d.get('announced_at') and pd.Timestamp(d['announced_at']).tzinfo is None:
                raise ValueError('Dividend announcement must have an explicit timezone')

    @staticmethod
    def _index(rows,key):
        out={}
        for r in rows:
            date.fromisoformat(r['date'])
            if key(r) in out:
                raise ValueError(f'Duplicate observation {key(r)}')
            for f in ('source_timestamp','available_at','bid_timestamp','ask_timestamp'):
                if r.get(f) and pd.Timestamp(r[f]).tzinfo is None:
                    raise ValueError(f'{f} requires timezone')
            out[key(r)]=r
        return out

    def stock(self,day):
        r=self.stocks.get(day)
        return r['price'] if r and finite(r.get('price')) and r['price']>0 else None

    def quote(self,ident,day):
        return self.quotes.get((ident,day))

    def signal_known(self,row,execution_day):
        if not row or row['date']!=self.calendar.previous(execution_day):
            return False
        if row.get('available_at'):
            return pd.Timestamp(row['available_at'])<=pd.Timestamp(self.calendar.signal(execution_day))
        # A disclosed overnight availability assumption is not a provider timestamp.
        return self.meta.get('availability_policy')=='previous_session_by_next_09_assumed'

    def standard(self,c):
        supported=(c.get('standard_verified') is True or (
            c.get('standard_assumption_allowed') is True and c.get('terms_status')=='research assumption'
            and bool(c.get('terms_source')) and not c.get('risk_flags')))
        return (supported and not c.get('risk_flags') and c.get('multiplier')==100
                and c.get('deliverable')=='100 AAPL shares' and c.get('underlying')==self.config.stock_ric
                and c.get('cp')=='C' and c.get('currency')=='USD')

    def observed(self,c,signal_date):
        if not (self.standard(c) and c['known_from']<=signal_date
                and self.first.get(c['id'],'9999-12-31')<=signal_date):
            return False
        if signal_date not in self._signal_cutoffs:
            self._signal_cutoffs[signal_date]=pd.Timestamp(self.calendar.signal(self.calendar.next(signal_date)))
        cutoff=self._signal_cutoffs[signal_date]
        if c.get('metadata_known_at') and pd.Timestamp(c['metadata_known_at'])>cutoff:
            return False
        for q in self.quotes_by_contract.get(c['id'],[]):
            if q['date']>signal_date:
                continue
            # A real one-sided quote can evidence membership without being an
            # executable BBO. Keep existence and fill/valuation gates separate.
            if not any(finite(q.get(f)) and q[f]>0 for f in ('bid','ask','vendor_mid','trade')):
                continue
            if q.get('available_at'):
                if pd.Timestamp(q['available_at'])<=cutoff:
                    return True
            elif self.meta.get('availability_policy')=='previous_session_by_next_09_assumed':
                return True
        return False


def load(path):
    return json.loads(Path(path).read_text())
