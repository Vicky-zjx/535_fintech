"""Synthetic test fixtures are never published as historical market data."""
from copy import deepcopy
import unittest
import pandas as pd
import exchange_calendars as xcals
from .historical import analyze, history_window, summarize
from .strategy import indicators


def fixture():
    w = history_window('2026-11-13')
    cal = xcals.get_calendar('XNYS', start=w['query_start'], end=w['analysis_end'])
    dates = cal.sessions_in_range(w['query_start'], w['analysis_end'])
    rows = [{'date': str(d.date()), 'close': 30.+.03*i} for i,d in enumerate(dates)]
    return {'mode': 'live', 'source': 'LSEG Data Platform', 'retrieved_at': '2026-11-16T03:00:00Z',
            'calendar': {'as_of': '2026-11-13'}, 'tickers': {
                t: {'identity_verified': True, 'history': deepcopy(rows)} for t in ('BAC','KO','PFE','F')}}


class HistoricalTests(unittest.TestCase):
    def test_complete_window_and_multiple_stocks(self):
        r = analyze(fixture())
        self.assertEqual(r['status'], 'complete')
        self.assertEqual(r['window']['analysis_start'], '2023-11-13')
        for d in r['tickers'].values():
            self.assertEqual(d['coverage']['observed_warmup_closes'], 50)
            self.assertEqual(d['daily']['evaluated_dates'], r['window']['expected_sample_sessions'])
            self.assertEqual(d['weekly']['pass_rates']['combined'], 1.)
        self.assertEqual(r['joint_weekly']['distribution']['4'], r['joint_weekly']['evaluated_dates'])
        self.assertNotIn('pnl', r); self.assertNotIn('sharpe', r)

    def test_indicators_match_live_engine(self):
        m = fixture(); r = analyze(m)
        for row in r['tickers']['BAC']['daily_rows'][::100]:
            history = [x for x in m['tickers']['BAC']['history'] if x['date'] <= row['signal_date']]
            live = indicators(history, row['signal_date'])
            for k in ('sma20','sma50','hv20','r5'):
                self.assertAlmostEqual(row[k], live[k], places=10)
            for k in ('trend','volatility','sudden_drop'):
                self.assertEqual(row[k], live['filters'][k])

    def test_future_prices_cannot_change_past_signals(self):
        m = fixture(); before = analyze(m)
        cutoff = '2025-06-01'
        for d in m['tickers'].values():
            for r in d['history']:
                if r['date'] >= cutoff: r['close'] *= 2
        after = analyze(m)
        for t in m['tickers']:
            self.assertEqual([r for r in before['tickers'][t]['daily_rows'] if r['signal_date'] < cutoff],
                             [r for r in after['tickers'][t]['daily_rows'] if r['signal_date'] < cutoff])

    def test_holiday_entry_uses_previous_close(self):
        r = analyze(fixture())
        week = next(x for x in r['tickers']['BAC']['weekly_rows'] if x['entry_session'] == '2026-09-08')
        self.assertEqual(week['signal_date'], '2026-09-04')
        self.assertTrue(week['first_weekly_session'])
        self.assertTrue(all(x['signal_date'] < x['entry_session'] for x in r['tickers']['BAC']['weekly_rows']))

    def test_partial_history_and_warmup_excluded(self):
        m = fixture()
        for d in m['tickers'].values(): d['history'] = d['history'][-86:]
        r = analyze(m)
        self.assertEqual(r['status'], 'partial')
        self.assertEqual(r['tickers']['BAC']['coverage']['observed_sessions'], 86)
        self.assertEqual(r['tickers']['BAC']['daily']['evaluated_dates'], 37)
        self.assertGreater(r['joint_weekly']['excluded_dates'], 0)

    def test_null_or_absent_close_is_not_filled_or_compressed(self):
        m = fixture(); bad = '2026-08-13'
        for t in ('BAC', 'KO'):
            for row in m['tickers'][t]['history']:
                if row['date'] == bad: row['close'] = None
        m['tickers']['KO']['history'] = [r for r in m['tickers']['KO']['history'] if r['date'] != bad]
        r = analyze(m)
        for t in ('BAC','KO'):
            self.assertIn(bad, r['tickers'][t]['coverage']['missing_dates'])
            invalid = [x for x in r['tickers'][t]['daily_rows'] if not x['valid']]
            self.assertEqual(len(invalid), 50)
            self.assertTrue(all(x['eligible'] is None for x in invalid))

    def test_overlapping_rejections_and_denominators(self):
        rows = [dict(valid=True, trend=False, volatility=False, sudden_drop=True, eligible=False),
                dict(valid=True, trend=False, volatility=True, sudden_drop=True, eligible=False),
                dict(valid=False, trend=None, volatility=None, sudden_drop=None, eligible=None)]
        s = summarize(rows)
        self.assertEqual(s['evaluated_dates'], 2); self.assertEqual(s['excluded_dates'], 1)
        self.assertEqual(s['standalone_rejections']['trend'], 2)
        self.assertEqual(s['exclusive_rejections']['trend'], 1)
        self.assertEqual(s['exclusive_rejections']['volatility'], 0)
        self.assertEqual(s['pass_rates']['volatility'], .5)

    def test_invalid_provenance_duplicate_or_future_data_rejected(self):
        for mutate in (lambda m: m.update(mode='test'),
                       lambda m: m['tickers']['BAC']['history'].append({'date':'2030-01-01','close':10}),
                       lambda m: m['tickers']['BAC']['history'].append(dict(m['tickers']['BAC']['history'][-1],close=1))):
            m = fixture(); mutate(m)
            with self.assertRaises(ValueError): analyze(m)

    def test_leap_year_window_uses_calendar_years(self):
        self.assertEqual(history_window('2024-02-29')['analysis_start'], '2021-02-28')


if __name__ == '__main__': unittest.main()
