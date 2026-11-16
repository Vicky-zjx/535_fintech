"""Offline fixtures are NOT market data or published results."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch
from .calendar import context, required_sessions
from .data_provider import conids_from_course, normalize_closes, normalize_contracts, fetch_market, named
from .portfolio import validate_account
from .run import run
from .sanji_orders import validate, publish_orders, read_orders
from .strategy import indicators, evaluate, select_contract
from .strategy_config import VERIFIED_CONIDS
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
            options_status='observed')
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

    def test_earnings_absent_unknown_or_upcoming_never_affects_puts(self):
        baseline = self.go()  # No calendar field is required.
        self.assertEqual(len(baseline['orders']), 4)
        for legacy in (None, {}, {'reliable': False},
                       {'reliable': True, 'known_on': '2026-11-13',
                        'through': '2027-01-01', 'dates': ['2026-11-16', '2026-11-20']},
                       {'dates': 'invalid legacy value'}):
            with self.subTest(legacy=legacy):
                self.m['tickers']['BAC']['earnings'] = legacy
                self.assertEqual(self.go(), baseline)

    def test_existing_put_blocks_duplicate(self):
        self.a['positions'] = [dict(ticker='BAC', kind='put', quantity=-1, multiplier=100,
            terms_status='standard_verified', strike=48.5, expiry='2026-11-20', mark=1.)]
        self.a['equity'] -= 100
        self.assertIn('Existing short option', ' '.join(self.decision(self.go())['reasons']))

    def test_stock_transitions_to_call_without_put_filters(self):
        self.stock()
        self.m['calendar']['first_session_of_week'] = False
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

    def test_no_silent_expiry_change_when_nearest_has_no_valid_strike(self):
        original = self.m['tickers']['BAC']['contracts'][0]
        self.m['tickers']['BAC']['contracts'].append(dict(original, expiry='2026-11-23', strike=80, ric='TEST-ITM'))
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

    def test_legacy_earnings_does_not_affect_calls(self):
        self.stock()
        baseline = self.go()
        self.m['tickers']['BAC']['earnings'] = {'reliable': False}
        self.assertEqual(self.go(), baseline)
        self.assertEqual(self.decision(baseline)['decision'], 'Sell Covered Call')


class DataTests(unittest.TestCase):
    def test_observed_display_name_header_despite_header_type_name(self):
        df = pd.DataFrame([['BAC.N', 'BAC']], columns=['Instrument', 'Ticker Symbol'])
        self.assertEqual(named(df, ['TR.TickerSymbol']).iloc[0]['TR.TickerSymbol'], 'BAC')

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

    def test_consolidated_underlying_must_match_verified_lookup(self):
        df = pd.DataFrame([dict(RIC='BACW202604850.U', StrikePrice=48.5, ExpiryDate='2026-11-20',
            CallPutOption='Put', UnderlyingQuoteRIC=['BAC'], LotSize=100, Currency='USD',
            ContractType='Standard', ExerciseStyle='A')])
        self.assertEqual(len(normalize_contracts(df, 'BAC', 'BAC', '2026-11-13')[0]), 1)
        self.assertEqual(normalize_contracts(df, 'BAC', 'BAC.N', '2026-11-13')[0], [])

    def test_provider_only_requests_identity_prices_contracts_and_deltas(self):
        market, _, _ = fixture()
        def get_data(universe, fields, **kwargs):
            ric = universe[0]; ticker = ric.split('.')[0]
            if fields == ['TR.TickerSymbol']:
                return pd.DataFrame([[ric, ticker]], columns=['Instrument']+fields)
            if fields == ['TR.PriceClose.date', 'TR.PriceClose']:
                return pd.DataFrame([[ric, r['date'], r['close']] for r in market['tickers'][ticker]['history']],
                                    columns=['Instrument']+fields)
            raise AssertionError('Unexpected API fields: '+str(fields))
        def search(**kwargs):
            ticker = kwargs['filter'].split("'")[1]
            return pd.DataFrame([dict(RIC=f'{ticker}W202604850.U', StrikePrice=48.5,
                ExpiryDate='2026-11-20', CallPutOption='Put', UnderlyingQuoteRIC=[ticker],
                LotSize=100, Currency='USD', ContractType='Standard', ExerciseStyle='A')])
        ld = SimpleNamespace(get_data=Mock(side_effect=get_data), get_history=Mock(return_value=pd.DataFrame()),
            HeaderType=SimpleNamespace(NAME='NAME'), discovery=SimpleNamespace(
                Views=SimpleNamespace(EQUITY_DERIVATIVE_QUOTES='options'), search=Mock(side_effect=search)))
        with patch('final_project.data_provider.query_lseg', side_effect=lambda *a, operation: operation(ld)), \
             patch('final_project.data_provider.time.sleep'):
            result = fetch_market(market['calendar'], '2026-11-16T03:00:00+00:00')
        self.assertEqual(ld.get_data.call_count, 12)  # Two identity checks + closes per ticker.
        self.assertEqual(ld.discovery.search.call_count, 4)
        self.assertEqual(ld.get_history.call_count, 4)
        for call in ld.get_data.call_args_list:
            self.assertIn(call.args[1], (['TR.TickerSymbol'], ['TR.PriceClose.date', 'TR.PriceClose']))
            self.assertNotIn('EventType', call.kwargs.get('parameters', {}))
            if call.args[1] == ['TR.PriceClose.date', 'TR.PriceClose']:
                from .historical import history_window
                self.assertEqual(call.kwargs['parameters']['SDate'], history_window(market['calendar']['as_of'])['query_start'])
                self.assertLess(call.kwargs['parameters']['SDate'], '2023-11-13')
        for call in ld.get_history.call_args_list:
            self.assertEqual(call.kwargs['fields'], ['DELTA_EXCH'])
        for t, d in result['tickers'].items():
            self.assertTrue(d['identity_verified']); self.assertEqual(d['options_status'], 'observed')
            self.assertEqual(d['errors'], [])
            self.assertNotIn('earnings', d); self.assertNotIn('earnings', result['raw'][t])

    def test_latest_close_recheck_requires_actual_date_not_requested_date(self):
        for stale in (False, True):
            market, _, _ = fixture(); as_of=market['calendar']['as_of']
            def get_data(universe, fields, **kwargs):
                ric=universe[0]; ticker=ric.split('.')[0]
                if fields == ['TR.TickerSymbol']:
                    return pd.DataFrame([[ric,ticker]],columns=['Instrument']+fields)
                history=market['tickers'][ticker]['history']
                if kwargs['parameters']['SDate'] == as_of:
                    rows=history[-2:-1] if stale else history[-1:]
                else:
                    rows=history[:-1]
                return pd.DataFrame([[ric,r['date'],r['close']] for r in rows],columns=['Instrument']+fields)
            ld=SimpleNamespace(get_data=Mock(side_effect=get_data),HeaderType=SimpleNamespace(NAME='NAME'),
                discovery=SimpleNamespace(Views=SimpleNamespace(EQUITY_DERIVATIVE_QUOTES='options'),search=Mock(return_value=pd.DataFrame())))
            with patch('final_project.data_provider.query_lseg',side_effect=lambda *a,operation:operation(ld)),patch('final_project.data_provider.time.sleep'):
                result=fetch_market(market['calendar'],'2026-11-16T03:00:00+00:00')
            for ticker,data in result['tickers'].items():
                self.assertEqual(any(r['date']==as_of for r in data['history']),not stale)
                self.assertIn('close_recheck',result['raw'][ticker])
                self.assertIn('older dated prices not substituted' if stale else 'Verified same-day',data['close_recheck_status'])


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        (self.root/'mkt').mkdir()
        (self.root/'docs/data').mkdir(parents=True)
        (self.root/'docs/data/conid_verification.json').write_bytes(
            (Path(__file__).resolve().parents[1]/'docs/data/conid_verification.json').read_bytes())
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

    def test_replay_preserves_snapshot_and_orders_even_with_valid_account(self):
        m, a, ids = fixture()
        ids = VERIFIED_CONIDS
        m.update(mode='live', source='LSEG Data Platform', retrieved_at='2026-11-16T03:00:00+00:00')
        a['source'] = 'Sanji'  # Unit-test-only adapter fixture, not a real account.
        data = self.root/'docs/data'
        snapshot = json.dumps(m).encode()
        (data/'market_snapshot.json').write_bytes(snapshot)
        (self.root/'mkt/positions.json').write_text(json.dumps(a))
        (self.root/'price_history.json').write_text(json.dumps({str(v): {'ticker': t} for t, v in ids.items()}))
        provider = Mock(side_effect=AssertionError('Replay must not query an API'))
        with patch('final_project.run.publish_orders') as publisher:
            # Even an intraday audit must retain its historical signal/target dates, not issue stale orders.
            rc = run(self.root, datetime(2026, 11, 16, 16, tzinfo=timezone.utc), provider=provider, replay=True)
        provider.assert_not_called(); publisher.assert_not_called()
        self.assertEqual(rc, 0); self.assertEqual(read_orders(self.root), [])
        self.assertEqual((data/'market_snapshot.json').read_bytes(), snapshot)
        s = json.loads((data/'strategy_status.json').read_text())
        self.assertEqual(s['evaluation_kind'], 'retained_market_replay')
        self.assertEqual(s['proposed_order_count'], 4)
        self.assertFalse(s['orders_updated'])
        self.assertEqual(s['market_data_retrieved_at'], m['retrieved_at'])
        self.assertEqual(s['calendar'], m['calendar'])
        self.assertNotIn('earnings', json.dumps(s).replace('no-earnings-filter-v1', ''))

    def test_fresh_run_still_publishes_validated_production_orders(self):
        m, a, ids = fixture()
        ids = VERIFIED_CONIDS
        m.update(mode='live', source='LSEG Data Platform', retrieved_at='2026-11-16T03:00:00+00:00')
        a['source'] = 'Sanji'
        (self.root/'mkt/positions.json').write_text(json.dumps(a))
        (self.root/'price_history.json').write_text(json.dumps({str(v): {'ticker': t} for t, v in ids.items()}))
        rc = run(self.root, datetime(2026, 11, 16, 3, tzinfo=timezone.utc), provider=lambda *args: m)
        self.assertEqual(rc, 0); self.assertEqual(len(read_orders(self.root)), 4)
        s = json.loads((self.root/'docs/data/strategy_status.json').read_text())
        self.assertTrue(s['orders_updated']); self.assertEqual(s['evaluation_kind'], 'fresh_api')

    def test_mirror_mismatch_preserved(self):
        (self.root/'mkt/open_orders.json').write_text('[{"bad": true}]\n')
        before = [(self.root/p).read_bytes() for p in ('open_orders.json', 'mkt/open_orders.json')]
        with patch('final_project.run.fetch_market') as provider:
            rc = run(self.root, datetime(2026, 11, 16, 3, tzinfo=timezone.utc), provider=provider)
        self.assertEqual(rc, 2)
        provider.assert_not_called()
        self.assertEqual(before, [(self.root/p).read_bytes() for p in ('open_orders.json', 'mkt/open_orders.json')])

    def test_verified_static_ids_generate_without_claiming_course_coverage(self):
        # Synthetic test account ONLY, confined to a temporary directory.
        m, a, _ = fixture()
        m.update(mode='live', source='LSEG Data Platform', retrieved_at='2026-11-16T03:00:00+00:00')
        a['source'] = 'Sanji'
        (self.root/'mkt/positions.json').write_text(json.dumps(a))
        (self.root/'price_history.json').write_text('{}')
        rc = run(self.root, datetime(2026, 11, 16, 3, tzinfo=timezone.utc), provider=lambda *args: m)
        self.assertEqual(rc, 0)
        self.assertEqual({o['underlying'] for o in read_orders(self.root)}, set(VERIFIED_CONIDS.values()))
        s = json.loads((self.root/'docs/data/strategy_status.json').read_text())
        self.assertTrue(s['orders_updated'])
        self.assertEqual(set(s['pipeline_audit']['course_coverage_unconfirmed']), set(VERIFIED_CONIDS))

    def test_real_market_without_account_preserves_production_bytes(self):
        m, _, _ = fixture()
        m.update(mode='live', source='LSEG Data Platform', retrieved_at='2026-11-16T03:00:00+00:00')
        paths = [self.root/p for p in ('open_orders.json', 'mkt/open_orders.json')]
        before = [p.read_bytes() for p in paths]
        self.assertEqual(run(self.root, datetime(2026, 11, 16, 3, tzinfo=timezone.utc), provider=lambda *args:m), 2)
        self.assertEqual(before, [p.read_bytes() for p in paths])
        s = json.loads((self.root/'docs/data/strategy_status.json').read_text())
        self.assertIn('Authoritative Sanji account unavailable', str(s['errors']))
        self.assertFalse(s['orders_updated'])


if __name__ == '__main__':
    unittest.main()
