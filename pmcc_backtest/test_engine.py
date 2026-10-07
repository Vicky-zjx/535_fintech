"""Synthetic unit fixtures ONLY. These prices never feed the published results."""
from copy import deepcopy
from dataclasses import replace
import unittest

from .calendar import Calendar
from .config import Config
from .data import Market, mid, fill
from .engine import Account, run
from .selection import long_call, short_call


def fixture():
    cfg=Config(start='2026-08-31',end='2026-09-11')
    cal=Calendar(cfg.start,cfg.end)
    dates=[cal.previous(cal.sessions[0]),*cal.sessions]
    contracts=[]
    for ident,k,expiry in [('LONG',75.,'2027-12-17'),('SHORT1',105.,'2026-09-04'),('SHORT2',105.,'2026-09-11')]:
        contracts.append(dict(id=ident,strike=k,expiry=expiry,last_trade_date=expiry,known_from=dates[0],
                              underlying='AAPL.O',cp='C',currency='USD',multiplier=100,deliverable='100 AAPL shares',
                              standard_verified=True,series_friday=expiry if ident!='LONG' else None))
    def availability(day):
        return cal.next(day)+'T08:00:00-04:00'
    stock=[dict(date=d,price=100.,precision='daily',available_at=availability(d)) for d in dates]
    options=[dict(id=c['id'],date=d,bid=27. if c['id']=='LONG' else .9,ask=29. if c['id']=='LONG' else 1.1,
                  precision='daily',available_at=availability(d)) for c in contracts for d in dates if d<=c['last_trade_date']]
    return cfg,dict(metadata=dict(source='UNIT_TEST_ONLY',synthetic=True,stock_unadjusted=True,
                                  dividend_assignment_enabled=True),stock=stock,contracts=contracts,options=options,dividends=[])


def market(cfg,data):
    return Market(data,cfg,Calendar(cfg.start,cfg.end),allow_test=True)


def row(data,ident,day):
    return next(q for q in data['options'] if q['id']==ident and q['date']==day)


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.cfg,self.data=fixture()

    def test_fixtures_rejected_from_real_run(self):
        with self.assertRaises(ValueError): run(self.data,self.cfg)

    def test_holiday_tuesday_previous_friday(self):
        cal=Calendar(self.cfg.start,self.cfg.end)
        self.assertEqual(cal.week('2026-09-08')['first_session'],'2026-09-08')
        self.assertEqual(cal.previous('2026-09-08'),'2026-09-04')
        result=run(self.data,self.cfg,allow_test=True)
        self.assertEqual([w['date'] for w in result['weekly_coverage']],['2026-08-31','2026-09-08'])
        self.assertTrue(result['weekly_coverage'][1]['holiday_shifted'])

    def test_early_close_dst(self):
        cal=Calendar('2025-10-01','2026-09-30')
        self.assertIn('T13:00:00-05:00',cal.close('2025-11-28'))
        self.assertIn('-04:00',cal.close('2026-03-09'))
        self.assertIn('-05:00',cal.close('2026-03-06'))

    def test_actual_friday_holiday_series(self):
        cfg=replace(self.cfg,start='2026-03-30',end='2026-04-06')
        cal=Calendar(cfg.start,cfg.end)
        self.assertEqual(cal.week('2026-03-30')['friday_last_session'],'2026-04-02')
        d=deepcopy(self.data)
        for r in d['stock']+d['options']:
            r['date']='2026-03-27' if r['date']=='2026-08-28' else r['date']
            if r['date']=='2026-03-27': r['available_at']='2026-03-30T08:00:00-04:00'
        for c in d['contracts']:
            c['known_from']='2026-03-27'
        c=d['contracts'][1];c.update(expiry='2026-04-02',last_trade_date='2026-04-02',series_friday='2026-04-03')
        selected,_=short_call(market(cfg,d),'2026-03-30')
        self.assertEqual(selected['id'],'SHORT1')
        c['series_friday']='2026-04-02'
        self.assertIsNone(short_call(market(cfg,d),'2026-03-30')[0])

    def test_never_invent_intermediate_strike(self):
        self.data['contracts'][1]['strike']=107.5
        selected,_=short_call(market(self.cfg,self.data),'2026-08-31')
        self.assertEqual(selected['strike'],107.5)

    def test_long_eligibility_and_expiry_ranking(self):
        selected,_=long_call(market(self.cfg,self.data),'2026-08-31')
        self.assertEqual(selected['strike'],75.)
        self.data['contracts'][0]['strike']=76.
        self.assertIsNone(long_call(market(self.cfg,self.data),'2026-08-31')[0])

    def test_not_known_until_future_observation(self):
        self.data['options']=[q for q in self.data['options'] if q['id']!='LONG' or q['date']>='2026-08-31']
        self.assertIsNone(long_call(market(self.cfg,self.data),'2026-08-31')[0])

    def test_unpublished_signal_quote_rejected(self):
        row(self.data,'LONG','2026-08-28')['available_at']='2026-08-31T17:00:00-04:00'
        self.assertIsNone(long_call(market(self.cfg,self.data),'2026-08-31')[0])

    def test_quote_validation(self):
        for q in [None,{},dict(bid=-1,ask=2),dict(bid=3,ask=2),dict(bid=1),dict(ask=2),
                  dict(bid=1,ask=2,bid_timestamp='a',ask_timestamp='b'),dict(vendor_mid=1)]:
            self.assertIsNone(mid(q))
        self.assertEqual(mid(dict(vendor_mid=1,vendor_mid_definition_verified=True)),1)
        self.assertIsNone(fill(dict(vendor_mid=1,vendor_mid_definition_verified=True),'BUY','quoted_side'))

    def test_zero_bid_never_new_short(self):
        row(self.data,'SHORT1','2026-08-31')['bid']=0
        for model in ('midpoint','quoted_side'):
            r=run(self.data,self.cfg,model=model,allow_test=True)
            self.assertEqual(r['weekly_coverage'][0]['reason'],'SHORT_BID_NOT_POSITIVE')
            self.assertTrue(r['ledger'][0]['long_only'])

    def test_otm_expiry_retains_long(self):
        result=run(self.data,self.cfg,allow_test=True)
        e=next(e for e in result['blotter'] if e['action']=='EXPIRE')
        self.assertEqual(e['long_after'],'LONG')
        self.assertIsNone(e['short_after'])

    def test_assignment_nav_cash_stock_conservation(self):
        m=market(self.cfg,self.data);a=Account(m,'pmcc','midpoint');d={'signal_spot':100}
        a.open_long(m.contracts['LONG'],'2026-08-31',d)
        a.open_short(m.contracts['SHORT1'],'2026-08-31',d)
        m.stocks['2026-09-04']['price']=110.
        row(self.data,'SHORT1','2026-09-04').update(bid=5.,ask=5.)
        before=a.snapshot('2026-09-04')['nav'];cash=a.cash
        a.assign('2026-09-04','MODELED_EXPIRY_ASSIGNMENT')
        after=a.snapshot('2026-09-04')['nav']
        self.assertAlmostEqual(before,after)
        self.assertEqual(a.cash-cash,10500)
        self.assertEqual(a.shares,-100);self.assertIsNotNone(a.long)
        self.assertEqual(a.cover_due,'2026-09-08')

    def test_cover_borrow_and_no_same_close_reentry(self):
        next(s for s in self.data['stock'] if s['date']=='2026-09-04')['price']=110.
        r=run(self.data,self.cfg,allow_test=True)
        self.assertEqual(r['weekly_coverage'][1]['reason'],'ASSIGNED_COVER_NO_SAME_CLOSE_REENTRY')
        self.assertAlmostEqual(r['attribution']['borrow_cost'],11000*.03*4/365)
        self.assertEqual(r['metrics']['expiry_assignments'],1)
        self.assertTrue(r['audit']['pnl_reconciled'])

    def test_cover_missing_keeps_obligation_incomplete(self):
        next(s for s in self.data['stock'] if s['date']=='2026-09-04')['price']=110.
        self.data['stock']=[s for s in self.data['stock'] if s['date']!='2026-09-08']
        r=run(self.data,self.cfg,allow_test=True)
        self.assertEqual(r['status'],'incomplete');self.assertIsNone(r['metrics']['net_pnl'])
        self.assertEqual(r['ledger'][-1]['stock_shares'],-100)

    def test_dividend_assignment_obligation_and_payment(self):
        for day in ('2026-08-31','2026-09-01'):
            next(s for s in self.data['stock'] if s['date']==day)['price']=110.
        row(self.data,'SHORT1','2026-08-31').update(bid=5,ask=5.2)
        self.data['dividends']=[dict(ex_date='2026-09-01',pay_date='2026-09-03',amount=.25,announced_at='2026-08-20T08:00:00-04:00')]
        r=run(self.data,self.cfg,allow_test=True)
        self.assertEqual(r['metrics']['early_assignments'],1)
        self.assertEqual(r['attribution']['dividends'],-25)
        self.assertEqual(sum(e['cash_delta'] for e in r['blotter'] if e['leg']=='DIVIDEND'),-25)
        self.assertTrue(r['audit']['pnl_reconciled'])

    def test_future_dividend_not_used_early(self):
        next(s for s in self.data['stock'] if s['date']=='2026-08-31')['price']=110.
        row(self.data,'SHORT1','2026-08-31').update(bid=5,ask=5.2)
        self.data['dividends']=[dict(ex_date='2026-09-01',pay_date='2026-09-03',amount=.25,announced_at='2026-09-01T08:00:00-04:00')]
        r=run(self.data,self.cfg,allow_test=True)
        self.assertEqual(r['metrics']['early_assignments'],0)

    def test_stock_dividend_not_double_counted(self):
        self.data['dividends']=[dict(ex_date='2026-09-01',pay_date='2026-09-03',amount=.25,announced_at='2026-08-20T08:00:00-04:00')]
        r=run(self.data,self.cfg,strategy='buy_hold',allow_test=True)
        self.assertAlmostEqual(r['metrics']['net_pnl'],25-2.)
        self.assertTrue(r['audit']['pnl_reconciled'])

    def test_missing_mark_gap_not_interpolated(self):
        self.data['options']=[q for q in self.data['options'] if not(q['id']=='LONG' and q['date']=='2026-09-01')]
        r=run(self.data,self.cfg,allow_test=True)
        self.assertEqual(r['status'],'incomplete')
        self.assertIsNone(r['ledger'][1]['nav'])
        self.assertEqual(r['ledger'][1]['long_contract'],'LONG')
        self.assertIsNone(r['metrics']['max_drawdown'])
        self.assertTrue(all(x['drawdown'] is None for x in r['ledger'][1:]))

    def test_missing_entry_no_retry_or_short_without_long(self):
        row(self.data,'LONG','2026-08-31').update(bid=None,ask=None)
        r=run(self.data,self.cfg,allow_test=True)
        self.assertFalse([e for e in r['blotter'] if e['date']<'2026-09-08'])

    def test_missing_short_keeps_long_and_no_rerank(self):
        row(self.data,'SHORT1','2026-08-31').update(bid=None,ask=None)
        r=run(self.data,self.cfg,allow_test=True)
        self.assertTrue(r['ledger'][0]['long_only'])
        self.assertEqual(r['weekly_coverage'][0]['selected_short'],'SHORT1')
        self.assertFalse([e for e in r['blotter'] if e['leg']=='SHORT_CALL' and e['date']<'2026-09-08'])

    def test_no_discretionary_borrowing(self):
        r=run(self.data,replace(self.cfg,initial_equity=2000),allow_test=True)
        self.assertFalse(r['blotter']);self.assertEqual(r['ledger'][0]['economic_cash'],2000)

    def test_paired_cover_liquidates_long_only_if_needed(self):
        m=market(self.cfg,self.data);a=Account(m,'pmcc','midpoint');d={'signal_spot':100}
        a.open_long(m.contracts['LONG'],'2026-08-31',d);a.open_short(m.contracts['SHORT1'],'2026-08-31',d)
        a.assign('2026-09-04','MODELED_EXPIRY_ASSIGNMENT')
        m.stocks['2026-09-08']['price']=590.
        self.assertTrue(a.cover('2026-09-08'))
        self.assertIsNone(a.long);self.assertEqual(a.shares,0)
        self.assertIn('MANDATORY_PAIRED_LIQUIDATION',[e['reason'] for e in a.events])

    def test_unsupported_short_rejected(self):
        m=market(self.cfg,self.data);a=Account(m,'pmcc','midpoint')
        self.assertEqual(a.open_short(m.contracts['SHORT1'],'2026-08-31',{}),'NO_COMPATIBLE_SUPPORT')

    def test_terminal_short_close_no_double_assignment(self):
        next(s for s in self.data['stock'] if s['date']=='2026-09-11')['price']=110.
        r=run(self.data,self.cfg,allow_test=True)
        terminal=[e for e in r['blotter'] if e['date']=='2026-09-11']
        self.assertTrue(any(e['leg']=='SHORT_CALL' and e['action']=='BUY' for e in terminal))
        self.assertFalse(any(e['action']=='ASSIGN' for e in terminal))
        self.assertEqual(r['ledger'][-1]['n_long'],0)

    def test_terminal_missing_quote_preserves_exposure(self):
        row(self.data,'LONG','2026-09-11').update(bid=None,ask=None)
        r=run(self.data,self.cfg,allow_test=True)
        self.assertEqual(r['status'],'incomplete');self.assertEqual(r['ledger'][-1]['n_long'],1)

    def test_terminal_failed_short_can_assign_but_no_retroactive_cover(self):
        row(self.data,'SHORT2','2026-09-11').update(bid=None,ask=None)
        next(s for s in self.data['stock'] if s['date']=='2026-09-11')['price']=110.
        r=run(self.data,self.cfg,allow_test=True)
        self.assertEqual(r['status'],'incomplete');self.assertEqual(r['ledger'][-1]['stock_shares'],-100)
        self.assertFalse(any(e['leg']=='ASSIGNED_STOCK' and e['date']=='2026-09-11' for e in r['blotter']))

    def test_terminal_entry_suppression(self):
        r=run(self.data,replace(self.cfg,end='2026-09-08'),allow_test=True)
        self.assertEqual(r['weekly_coverage'][-1]['reason'],'TERMINAL_ENTRIES_SUPPRESSED')

    def test_future_changes_cannot_change_past_trades(self):
        before=run(self.data,self.cfg,allow_test=True)
        other=deepcopy(self.data)
        for q in other['options']:
            if q['date']>'2026-09-04': q.update(bid=q['bid']*2,ask=q['ask']*2)
        after=run(other,self.cfg,allow_test=True)
        old=[e for e in before['blotter'] if e['date']<='2026-09-04']
        new=[e for e in after['blotter'] if e['date']<='2026-09-04']
        self.assertEqual(old,new)

    def test_quoted_side_costs_and_reconciliation(self):
        a=run(self.data,self.cfg,allow_test=True)
        b=run(self.data,self.cfg,model='quoted_side',allow_test=True)
        self.assertGreater(a['metrics']['net_pnl'],b['metrics']['net_pnl'])
        self.assertEqual(a['attribution']['option_commissions'],5*.65)
        for r in (a,b):
            self.assertTrue(r['audit']['pnl_reconciled']);self.assertTrue(r['audit']['cash_reconciled'])
            self.assertIsNone(r['metrics']['annualized_metrics'])

    def test_cc_assignment_flat_next_week_rebuys_before_short(self):
        next(s for s in self.data['stock'] if s['date']=='2026-09-04')['price']=110.
        self.data['contracts'][2]['strike']=117.5
        r=run(self.data,self.cfg,strategy='covered_call',allow_test=True)
        e=next(e for e in r['blotter'] if e['action']=='ASSIGN')
        self.assertEqual(e['shares_after'],0)
        events=[e for e in r['blotter'] if e['date']=='2026-09-08']
        self.assertEqual([e['leg'] for e in events],['STOCK','SHORT_CALL'])

    def test_nonstandard_contract_excluded(self):
        self.data['contracts'][0]['multiplier']=10
        self.assertIsNone(long_call(market(self.cfg,self.data),'2026-08-31')[0])

    def test_replacement_closing_quote_failure_keeps_support(self):
        m=market(self.cfg,self.data);a=Account(m,'pmcc','midpoint');d={'signal_spot':100}
        a.open_long(m.contracts['LONG'],'2026-08-31',d)
        a.long['expiry']='2026-10-16'
        row(self.data,'LONG','2026-09-08').update(bid=None,ask=None)
        a.weekly('2026-09-08')
        self.assertTrue(a.halted);self.assertIsNotNone(a.long);self.assertIsNone(a.short)

    def test_replacement_without_candidate_closes_old_before_flat(self):
        m=market(self.cfg,self.data);a=Account(m,'pmcc','midpoint');d={'signal_spot':100}
        a.open_long(m.contracts['LONG'],'2026-08-31',d)
        a.long['expiry']='2026-10-16'
        a.weekly('2026-09-08')
        self.assertIsNone(a.long);self.assertFalse(a.halted)
        self.assertEqual(a.weeks[-1]['reason'],'NO_ELIGIBLE_OBSERVED_LONG')


if __name__=='__main__': unittest.main()
