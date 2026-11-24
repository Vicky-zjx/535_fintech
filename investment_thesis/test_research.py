"""Artificial fixtures test arithmetic only; published evidence uses LSEG files."""
from copy import deepcopy
import csv
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from tempfile import TemporaryDirectory
from datetime import datetime, timezone
import exchange_calendars as xcals
from .research import analyze, outcomes, comparison, wrong_if, cost_sensitivity, csv_text
from final_project.strategy_config import STRATEGY_REVISION
from .option_audit import audit, finite
from .refresh import refresh


def fixture():
    dates = [str(x.date()) for x in xcals.get_calendar('XNYS').sessions_in_range('2025-01-02', '2026-01-30')]
    return dict(kind='historical_technical_signal_analysis', source='LSEG Data Platform',
                strategy_revision=STRATEGY_REVISION, market_retrieved_at='2026-02-02T00:00:00Z',
                market_snapshot_sha256='fixture-only',
                window=dict(analysis_start=dates[0], analysis_end=dates[-1]),
                tickers={t: {'daily_rows': [dict(signal_date=d, close=100.+i/10, valid=True,
                                               eligible=i%2 == 0, exclusion=None)
                                          for i,d in enumerate(dates)]} for t in ('BAC','KO','PFE','F')})


class ThesisTests(unittest.TestCase):
    def test_reference_is_next_session_not_signal_close_and_requires_six_prices(self):
        h = fixture(); dates, rows = outcomes(h)
        r = rows['BAC'][0]
        self.assertEqual(r['reference_date'], dates[1]); self.assertEqual(r['outcome_date'], dates[6])
        self.assertAlmostEqual(r['stock_return'], 100.6/100.1-1)
        self.assertEqual(r['adverse_move'], 0.)
        self.assertEqual([r['status'] for r in rows['BAC'][-6:]], ['unmatured']*6)

    def test_missing_intermediate_or_endpoint_close_excludes_whole_path_no_fill(self):
        for index in (1, 3, 6):
            h = fixture(); h['tickers']['BAC']['daily_rows'][index]['close'] = None
            r = outcomes(h)[1]['BAC'][0]
            self.assertEqual(r['status'], 'missing_path'); self.assertIsNone(r['stock_return'])
            self.assertIsNone(r['adverse_move']); self.assertEqual(len(r['missing_dates']), 1)

    def test_tail_uses_intermediate_low_not_just_endpoint(self):
        h = fixture(); h['tickers']['BAC']['daily_rows'][3]['close'] = 90.
        r = outcomes(h)[1]['BAC'][0]
        self.assertTrue(r['tail_event']); self.assertGreater(r['stock_return'], 0)
        self.assertAlmostEqual(r['adverse_move'], 1-90/100.1)

    def test_invalid_signal_is_not_a_failed_filter_and_unknown_is_not_zero(self):
        h = fixture(); h['tickers']['BAC']['daily_rows'][0].update(valid=False,eligible=None,exclusion='missing')
        r = outcomes(h)[1]['BAC'][0]
        self.assertEqual(r['status'], 'signal_unavailable'); self.assertIsNone(r['cohort'])
        self.assertIsNone(r['stock_return'])

    def test_future_prices_do_not_change_a_past_completed_tracker(self):
        h = fixture(); before = analyze(h)
        for d in h['tickers'].values():
            for r in d['daily_rows'][180:]: r['close'] *= .5
        after = analyze(h)
        self.assertEqual(before['rolling'][:180], after['rolling'][:180])

    def test_126_entry_sessions_no_reindexing_and_equal_stock_weights(self):
        r = analyze(fixture()); latest = r['rolling'][-1]
        for s in latest['tickers'].values():
            self.assertEqual(s['pass']['n']+s['fail']['n'],126)
        self.assertTrue(latest['aggregate']['sufficient'])
        self.assertEqual(latest['aggregate']['pass_mean_return'],
                         sum(s['pass']['mean_return'] for s in latest['tickers'].values())/4)
        self.assertFalse(r['prospective']['aggregate']['sufficient'])

    def test_minimum_counts_missing_cohort_and_wrong_if(self):
        rows = outcomes(fixture())[1]
        rows['BAC'] = rows['BAC'][:30]
        s = comparison(rows)
        self.assertFalse(s['aggregate']['sufficient']); self.assertIsNone(s['aggregate']['downside_benefit'])
        self.assertEqual(wrong_if(s)['no_downside_benefit'], 'insufficient')
        ready = analyze(fixture())['rolling'][-1]
        self.assertEqual(ready['wrong_if']['no_downside_benefit'], 'triggered') # both loss means exactly zero

    def test_wrong_if_uses_registered_sample_floor_not_confidence_intervals(self):
        stats = analyze(fixture())['rolling'][-1]
        stats['aggregate'].update(baseline_downside_benefit=.001, baseline_tail_benefit=.01)
        expected = {'no_downside_benefit': 'not_triggered', 'no_tail_benefit': 'not_triggered'}
        # Test-only interval metadata must never alter the registered point-estimate rule.
        for interval in ([-.1, .1], [.01, .02], [-.02, -.01], None):
            stats['aggregate']['ci95'] = interval
            self.assertEqual(wrong_if(stats), expected)
        stats['aggregate']['sufficient'] = False
        self.assertEqual(set(wrong_if(stats).values()), {'insufficient'})
        stats['aggregate'].update(sufficient=True, baseline_downside_benefit=-.001)
        self.assertEqual(wrong_if(stats)['no_downside_benefit'], 'triggered')

    def test_calendar_holidays_not_weekdays_and_all_session_rows_required(self):
        h = fixture(); dates, rows = outcomes(h)
        r = next(r for r in rows['BAC'] if r['signal_date'] == '2025-01-17')
        self.assertEqual(r['reference_date'], '2025-01-21')
        h['tickers']['BAC']['daily_rows'].pop(10)
        with self.assertRaises(ValueError): outcomes(h)

    def test_holiday_or_weekend_window_start_does_not_change_session_sample(self):
        for start,first in [('2025-01-01','2025-01-02'),('2025-01-04','2025-01-06')]:
            h=fixture(); h['window']['analysis_start']=start
            for values in h['tickers'].values():
                values['daily_rows']=[r for r in values['daily_rows'] if r['signal_date']>=start]
            dates,rows=outcomes(h)
            self.assertEqual(dates[0],first)
            self.assertNotIn(start,dates)
            self.assertEqual(len(rows['BAC']),len(h['tickers']['BAC']['daily_rows']))
            self.assertEqual(rows['BAC'][0]['reference_date'],dates[1])
            self.assertEqual(rows['BAC'][0]['outcome_date'],dates[6])
            self.assertEqual(h['window']['analysis_start'],start)

    def test_review_compares_unconditional_baseline_not_only_failed_signals(self):
        r = analyze(fixture())['full_sample']
        a = r['aggregate']
        a.update(downside_benefit=.01, tail_benefit=.01,
                 baseline_downside_benefit=-.001, baseline_tail_benefit=-.001)
        self.assertEqual(wrong_if(r), {'no_downside_benefit':'triggered','no_tail_benefit':'triggered'})

    def test_provenance_invalid_price_and_boolean_validation(self):
        for mutate in (lambda h:h.update(source='synthetic'),
                       lambda h:h['tickers']['BAC']['daily_rows'][3].update(close=0),
                       lambda h:h['tickers']['BAC']['daily_rows'][3].update(eligible=None)):
            h = fixture(); mutate(h)
            with self.assertRaises(ValueError): analyze(h)

    def test_costs_are_assumptions_not_returns_or_strategy_fee_changes(self):
        c = cost_sensitivity()
        self.assertIn('not_estimated_alpha', c['kind'])
        self.assertAlmostEqual(c['examples'][0]['assumed_cost'],3.30)
        self.assertAlmostEqual(c['examples'][0]['break_even_bps'],3.4375)
        self.assertAlmostEqual(c['examples'][1]['break_even_bps'],11.785714285714286)

    def test_all_cost_scenarios_reproduce_and_negative_edge_is_retained(self):
        for e in cost_sensitivity()['examples']:
            self.assertEqual([x['gross_bps'] for x in e['scenarios']], [5,10,20,30,50])
            for x in e['scenarios']:
                self.assertAlmostEqual(x['net_dollars'],e['collateral']*x['gross_bps']/10000-3.30)
                self.assertAlmostEqual(x['net_bps'],x['net_dollars']/e['collateral']*10000)
        self.assertLess(cost_sensitivity()['examples'][1]['scenarios'][1]['net_dollars'],0)

    def test_maturity_and_calendar_freshness_are_not_the_generation_date(self):
        r=analyze(fixture())
        self.assertEqual(r['latest_matured_outcome_date'],r['window']['analysis_end'])
        self.assertGreater(r['next_market_session'],r['window']['analysis_end'])
        self.assertEqual(r['next_market_session'],'2026-02-02')
        self.assertIn('21:00:00',r['next_market_close_at'])

    def test_option_inventory_does_not_infer_returns_from_metadata(self):
        root=Path(__file__).resolve().parents[1]
        a=audit(root)
        self.assertEqual(a['status'],'insufficient_option_data')
        self.assertIsNone(a['economic_advantage'])
        self.assertFalse(a['extension']['original_registered_condition'])
        for s in a['snapshots']:
            if s['status']!='inventoried':continue
            raw=json.loads((root/s['path']).read_text())
            for t,c in s['tickers'].items():
                self.assertEqual(c['contracts'],len(raw['tickers'][t]['contracts']))
                self.assertEqual(c['puts'],sum(x['type']=='put' for x in raw['tickers'][t]['contracts']))
        for v in (None,True,float('nan'),float('inf'),'0'):
            self.assertFalse(finite(v))
        self.assertTrue(finite(0.))

    def test_failed_upstream_retains_both_evidence_files_and_records_failure(self):
        with TemporaryDirectory() as tmp:
            d=Path(tmp)/'investment-thesis/data';d.mkdir(parents=True)
            before=b'{"generated_at":"prior","market_snapshot_sha256":"prior-hash"}'
            (d/'thesis_tracker.json').write_bytes(before)
            (d/'thesis_observations.csv').write_bytes(b'prior-csv')
            with patch('investment_thesis.refresh.build') as build:
                status=refresh(tmp,datetime.now(timezone.utc),'failure')
            build.assert_not_called()
            self.assertEqual(status['status'],'failed')
            self.assertEqual(status['evidence_generated_at'],'prior')
            self.assertEqual((d/'thesis_tracker.json').read_bytes(),before)
            self.assertEqual((d/'thesis_observations.csv').read_bytes(),b'prior-csv')

    def test_failed_validation_rolls_back_only_own_outputs(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);d=root/'investment-thesis/data';d.mkdir(parents=True)
            (d/'thesis_tracker.json').write_text('{}');(d/'thesis_observations.csv').write_text('old')
            (root/'open_orders.json').write_text('protected')
            def bad_build(*args):
                (d/'thesis_tracker.json').write_text('{"unvalidated":true}')
                (d/'thesis_observations.csv').write_text('new')
                return {'generated_at':'new','market_snapshot_sha256':'new'}
            with patch('investment_thesis.refresh.build',side_effect=bad_build),patch('investment_thesis.refresh.check',side_effect=ValueError('bad data')):
                status=refresh(root,datetime.now(timezone.utc))
            self.assertEqual(status['status'],'failed')
            self.assertEqual((d/'thesis_tracker.json').read_text(),'{}')
            self.assertEqual((d/'thesis_observations.csv').read_text(),'old')
            self.assertEqual((root/'open_orders.json').read_text(),'protected')

    def test_csv_nulls_not_zero_and_no_mutation(self):
        h = fixture(); before = deepcopy(h); r = analyze(h)
        self.assertEqual(h,before)
        rows = list(csv.DictReader(io.StringIO(csv_text(r))))
        self.assertEqual(rows[-1]['stock_return'],''); self.assertEqual(rows[-1]['status'],'unmatured')
        self.assertNotIn('orders',r); self.assertNotIn('sharpe',r)

    def test_real_file_matches_raw_closes_and_csv_all_rows(self):
        root = Path(__file__).resolve().parents[1]
        h = json.loads((root/'docs/data/historical_signals.json').read_text())
        dates, result = outcomes(h)
        for t, rows in result.items():
            prices = h['tickers'][t]['daily_rows']
            for r in rows:
                if r['status'] == 'observed':
                    a,b = r['reference_index'],r['outcome_index']
                    self.assertAlmostEqual(r['stock_return'], prices[b]['close']/prices[a]['close']-1)
                    self.assertEqual(len(prices[a:b+1]),6)
                    self.assertTrue(all(x['close'] is not None for x in prices[a:b+1]))


if __name__ == '__main__': unittest.main()
