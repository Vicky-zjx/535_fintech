"""One-unit PMCC, cash-funded covered call and buy/hold with event accounting.

Economic cash includes trade-date proceeds; unsettled sales are not represented
again as receivables. Dividend balances and borrow liabilities are separate.
No broker buying-power or automatic-exercise claim is made.
"""
from datetime import date
import math
import pandas as pd

from .calendar import Calendar
from .config import Config
from .data import Market, fill, finite, mid
from .selection import long_call, short_call


class Account:
    def __init__(self, market, strategy, model):
        self.m,self.cfg,self.cal=market,market.config,market.calendar
        self.strategy,self.model=strategy,model
        self.cash=self.cfg.initial_equity
        self.long=self.short=None
        self.long_basis=self.short_basis=self.stock_basis=0.0
        self.shares=0
        self.div_balances=[]
        self.borrow_due=0.0
        self.pnl=dict(long_realized=0.0,short_realized=0.0,stock_realized=0.0,dividends=0.0,
                      option_commissions=0.0,stock_slippage=0.0,borrow_cost=0.0)
        self.events,self.ledger,self.weeks,self.errors=[],[],[],[]
        self.initial_outlay=None
        self.first_stock_equivalent=None
        self.premiums=0.0
        self.cover_due=None
        self.previous_day=None
        self.last_stock=None
        self.halted=False
        self.ever_valuation_gap=False

    def reserved(self):
        return self.borrow_due+sum(-d['balance'] for d in self.div_balances if d['balance']<0)

    def usable_cash(self):
        return self.cash-self.reserved()

    def compatible(self,long,short):
        return (long and long['underlying']==short['underlying'] and long['strike']<=short['strike']
                and long['expiry']>short['expiry'] and long['deliverable']==short['deliverable']
                and long['multiplier']==short['multiplier']==100)

    def event(self,day,action,leg,ident,qty,price,cash_delta,reason,*,contract=None,signal=None,
              commission=0.0,slippage=0.0,phase='closing_execution',q=None):
        self.cash+=cash_delta
        e=dict(id=len(self.events)+1,strategy=self.strategy,fill_model=self.model,date=day,
               execution_reference=self.cal.close(day),execution_time_is_modeled=True,
               event_phase=phase,signal_date=self.cal.previous(day) if signal else None,
               signal_at=self.cal.signal(day) if signal else None,leg=leg,contract=ident,action=action,
               quantity=qty,price=price,cash_delta=cash_delta,commission=commission,
               stock_slippage_cost=slippage,reason=reason,cash_after=self.cash,shares_after=self.shares,
               long_after=self.long['id'] if self.long else None,short_after=self.short['id'] if self.short else None,
               strike=contract['strike'] if contract else None,expiry=contract['expiry'] if contract else None,
               multiplier=contract['multiplier'] if contract else None,
               source_timestamp=q.get('source_timestamp') if q else None,
               source_precision=q.get('precision','daily') if q else None,
               source_event_timestamp=q.get('event_timestamp') if q else None,
               source_quote_method=q.get('method','daily_bbo' if contract else 'daily_stock_print') if q else None,
               source_snapshot_sha256=q.get('raw_sha256',q.get('source_snapshot_sha256')) if q else None,
               source_date=q.get('date') if q else None,
               signal_spot=signal.get('signal_spot') if signal else None,
               execution_spot=self.m.stock(day),actual_fill_timestamp=None)
        self.events.append(e)
        self.check()
        return e

    def check(self):
        assert self.shares in (-100,0,100)
        assert not self.short or (self.strategy=='pmcc' and self.compatible(self.long,self.short) and self.shares==0) or (self.strategy=='covered_call' and self.shares==100)
        assert self.strategy!='pmcc' or self.shares<=0
        assert self.strategy=='pmcc' or self.long is None
        assert math.isfinite(self.cash)

    def fail(self,day,reason,fatal=False):
        self.errors.append(dict(date=day,reason=reason,unresolved=fatal))
        if fatal:
            self.halted=True

    def open_long(self,c,day,decision):
        q=self.m.execution_quote(c['id'],day); p=fill(q,'BUY',self.model)
        fee=self.cfg.option_commission
        if p is None or p<=0:
            return 'LONG_EXECUTION_QUOTE_MISSING_OR_INVALID'
        if self.usable_cash()<100*p+fee-1e-8:
            return 'LONG_UNAFFORDABLE_NO_BORROWING'
        self.long,self.long_basis=c,p
        self.pnl['option_commissions']+=fee
        self.event(day,'BUY','LONG_CALL',c['id'],1,p,-100*p-fee,'INITIAL_LONG' if self.initial_outlay is None else 'REPLACEMENT_LONG',
                   contract=c,commission=fee,signal=decision,q=q)
        if self.initial_outlay is None:
            self.initial_outlay=100*p+fee
            self.first_stock_equivalent=100*self.m.stock(day)*(1+self.cfg.stock_slippage_bps/10000)
        return None

    def close_long(self,day,reason,decision=None):
        if not self.long:
            return True
        if self.short or self.shares<0:
            raise AssertionError('Resolve short-call/assigned-stock obligations before a discretionary long close')
        c=self.long; q=self.m.execution_quote(c['id'],day); p=fill(q,'SELL',self.model)
        if p is None:
            self.fail(day,reason+'_LONG_CLOSE_QUOTE_MISSING',True); return False
        fee=self.cfg.option_commission
        self.pnl['long_realized']+=100*(p-self.long_basis)
        self.pnl['option_commissions']+=fee
        self.long=None
        self.event(day,'SELL','LONG_CALL',c['id'],1,p,100*p-fee,reason,contract=c,commission=fee,signal=decision,q=q)
        return True

    def open_short(self,c,day,decision):
        if self.short or self.shares<0 or (self.strategy=='pmcc' and not self.compatible(self.long,c)) or (self.strategy=='covered_call' and self.shares!=100):
            return 'NO_COMPATIBLE_SUPPORT'
        q=self.m.execution_quote(c['id'],day); p=fill(q,'SELL',self.model)
        if q and (q.get('bid') is not None or q.get('ask') is not None) and (not finite(q.get('bid')) or q['bid']<=0):
            return 'SHORT_BID_NOT_POSITIVE'
        if p is None or p<=0:
            return 'SHORT_EXECUTION_QUOTE_MISSING_OR_INVALID'
        fee=self.cfg.option_commission
        if self.usable_cash()+100*p-fee < -1e-8:
            return 'SHORT_FEES_UNAFFORDABLE'
        self.short,self.short_basis=c,p
        self.premiums+=100*p; self.pnl['option_commissions']+=fee
        self.event(day,'SELL','SHORT_CALL',c['id'],1,p,100*p-fee,'WEEKLY_5_PERCENT_SIGNAL_TARGET',
                   contract=c,commission=fee,signal=decision,q=q)
        decision.update(outcome='filled',reason='FILLED_PRESELECTED_SHORT',execution_spot=self.m.stock(day),
                        actual_entry_moneyness=c['strike']/self.m.stock(day)-1,
                        time_to_last_trade_days=(pd.Timestamp(self.cal.close(c['last_trade_date']))-pd.Timestamp(self.cal.close(day))).total_seconds()/86400,
                        positive_bid_verified=q.get('bid') is not None)
        return None

    def close_short(self,day,reason):
        if not self.short:
            return True
        c=self.short; q=self.m.execution_quote(c['id'],day); p=fill(q,'BUY',self.model)
        if p is None:
            self.fail(day,reason+'_SHORT_CLOSE_QUOTE_MISSING',True); return False
        fee=self.cfg.option_commission
        # Mandatory risk resolution may spend economic cash; a resulting deficit
        # is explicitly unresolved, never financed by a new discretionary trade.
        self.pnl['short_realized']+=100*(self.short_basis-p)
        self.pnl['option_commissions']+=fee
        self.short=None
        self.event(day,'BUY','SHORT_CALL',c['id'],1,p,-100*p-fee,reason,contract=c,commission=fee,q=q)
        if self.cash<0:
            self.fail(day,'MANDATORY_CLOSE_CASH_DEFICIT',True)
        return True

    def buy_stock(self,day,decision):
        s=self.m.stock(day)
        if s is None:
            return 'STOCK_EXECUTION_MISSING'
        slip=100*s*self.cfg.stock_slippage_bps/10000
        cost=100*s+slip
        if self.usable_cash()<cost-1e-8:
            return 'STOCK_UNAFFORDABLE_NO_BORROWING'
        self.shares=100; self.stock_basis=s; self.pnl['stock_slippage']+=slip
        self.event(day,'BUY','STOCK',self.cfg.stock_ric,100,cost/100,-cost,'CASH_FUNDED_100_SHARES',slippage=slip,signal=decision,q=self.m.stocks[day])
        if self.initial_outlay is None:
            self.initial_outlay=cost; self.first_stock_equivalent=cost
        return None

    def sell_stock(self,day,reason):
        s=self.m.stock(day)
        if s is None or self.short:
            self.fail(day,reason+'_STOCK_CLOSE_UNRESOLVED',True); return False
        slip=100*s*self.cfg.stock_slippage_bps/10000
        self.pnl['stock_realized']+=100*(s-self.stock_basis)
        self.pnl['stock_slippage']+=slip; self.shares=0
        self.event(day,'SELL','STOCK',self.cfg.stock_ric,100,s-slip/100,100*s-slip,reason,slippage=slip,q=self.m.stocks[day])
        return True

    def cover(self,day):
        """Precommitted next-session cover; liquidate long only when needed to fund it."""
        if self.shares!=-100:
            return False
        s=self.m.stock(day)
        if s is None:
            self.fail(day,'ASSIGNED_STOCK_COVER_QUOTE_MISSING',True); return False
        slip=100*s*self.cfg.stock_slippage_bps/10000
        required=100*s+slip
        paired=self.usable_cash()<required-1e-8
        if paired:
            if not self.long or self.short:
                self.fail(day,'ASSIGNED_COVER_UNFUNDED',True); return False
            c=self.long; q=self.m.execution_quote(c['id'],day); p=fill(q,'SELL',self.model)
            fee=self.cfg.option_commission
            if p is None:
                self.fail(day,'PAIRED_LIQUIDATION_LONG_QUOTE_MISSING',True); return False
            if self.usable_cash()+100*p-fee<required-1e-8:
                self.fail(day,'PAIRED_LIQUIDATION_INSUFFICIENT_EQUITY',True); return False
            # Both required prices checked; record distinct executions and costs.
            self.pnl['long_realized']+=100*(p-self.long_basis)
            self.pnl['option_commissions']+=fee; self.long=None
            self.event(day,'SELL','LONG_CALL',c['id'],1,p,100*p-fee,'MANDATORY_PAIRED_LIQUIDATION',contract=c,commission=fee,q=q)
        self.pnl['stock_realized']+=100*(self.stock_basis-s)
        self.pnl['stock_slippage']+=slip; self.shares=0; self.cover_due=None
        self.event(day,'BUY','ASSIGNED_STOCK',self.cfg.stock_ric,100,required/100,-required,
                   'MANDATORY_PAIRED_COVER' if paired else 'NEXT_SESSION_ASSIGNED_STOCK_COVER',slippage=slip,q=self.m.stocks[day])
        if self.borrow_due:
            cost=self.borrow_due; self.borrow_due=0.0
            self.event(day,'PAY','BORROW',self.cfg.stock_ric,0,None,-cost,'PAY_ACCRUED_BORROW')
        return True

    def assign(self,day,reason):
        c=self.short
        self.pnl['short_realized']+=100*self.short_basis
        self.short=None
        if self.strategy=='pmcc':
            assert self.long and self.shares==0
            self.shares=-100; self.stock_basis=c['strike']; self.cover_due=self.cal.next(day)
        else:
            assert self.shares==100
            self.pnl['stock_realized']+=100*(c['strike']-self.stock_basis); self.shares=0
        self.event(day,'ASSIGN','SHORT_CALL',c['id'],1,c['strike'],100*c['strike'],reason,contract=c,phase='after_close')

    def expire(self,day):
        c=self.short; self.short=None
        self.pnl['short_realized']+=100*self.short_basis
        self.event(day,'EXPIRE','SHORT_CALL',c['id'],1,0.0,0.0,'EXPIRY_LESS_THAN_001_ITM',contract=c,phase='after_close')

    def accrue(self,day):
        if self.shares<0 and self.previous_day:
            days=(date.fromisoformat(day)-date.fromisoformat(self.previous_day)).days
            if self.last_stock is None:
                self.fail(day,'BORROW_REFERENCE_MISSING',True); return
            cost=100*self.last_stock*self.cfg.borrow_rate*days/365
            self.borrow_due+=cost; self.pnl['borrow_cost']+=cost
            self.event(day,'ACCRUE','BORROW',self.cfg.stock_ric,0,None,0.0,f'{days}_CALENDAR_DAYS_AT_PREVIOUS_STOCK_REFERENCE',phase='before_close')
        for d in self.m.dividends:
            if d['ex_date']==day and self.shares:
                amount=self.shares*d['amount']
                self.div_balances.append(dict(balance=amount,pay_date=d.get('pay_date')))
                self.pnl['dividends']+=amount
                self.event(day,'ACCRUE','DIVIDEND',self.cfg.stock_ric,abs(self.shares),d['amount'],0.0,
                           'EX_DATE_CARRIED_SHARES_ENTITLEMENT' if amount>0 else 'EX_DATE_ASSIGNED_SHORT_STOCK_OBLIGATION',phase='session_open')
        for d in self.div_balances:
            if d['balance'] and d['pay_date'] and d['pay_date']<=day:
                balance=d['balance']; d['balance']=0.0
                self.event(day,'RECEIVE' if balance>0 else 'PAY','DIVIDEND',self.cfg.stock_ric,0,None,balance,'DIVIDEND_PAY_DATE',phase='session_open')

    def after_close(self,day):
        if not self.short:
            return
        c=self.short; s=self.m.stock(day)
        if day>=c['last_trade_date']:
            if s is None:
                self.fail(day,'EXPIRY_STOCK_REFERENCE_MISSING',True); return
            if s-c['strike']>=self.cfg.assignment_itm-1e-10:
                self.assign(day,'MODELED_EXPIRY_ASSIGNMENT')
            else:
                self.expire(day)
            return
        if self.m.meta.get('dividend_assignment_enabled') is not True:
            return
        for d in self.m.dividends:
            if self.cal.next(day)!=d['ex_date'] or not d.get('announced_at') or pd.Timestamp(d['announced_at'])>pd.Timestamp(self.cal.close(day)):
                continue
            qmid=self.m.mark(c['id'],day)
            if s is None or qmid is None:
                self.fail(day,'DIVIDEND_ASSIGNMENT_INPUT_MISSING',True); return
            if s>c['strike'] and max(qmid-max(s-c['strike'],0),0)<d['amount']:
                self.assign(day,'MODELED_DIVIDEND_ASSIGNMENT'); return

    def snapshot(self,day,force_gap=False):
        s=self.m.stock(day)
        lm=self.m.mark(self.long['id'],day) if self.long else 0.0
        sm=self.m.mark(self.short['id'],day) if self.short else 0.0
        missing=[]
        if self.long and lm is None: missing.append('LONG_MARK')
        if self.short and sm is None: missing.append('SHORT_MARK')
        if self.shares and s is None: missing.append('STOCK_MARK')
        if force_gap: missing.append('UNRESOLVED_OBLIGATION')
        if missing:
            self.ever_valuation_gap=True
            if not force_gap:
                details=[]
                for contract,label in ((self.long,'LONG_MARK'),(self.short,'SHORT_MARK')):
                    if contract and label in missing:
                        quote=self.m.quote(contract['id'],day)
                        reason=('NO_SAME_DATE_OBSERVATION' if not quote else
                                'MISSING_BID' if quote.get('bid') is None else
                                'MISSING_ASK' if quote.get('ask') is None else
                                'INVALID_OR_INCONSISTENT_BBO')
                        details.append(contract['id']+': '+reason+'; no eligible same-event quote within final 60 seconds')
                self.errors.append(dict(date=day,reason='VALUATION_GAP',fields=missing,
                                       long_contract=self.long['id'] if self.long else None,
                                       short_contract=self.short['id'] if self.short else None,
                                       details='; '.join(details),
                                       unresolved=False,affects='daily NAV, return path and full-sample drawdown; not a fabricated fill'))
        dr=sum(d['balance'] for d in self.div_balances if d['balance']>0)
        dp=sum(-d['balance'] for d in self.div_balances if d['balance']<0)
        long_mv=100*lm if lm is not None else None
        short_mv=-100*sm if sm is not None else None
        stock_mv=self.shares*s if self.shares and s is not None else (0.0 if not self.shares else None)
        nav=None if missing else self.cash+long_mv+short_mv+stock_mv+dr-dp-self.borrow_due
        exposure=0.0 if s is not None else None
        if s is not None:
            delta_shares=float(self.shares)
            for c,sign in ((self.long,1),(self.short,-1)):
                if c:
                    q=self.m.quote(c['id'],day)
                    if not q or not finite(q.get('delta')) or not 0<=q['delta']<=1 or q.get('delta_source') not in ('historical','estimated contemporaneous'):
                        exposure=None; break
                    delta_shares+=sign*100*q['delta']
            else:
                exposure=s*delta_shares
        deployed=(100*self.long_basis if self.long else 0)+(100*self.stock_basis if self.shares>0 else 0)
        mark_sources={}
        for c,label in ((self.long,'long'),(self.short,'short')):
            if c:
                q=self.m.quote(c['id'],day)
                event=q.get('valuation_quote',{}) if q else {}
                mark_sources[label]=('daily_bbo' if mid(q) is not None else
                    {k:event.get(k) for k in ('method','source_timestamp','event_timestamp','raw_sha256','age_seconds')}
                    if q and self.m.mark(c['id'],day) is not None else 'unavailable')
        row=dict(date=day,closing_reference=self.cal.close(day),strategy=self.strategy,fill_model=self.model,
                 economic_cash=self.cash,long_contract=self.long['id'] if self.long else None,n_long=int(bool(self.long)),
                 short_contract=self.short['id'] if self.short else None,n_short=int(bool(self.short)),stock_shares=self.shares,
                 long_mark=lm,short_mark=sm,stock_mark=s,long_mv=long_mv,short_mv=short_mv,stock_mv=stock_mv,
                 dividend_receivables=dr,dividend_payables=dp,accrued_cost_liabilities=self.borrow_due,
                 nav=nav,valuation_gaps=missing,unresolved=self.halted,capital_deployed_cost=deployed,
                 long_only=bool(self.long and not self.short and self.shares==0),
                 delta_dollar=exposure,delta_to_nav=exposure/nav if exposure is not None and nav is not None and nav>0 else None,
                 broker_buying_power=None,settled_cash=None,mark_sources=mark_sources)
        self.ledger.append(row)
        return row

    def weekly(self,day,covered_today=False):
        sig=self.cal.previous(day); w=self.cal.week(day); s=self.m.stock(sig)
        d=dict(date=day,signal_date=sig,signal_at=self.cal.signal(day),closing_reference=self.cal.close(day),
               strategy=self.strategy,fill_model=self.model,signal_spot=s,execution_spot=None,signal_target=s*(1+self.cfg.short_otm) if s else None,
               friday_series=w['friday'],last_session=w['friday_last_session'],holiday_shifted=day!=w['monday'],
               selected_long=None,selected_short=None,selected_strike=None,actual_entry_moneyness=None,
               time_to_last_trade_days=None,outcome='skipped',reason='',positive_bid_verified=None)
        self.weeks.append(d)
        coverage=self.m.short_coverage(w['friday'])
        d.update(candidate_coverage=coverage['scope'] if coverage else 'unassessed_observed_subset',
                 candidate_coverage_complete=bool(coverage and coverage['complete']),
                 signal_observed_contracts=coverage.get('signal_observed_contracts') if coverage else None,
                 candidate_requests=coverage.get('queried_candidates') if coverage else None)
        if covered_today or self.shares<0:
            d['reason']='ASSIGNED_COVER_NO_SAME_CLOSE_REENTRY'; return
        if self.short:
            d['reason']='EXISTING_SHORT_OBLIGATION'; return
        if s is None or not self.m.signal_known(self.m.stocks.get(sig),day):
            d['reason']='SIGNAL_STOCK_MISSING'; return
        if self.m.stock(day) is None:
            d['reason']='EXECUTION_STOCK_MISSING'; return
        if self.strategy=='buy_hold':
            if self.shares:
                d.update(outcome='not_scheduled',reason='BUY_AND_HOLD_NO_WEEKLY_OVERLAY'); return
            # One initial opportunity, never select a more favorable later entry.
            if day!=self.cal.weekly()[0]['date']:
                d['reason']='INITIAL_BUY_AND_HOLD_OPPORTUNITY_MISSED'; return
            reason=self.buy_stock(day,d)
            d.update(outcome='filled' if reason is None else 'skipped',reason=reason or 'INITIAL_BUY_AND_HOLD')
            return
        replacement=bool(self.long and (date.fromisoformat(self.long['expiry'])-date.fromisoformat(day)).days<=self.cfg.replace_dte)
        desired=self.long
        long_error=None
        if self.strategy=='pmcc' and (not self.long or replacement):
            desired,long_error=long_call(self.m,day)
        chosen,short_error=short_call(self.m,day,desired) if self.strategy!='pmcc' or desired else (None,'NO_COMPATIBLE_LONG_SELECTED')
        d.update(selected_long=desired['id'] if desired else None,selected_short=chosen['id'] if chosen else None,
                 selected_strike=chosen['strike'] if chosen else None)
        # Both desired contracts are locked before any execution quote is read.
        if replacement and not self.close_long(day,'SCHEDULED_90_DTE_REPLACEMENT',d):
            d['reason']='REPLACEMENT_CLOSE_UNRESOLVED'; return
        if self.strategy=='pmcc' and not self.long:
            if not desired:
                d['reason']=long_error; return
            reason=self.open_long(desired,day,d)
            if reason:
                d['reason']=reason; return
        if self.strategy=='covered_call' and self.shares==0:
            reason=self.buy_stock(day,d)
            if reason:
                d['reason']=reason; return
        if not chosen:
            d['reason']=short_error; return
        reason=self.open_short(chosen,day,d)
        if reason:
            d['reason']=reason

    def terminal(self,day):
        self.close_short(day,'PREPLANNED_TERMINAL_LIQUIDATION')
        if self.shares<0:
            self.cover(day)
        if self.shares>0 and not self.short:
            self.sell_stock(day,'PREPLANNED_TERMINAL_LIQUIDATION')
        if self.long and not self.short and self.shares==0:
            self.close_long(day,'PREPLANNED_TERMINAL_LIQUIDATION')

    def run(self):
        for day in self.cal.sessions:
            self.accrue(day)
            terminal=day==self.cal.sessions[-1]
            covered_today=False
            if self.cover_due and self.cover_due<=day and not self.halted:
                covered_today=self.cover(day)
            if terminal:
                # Terminal executions precede after-close assignment. A new
                # after-close obligation is never covered retroactively today.
                self.terminal(day)
            elif not self.halted and self.cal.week(day)['first_session']==day:
                self.weekly(day,covered_today)
            if self.long and self.long['last_trade_date']<=day and not terminal and not self.halted:
                if self.short or self.shares<0:
                    self.fail(day,'SUPPORTING_LONG_EXPIRY_UNRESOLVED',True)
                else:
                    self.close_long(day,'MANDATORY_LONG_EXPIRY_RISK_CLOSE')
            self.after_close(day)
            if terminal and (self.long or self.short or self.shares):
                self.fail(day,'TERMINAL_POSITIONS_UNRESOLVED',True)
            self.snapshot(day,self.halted)
            self.previous_day,self.last_stock=day,self.m.stock(day)
            if self.halted:
                break
        # List every remaining weekly opportunity after an unresolved mandatory
        # event, rather than dropping losing or unavailable weeks from the log.
        existing={r['date'] for r in self.weeks}
        for w in self.cal.weekly():
            if w['date'] not in existing:
                self.weeks.append(dict(date=w['date'],signal_date=w['previous_session'],signal_at=w['signal_at'],
                                       closing_reference=w['closing_reference'],strategy=self.strategy,fill_model=self.model,
                                       holiday_shifted=w['date']!=w['monday'],friday_series=w['friday'],
                                       outcome='skipped',reason='TERMINAL_ENTRIES_SUPPRESSED' if w['date']==self.cal.sessions[-1] else 'RUN_HALTED_UNRESOLVED_EXPOSURE'))
        self.weeks.sort(key=lambda r:r['date'])
        return self.result()

    def result(self):
        last=self.ledger[-1]
        complete=not self.halted and not self.ever_valuation_gap
        # Intermediate mark gaps invalidate path statistics, not independently
        # reconciled terminal cash after every position has actually closed.
        terminal_resolved=(not self.halted and last['date']==self.cal.sessions[-1]
                           and self.long is None and self.short is None and self.shares==0)
        nav=last['nav'] if terminal_resolved else None
        long_unrealized=100*(last['long_mark']-self.long_basis) if self.long and last['long_mark'] is not None else (None if self.long else 0.0)
        short_unrealized=100*(self.short_basis-last['short_mark']) if self.short and last['short_mark'] is not None else (None if self.short else 0.0)
        stock_unrealized=self.shares*(last['stock_mark']-self.stock_basis) if self.shares and last['stock_mark'] is not None else (None if self.shares else 0.0)
        attribution={**self.pnl,'long_unrealized':long_unrealized,'short_unrealized':short_unrealized,'stock_unrealized':stock_unrealized}
        costs=sum(attribution[k] for k in ('option_commissions','stock_slippage','borrow_cost'))
        parts=[attribution[k] for k in ('long_realized','short_realized','stock_realized','long_unrealized','short_unrealized','stock_unrealized','dividends')]
        reconciled=None
        if nav is not None and all(x is not None for x in parts):
            reconciled=math.isclose(sum(parts)-costs,nav-self.cfg.initial_equity,abs_tol=1e-6)
            assert reconciled,'P&L attribution failed'
        event_cash=self.cfg.initial_equity+sum(e['cash_delta'] for e in self.events)
        assert math.isclose(event_cash,self.cash,abs_tol=1e-6),'Cash reconciliation failed'
        peak=self.cfg.initial_equity; observed_peak=peak
        prior=self.cfg.initial_equity; gap=False; drawdowns=[]; observed_drawdowns=[]; returns=[]
        for r in self.ledger:
            n=r['nav']
            r['daily_return']=n/prior-1 if n is not None and prior is not None and prior>0 else None
            if r['daily_return'] is not None: returns.append(r['daily_return'])
            prior=n
            if n is None:r['observed_drawdown']=None
            else:
                observed_peak=max(observed_peak,n)
                r['observed_drawdown']=n/observed_peak-1
                observed_drawdowns.append(r['observed_drawdown'])
            if n is None: gap=True
            if not gap:
                peak=max(peak,n); r['drawdown']=n/peak-1
                drawdowns.append(r['drawdown'])
            else: r['drawdown']=None
        metrics=dict(ending_nav=nav,net_pnl=nav-self.cfg.initial_equity if nav is not None else None,
                     account_return=nav/self.cfg.initial_equity-1 if nav is not None else None,
                     max_drawdown=min(drawdowns) if complete and drawdowns else None,
                     max_observed_drawdown=min(observed_drawdowns) if observed_drawdowns else None,
                     observed_drawdown_is_lower_bound=not complete,
                     valuation_gap_dates=[r['date'] for r in self.ledger if r['valuation_gaps']],
                     initial_capital_outlay=self.initial_outlay,
                     stock_equivalent_at_entry=self.first_stock_equivalent,
                     entry_capital_saved=self.first_stock_equivalent-self.initial_outlay if self.initial_outlay is not None else None,
                     transaction_costs=costs,gross_premiums=self.premiums,
                     short_calls=sum(e['action']=='SELL' and e['leg']=='SHORT_CALL' for e in self.events),
                     expiry_assignments=sum(e['reason']=='MODELED_EXPIRY_ASSIGNMENT' for e in self.events),
                     early_assignments=sum(e['reason']=='MODELED_DIVIDEND_ASSIGNMENT' for e in self.events),
                     skipped_weeks=sum(w['outcome']=='skipped' for w in self.weeks),
                     long_only_sessions=sum(r['long_only'] for r in self.ledger),
                     short_stock_sessions=sum(r['stock_shares']<0 for r in self.ledger),
                     valuation_gap_sessions=sum(bool(r['valuation_gaps']) for r in self.ledger),
                     valid_daily_returns=len(returns),annualized_metrics=None)
        metrics.update(terminal_resolved=terminal_resolved,valuation_path_complete=complete)
        return dict(strategy=self.strategy,fill_model=self.model,status='complete' if complete else 'incomplete',
                    metrics=metrics,attribution=attribution,blotter=self.events,ledger=self.ledger,weekly_coverage=self.weeks,
                    issues=self.errors,audit=dict(cash_reconciled=True,pnl_reconciled=reconciled),
                    limitations=['Economic cash is trade-date cash including unsettled proceeds, not settled cash or broker buying power.',
                                 'Long calls are paid in full; discretionary entries cannot borrow; assignment can create temporary short stock.',
                                 'Previous-session EOD availability by the next 09:00 signal checkpoint is an assumption unless a provider availability timestamp is supplied.',
                                 'Expiry-only assignment baseline: dividend announcement coverage is unavailable.' if not self.m.meta.get('dividend_assignment_enabled') else 'Early assignments are a stated dividend model, not observed exercises.'])


def run(data,config=Config(),strategy='pmcc',model='midpoint',*,allow_test=False):
    if strategy not in ('pmcc','covered_call','buy_hold') or model not in ('midpoint','quoted_side'):
        raise ValueError('Unsupported strategy/fill model')
    cal=Calendar(config.start,config.end)
    if not cal.sessions:
        raise ValueError('No trading sessions')
    return Account(Market(data,config,cal,allow_test=allow_test),strategy,model).run()
