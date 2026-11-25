"""Private evidence, deterministic arithmetic; never calls an API."""
from copy import deepcopy
import json
import os
from pathlib import Path
import unittest
from .put_payoff import observations, analyze, RATIOS
from .fixed_store import load

ROOT=Path(__file__).resolve().parents[1]


class PayoffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.p=load(ROOT)['content']['hypothetical_put_payoff']

    def test_fixed_design_counts_costs_and_opportunity_identity(self):
        self.assertEqual(self.p['scheduled_mature_weeks'],260)
        self.assertEqual(self.p['design']['strike_to_signal_spot'],list(RATIOS))
        self.assertIsNone(self.p['estimated_option_alpha']);self.assertEqual(self.p['premium_observations'],0)
        for t,ratios in self.p['tickers'].items():
            for z in ratios.values():
                u,f,q=z['unfiltered'],z['filtered'],z['eligible_frequency']
                self.assertEqual(u['n'],260);self.assertEqual(z['exclusions'],{'unmatured':1})
                self.assertAlmostEqual(q,f['n']/260)
                for g in (u,f):self.assertAlmostEqual(g['break_even_after_cost'],g['mean_loss']+g['mean_cost'])
                self.assertAlmostEqual(z['weekly_filtered_loss'],q*f['mean_loss'])
                self.assertAlmostEqual(z['weekly_break_even_reduction'],u['break_even_after_cost']-q*f['break_even_after_cost'])
                self.assertEqual([b['block_weeks'] for b in z['sensitivity']],[2,4,8])
                # A higher strike cannot lower put liability / strike.
            self.assertGreaterEqual(ratios['1.0']['filtered']['mean_loss'],ratios['0.9']['filtered']['mean_loss'])

    def test_no_loss_sample_is_not_statistical_certainty(self):
        z=self.p['tickers']['KO']['0.9'];self.assertEqual(z['filtered']['positive_loss_events'],0)
        for b in z['sensitivity']:self.assertIsNone(b['conditional_loss_reduction']['ci95'])
        self.assertTrue(z['sparse_loss_events'])
        with self.assertRaises(ValueError):analyze({},0)

    def test_private_reproduction_dates_real_prices_and_bootstrap(self):
        path=os.environ.get('THESIS_PRIVATE_HISTORY')
        if not path:self.skipTest('Private evidence not configured')
        e=json.loads(Path(path).read_text())['evidence'];before=deepcopy(e)
        rows=observations(e)
        for r in rows:
            self.assertLess(r['signal_date'],r['entry_date']);self.assertIn(r['dte'],[6,7,8])
            if r['status']!='observed':continue
            prices={q['date']:q['close'] for q in e['tickers'][r['ticker']]['history']}
            strike=r['ratio']*prices[r['signal_date']]
            self.assertAlmostEqual(r['loss'],max(strike-prices[r['expiry_date']],0)/strike)
            self.assertAlmostEqual(r['cost'],3.30/(100*strike))
        # Good Friday shifts expiry and the next entry to Thursday, not a fake Friday close.
        april=[r for r in rows if r['entry_date']=='2024-03-22']
        self.assertTrue(april);self.assertTrue(all(r['expiry_date']=='2024-03-28' for r in april))
        self.assertEqual(analyze(e),self.p);self.assertEqual(e,before)


if __name__=='__main__':unittest.main()
