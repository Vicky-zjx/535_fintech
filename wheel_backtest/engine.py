"""One-contract cash-secured Wheel, transaction accounting, no synthetic fills."""
from copy import deepcopy
import math
import pandas as pd
from .config import Config
from .data import Market,finite,mid
from .metrics import calculate


class Account:
    def __init__(self,market,strategy,model):
        if strategy not in ('wheel','buy_hold') or model not in ('quoted_side','midpoint'):raise ValueError('Unknown account/model')
        self.m=market;self.cfg=market.config;self.cal=market.calendar;self.strategy=strategy;self.model=model
        self.cash=self.cfg.initial_cash;self.shares=0;self.basis=0.;self.position=None
        self.realized_option=0.;self.realized_stock=0.;self.dividend_income=0.;self.receivables={}
        self.commissions=0.;self.stock_costs=0.;self.assignment_fees=0.;self.gross_premiums=0.;self.option_buybacks=0.
        self.events=[];self.ledger=[];self.snapshots=[];self.decisions=[];self.issues=[];self.halted=False

    def reserved(self):return 100*self.position['strike'] if self.position and self.position['cp']=='P' else 0.

    def check(self):
        assert self.shares>=0 and isinstance(self.shares,int)
        assert self.cash>=-1e-7 and self.reserved()<=self.cash+1e-7
        if self.position:
            assert self.strategy=='wheel' and self.position['multiplier']==100
            assert self.shares==0 if self.position['cp']=='P' else self.shares==100
        if self.strategy=='wheel':assert self.shares in (0,100)
        assert math.isclose(self.cash,self.cfg.initial_cash+sum(e['net_cash_flow'] for e in self.events),abs_tol=1e-6)

    def issue(self,day,reason,contract=None):
        self.issues.append(dict(date=day,reason=reason,contract=contract,source='LSEG historical input / accounting gate'))

    def snapshot(self,day,phase='EOD',mark_day=None):
        mark_day=mark_day or day;s=self.m.stock(mark_day);p=self.position;q=self.m.closing_quote(p['id'],mark_day) if p else None
        mark=mid(q) if p else 0.;stock_mv=s*self.shares if self.shares and s is not None else 0. if not self.shares else None
        liability=100*mark if mark is not None else None;div=sum(x['balance'] for x in self.receivables.values())
        economic_cash=self.cash+div
        equity=economic_cash+stock_mv-liability if stock_mv is not None and liability is not None and not self.halted else None
        option_unrealized=100*(p['entry_premium']-mark) if p and mark is not None else 0. if not p else None
        stock_unrealized=stock_mv-self.shares*self.basis if stock_mv is not None else None
        costs=self.commissions+self.assignment_fees+self.stock_costs
        net_realized=self.realized_option+self.realized_stock+self.dividend_income-costs
        state=dict(date=day,timestamp=self.cal.close(day),phase=phase,mark_date=mark_day,strategy=self.strategy,fill_model=self.model,
            cash=self.cash,dividend_receivable=div,economic_cash=economic_cash,reserved_cash=self.reserved(),buying_power=self.cash-self.reserved(),
            shares=self.shares,share_acquisition_cost=self.basis if self.shares else None,stock_mark=s,stock_value=stock_mv,
            short_put=p['id'] if p and p['cp']=='P' else None,covered_call=p['id'] if p and p['cp']=='C' else None,
            option=deepcopy(p),option_mark=mark,option_liability=liability,equity=equity,
            realized_option_pnl=self.realized_option,realized_stock_pnl=self.realized_stock,dividend_income=self.dividend_income,
            realized_pnl_net=net_realized,unrealized_option_pnl=option_unrealized,unrealized_stock_pnl=stock_unrealized,
            commissions=self.commissions,stock_execution_costs=self.stock_costs,assignment_fees=self.assignment_fees,
            source_timestamp=q.get('source_timestamp') if q else None,unresolved=self.halted)
        if equity is not None:
            assert math.isclose(equity-self.cfg.initial_cash,net_realized+option_unrealized+stock_unrealized,abs_tol=1e-6),'P&L attribution'
        return state

    def event(self,day,event_type,mutation,*,gross=0.,fee=0.,slippage=0.,price=None,quantity=0,c=None,q=None,reason='',realized=0.,stock_action=None,phase='closing_reference',mark_day=None):
        before=self.snapshot(day,'before_event',mark_day)
        self.cash+=gross-fee-slippage
        if event_type in ('SELL_TO_OPEN','BUY_TO_CLOSE'):self.commissions+=fee
        else:self.assignment_fees+=fee
        self.stock_costs+=slippage;mutation()
        timestamp=self.cal.close(day)
        if phase=='session_open':timestamp=self.cal.exchange.session_open(day).tz_convert('America/New_York').isoformat()
        elif phase=='modeled_after_close':timestamp=(pd.Timestamp(timestamp)+pd.Timedelta(microseconds=1)).isoformat()
        ident=f'{self.strategy}-{self.model}-{len(self.events)+1:04d}'
        after=self.snapshot(day,'after_event',mark_day)
        record=dict(event_id=ident,timestamp=timestamp,timestamp_is_modeled=True,date=day,event_type=event_type,phase=phase,
            strategy=self.strategy,fill_model=self.model,underlying=self.cfg.stock_ric,contract=c['id'] if c else None,
            cp=c['cp'] if c else None,expiry=c['expiry'] if c else None,strike=c['strike'] if c else None,
            quantity=quantity,multiplier=100 if c else 1,fill_price=price,bid=q.get('bid') if q else None,ask=q.get('ask') if q else None,
            midpoint=mid(q),spread=q['ask']-q['bid'] if q and finite(q.get('bid')) and finite(q.get('ask')) else None,
            quote_date=q.get('date') if q else None,quote_timestamp=q.get('source_timestamp') if q else None,
            quote_precision=q.get('precision') if q else None,source_snapshot_sha256=q.get('source_snapshot_sha256',q.get('raw_sha256')) if q else None,
            gross_cash_flow=gross,commission=fee if event_type in ('SELL_TO_OPEN','BUY_TO_CLOSE') else 0.,
            assignment_fee=fee if 'ASSIGN' in event_type else 0.,stock_execution_cost=slippage,
            net_cash_flow=gross-fee-slippage,realized_pnl_gross=realized,stock_action=stock_action,
            cash_before=before['cash'],cash_after=after['cash'],shares_before=before['shares'],shares_after=after['shares'],
            source='LSEG historical observations' if q else 'contractual transfer / disclosed model',reason=reason,
            assumption_flags=['simulated, not observed execution','daily source time unknown' if q and not q.get('source_timestamp') else 'source time retained' if q else 'non-market event'],
            before=before,after=after)
        self.events.append(record)
        for side,state in [('before',before),('after',after)]:
            self.snapshots.append(state|{'snapshot_id':ident+'-'+side,'timestamp':timestamp,'event_id':ident})
        self.check()

    def open(self,c,day,decision):
        q=self.m.execution_quote(c['id'],day);value=mid(q);s=self.m.stock(day)
        if value is None or s is None or not finite(q.get('bid')) or q['bid']<=0:
            return 'EXECUTION_QUOTE_MISSING_INVALID_OR_ZERO_BID'
        if (q['ask']-q['bid'])/value>self.cfg.max_relative_spread:return 'EXECUTION_SPREAD_TOO_WIDE'
        fee=self.cfg.option_commission
        # The premium being received cannot finance the initial collateral check.
        if c['cp']=='P' and self.cash<100*c['strike']+fee+self.cfg.assignment_fee:return 'INSUFFICIENT_CASH_COLLATERAL'
        if c['cp']=='C' and self.shares!=100:return 'CALL_NOT_COVERED'
        fill=q['bid'] if self.model=='quoted_side' else value
        def change():
            self.position={k:c[k] for k in ('id','cp','strike','expiry','last_trade_date','multiplier')}
            self.position.update(quantity=1,entry_date=day,entry_premium=fill,signal_date=decision['signal_date'],entry_fee=fee)
            self.gross_premiums+=100*fill
        self.event(day,'SELL_TO_OPEN',change,gross=100*fill,fee=fee,price=fill,quantity=1,c=c,q=q,
            reason='Prior-session 09:00 signal; preselected observed contract; simulated daily closing reference')
        return 'OPENED'

    def close(self,day,reason):
        """Explicit necessary buyback hook, NOT called by the hold-to-expiry baseline."""
        p=self.position
        if not p:return False
        q=self.m.execution_quote(p['id'],day);value=mid(q)
        if value is None:return False
        price=q['ask'] if self.model=='quoted_side' else value;fee=self.cfg.option_commission
        if self.cash<100*price+fee:return False
        realized=100*(p['entry_premium']-price)
        def change():self.realized_option+=realized;self.option_buybacks+=100*price;self.position=None
        self.event(day,'BUY_TO_CLOSE',change,gross=-100*price,fee=fee,price=price,quantity=1,c=p,q=q,reason=reason,realized=realized)
        return True

    def expiry(self,day,early=False):
        p=self.position
        if not p:return
        s=self.m.stock(day)
        if s is None:self.issue(day,'ASSIGNMENT_STOCK_PRICE_MISSING',p['id']);self.halted=True;return
        intrinsic=max(0.,p['strike']-s if p['cp']=='P' else s-p['strike'])
        assign=early or (intrinsic>0 and intrinsic+1e-9>=self.cfg.assignment_itm)
        premium=100*p['entry_premium'];fee=self.cfg.assignment_fee if assign else 0.
        if assign and p['cp']=='P' and self.cash<100*p['strike']+fee:
            self.issue(day,'UNFUNDED_CONTRACTUAL_ASSIGNMENT',p['id']);self.halted=True;return
        stock_realized=100*(p['strike']-self.basis) if assign and p['cp']=='C' else 0.
        def change():
            self.realized_option+=premium;self.position=None
            if assign:
                if p['cp']=='P':self.shares=100;self.basis=p['strike']
                else:self.realized_stock+=stock_realized;self.shares=0;self.basis=0.
        self.event(day,('PUT_ASSIGNMENT' if p['cp']=='P' else 'CALL_ASSIGNMENT') if assign else 'EXPIRE',change,
            gross=(-100*p['strike'] if p['cp']=='P' else 100*p['strike']) if assign else 0.,fee=fee,
            price=p['strike'] if assign else 0.,quantity=1,c=p,realized=premium+stock_realized,
            stock_action=('ACQUIRE_100_AT_STRIKE' if p['cp']=='P' else 'DELIVER_100_AT_STRIKE') if assign else None,
            reason='MODELED_PRE_EX_DIVIDEND_ASSIGNMENT' if early else 'MODELED_EXPIRY_ITM_ASSIGNMENT' if assign else 'MODELED_EXPIRY_WORTHLESS',phase='modeled_after_close')

    def dividends(self,day):
        for d in self.m.dividends:
            if d['ex_date']==day and self.shares:
                amount=self.shares*d['amount'];shares=self.shares
                def accrue():self.receivables[day]={'balance':amount,'pay_date':d.get('pay_date')};self.dividend_income+=amount
                self.event(day,'DIVIDEND_ENTITLEMENT',accrue,quantity=shares,price=d['amount'],reason='Carried shares at ex-date open; cash not spendable before pay date',phase='session_open',mark_day=self.cal.previous(day),realized=amount)
        for ex,record in list(self.receivables.items()):
            if record['pay_date']==day and record['balance']:
                amount=record['balance']
                self.event(day,'DIVIDEND_PAYMENT',lambda record=record:record.update(balance=0.),gross=amount,reason='Pay accrued dividend once; no second P&L recognition',phase='session_open',mark_day=self.cal.previous(day))

    def benchmark_buy(self,day):
        s=self.m.stock(day)
        if s is None:self.issue(day,'BENCHMARK_INITIAL_STOCK_MISSING');self.halted=True;return
        n=int(self.cash//(s*(1+self.cfg.stock_slippage_bps/10000)))
        if not n:self.issue(day,'BENCHMARK_CAPITAL_BELOW_ONE_SHARE');return
        slip=n*s*self.cfg.stock_slippage_bps/10000
        def change():self.shares=n;self.basis=s
        self.event(day,'STOCK_BUY',change,gross=-n*s,slippage=slip,quantity=n,price=s,q=self.m.stocks[day],reason='Same capital and dates; maximum whole shares; residual cash earns zero')

    def run(self):
        for index,day in enumerate(self.cal.sessions):
            if not self.halted:self.dividends(day)
            if self.strategy=='buy_hold':
                if index==0 and not self.halted:self.benchmark_buy(day)
            elif self.cal.week(day)['first_session']==day:
                cp='C' if self.shares else 'P';candidates,decision=self.m.candidates(day,cp,self.basis if self.shares else None)
                if self.halted:decision['outcome']='UNRESOLVED_PRIOR_OBLIGATION'
                elif self.position:decision['outcome']='EXISTING_OPTION_HELD_TO_EXPIRY'
                elif candidates:decision['outcome']=self.open(candidates[0],day,decision)
                else:decision['outcome']=decision['reason']
                self.decisions.append(decision)
            if self.position and not self.halted:
                if day>=self.position['last_trade_date']:self.expiry(day)
                elif self.position['cp']=='C' and self.cfg.early_assignment=='dividend_call':
                    for d in self.m.dividends:
                        if d['ex_date']!=self.cal.next(day) or not d.get('announced_at') or pd.Timestamp(d['announced_at'])>pd.Timestamp(self.cal.close(day)):continue
                        s=self.m.stock(day);mark=self.m.mark(self.position['id'],day)
                        if s is None or mark is None:self.issue(day,'EARLY_ASSIGNMENT_INPUT_MISSING',self.position['id']);self.halted=True;break
                        intrinsic=max(0.,s-self.position['strike'])
                        if intrinsic>0 and intrinsic+1e-9>=self.cfg.assignment_itm and max(mark-intrinsic,0)<d['amount']:self.expiry(day,early=True)
                        break
            row=self.snapshot(day)
            # End-of-day is after the modeled post-close assignment/expiry,
            # not a timestamp just before an event already reflected in equity.
            if self.events and self.events[-1]['date']==day:
                last=pd.Timestamp(self.events[-1]['timestamp'])
                if last>=pd.Timestamp(row['timestamp']):
                    row['timestamp']=(last+pd.Timedelta(microseconds=1)).isoformat()
            if row['equity'] is None:self.issue(day,'VALUATION_UNAVAILABLE_NO_IMPUTATION',self.position['id'] if self.position else None)
            self.ledger.append(row);self.snapshots.append(row|{'snapshot_id':f'{self.strategy}-{self.model}-{day}-EOD','event_id':None})
            self.check()
        stats=calculate(self.ledger,self.cfg.initial_cash,self.cfg.start,self.cfg.end,self.cfg.risk_free_rate)
        opened=[e for e in self.events if e['event_type']=='SELL_TO_OPEN'];supported=self.strategy=='buy_hold' or bool(opened)
        stats.update(option_entries=len(opened),put_assignments=sum(e['event_type']=='PUT_ASSIGNMENT' for e in self.events),
            call_assignments=sum(e['event_type']=='CALL_ASSIGNMENT' for e in self.events),rolls=0,
            worthless_expiries=sum(e['event_type']=='EXPIRE' for e in self.events),gross_premiums=self.gross_premiums,
            net_premiums_after_option_costs=self.gross_premiums-self.option_buybacks-self.commissions-self.assignment_fees,
            option_commissions=self.commissions,stock_execution_costs=self.stock_costs,assignment_fees=self.assignment_fees,
            days_with_shares=sum(r['shares']>0 for r in self.ledger),days_without_shares=sum(r['shares']==0 for r in self.ledger),
            total_costs=self.commissions+self.stock_costs+self.assignment_fees,empirical_strategy_supported=supported,
            spread_cost_vs_mid=sum(100*(e['midpoint']-e['fill_price']) for e in opened))
        if not supported:
            for k in ('ending_equity','net_pnl','total_return','cagr','annualized_volatility','sharpe','available_daily_return_sharpe','max_drawdown','observed_max_drawdown','calmar'):stats[k]=None
        return dict(strategy=self.strategy,fill_model=self.model,
            status='unsupported_no_option_fills' if not supported else 'incomplete_valuation' if not stats['full_path_complete'] else 'observed_universe_run',
            metrics=stats,events=self.events,ledger=self.ledger,snapshots=self.snapshots,decisions=self.decisions,issues=self.issues,
            accounting_reconciled=True,terminal_policy='Hold remaining shares/options at real same-date marks; no forced closing trades or invented rolls.')


def run(data,cfg=Config(),strategy='wheel',model='quoted_side',*,allow_test=False):
    market=Market(data,cfg,allow_test=allow_test)
    md=market.meta
    if md.get('corporate_action_review',{}).get('unresolved_adjustment_event') or md.get('corporate_actions'):
        raise ValueError('Unresolved split/delisting/adjustment: no standard-contract backtest permitted')
    if not allow_test and md.get('dividend_coverage_verified') is not True:raise ValueError('Dividend coverage not established')
    return Account(market,strategy,model).run()
