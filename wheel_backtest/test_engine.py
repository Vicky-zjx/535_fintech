"""SYNTHETIC UNIT TESTS ONLY — never input to the published historical results."""
from copy import deepcopy
from dataclasses import replace
import unittest
from .config import Config
from .data import Calendar,Market,candidate_ric,parse_ric
from .engine import run,Account


def fixture(end='2026-08-28'):
    cfg=Config(start='2026-08-03',end=end,initial_cash=20000.)
    cal=Calendar(cfg.start,cfg.end);days=[cal.previous(cal.sessions[0]),*cal.sessions]
    contracts=[]
    for w in cal.weekly():
        for cp,k in [('P',95.),('C',105.)]:
            contracts.append(dict(id=candidate_ric('AAPL.O',w['friday'],k,cp),underlying='AAPL.O',cp=cp,strike=k,
                expiry=w['friday'],last_trade_date=w['friday_last_session'],known_from=days[0],currency='USD',
                multiplier=100,deliverable='100 AAPL shares',standard_verified=True))
    stock=[dict(date=d,price=100.,available_at=cal.next(d)+'T08:00:00-04:00') for d in days]
    options=[dict(id=c['id'],date=d,bid=.9,ask=1.1,trade=1.,delta=-.25 if c['cp']=='P' else .25,
                  delta_source='historical',precision='daily',available_at=cal.next(d)+'T08:00:00-04:00')
             for c in contracts for d in days if d<=c['last_trade_date']]
    return cfg,dict(metadata=dict(source='UNIT_TEST_ONLY',synthetic=True,stock_unadjusted=True,dividend_coverage_verified=True),
                    contracts=contracts,stock=stock,options=options,dividends=[])


def price(data,day,spot):next(r for r in data['stock'] if r['date']==day)['price']=spot
def quote(data,ident,day):return next(q for q in data['options'] if q['id']==ident and q['date']==day)
def simulate(data,cfg,**kw):return run(data,cfg,allow_test=True,**kw)


class WheelTests(unittest.TestCase):
    def setUp(self):self.cfg,self.data=fixture()
    def test_synthetic_publication_rejected(self):
        with self.assertRaises(ValueError):run(self.data,self.cfg)
    def test_put_expires_worthless(self):
        r=simulate(self.data,self.cfg);self.assertEqual(r['metrics']['worthless_expiries'],4)
        self.assertTrue(all(x['shares']==0 for x in r['ledger']));self.assertEqual(r['metrics']['option_entries'],4)
        self.assertAlmostEqual(r['metrics']['net_pnl'],4*(90-.65))
    def test_put_assignment_acquires_100(self):
        price(self.data,'2026-08-07',90);r=simulate(self.data,self.cfg)
        e=next(e for e in r['events'] if e['event_type']=='PUT_ASSIGNMENT')
        self.assertEqual(e['shares_after'],100);self.assertEqual(e['shares_before'],0)
        self.assertEqual(e['net_cash_flow'],-9500);self.assertEqual(e['after']['share_acquisition_cost'],95)
        self.assertIsNone(e['after']['option']);self.assertEqual(e['after']['reserved_cash'],0)
    def test_exact_one_cent_itm_assigns_despite_binary_float(self):
        price(self.data,'2026-08-07',94.99)
        self.assertEqual(simulate(self.data,self.cfg)['metrics']['put_assignments'],1)
    def test_covered_call_expires_keeps_stock(self):
        price(self.data,'2026-08-07',90);r=simulate(self.data,self.cfg)
        self.assertEqual(r['ledger'][-1]['shares'],100);self.assertEqual(r['metrics']['call_assignments'],0)
        self.assertTrue(any(e['event_type']=='EXPIRE' and e['cp']=='C' for e in r['events']))
    def test_call_assignment_returns_cash(self):
        price(self.data,'2026-08-07',90);price(self.data,'2026-08-14',110);r=simulate(self.data,self.cfg)
        e=next(e for e in r['events'] if e['event_type']=='CALL_ASSIGNMENT')
        self.assertEqual((e['shares_before'],e['shares_after']),(100,0));self.assertEqual(e['net_cash_flow'],10500)
        self.assertEqual(e['after']['option_liability'],0);self.assertEqual(e['realized_pnl_gross'],1090)
    def test_multiple_complete_cycles(self):
        for d in ['2026-08-07','2026-08-21']:price(self.data,d,90)
        for d in ['2026-08-14','2026-08-28']:price(self.data,d,110)
        r=simulate(self.data,self.cfg)
        self.assertEqual((r['metrics']['put_assignments'],r['metrics']['call_assignments']),(2,2));self.assertEqual(r['metrics']['rolls'],0)
    def test_premiums_are_not_profit_in_crash(self):
        for row in self.data['stock']:
            if row['date']>='2026-08-07':row['price']=40.
        r=simulate(self.data,self.cfg);self.assertGreater(r['metrics']['gross_premiums'],0);self.assertLess(r['metrics']['net_pnl'],0)
    def test_insufficient_collateral_no_premium_financing(self):
        cfg=replace(self.cfg,initial_cash=9499.)
        r=simulate(self.data,cfg);self.assertEqual(r['events'],[])
        self.assertEqual(r['decisions'][0]['outcome'],'INSUFFICIENT_CASH_COLLATERAL');self.assertIsNone(r['metrics']['total_return'])
    def test_missing_execution_no_later_reranking(self):
        ric=self.data['contracts'][0]['id'];quote(self.data,ric,'2026-08-03')['bid']=None
        r=simulate(self.data,self.cfg);self.assertEqual(r['decisions'][0]['outcome'],'EXECUTION_QUOTE_MISSING_INVALID_OR_ZERO_BID')
        self.assertFalse(any(e['date']=='2026-08-03' for e in r['events']))
    def test_missing_mark_preserves_gap_and_withholds_stats(self):
        quote(self.data,self.data['contracts'][0]['id'],'2026-08-04')['ask']=None
        r=simulate(self.data,self.cfg);self.assertEqual(r['metrics']['valuation_gap_dates'],['2026-08-04'])
        self.assertIsNone(r['metrics']['max_drawdown']);self.assertIsNone(r['metrics']['sharpe']);self.assertIsNotNone(r['metrics']['total_return'])
        self.assertTrue(all(x['drawdown'] is None for x in r['ledger'][1:]));self.assertIsNotNone(r['ledger'][2]['observed_drawdown'])
    def test_zero_bid_valid_mark_not_sale(self):
        quote(self.data,self.data['contracts'][0]['id'],'2026-08-04')['bid']=0
        r=simulate(self.data,self.cfg);self.assertIsNotNone(r['ledger'][1]['equity'])
        quote(self.data,self.data['contracts'][0]['id'],'2026-08-03')['bid']=0
        self.assertNotEqual(simulate(self.data,self.cfg)['decisions'][0]['outcome'],'OPENED')
    def test_valuation_only_event_cannot_be_execution_or_signal(self):
        ric=self.data['contracts'][0]['id'];q=quote(self.data,ric,'2026-08-03');q['bid']=None
        q['valuation_quote']=dict(date='2026-08-03',bid=.9,ask=1.1,method='same_event_bbo_final_60_seconds',
            source_timestamp='2026-08-03T15:59:45-04:00',event_timestamp='2026-08-03T15:59:48-04:00',raw_sha256='UNIT_TEST_ONLY',valuation_only=True,closing_reference_only=True)
        m=Market(self.data,self.cfg,allow_test=True)
        self.assertEqual(m.mark(ric,'2026-08-03'),1.)
        self.assertIsNone(m.execution_quote(ric,'2026-08-03'))
    def test_invalid_spread_rejected(self):
        quote(self.data,self.data['contracts'][0]['id'],'2026-08-03')['bid']=2
        self.assertNotEqual(simulate(self.data,self.cfg)['decisions'][0]['outcome'],'OPENED')
    def test_adjusted_contract_excluded(self):
        self.data['contracts'][0].update(multiplier=10,deliverable='10 AAPL shares',risk_flags=['mini'])
        self.assertNotEqual(simulate(self.data,self.cfg)['decisions'][0]['outcome'],'OPENED')
    def test_split_requires_review_not_silent_continuation(self):
        self.data['metadata']['corporate_action_review']={'unresolved_adjustment_event':True}
        with self.assertRaisesRegex(ValueError,'split'):simulate(self.data,self.cfg)
    def test_costs_and_event_snapshots_reconcile(self):
        r=simulate(self.data,self.cfg);cash=self.cfg.initial_cash
        self.assertEqual(len(r['snapshots']),len(r['ledger'])+2*len(r['events']))
        for e in r['events']:
            self.assertAlmostEqual(cash,e['cash_before']);cash+=e['net_cash_flow'];self.assertAlmostEqual(cash,e['cash_after'])
            a=e['after'];self.assertAlmostEqual(a['equity'],a['cash']+a['dividend_receivable']+a['stock_value']-a['option_liability'])
        self.assertAlmostEqual(r['metrics']['option_commissions'],4*.65)
        first=r['events'][0];self.assertAlmostEqual(first['after']['equity'],self.cfg.initial_cash-10-.65)
    def test_future_membership_not_selected(self):
        c=self.data['contracts'][0];self.data['options']=[q for q in self.data['options'] if q['id']!=c['id'] or q['date']>='2026-08-03']
        self.assertEqual(simulate(self.data,self.cfg)['decisions'][0]['outcome'],'CANDIDATE_DATA_NOT_COVERED')
    def test_future_signal_availability_rejected(self):
        quote(self.data,self.data['contracts'][0]['id'],'2026-07-31')['available_at']='2026-08-03T10:00:00-04:00'
        self.assertNotEqual(simulate(self.data,self.cfg)['decisions'][0]['outcome'],'OPENED')
    def test_future_quote_timestamp_rejected(self):
        quote(self.data,self.data['contracts'][0]['id'],'2026-08-03')['source_timestamp']='2026-08-04T15:00:00-04:00'
        self.assertNotEqual(simulate(self.data,self.cfg)['decisions'][0]['outcome'],'OPENED')
    def test_delta_not_estimated_or_silently_switched(self):
        for q in self.data['options']:q['delta_source']='estimated'
        r=simulate(self.data,self.cfg);self.assertFalse(r['events'])
        r=simulate(self.data,replace(self.cfg,selection='otm_moneyness'));self.assertTrue(r['events'])
    def test_cost_floor_skip(self):
        price(self.data,'2026-08-07',90)
        for c in self.data['contracts']:
            if c['cp']=='C':c['strike']=94.
        for r in self.data['stock']:
            if r['date']>='2026-08-10':r['price']=90.
        r=simulate(self.data,self.cfg);self.assertEqual(r['metrics']['option_entries'],1)
    def test_bid_midpoint_spread_sensitivity(self):
        bid=simulate(self.data,self.cfg);mid=simulate(self.data,self.cfg,model='midpoint')
        self.assertAlmostEqual(mid['metrics']['net_pnl']-bid['metrics']['net_pnl'],40)
    def test_assignment_fee_not_double_charged(self):
        price(self.data,'2026-08-07',90);cfg=replace(self.cfg,assignment_fee=2.)
        r=simulate(self.data,cfg);self.assertEqual(r['metrics']['assignment_fees'],2.)
    def test_necessary_buyback_uses_ask(self):
        a=Account(Market(self.data,self.cfg,allow_test=True),'wheel','quoted_side');c,d=a.m.candidates('2026-08-03','P')
        a.open(c[0],'2026-08-03',d);self.assertTrue(a.close('2026-08-04','Explicit test necessary close, not baseline'))
        self.assertEqual(a.events[-1]['fill_price'],1.1);self.assertAlmostEqual(a.commissions,1.3)
    def test_terminal_hold_has_real_liability(self):
        cfg=replace(self.cfg,end='2026-08-05');r=simulate(self.data,cfg)
        self.assertEqual(r['ledger'][-1]['option_liability'],100);self.assertEqual(r['metrics']['rolls'],0)
        self.assertFalse(any(e['event_type']=='BUY_TO_CLOSE' for e in r['events']))
    def test_dividend_accrual_payment_not_double_counted(self):
        self.data['dividends']=[dict(ex_date='2026-08-10',pay_date='2026-08-13',amount=1.,announced_at='2026-08-01T00:00:00-04:00')]
        price(self.data,'2026-08-07',90);r=simulate(self.data,self.cfg)
        ex=next(x for x in r['ledger'] if x['date']=='2026-08-10');pay=next(x for x in r['ledger'] if x['date']=='2026-08-13')
        self.assertEqual(ex['dividend_receivable'],100);self.assertEqual(pay['dividend_receivable'],0)
        self.assertEqual(pay['dividend_income'],100);self.assertAlmostEqual(pay['cash']-ex['cash'],100)
    def test_pre_dividend_call_assignment_model(self):
        price(self.data,'2026-08-07',90);price(self.data,'2026-08-11',110)
        self.data['dividends']=[dict(ex_date='2026-08-12',pay_date='2026-08-14',amount=1.,announced_at='2026-08-01T00:00:00-04:00')]
        ident=next(c['id'] for c in self.data['contracts'] if c['cp']=='C' and c['expiry']=='2026-08-14')
        quote(self.data,ident,'2026-08-11').update(bid=5.,ask=5.1)
        r=simulate(self.data,self.cfg);e=next(e for e in r['events'] if e['event_type']=='CALL_ASSIGNMENT')
        self.assertEqual(e['date'],'2026-08-11');self.assertEqual(e['reason'],'MODELED_PRE_EX_DIVIDEND_ASSIGNMENT')
        self.assertEqual(r['ledger'][-1]['dividend_income'],0)
    def test_expiry_missing_stock_halts_without_fabricating_assignment(self):
        price(self.data,'2026-08-07',None);r=simulate(self.data,self.cfg)
        self.assertIsNone(r['metrics']['ending_equity']);self.assertTrue(r['ledger'][-1]['unresolved'])
    def test_holiday_and_ric_conventions(self):
        cal=Calendar('2026-09-01','2026-09-30');self.assertEqual(cal.week('2026-09-08')['first_session'],'2026-09-08')
        ident=candidate_ric('AAPL.O','2026-08-07',300.,'P');self.assertEqual(ident,'AAPLT072630000.U^H26')
        self.assertEqual(parse_ric(ident,'AAPL.O')['cp'],'P')
        with self.assertRaises(ValueError):parse_ric('AAPLT072630000.U^T26','AAPL.O')
    def test_benchmark_whole_shares_same_costs_and_no_terminal_sale(self):
        r=simulate(self.data,self.cfg,strategy='buy_hold');self.assertEqual(r['ledger'][-1]['shares'],199)
        self.assertAlmostEqual(r['metrics']['stock_execution_costs'],1.99);self.assertEqual(len(r['events']),1)


if __name__=='__main__':unittest.main()
