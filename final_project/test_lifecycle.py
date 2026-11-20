"""Isolated temporary fixtures, never market data or execution claims."""
from copy import deepcopy
import json
from unittest import TestCase
from unittest.mock import patch

from .course import read_state, next_state, initial_account, STATE_PATH
from .lifecycle import read_history, advance_history, build, HISTORY_PATH, REPORT_PATH
from .sanji_orders import read_orders, publish_orders, atomic_json
from .strategy import evaluate
from .strategy_config import VERIFIED_CONIDS
from . import test_course


class LifecycleTests(TestCase):
    setUp = test_course.CourseTests.setUp
    tearDown = test_course.CourseTests.tearDown
    go = test_course.CourseTests.go
    report = test_course.CourseTests.report

    def seed(self, session='2026-11-02', expiry='2026-11-06', authoritative=False):
        result = evaluate(self.market, initial_account(self.market['calendar']['as_of']), VERIFIED_CONIDS, [], course_proposal=True)
        orders = deepcopy(result['orders'])
        for o in orders:
            o['id'] = o['id'].replace(o['for'], session)
            o['for'], o['expiry'] = session, expiry
            if authoritative:
                o['id'] = o['id'].replace('fin535-course-', 'fin535-wheel-')
        account = initial_account(self.market['calendar']['as_of'])
        if authoritative:
            account['source'] = 'Sanji'
            atomic_json(self.root/'mkt/positions.json', account)
        state = next_state(read_state(self.root), orders, account, hypothetical=not authoritative)
        history = advance_history(read_history(self.root), orders)
        publish_orders(self.root, orders, course_state=state, proposal_history=history)
        return orders

    def test_repeated_run_and_report_are_idempotent(self):
        self.assertEqual(self.go(), 0)
        first = read_history(self.root)
        one = build(self.root)
        self.assertEqual(self.go(), 0)
        self.assertEqual(first, read_history(self.root))
        two = build(self.root)
        self.assertEqual(one['records'], two['records'])
        self.assertEqual(one['conditional_preview'], two['conditional_preview'])
        self.assertEqual(two, build(self.root))
        self.assertEqual(len(one['records']), 4)
        self.assertTrue(all(r['status'] == 'current_proposed' for r in one['records']))

    def test_past_session_and_option_expiry_do_not_resolve_any_order(self):
        old = self.seed()
        self.assertEqual(self.go(), 0)
        self.assertEqual(read_orders(self.root), [])
        report = build(self.root)
        self.assertEqual([r['order'] for r in read_history(self.root)['proposals']], sorted(old, key=lambda o:o['id']))
        for r in report['records']:
            self.assertEqual(r['status'], 'previous_unconfirmed')
            self.assertTrue(r['option_expiry_passed'])
            self.assertTrue(r['ticker_locked'])
            self.assertEqual(r['execution_status'], 'unknown')
        self.assertEqual(sum(r['reserved_put_collateral'] for r in report['records']), self.report()['capital']['put_collateral'])
        self.assertFalse(report['automatic_release_enabled'])

    def test_authoritative_pending_date_does_not_silently_release(self):
        old = self.seed(authoritative=True)
        self.assertEqual(self.go(mode='authoritative'), 0)
        self.assertEqual(read_orders(self.root), [])
        self.assertEqual(read_state(self.root)['unconfirmed_orders'], old)
        self.assertGreater(self.report()['capital']['put_collateral'], 0)
        self.assertTrue(all(d['category']=='Already proposed' for d in self.report()['decisions']))
        self.assertEqual(build(self.root)['conditional_preview']['status'], 'unavailable')

    def test_explicit_resolution_retains_terms_without_inventing_outcome(self):
        old = self.seed()
        account = initial_account(self.market['calendar']['as_of'])
        account.update(source='Sanji', resolved_order_ids=[o['id'] for o in old])
        atomic_json(self.root/'mkt/positions.json', account)
        self.assertEqual(self.go(), 0)
        rows = [r for r in build(self.root)['records'] if r['order']['id'] in account['resolved_order_ids']]
        self.assertEqual(len(rows), 4)
        for r in rows:
            self.assertEqual(r['status'], 'authoritative_resolution_unspecified')
            self.assertFalse(r['ticker_locked'])
            self.assertEqual(r['reserved_put_collateral'], 0)
            self.assertEqual(r['order'], next(o for o in old if o['id']==r['order']['id']))

    def test_invalid_account_cannot_resolve_history(self):
        old = self.seed()
        account = initial_account(self.market['calendar']['as_of'])
        account.update(source='Sanji', equity=1, resolved_order_ids=[o['id'] for o in old])
        atomic_json(self.root/'mkt/positions.json', account)
        before = (self.root/HISTORY_PATH).read_bytes()
        self.assertEqual(self.go(), 2)
        build(self.root)
        self.assertEqual((self.root/HISTORY_PATH).read_bytes(), before)

    def test_conditional_preview_can_evaluate_later_week_without_releasing_commitments(self):
        self.seed()
        self.assertEqual(self.go(), 0)
        paths = [self.root/p for p in (STATE_PATH, HISTORY_PATH, 'open_orders.json', 'mkt/open_orders.json')]
        before = [p.read_bytes() for p in paths]
        preview = build(self.root)['conditional_preview']
        self.assertEqual(len(preview['candidates']), 4)
        self.assertFalse(preview['execution_eligible'])
        self.assertFalse(preview['orders_written'])
        self.assertFalse(preview['reservations_released'])
        self.assertTrue(all('id' not in c and 'action' not in c for c in preview['candidates']))
        self.assertEqual(before, [p.read_bytes() for p in paths])
        self.assertGreater(self.report()['capital']['put_collateral'], 0)

    def test_preview_keeps_same_week_lock(self):
        self.assertEqual(self.go(), 0)
        preview = build(self.root)['conditional_preview']
        self.assertEqual(preview['candidates'], [])
        self.assertTrue(all('trading week' in ' '.join(d['reasons']) for d in preview['decisions']))

    def test_report_build_cannot_change_issued_terms(self):
        self.go()
        state = read_state(self.root)
        state['unconfirmed_orders'][0]['strike'] += 1
        atomic_json(self.root/STATE_PATH, state)
        with self.assertRaisesRegex(ValueError, 'history conflicts'):
            build(self.root)

    def test_missing_commitment_state_does_not_reset_account(self):
        self.go()
        (self.root/STATE_PATH).unlink()  # Temp fixture, not a real account.
        with self.assertRaisesRegex(ValueError, 'no initial cash reset'):
            read_state(self.root)

    def test_empty_history_after_blocked_first_attempt_does_not_block_initial_course_cycle(self):
        self.assertEqual(self.go(mode='authoritative'), 2)
        build(self.root)
        self.assertEqual(read_history(self.root)['proposals'], [])
        self.assertEqual(self.go(), 0)
        self.assertEqual(len(read_orders(self.root)), 4)

    def test_full_history_recovers_weekly_proposal_evidence(self):
        self.go()
        state = read_state(self.root)
        expected = deepcopy(state['put_proposal_history'])
        state['put_proposal_history'] = []
        atomic_json(self.root/STATE_PATH, state)
        self.assertEqual(read_state(self.root)['put_proposal_history'], expected)

    def test_authoritative_history_cannot_revert_to_course_cash(self):
        self.seed(authoritative=True)
        state = read_state(self.root)
        state['authoritative_account_seen'] = False
        atomic_json(self.root/STATE_PATH, state)
        with self.assertRaisesRegex(ValueError, 'cannot revert'):
            read_state(self.root)

    def test_preview_failure_or_mismatched_market_is_not_silently_replaced(self):
        self.go()
        m = deepcopy(self.market); m['retrieved_at'] = 'changed'
        atomic_json(self.root/'docs/data/market_snapshot.json', m)
        preview = build(self.root)['conditional_preview']
        self.assertEqual(preview['status'], 'unavailable')
        self.assertNotIn('candidates', preview)

    def test_history_rollback_on_order_write_failure(self):
        self.go()
        paths = [self.root/p for p in (STATE_PATH, HISTORY_PATH, 'open_orders.json', 'mkt/open_orders.json')]
        before = [p.read_bytes() for p in paths]
        def fail(path, payload):
            if path == self.root/'mkt/open_orders.json':
                raise OSError('TEST mirror failure')
            atomic_json(path, payload)
        with patch('final_project.sanji_orders.atomic_json', side_effect=fail):
            self.assertEqual(self.go(), 2)
        self.assertEqual(before, [p.read_bytes() for p in paths])
