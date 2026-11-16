"""Gap and weekly-cap regressions; fabricated fixtures confined to unit tests."""
from copy import deepcopy
from datetime import date, timedelta
import math
import statistics
import unittest
from types import SimpleNamespace
from .test_strategy import fixture
from .strategy import indicators, evaluate
from .indicators import compute, IndicatorUnavailable
from .data_provider import merge_recovered, recover_closes
from .course import trading_week, proposal_history, next_state
import pandas as pd


class FlexibleEntryTests(unittest.TestCase):
    def setUp(self):
        self.m, self.a, self.ids = fixture()
        self.h = self.m['tickers']['BAC']['history']
        self.day = self.m['calendar']['as_of']

    def test_fifty_of_fifty_five_and_exact_smas(self):
        for i in (5, 10, 15, 20, 25): self.h[i]['close'] = None
        r = indicators(self.h, self.day)
        values = [x['close'] for x in self.h if x['close'] is not None]
        self.assertEqual(r['sma50'], statistics.mean(values))
        self.assertEqual(r['sma20'], statistics.mean(values[-20:]))
        self.assertEqual(len(r['observation_window']['missing_dates']), 5)
        self.h[30]['close'] = None
        with self.assertRaisesRegex(ValueError, 'at least 50'): indicators(self.h, self.day)

    def test_hv_never_bridges_a_gap(self):
        self.h[-3]['close'] = None
        r = indicators(self.h, self.day)
        adjacent = [(a,b) for a,b in zip(self.h, self.h[1:]) if a['close'] and b['close']][-20:]
        expected = statistics.stdev(math.log(b['close']/a['close']) for a,b in adjacent)*math.sqrt(252)
        self.assertAlmostEqual(r['hv20'], expected)
        self.assertEqual(r['observation_window']['hv20_return_pairs'], [[a['date'],b['date']] for a,b in adjacent])
        self.assertGreater(len(self.h)-self.h.index(adjacent[0][0]), 21)

    def test_latest_and_actual_five_session_anchor_required(self):
        for index, reason in ((-1,'Latest completed'),(-6,'Five-day return')):
            history=deepcopy(self.h); history[index]['close']=None
            with self.assertRaisesRegex(ValueError,reason): indicators(history,self.day)

    def test_resolved_monday_proposal_still_locks_tuesday(self):
        first=evaluate(self.m,self.a,self.ids,[])['orders']
        issued=proposal_history([],first)
        self.a['resolved_order_ids']=[o['id'] for o in first]
        self.m['calendar']['target_session']='2026-11-17'
        self.m['calendar']['first_session_of_week']=False
        r=evaluate(self.m,self.a,self.ids,[],put_history=issued)
        self.assertEqual(r['orders'],[])
        self.assertTrue(all(d['category']=='Already proposed' for d in r['decisions']))
        self.assertEqual(trading_week('2026-11-16'),trading_week('2026-11-20'))
        self.assertNotEqual(trading_week('2026-11-20'),trading_week('2026-11-23'))
        self.assertEqual(trading_week('2027-01-01'),'2026-12-28')

    def test_resolution_does_not_erase_persistent_week_history(self):
        orders=evaluate(self.m,self.a,self.ids,[])['orders']
        state=dict(unconfirmed_orders=[],authoritative_account_seen=False,put_proposal_history=[])
        state=next_state(state,orders,self.a,hypothetical=False)
        self.a['resolved_order_ids']=[o['id'] for o in orders]
        updated=next_state(state,[],self.a,hypothetical=False)
        self.assertEqual(updated['put_proposal_history'],proposal_history([],orders))

    def test_next_week_can_enter_only_when_no_unconfirmed_obligation(self):
        orders=evaluate(self.m,self.a,self.ids,[])['orders']
        self.m['calendar']['target_session']='2026-11-23'
        for d in self.m['tickers'].values():
            for c in d['contracts']: c['expiry']='2026-11-27'
        self.a['resolved_order_ids']=[o['id'] for o in orders]
        r=evaluate(self.m,self.a,self.ids,[],put_history=proposal_history([],orders))
        self.assertEqual(len(r['orders']),4)

    def test_option_failure_is_isolated_but_capital_not_weakened(self):
        self.m['tickers']['BAC']['options_status']='unavailable'
        r=evaluate(self.m,self.a,self.ids,[])
        self.assertEqual(len(r['orders']),3)
        self.assertEqual(r['decisions'][0]['category'],'Option unavailable')
        self.a['equity']=self.a['cash']=1000
        r=evaluate(self.m,self.a,self.ids,[])
        self.assertFalse(r['orders'])
        self.assertTrue(any(d['category']=='Capital limit reached' for d in r['decisions']))

    def test_scarce_capital_prefers_lower_hv_and_keeps_cash_reserve(self):
        for index,data in enumerate(self.m['tickers'].values()):
            for i,row in enumerate(data['history']):
                row['close']=90+.2*i+(index+1)*.03*math.sin(i)
            for c in data['contracts']:
                c['strike']=99 if c['type']=='put' else 110
        r=evaluate(self.m,self.a,self.ids,[])
        expected=sorted(r['decisions'],key=lambda d:(d['hv20'],d['ticker']))[:2]
        self.assertEqual([o['underlying'] for o in r['orders']],[self.ids[d['ticker']] for d in expected])
        self.assertLessEqual(r['capital']['exposure'],28000)
        self.assertGreaterEqual(r['capital']['uncommitted_cash'],12000)

    def test_matching_alternate_recovery_only_fills_missing_dates(self):
        incoming=deepcopy(self.h); self.h[-1]['close']=None
        dates=[r['date'] for r in self.h]
        rows, filled=merge_recovered(self.h,incoming,dates,alternate=True)
        self.assertEqual(filled,[self.day]); self.assertEqual(rows,incoming)
        with self.assertRaisesRegex(ValueError,'five matching'):
            merge_recovered(self.h,incoming[-1:],dates,alternate=True)
        incoming[0]['close']+=1
        with self.assertRaisesRegex(ValueError,'disagree'):
            merge_recovered(self.h,incoming,dates,alternate=True)

    def test_requery_recovers_only_actual_returned_dates(self):
        source=deepcopy(self.h)
        for stale in (False,True):
            d=dict(ric='BAC.N',history=deepcopy(source[:-1])); raw={}
            def get_data(universe,fields,**kwargs):
                rows=source[:-1] if stale else source
                return pd.DataFrame([[universe[0],r['date'],r['close']] for r in rows],columns=['Instrument']+fields)
            ld=SimpleNamespace(get_data=get_data,HeaderType=SimpleNamespace(NAME='NAME'))
            recover_closes(ld,lambda f,*a,**k:f(*a,**k),'BAC',d,raw,self.day)
            self.assertEqual(d['price_recovery']['latest_completed_close_valid'],not stale)
            self.assertEqual(d['price_recovery']['remaining_missing_dates'],[self.day] if stale else [])


if __name__=='__main__': unittest.main()
