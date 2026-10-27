"""Reuse source-aware PMCC price access, not its call-only position rules."""
from datetime import date
from decimal import Decimal
import re
import pandas as pd
from pmcc_backtest.calendar import Calendar
from pmcc_backtest.data import Market as BaseMarket, finite, mid
from pmcc_backtest.contracts import RIC_SOURCE, OCC_SOURCE, ADJUSTMENT_SOURCE


def parse_ric(ident,stock_ric):
    m=re.fullmatch(r'([A-Z]+)([A-X])(\d{2})(\d{2})(\d{5})\.U(?:\^([A-L])(\d{2}))?',ident)
    if not m: raise ValueError('Nonstandard/mini/adjusted RIC or unsupported encoding')
    root,code,dd,yy,k,suffix,sy=m.groups();month=(ord(code)-65)%12+1
    if root!=stock_ric.split('.')[0]: raise ValueError('Underlying conflict')
    if suffix and (ord(suffix)-64!=month or sy!=yy): raise ValueError('Expiration suffix conflict')
    return dict(id=ident,underlying=stock_ric,cp='C' if code<='L' else 'P',
                strike=int(k)/100,expiry=str(date(2000+int(yy),month,int(dd))))


def candidate_ric(stock_ric,expiry,strike,cp):
    """Unverified probe only. DD is padded; suffix is A-L for BOTH types."""
    d=date.fromisoformat(expiry);cents=Decimal(str(strike))*100
    if cp not in ('C','P') or cents!=cents.to_integral_value() or not 0<cents<100000: raise ValueError('Unsupported RIC inputs')
    suffix=chr(64+d.month);code=chr((64 if cp=='C' else 76)+d.month)
    ric=f'{stock_ric.split(".")[0]}{code}{d.day:02d}{d:%y}{int(cents):05d}.U^{suffix}{d:%y}'
    parse_ric(ric,stock_ric)
    return ric


def resolve(ident,stock_ric,cal,rows,review):
    c=parse_ric(ident,stock_ric)
    if review.get('unresolved_adjustment_event'): raise ValueError('Unresolved corporate action')
    dates=sorted(q['date'] for q in rows if any(finite(q.get(k)) and q[k]>0 for k in ('bid','ask','trade','vendor_mid')))
    if not dates: raise ValueError('No historical evidence; not proof of no listing')
    last=str(cal.exchange.date_to_session(c['expiry'],direction='previous').date())
    c.update(last_trade_date=last,known_from=dates[0],first_observed_quote_date=dates[0],last_observed_quote_date=dates[-1],
        multiplier=100,currency='USD',deliverable=f'100 {stock_ric.split(".")[0]} shares',standard_verified=False,
        standard_assumption_allowed=True,terms_status='research assumption',risk_flags=[],
        terms_source=[OCC_SOURCE,ADJUSTMENT_SOURCE],
        provenance={'identity':{'status':'rule-derived, zero-padded day; A-L expired suffix','source':RIC_SOURCE},
                    'terms':{'status':'standard 100-share American terms assumed, NOT individually confirmed'},
                    'corporate_actions':review,'last_trade_date':{'status':'calendar/rule-derived; not last quote'}})
    return c


class Market(BaseMarket):
    def __init__(self,data,cfg,*,allow_test=False):
        self.allow_test=allow_test
        super().__init__(data,cfg,Calendar(cfg.start,cfg.end),allow_test=allow_test)
        if not allow_test:
            for c in self.contracts.values():
                parsed=parse_ric(c['id'],cfg.stock_ric)
                if any(c[k]!=v for k,v in parsed.items()): raise ValueError('RIC/metadata conflict: '+c['id'])
        self.exclusions=[dict(id=c['id'],reason='NONSTANDARD_OR_UNRESOLVED_TERMS') for c in self.contracts.values() if not self.standard(c)]

    def standard(self,c):
        supported=c.get('standard_verified') is True or (c.get('standard_assumption_allowed') is True and c.get('terms_status')=='research assumption' and c.get('terms_source'))
        return bool(supported and not c.get('risk_flags') and c.get('cp') in ('C','P') and c.get('multiplier')==100 and
                    c.get('deliverable')==f'100 {self.config.stock_ric.split(".")[0]} shares' and
                    c.get('underlying')==self.config.stock_ric and c.get('currency')=='USD')

    def quote(self,ident,day):
        q=super().quote(ident,day)
        if not q:return None
        close=pd.Timestamp(self.calendar.close(day))
        for key in ('source_timestamp','bid_timestamp','ask_timestamp'):
            if q.get(key):
                t=pd.Timestamp(q[key])
                if t>close or str(t.tz_convert('America/New_York').date())!=day:return None
        return q

    def stock(self,day):
        q=self.stocks.get(day)
        if q and q.get('source_timestamp'):
            t=pd.Timestamp(q['source_timestamp'])
            if t>pd.Timestamp(self.calendar.close(day)) or str(t.tz_convert('America/New_York').date())!=day:return None
        return super().stock(day)

    def candidates(self,day,cp,basis=None):
        cfg=self.config;sig=self.calendar.previous(day);spot=self.stock(sig)
        info=dict(date=day,signal_date=sig,signal_at=self.calendar.signal(day),cp=cp,signal_spot=spot,
                  universe_complete=False,known_contracts=0,valid_signal_quotes=0,eligible_contracts=0,selected=None,reason=None)
        if spot is None or not self.signal_known(self.stocks.get(sig),day):return [],info|{'reason':'SIGNAL_STOCK_UNAVAILABLE'}
        known=[];eligible=[]
        for c in self.contracts.values():
            dte=(date.fromisoformat(c['expiry'])-date.fromisoformat(day)).days
            friday=self.calendar.week(c['expiry'])['friday']
            weekly=(c['expiry']==friday or (date.fromisoformat(c['expiry']).weekday()==3 and not self.calendar.exchange.is_session(friday)))
            if c['cp']!=cp or not cfg.dte_min<=dte<=cfg.dte_max or not weekly or c['last_trade_date']<=day or not self.observed(c,sig):continue
            known.append(c);q=self.quote(c['id'],sig);m=mid(q)
            if m is None or not self.signal_known(q,day):continue
            info['valid_signal_quotes']+=1
            if not finite(q.get('bid')) or q['bid']<=0 or (q['ask']-q['bid'])/m>cfg.max_relative_spread:continue
            k=c['strike']
            if (cp=='P' and k>=spot) or (cp=='C' and k<=spot):continue
            if cp=='C' and cfg.call_cost_floor and basis is not None and k<basis:continue
            if cfg.selection=='historical_delta':
                delta=q.get('delta');target=cfg.put_delta if cp=='P' else cfg.call_delta
                if q.get('delta_source')!='historical' or not finite(delta) or not (-1<delta<0 if cp=='P' else 0<delta<1):continue
                distance=abs(delta-target)
                if distance>cfg.delta_tolerance:continue
            else:
                target=spot*(1-cfg.otm_fraction if cp=='P' else 1+cfg.otm_fraction)
                if (cp=='P' and k>target) or (cp=='C' and k<target):continue
                distance=abs(k-target)
            eligible.append((abs(dte-cfg.dte_target),c['expiry'],distance,-k if cp=='P' else k,c['id'],c))
        info.update(known_contracts=len(known),eligible_contracts=len(eligible))
        eligible.sort(key=lambda x:x[:-1]);selected=[x[-1] for x in eligible]
        info['reason']='SELECTED_FROM_OBSERVED_SUBSET' if selected else 'NO_ELIGIBLE_IN_OBSERVED_SUBSET' if known else 'CANDIDATE_DATA_NOT_COVERED'
        if selected:info['selected']=selected[0]['id']
        return selected,info
