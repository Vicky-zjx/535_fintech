"""Arithmetic fixtures only; no fabricated market observations are published."""
from datetime import date, timedelta
import math
import statistics
import unittest
from .metrics import calculate


class MetricsTests(unittest.TestCase):
    def evaluate(self, values, rf=0):
        start=date(2026,8,3)
        rows=[dict(date=str(start+timedelta(days=i)),equity=v) for i,v in enumerate(values)]
        return rows,calculate(rows,100,str(start),rows[-1]['date'] if rows else str(start),rf)

    def test_gap_preserves_nav_and_excludes_both_adjacent_returns(self):
        values=[101,None,120,118,122]
        rows,m=self.evaluate(values)
        self.assertEqual([r['equity'] for r in rows],values)
        self.assertEqual([r['daily_return'] for r in rows],[.010000000000000009,None,None,118/120-1,122/118-1])
        returns=[101/100-1,118/120-1,122/118-1]
        expected=statistics.mean(returns)/statistics.stdev(returns)*math.sqrt(252)
        self.assertAlmostEqual(m['available_daily_return_sharpe'],expected)
        self.assertEqual(m['valid_daily_returns'],3)
        self.assertEqual(m['daily_return_session_count'],5)
        self.assertEqual(m['excluded_daily_return_dates'],['2026-08-04','2026-08-05'])
        self.assertEqual(m['excluded_daily_return_count'],2)
        self.assertIsNone(m['sharpe']);self.assertIsNone(m['max_drawdown'])
        self.assertTrue(all(r['drawdown'] is None for r in rows[1:]))
        self.assertIsNotNone(rows[-1]['observed_drawdown'])

    def test_complete_sample_matches_original_sharpe(self):
        _,m=self.evaluate([101,99,103,104])
        self.assertEqual(m['available_daily_return_sharpe'],m['sharpe'])
        self.assertEqual(m['excluded_daily_return_dates'],[])

    def test_risk_free_rate_and_sample_standard_deviation(self):
        rows,m=self.evaluate([101,None,120,118,122],.05)
        returns=[r['daily_return'] for r in rows if r['daily_return'] is not None]
        expected=(statistics.mean(returns)-(1.05**(1/252)-1))/statistics.stdev(returns)*math.sqrt(252)
        self.assertAlmostEqual(m['available_daily_return_sharpe'],expected)

    def test_empty_single_or_constant_sample_is_undefined(self):
        for values in ([],[101],[100,100,100],[None,None]):
            with self.subTest(values=values):
                _,m=self.evaluate(values)
                self.assertIsNone(m['available_daily_return_sharpe'])

    def test_first_last_and_consecutive_gaps_never_bridge(self):
        for values,valid in (([None,101,102,99],2),([101,102,None],2),([101,None,None,150,151],2)):
            with self.subTest(values=values):
                rows,m=self.evaluate(values)
                self.assertEqual(m['valid_daily_returns'],valid)
                self.assertEqual(m['excluded_daily_return_count'],len(values)-valid)
                for i,r in enumerate(rows):
                    if r['equity'] is None or (i and rows[i-1]['equity'] is None):
                        self.assertIsNone(r['daily_return'])


if __name__=='__main__':unittest.main()
