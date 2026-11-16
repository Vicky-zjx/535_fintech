"""Mode isolation, real-response replay and authoritative identifier regressions."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from .demo import build, examples
from .sanji_orders import publish_orders, validate
from .strategy import evaluate
from .test_strategy import fixture
from .verify_conids import verified_mapping, resolve_identifiers
from .strategy_config import VERIFIED_CONIDS

ROOT = Path(__file__).resolve().parents[1]


class DemoTests(unittest.TestCase):
    def test_static_identifiers_and_course_coverage_are_separate(self):
        evidence = json.loads((ROOT/'docs/data/conid_verification.json').read_text())
        ids, coverage = resolve_identifiers(evidence, {'265598': {'name': 'APPLE INC'}})
        self.assertEqual(ids, VERIFIED_CONIDS)
        self.assertTrue(all(v['course_binding'] == 'unconfirmed' for v in coverage.values()))
        _, coverage = resolve_identifiers(evidence, {str(v): {'symbol': t} for t,v in ids.items()})
        self.assertTrue(all(v['course_binding'] == 'confirmed' for v in coverage.values()))
        for bad in ({}, dict(ids, BAC=1), dict(ids, BAC=True)):
            with self.assertRaises(ValueError):
                resolve_identifiers(evidence, {}, configured=bad)
        for bad in ({'1': {'symbol': 'BAC'}}, {'10098': {'symbol': 'KO'}}, {'10098': {'ric': 'F.N'}}):
            with self.assertRaises(ValueError):
                resolve_identifiers(evidence, bad)

    def test_real_public_identifiers(self):
        evidence = json.loads((ROOT/'docs/data/conid_verification.json').read_text())
        self.assertEqual(verified_mapping(evidence), {'BAC': 10098, 'KO': 8894, 'PFE': 11031, 'F': 9599491})
        bad = deepcopy(evidence)
        bad['records']['BAC']['detail_response']['secdef'][0]['currency'] = 'MXN'
        with self.assertRaisesRegex(ValueError, 'identity mismatch'):
            verified_mapping(bad)

    def test_hypothetical_account_forbidden_in_live_mode(self):
        m, a, ids = fixture()
        m['mode'] = 'live'; a['source'] = 'HYPOTHETICAL_DEMONSTRATION'
        r = evaluate(m, a, ids, [])
        self.assertEqual(r['status'], 'blocked'); self.assertIsNone(r['orders'])

    def test_demo_requires_explicit_hypothetical_source(self):
        m, a, ids = fixture()
        m['mode'] = 'demonstration'
        r = evaluate(m, a, ids, [])
        self.assertEqual(r['status'], 'blocked')

    def test_demo_keeps_all_put_checks_and_idempotence(self):
        # These synthetic prices exist ONLY in unit tests, never on the site.
        m, a, ids = fixture()
        m['mode'] = 'demonstration'; a['source'] = 'HYPOTHETICAL_DEMONSTRATION'
        r = evaluate(m, a, ids, [])
        self.assertEqual(len(r['orders']), 4)
        self.assertTrue(all(o['id'].startswith('fin535-demo-') for o in r['orders']))
        repeated = evaluate(m, a, ids, r['orders'])
        self.assertEqual(repeated['orders'], r['orders'])
        m['tickers']['BAC']['history'][-1]['close'] = 45
        r = evaluate(m, a, ids, [])
        self.assertNotIn(ids['BAC'], [o['underlying'] for o in r['orders']])
        self.assertIn('trend filter failed', str(r['decisions']))

    def test_demo_does_not_bypass_capital(self):
        m, a, ids = fixture()
        m['mode'] = 'demonstration'; a['source'] = 'HYPOTHETICAL_DEMONSTRATION'
        a['cash'] = a['equity'] = 1000.
        r = evaluate(m, a, ids, [])
        self.assertEqual(r['orders'], [])
        self.assertIn('30% of equity', str(r['decisions']))

    def test_publisher_refuses_demo_orders(self):
        m, a, ids = fixture()
        m['mode'] = 'demonstration'; a['source'] = 'HYPOTHETICAL_DEMONSTRATION'
        orders = evaluate(m, a, ids, [])['orders']
        with self.assertRaisesRegex(ValueError, 'production queue'):
            publish_orders('/unused', orders)

    def test_real_snapshot_replay_never_changes_production(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root/'docs/data').mkdir(parents=True); (root/'mkt').mkdir()
            # Noncanonical whitespace proves byte preservation rather than rewriting [].
            for p in ('open_orders.json', 'mkt/open_orders.json'):
                (root/p).write_bytes(b'[  ]\n')
            for p in ('market_snapshot.json', 'conid_verification.json'):
                shutil.copyfile(ROOT/'docs/data'/p, root/'docs/data'/p)
            result = build(root, datetime.now(timezone.utc))
            for p in ('open_orders.json', 'mkt/open_orders.json'):
                self.assertEqual((root/p).read_bytes(), b'[  ]\n')
            for s in result['scenarios']:
                if s['account'] is not None:
                    self.assertEqual(s['account']['equity'], 40000.)
                    self.assertEqual(s['account']['source'], 'HYPOTHETICAL_DEMONSTRATION')
                else:
                    self.assertEqual(s['status'], 'blocked')
                    self.assertIsNone(s['proposed_orders'])
                if s['proposed_orders'] is not None:
                    validate(s['proposed_orders'])
            if result['market_retrieved_at'] == '2026-11-16T07:21:13.214133+00:00':
                flat, held = result['scenarios']
                self.assertEqual([(o['underlying'], o['strike']) for o in flat['proposed_orders']],
                                 [(8894, 96.), (11031, 28.)])
                self.assertEqual(flat['capital']['put_collateral'], 12400.)
                self.assertEqual(flat['capital']['uncommitted_cash'], 27600.)
                self.assertEqual(held['order_count'], 3)
            self.assertNotIn('earnings', json.dumps(result['scenarios']))
            market = json.loads((root/'docs/data/market_snapshot.json').read_text())
            market['mode'] = 'test'
            (root/'docs/data/market_snapshot.json').write_text(json.dumps(market))
            with self.assertRaisesRegex(ValueError, 'real LSEG response'):
                build(root, datetime.now(timezone.utc))

    def test_example_books_reconcile_without_claiming_fills(self):
        m, _, _ = fixture()
        cases = examples(m)
        for _, _, account in cases:
            marked = sum(p['quantity']*p['cost_basis'] for p in account['positions'])
            self.assertEqual(account['cash'] + marked, account['equity'])
            self.assertEqual(account['resolved_order_ids'], [])

    def test_missing_price_does_not_crash_demo_or_fabricate_stock_account(self):
        m, _, ids = fixture()
        m['tickers']['BAC']['history'][-1]['close'] = None
        flat, held = examples(m)
        self.assertEqual(flat[2]['cash'], 40000.)
        self.assertIsNone(held[2])
        self.assertIn('close is missing/stale', held[1])
        m['mode'] = 'demonstration'
        result = evaluate(m, flat[2], ids, [])
        self.assertEqual(result['status'], 'success')
        self.assertEqual(len(result['orders']), 3)
        result = evaluate(m, held[2], ids, [])
        self.assertEqual(result['status'], 'blocked')
        self.assertIsNone(result['orders'])
