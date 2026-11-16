"""Offline fixtures are NOT market data or published results."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from .calendar import context, required_sessions
from .data_provider import conids_from_course, normalize_closes, normalize_contracts, earnings_calendar
from .portfolio import validate_account
from .run import run
from .sanji_orders import validate, publish_orders, read_orders
from .strategy import indicators, evaluate, select_contract
import pandas as pd


def fixture():
    ctx = context(datetime(2026, 11, 16, 3, tzinfo=timezone.utc))
    market = {'mode': 'test', 'calendar': ctx, 'tickers': {}}
    for i, (t, close) in enumerate([('BAC', 50), ('KO', 60), ('PFE', 30), ('F', 10)]):
        history = [{'date': d, 'close': close*(.9+.1*j/49)} for j, d in enumerate(required_sessions(ctx['as_of']))]
        contracts = [dict(ric=f'TEST-{t}-{cp}-{k}', type=cp, strike=round(close*k, 2), expiry='2026-11-20',
                          multiplier=100, terms_verified=True, observed_on=ctx['as_of'],
                          delta=(-.25 if cp == 'put' else .25), delta_date=ctx['as_of'])
                     for cp, k in [('put', .97), ('call', 1.), ('call', 1.02), ('call', 1.04)]]
        market['tickers'][t] = dict(identity_verified=True, history=history, contracts=contracts,
            options_status='observed', earnings={'reliable': True, 'known_on': ctx['as_of'],
                                                'through': '2027-01-01', 'dates': ['2026-12-01']})
    account = dict(schema_version=1, source='TEST_FIXTURE', as_of=ctx['as_of'], currency='USD',
                   cash=40000., equity=40000., positions=[], resolved_order_ids=[])
    # Deliberately artificial IDs, only in this named test fixture.
    return market, account, {'BAC': 90000001, 'KO': 90000002, 'PFE': 90000003, 'F': 90000004}


class StrategyTests(unittest.TestCase):
    def setUp(self):
        self.m, self.a, self.ids = fixture()

    def go(self, pending=None):
        return evaluate(self.m, self.a, self.ids, pending or [])

    def decision(self, result, ticker='BAC'):
        return next(d for d in result['decisions'] if d['ticker'] == ticker)

    def stock(self, basis=50):
        self.a['positions'] = [dict(ticker='BAC', kind='stock', quantity=100, cost_basis=basis)]
        self.a['cash'] -= 5000

    def test_all_pass_puts(self):
        r = self.go()
        self.assertEqual(r['status'], 'success')
        self.assertEqual(len(r['orders']), 4)
        self.assertTrue(all(o['contract'] == 'put' for o in r['orders']))

    def test_trend_failure(self):
        self.m['tickers']['BAC']['history'][-1]['close'] = 45
        self.assertIn('trend filter failed', self.decision(self.go())['reasons'])

    def test_volatility_failure(self):
        for i, r in enumerate(self.m['tickers']['BAC']['history'][-21:]):
            r['close'] = 50 if i % 2 else 60
        self.assertIn('volatility filter failed', self.decision(self.go())['reasons'])

    def test_sudden_drop(self):
        self.m['tickers']['BAC']['history'][-1]['close'] = 40
        self.assertIn('sudden_drop filter failed', self.decision(self.go())['reasons'])

    def test_earnings_inclusive(self):
        for day in ('2026-11-16', '2026-11-20'):
            self.m['tickers']['BAC']['earnings']['dates'] = [day]
            self.assertIn('Earnings blackout', ' '.join(self.decision(self.go())['reasons']))

    def test_unknown_earnings_blocks_put(self):
        self.m['tickers']['BAC']['earnings']['reliable'] = False
        self.assertFalse(self.decision(self.go())['eligible'])

    def test_existing_put_blocks_duplicate(self):
        self.a['positions'] = [dict(ticker='BAC', kind='put', quantity=-1, multiplier=100,
            terms_status='standard_verified', strike=48.5, expiry='2026-11-20', mark=1.)]
        self.a['equity'] -= 100
        self.assertIn('Existing short option', ' '.join(self.decision(self.go())['reasons']))

    def test_stock_transitions_to_call_without_put_filters(self):
        self.stock()
        self.m['calendar']['first_session_of_week'] = False
        self.m['tickers']['BAC']['earnings']['reliable'] = False
        self.assertEqual(self.decision(self.go())['decision'], 'Sell Covered Call')

    def test_existing_call_no_duplicate(self):
        self.stock()
        self.a['positions'].append(dict(ticker='BAC', kind='call', quantity=-1, multiplier=100,
            terms_status='standard_verified', strike=52, expiry='2026-11-20', mark=1.))
        self.a['equity'] -= 100
        self.assertFalse(self.decision(self.go())['eligible'])

    def test_cost_basis_threshold(self):
        self.stock(100)
        self.assertFalse(self.decision(self.go())['eligible'])

    def test_missing_cost_basis(self):
        self.stock(None)
        self.assertIn('cost basis unavailable', ' '.join(self.decision(self.go())['reasons']))

    def test_no_naked_call_or_borrowing(self):
        self.a['cash'] = -10
        self.assertEqual(self.go()['status'], 'blocked')
        self.a['cash'] = 40000
        self.a['positions'] = [dict(ticker='BAC', kind='call', quantity=-1, multiplier=100,
            terms_status='standard_verified', strike=52, expiry='2026-11-20', mark=0.)]
        self.assertEqual(self.go()['status'], 'blocked')

    def test_cash_and_exposure_limits(self):
        self.a['cash'] = self.a['equity'] = 1000
        r = self.go()
        self.assertEqual(r['orders'], [])
        self.assertTrue(any('30%' in x for x in self.decision(r)['reasons']))

    def test_holiday_tuesday_is_first_session(self):
        ctx = context(datetime(2026, 9, 8, 2, tzinfo=timezone.utc))
        self.assertEqual(ctx['target_session'], '2026-09-08')
        self.assertTrue(ctx['first_session_of_week'])

    def test_intraday_run_blocked(self):
        with self.assertRaisesRegex(ValueError, 'already open'):
            context(datetime(2026, 11, 16, 16, tzinfo=timezone.utc))

    def test_same_session_idempotent(self):
        first = self.go()
        second = self.go(first['orders'])
        self.assertEqual(first['orders'], second['orders'])
        self.assertAlmostEqual(first['capital']['exposure'], second['capital']['exposure'])

    def test_no_put_midweek_valid_empty(self):
        self.m['calendar']['first_session_of_week'] = False
        self.assertEqual(self.go()['orders'], [])

    def test_stale_or_missing_price_blocks_batch(self):
        self.m['tickers']['BAC']['history'].pop()
        r = self.go()
        self.assertEqual(r['status'], 'blocked')
        self.assertIsNone(r['orders'])

    def test_account_missing_stale_and_nav_mismatch(self):
        self.assertEqual(evaluate(self.m, None, self.ids, [])['status'], 'blocked')
        self.a['as_of'] = '2026-11-12'
        self.assertEqual(self.go()['status'], 'blocked')
        self.a['as_of'] = '2026-11-13'; self.a['equity'] = 10000
        self.assertEqual(self.go()['status'], 'blocked')

    def test_live_rejects_fixture_account(self):
        self.m['mode'] = 'live'
        self.assertEqual(self.go()['status'], 'blocked')

    def test_no_conid_guessing(self):
        self.ids.pop('BAC')
        self.assertEqual(self.go()['status'], 'blocked')
        self.assertEqual(conids_from_course({'265598': {'name': 'APPLE INC'}}), {})

    def test_schema_exact_no_limit_market(self):
        order = self.go()['orders'][0]
        self.assertEqual(validate([order]), [order])
        for key, val in [('lmt_prc', 'mid'), ('underlying', 'BAC'), ('qty', True), ('strike', 'pct:-3')]:
            modified = dict(order, **{key: val})
            with self.assertRaises(ValueError):
                validate([modified])

    def test_put_fallback_real_observed_strike(self):
        for c in self.m['tickers']['BAC']['contracts']:
            c['delta_date'] = None
        d = self.decision(self.go())
        self.assertEqual(d['candidate']['strike'], 48.5)
        self.assertIn('not 25-delta', d['candidate']['selection_method'])

    def test_call_fallback_two_observed_strikes(self):
        self.stock()
        for c in self.m['tickers']['BAC']['contracts']:
            c['delta'] = None
        self.assertEqual(self.decision(self.go())['candidate']['strike'], 52.)
        self.a['positions'][0]['cost_basis'] = 52
        self.assertFalse(self.decision(self.go())['eligible'])

    def test_earlier_greeks_not_relabelled(self):
        for c in self.m['tickers']['BAC']['contracts']:
            c['delta_date'] = '2026-11-12'
        self.assertIn('Fallback', self.decision(self.go())['candidate']['selection_method'])

    def test_resolved_id_not_reissued(self):
        self.a['resolved_order_ids'] = [self.go()['orders'][0]['id']]
        self.assertEqual(len(self.go()['orders']), 3)

    def test_partial_shares_do_not_open_new_put(self):
        self.a['positions'] = [dict(ticker='BAC', kind='stock', quantity=50, cost_basis=50)]
        self.a['cash'] -= 2500
        self.assertFalse(self.decision(self.go())['eligible'])

    def test_pending_call_not_double_counted(self):
        self.stock()
        r = self.go()
        second = self.go(r['orders'])
        self.assertEqual(second['capital']['exposure'], r['capital']['exposure'])

    def test_closest_actual_expiry_and_dte(self):
        original = self.m['tickers']['BAC']['contracts'][0]
        self.m['tickers']['BAC']['contracts'].append(dict(original, expiry='2026-11-23', ric='TEST-MONDAY'))
        self.assertEqual(self.decision(self.go())['candidate']['expiry'], '2026-11-23')
        self.m['tickers']['BAC']['contracts'] = [dict(original, expiry='2026-11-27')]
        self.assertFalse(self.decision(self.go())['eligible'])

    def test_rank_by_hv_then_ticker(self):
        self.a['cash'] = self.a['equity'] = 20000.
        r = self.go()
        self.assertLessEqual(r['capital']['exposure'], 14000.)
        self.assertGreaterEqual(r['capital']['uncommitted_cash'], 6000.)
        self.assertTrue(any(not d['eligible'] for d in r['decisions']))

    def test_lowest_hv_wins_capital_competition(self):
        self.a['cash'] = self.a['equity'] = 20000.
        values = []
        for t, hv in [('BAC', .3), ('KO', .2), ('PFE', .1), ('F', .4)]:
            value = indicators(self.m['tickers'][t]['history'], self.m['calendar']['as_of'])
            value['hv20'] = hv
            values.append(value)
        with patch('final_project.strategy.indicators', side_effect=values):
            r = self.go()
        self.assertEqual([o['underlying'] for o in r['orders']], [self.ids[t] for t in ('PFE', 'KO', 'BAC')])

    def test_conflicting_pending_and_account_blocks(self):
        previous = self.go()['orders']
        self.stock()
        self.assertEqual(self.go(previous)['status'], 'blocked')

    def test_future_close_rejected(self):
        self.m['tickers']['BAC']['history'].append({'date': '2026-11-16', 'close': 100})
        self.assertEqual(self.go()['status'], 'blocked')

    def test_unknown_terms_and_observation_date_excluded(self):
        for c in self.m['tickers']['BAC']['contracts']:
            c['terms_verified'] = False
        self.assertFalse(self.decision(self.go())['eligible'])

    def test_earnings_filter_not_required_for_call(self):
        self.stock()
        self.m['tickers']['BAC']['earnings'] = {'reliable': False}
        self.assertEqual(self.decision(self.go())['decision'], 'Sell Covered Call')


class DataTests(unittest.TestCase):
    def test_duplicate_date_headers(self):
        df = pd.DataFrame([['BAC.N', '2026-11-13', 50]], columns=['Instrument', 'TR.PriceClose', 'TR.PriceClose'])
        self.assertEqual(normalize_closes(df, 'BAC.N', '2026-11-01', '2026-11-13')[0]['close'], 50.)

    def test_standard_contract_identity(self):
        df = pd.DataFrame([dict(RIC='BACW202604850.U', StrikePrice=48.5, ExpiryDate='2026-11-20',
            CallPutOption='Put', UnderlyingQuoteRIC=['BAC.N'], LotSize=100, Currency='USD',
            ContractType='Standard', ExerciseStyle='A')])
        c, errors = normalize_contracts(df, 'BAC', 'BAC.N', '2026-11-13')
        self.assertEqual(len(c), 1); self.assertFalse(errors)
        df.loc[0, 'LotSize'] = 10
        self.assertEqual(normalize_contracts(df, 'BAC', 'BAC.N', '2026-11-13')[0], [])

    def test_earnings_status_false_means_confirmed(self):
        df = pd.DataFrame([['BAC.N', '2027-01-15', 'RES', False]],
                          columns=['Instrument', 'TR.EventStartDate', 'TR.EventType', 'TR.EventStatus'])
        self.assertTrue(earnings_calendar(df, 'BAC.N', '2026-11-13', '2027-05-01')['reliable'])
        df.iloc[0, 3] = True
        self.assertFalse(earnings_calendar(df, 'BAC.N', '2026-11-13', '2027-05-01')['reliable'])


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        (self.root/'mkt').mkdir()
        for p in ['open_orders.json', 'mkt/open_orders.json']:
            (self.root/p).write_text('[]\n')

    def tearDown(self):
        self.tmp.cleanup()

    def test_identical_files_and_dry_run(self):
        m, a, ids = fixture()
        orders = evaluate(m, a, ids, [])['orders']
        publish_orders(self.root, orders)
        self.assertEqual(read_orders(self.root), orders)
        self.assertEqual((self.root/'open_orders.json').read_bytes(), (self.root/'mkt/open_orders.json').read_bytes())

    def test_api_failure_preserves_prior_files(self):
        m, a, ids = fixture(); orders = evaluate(m, a, ids, [])['orders']
        publish_orders(self.root, orders)
        def failure(*args):
            raise RuntimeError('TEST authentication failed')
        rc = run(self.root, datetime(2026, 11, 16, 3, tzinfo=timezone.utc), provider=failure)
        self.assertEqual(rc, 2)
        self.assertEqual(read_orders(self.root), orders)
        self.assertFalse(json.loads((self.root/'docs/data/strategy_status.json').read_text())['orders_updated'])

    def test_invalid_order_never_published(self):
        with self.assertRaises(ValueError):
            publish_orders(self.root, [{'id': 'invalid'}])
        self.assertEqual(read_orders(self.root), [])

    def test_mirror_mismatch_preserved(self):
        (self.root/'mkt/open_orders.json').write_text('[{"bad": true}]\n')
        before = [(self.root/p).read_bytes() for p in ('open_orders.json', 'mkt/open_orders.json')]
        with patch('final_project.run.fetch_market') as provider:
            rc = run(self.root, datetime(2026, 11, 16, 3, tzinfo=timezone.utc), provider=provider)
        self.assertEqual(rc, 2)
        provider.assert_not_called()
        self.assertEqual(before, [(self.root/p).read_bytes() for p in ('open_orders.json', 'mkt/open_orders.json')])


if __name__ == '__main__':
    unittest.main()
