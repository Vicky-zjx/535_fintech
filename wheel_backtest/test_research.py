"""Arithmetic and real-publication checks. Never change the saved market input."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from .research import committed, capital_summary, fixed_share_benchmark, build_research, adjacent_returns, prefix_drawdown
from .test_engine import fixture, simulate, price

ROOT = Path(__file__).resolve().parents[1]


class ResearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = json.loads((ROOT/'wheel/results.json').read_text())
        cls.research = build_research(cls.book)

    def test_original_results_not_mutated(self):
        before = deepcopy(self.book); build_research(self.book)
        self.assertEqual(before, self.book)

    def test_original_pnl_and_returns_preserved_both_fills(self):
        for model, pnl in [('quoted_side',1865.85),('midpoint',1916.35)]:
            r=next(r for r in self.book['runs'] if r['strategy']=='wheel' and r['fill_model']==model)
            c=self.research['accounts']['wheel:'+model]['capital']
            self.assertAlmostEqual(r['metrics']['net_pnl'],pnl)
            self.assertAlmostEqual(r['metrics']['total_return'],pnl/50000)
            self.assertAlmostEqual(c['return_on_average_committed'],pnl/32108.870967741936)
        self.assertAlmostEqual(self.book['runs'][-1]['metrics']['net_pnl'],3275.198706)

    def test_published_missing_quote_review_still_retains_gap(self):
        review=json.loads((ROOT/'wheel/valuation_review.json').read_text())
        self.assertEqual(review['status'],'unresolved_existing_valuation_rule')
        self.assertIsNone(review['daily_quote']['bid'])
        self.assertTrue(all(not e['eligible_under_current_rule'] for e in review['evidence']))
        for model in ('quoted_side','midpoint'):
            r=next(r for r in self.book['runs'] if r['strategy']=='wheel' and r['fill_model']==model)
            self.assertIsNone(next(s for s in r['ledger'] if s['date']==review['date'])['equity'])

    def test_collateral_and_share_cost_no_double_count(self):
        r = self.book['runs'][0]
        for s in r['snapshots']:
            p = s['option']; c = committed(s)
            if p and p['cp']=='P': self.assertEqual(c, p['strike']*100)
            elif s['shares']: self.assertEqual(c, s['shares']*s['share_acquisition_cost'])
            else: self.assertEqual(c, 0)
        wrong = deepcopy(next(s for s in r['snapshots'] if s['covered_call']))
        wrong['reserved_cash'] = 100
        with self.assertRaisesRegex(ValueError, 'collateral'): committed(wrong)

    def test_peak_includes_expiry_day_release(self):
        r = self.book['runs'][0]; c = capital_summary(r, 50000)
        day = next(d for d in c['daily'] if d['date']=='2026-07-10')
        self.assertEqual(day['eod_committed'], 0); self.assertEqual(day['peak_committed'], 30000)
        self.assertAlmostEqual(c['average_committed'], 32108.870967741936)
        self.assertAlmostEqual(c['average_eod_committed'], 29548.387096774193)
        self.assertAlmostEqual(c['utilization'], .6421774193548387)
        self.assertAlmostEqual(c['return_on_average_committed'], 1865.85/c['average_committed'])
        self.assertEqual(c['sessions_with_shares'], 34); self.assertEqual(c['sessions_without_shares'], 28)
        self.assertEqual(len(c['daily']), 62)  # The NAV gap does not erase known commitment.
        self.assertAlmostEqual(c['average_cash'], c['average_reserved_cash']+c['average_unreserved_cash'])

    def test_fixed_100_cash_price_cost_dividends(self):
        r = self.research['fixed_benchmark']; initial = self.book['config']['initial_cash']
        buy = next(e for e in r['events'] if e['event_type']=='STOCK_BUY')
        self.assertEqual(buy['quantity'],100); self.assertEqual(buy['fill_price'],312.66)
        self.assertAlmostEqual(buy['stock_execution_cost'],3.1266)
        for row in r['ledger']:
            cash = initial+sum(e['net_cash_flow'] for e in r['events'] if e['date']<=row['date'])
            self.assertAlmostEqual(row['cash'],cash)
            self.assertEqual(row['shares'],100)
            self.assertAlmostEqual(row['equity'],cash+100*row['stock_mark']+row['dividend_receivable'])
        self.assertAlmostEqual(r['ledger'][-1]['dividend_income'],27)
        self.assertAlmostEqual(r['metrics']['net_pnl'],2059.8734)
        self.assertAlmostEqual(r['metrics']['total_return'],2059.8734/50000)
        ex=next(row for row in r['ledger'] if row['date']=='2026-08-10')
        self.assertAlmostEqual(ex['dividend_receivable'],27)
        self.assertEqual(len(r['events']),3)

    def test_fixed_100_rejects_unaffordable_or_non_stock_account(self):
        with self.assertRaisesRegex(ValueError,'afford'): fixed_share_benchmark(self.book,1000)
        b=deepcopy(self.book);b['runs'][-1]['snapshots'][0]['reserved_cash']=1
        with self.assertRaisesRegex(ValueError,'stock-only'): fixed_share_benchmark(b)

    def test_common_dates_never_bridge_gap(self):
        for model in ('quoted_side','midpoint'):
            c=self.research['common_observations'][model]
            self.assertEqual(len(c['dates']),60)
            self.assertEqual(c['excluded_dates'],['2026-08-13','2026-08-14'])
            self.assertAlmostEqual(c['accounts']['buy_hold:quoted_side']['sharpe'],.933454429164,places=8)
            self.assertAlmostEqual(c['accounts']['wheel:'+model]['sharpe'],next(r['metrics']['available_daily_return_sharpe'] for r in self.book['runs'] if r['strategy']=='wheel' and r['fill_model']==model))
        r=deepcopy(self.book['runs'][0]);next(s for s in r['ledger'] if s['date']=='2026-08-14')['daily_return']=0.
        with self.assertRaisesRegex(ValueError,'bridges'): adjacent_returns(r,50000)

    def test_valid_prefix_stops_before_gap(self):
        r=self.book['runs'][0];p=prefix_drawdown(r,50000)
        self.assertEqual(p['start'],'2026-07-06');self.assertEqual(p['end'],'2026-08-12')
        self.assertEqual(p['sessions'],28)
        self.assertAlmostEqual(p['max_drawdown'],min(s['drawdown'] for s in r['ledger'] if s['drawdown'] is not None))
        empty=deepcopy(r);empty['ledger'][0]['equity']=None
        self.assertIsNone(prefix_drawdown(empty,50000)['max_drawdown'])
        self.assertIsNone(r['metrics']['max_drawdown'])

    def test_dividend_event_timestamps_match_all_representations(self):
        cfg,data=fixture();price(data,'2026-08-07',90)
        data['dividends']=[dict(ex_date='2026-08-10',pay_date='2026-08-13',amount=1.,announced_at='2026-08-01T00:00:00-04:00')]
        r=simulate(data,cfg)
        for e in r['events']:
            for side in ('before','after'):
                snap=next(s for s in r['snapshots'] if s['snapshot_id']==e['event_id']+'-'+side)
                self.assertEqual(e[side]['timestamp'],e['timestamp']);self.assertEqual(snap['timestamp'],e['timestamp'])
                self.assertEqual(snap['mark_date'],e[side]['mark_date'])
            if e['event_type'].startswith('DIVIDEND'):
                self.assertIn('T09:30:00',e['timestamp'])
                self.assertLess(e['before']['mark_date'],e['date'])
        self.assertEqual(r['ledger'][-1]['dividend_income'],100)


if __name__=='__main__': unittest.main()
