"""Synthetic fixtures only in temp directories; retained real-LSEG integration is labeled."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from .course import initial_account, initial_policy, review_initial_proposals, read_state, next_state, STATE_PATH
from .run import run
from .sanji_orders import read_orders, atomic_json, publish_orders
from .strategy import evaluate
from .strategy_config import VERIFIED_CONIDS
from .test_strategy import fixture

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 16, 3, tzinfo=timezone.utc)


class CourseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        (self.root/'docs/data').mkdir(parents=True); (self.root/'mkt').mkdir()
        for name in ('open_orders.json', 'mkt/open_orders.json'):
            (self.root/name).write_text('[]\n')
        shutil.copyfile(ROOT/'docs/data/conid_verification.json', self.root/'docs/data/conid_verification.json')
        self.market, self.account, _ = fixture()
        # Injected unit-test provider only; never write these synthetic data to the repository.
        self.market.update(mode='live', source='LSEG Data Platform', retrieved_at=NOW.isoformat())

    def tearDown(self):
        self.tmp.cleanup()

    def go(self, **kwargs):
        return run(self.root, NOW, provider=lambda *args: self.market, **kwargs)

    def report(self):
        return json.loads((self.root/'docs/data/strategy_status.json').read_text())

    def test_initial_inventory_and_capital_have_separate_authorities(self):
        policy = initial_policy()
        self.assertEqual(policy['initial_inventory'], {'shares': 0, 'open_puts': 0, 'open_calls': 0})
        self.assertIn('Professor clarification', policy['inventory_authority'])
        self.assertIn('Student-selected', policy['cash_authority'])
        self.assertEqual(policy['starting_cash'], 40000)
        self.assertFalse(policy['professor_confirmed_cash_amount'])
        self.assertFalse(policy['official_sanji_balance'])
        self.assertFalse(policy['initial_positions_file_required'])
        policy['initial_inventory']['shares'] = 100
        self.assertEqual(initial_policy()['initial_inventory']['shares'], 0)

    def test_initial_audit_writes_no_positions_or_fills_and_matches_capital(self):
        self.assertEqual(self.go(), 0)
        s = self.report(); review = s['initial_cycle_review']
        self.assertEqual(s['initial_account_policy'], initial_policy())
        self.assertEqual(review['status'], 'validated')
        self.assertEqual(review['proposals'], read_orders(self.root))
        self.assertEqual(review['capital'], s['capital'])
        self.assertFalse(review['orders_written'])
        self.assertFalse(review['fills_inferred'])
        self.assertTrue(all(o['contract'] == 'put' for o in review['proposals']))
        self.assertFalse((self.root/'mkt/positions.json').exists())
        self.assertFalse((self.root/'mkt/fills.json').exists())

    def test_repeated_initial_replay_preserves_every_commitment_byte(self):
        self.go()
        paths = [self.root/p for p in ('open_orders.json', 'mkt/open_orders.json', STATE_PATH, 'docs/data/market_snapshot.json')]
        before = [p.read_bytes() for p in paths]
        def no_api(*args): raise AssertionError('Replay must not request data')
        self.assertEqual(run(self.root, NOW, provider=no_api, replay=True), 0)
        self.assertEqual([p.read_bytes() for p in paths], before)
        self.assertEqual(self.report()['initial_cycle_review']['status'], 'validated')
        self.assertFalse(self.report()['orders_updated'])
        self.assertEqual(self.report()['capital']['cash'], 40000)

    def test_initial_review_cannot_reset_earlier_cycle_or_authoritative_state(self):
        state = read_state(self.root)
        for change in ({'authoritative_account_seen': True}, {'put_proposal_history': [
                {'id': 'earlier', 'underlying': 8894, 'for': '2026-11-09', 'week': '2026-11-09'}]}):
            review = review_initial_proposals(self.market, VERIFIED_CONIDS, [], dict(state, **change))
            self.assertEqual(review['status'], 'not_initial_cycle')
            self.assertNotIn('proposals', review)
            self.assertFalse(review['fills_inferred'])

    def test_initial_review_rejects_changed_pending_strike_without_releasing_it(self):
        self.go()
        pending = read_orders(self.root); pending[0]['strike'] += 1
        before = deepcopy(pending)
        review = review_initial_proposals(self.market, VERIFIED_CONIDS, pending, read_state(self.root))
        self.assertEqual(review['status'], 'blocked')
        self.assertFalse(review['existing_proposals_match'])
        self.assertEqual(pending, before)

    def test_student_simulation_authority_does_not_create_official_balance(self):
        self.assertEqual(self.go(mode='authoritative'), 2)
        s = self.report()
        self.assertIn('simulation only', s['account_status'])
        self.assertIn('not an official balance', str(s['errors']))
        self.assertIsNone(s['account_assumptions'])
        self.assertEqual(read_orders(self.root), [])

    def test_latest_real_initial_puts_reproduce_when_available_without_inferred_fills(self):
        real = json.loads((ROOT/'docs/data/market_snapshot.json').read_text())
        retained = read_orders(ROOT)
        before = deepcopy(real)
        review = review_initial_proposals(real, VERIFIED_CONIDS, retained, read_state(ROOT))
        if review['status'] != 'validated':
            # Later nightly snapshots may be incomplete or have legitimately changed
            # candidates. Preflight must still permit the next real recovery query.
            self.assertIn(review['status'], ('not_initial_cycle', 'blocked'))
            self.assertFalse(review['orders_written'])
            self.assertFalse(review['fills_inferred'])
            self.assertEqual(real, before)
            return
        self.assertEqual(review['status'], 'validated')
        self.assertTrue(review['existing_proposals_match'])
        self.assertEqual(sum(r['collateral'] for r in review['collateral_by_proposal']), review['capital']['put_collateral'])
        self.assertEqual(review['capital']['cash'], 40000)
        self.assertEqual(review['capital']['uncommitted_cash'], 40000-review['capital']['put_collateral'])
        self.assertEqual(real, before)

    def test_missing_sanji_generates_four_puts_without_fake_positions(self):
        self.assertEqual(self.go(), 0)
        orders = read_orders(self.root)
        self.assertEqual(len(orders), 4)
        self.assertEqual({o['underlying'] for o in orders}, set(VERIFIED_CONIDS.values()))
        self.assertTrue(all(o['id'].startswith('fin535-course-') and o['action']=='SHT' and
                            o['for']=='2026-11-16' and o['expiry']=='2026-11-20' for o in orders))
        self.assertFalse((self.root/'mkt/positions.json').exists())
        self.assertFalse((self.root/'mkt/fills.json').exists())
        s = self.report()
        self.assertEqual(s['account_mode'], 'course_proposal')
        self.assertEqual(s['account_assumptions']['starting_cash'], 40000)
        self.assertEqual(s['evaluated_orders'], orders)
        self.assertTrue(s['orders_updated'])
        self.assertEqual(read_state(self.root)['unconfirmed_orders'], orders)

    def test_second_run_same_session_identical_no_extra_reservations(self):
        self.go(); before = read_orders(self.root); capital = self.report()['capital']
        self.go()
        self.assertEqual(read_orders(self.root), before)
        self.assertEqual(self.report()['capital'], capital)
        self.assertEqual(self.report()['new_order_ids'], [])
        self.assertTrue(self.report()['orders_updated'])
        self.assertFalse(self.report()['order_files_changed'])

    def test_old_unconfirmed_orders_lock_tickers_and_collateral_even_after_expiry(self):
        self.go(); state = read_state(self.root); original = self.report()['capital']
        pending = state['unconfirmed_orders']
        for o in pending:
            o['for']='2026-11-02'; o['expiry']='2026-11-06'
            o['id']=o['id'].replace('2026-11-16','2026-11-02')
        atomic_json(self.root/STATE_PATH, state)
        publish_orders(self.root, [])
        self.assertEqual(self.go(), 0)
        self.assertEqual(read_orders(self.root), [])
        self.assertEqual(self.report()['outcome'], 'awaiting_order_confirmation')
        self.assertEqual(self.report()['capital'], original)
        self.assertEqual(self.report()['past_unconfirmed_proposal_count'], 4)
        self.assertTrue(all('ticker locked' in ' '.join(d['reasons']) for d in self.report()['decisions']))

    def test_pending_missing_from_queue_remains_reserved(self):
        self.go(); publish_orders(self.root, [])
        self.assertEqual(self.go(), 0)
        self.assertEqual(len(read_orders(self.root)), 4)

    def test_untracked_or_modified_queue_blocks_flat_assumption(self):
        self.go(); orders = read_orders(self.root); orders[0]['strike'] += 1
        publish_orders(self.root, orders)
        self.assertEqual(self.go(), 2)
        self.assertEqual(read_orders(self.root), orders)
        self.assertIn('not reconciled', str(self.report()['errors']))

    def test_api_failure_preserves_orders_and_commitments(self):
        self.go()
        paths = [self.root/p for p in ('open_orders.json','mkt/open_orders.json',STATE_PATH)]
        before = [p.read_bytes() for p in paths]
        def failure(*args): raise RuntimeError('TEST API failure')
        self.assertEqual(run(self.root, NOW, provider=failure), 2)
        self.assertEqual([p.read_bytes() for p in paths], before)

    def test_bad_market_preserves_orders(self):
        self.go(); before = read_orders(self.root)
        for data in self.market['tickers'].values():
            data['history'].pop()
        self.assertEqual(self.go(), 2)
        self.assertEqual(read_orders(self.root), before)
        self.assertEqual(self.report()['outcome'], 'missing_inputs')
        self.assertIsNone(self.report()['evaluated_orders'])

    def test_wrong_market_session_rejected(self):
        self.market['calendar']['target_session']='2026-11-17'
        self.assertEqual(self.go(), 2)
        self.assertIn('calendar differs', str(self.report()['errors']))

    def test_nonlive_market_never_published(self):
        self.market['mode']='test'
        self.assertEqual(self.go(), 2)
        self.assertEqual(read_orders(self.root), [])

    def test_valid_no_trade_is_success_and_automatically_writes_empty_queue(self):
        for d in self.market['tickers'].values():
            d['history'][-1]['close'] *= .8
        self.assertEqual(self.go(), 0)
        s=self.report()
        self.assertEqual(s['outcome'], 'no_eligible_trades')
        self.assertTrue(s['orders_updated'])
        self.assertEqual(s['evaluated_orders'], [])

    def test_capital_competition_keeps_all_limits(self):
        # Four separately eligible puts at ~10k collateral each exceed 28k total.
        for i, data in enumerate(self.market['tickers'].values()):
            factor = (100+i)/data['history'][-1]['close']
            for r in data['history']: r['close'] *= factor
            for c in data['contracts']: c['strike'] *= factor
        self.assertEqual(self.go(), 0)
        s=self.report()
        self.assertEqual(len(read_orders(self.root)), 2)
        self.assertLessEqual(s['capital']['exposure'], 28000)
        self.assertGreaterEqual(s['capital']['uncommitted_cash'], 12000)
        self.assertTrue(any('70%' in str(d['reasons']) for d in s['decisions']))

    def test_authoritative_mode_stays_strict(self):
        self.assertEqual(self.go(mode='authoritative'), 2)
        self.assertFalse((self.root/STATE_PATH).exists())
        self.assertIsNone(self.report()['account_assumptions'])

    def test_present_but_invalid_official_file_never_falls_back(self):
        atomic_json(self.root/'mkt/positions.json', {})
        self.assertEqual(self.go(), 2)
        self.assertEqual(self.report()['account_mode'], 'authoritative')
        self.assertEqual(json.loads((self.root/'mkt/positions.json').read_text()), {})

    def test_authoritative_holdings_allow_call_without_strategy_rewrite(self):
        self.account['source']='Sanji'  # Clearly synthetic authoritative-format UNIT fixture.
        self.account['cash'] -= 5000
        self.account['positions']=[dict(ticker='BAC',kind='stock',quantity=100,cost_basis=50)]
        atomic_json(self.root/'mkt/positions.json', self.account)
        before=(self.root/'mkt/positions.json').read_bytes()
        self.assertEqual(self.go(), 0)
        self.assertEqual(next(o for o in read_orders(self.root) if o['underlying']==10098)['contract'], 'call')
        self.assertEqual((self.root/'mkt/positions.json').read_bytes(), before)
        self.assertEqual(self.report()['account_mode'], 'authoritative')

    def test_disappeared_official_account_does_not_reset_cash(self):
        self.account['source']='Sanji'
        atomic_json(self.root/'mkt/positions.json', self.account)
        self.go(); before=read_orders(self.root)
        (self.root/'mkt/positions.json').unlink()  # Unit temp fixture only.
        self.assertEqual(self.go(), 2)
        self.assertEqual(read_orders(self.root), before)
        self.assertIn('disappeared', str(self.report()['errors']))

    def test_unconfirmed_proposals_require_reconciliation_on_authoritative_switch(self):
        self.go(); proposed=read_orders(self.root)
        self.account['source']='Sanji'
        self.account['cash'] -= 5000
        self.account['positions']=[dict(ticker='BAC',kind='stock',quantity=100,cost_basis=50)]
        atomic_json(self.root/'mkt/positions.json', self.account)
        self.assertEqual(self.go(), 2)  # Can't assume prior put wasn't filled.
        self.account['resolved_order_ids']=[o['id'] for o in proposed]
        atomic_json(self.root/'mkt/positions.json', self.account)
        self.assertEqual(self.go(), 0)
        self.assertEqual(read_state(self.root)['unconfirmed_orders'], [])

    def test_course_book_cannot_claim_stocks_or_premium(self):
        a=initial_account('2026-11-13')
        for change in ({'cash':40001}, {'positions':[dict(ticker='BAC',kind='stock',quantity=100,cost_basis=50)]}):
            r=evaluate(self.market,dict(a,**change),VERIFIED_CONIDS,[],course_proposal=True)
            self.assertEqual(r['status'],'blocked')

    def test_explicit_course_opt_in_cannot_leak_into_strict_live_evaluation(self):
        r=evaluate(self.market,initial_account('2026-11-13'),VERIFIED_CONIDS,[])
        self.assertEqual(r['status'],'blocked')

    def test_transaction_failure_restores_exact_bytes_and_state(self):
        self.go()
        paths=[self.root/p for p in (STATE_PATH,'open_orders.json','mkt/open_orders.json')]
        before=[p.read_bytes() for p in paths]
        counter=0
        def fail_third(path, payload):
            nonlocal counter
            counter+=1
            if counter==3: raise OSError('TEST disk failure')
            atomic_json(path,payload)
        with patch('final_project.sanji_orders.atomic_json',side_effect=fail_third):
            self.assertEqual(self.go(), 2)
        self.assertEqual([p.read_bytes() for p in paths],before)
        self.assertFalse(self.report()['orders_updated'])

    def test_retained_real_lseg_week_start_can_generate_two_course_puts(self):
        real=json.loads((ROOT/'docs/data/entry_example_market.json').read_text())
        r=evaluate(real,initial_account(real['calendar']['as_of']),VERIFIED_CONIDS,[],course_proposal=True)
        self.assertEqual(r['status'],'success')
        self.assertEqual([(o['underlying'],o['strike'],o['expiry']) for o in r['orders']],
                         [(8894,96.,'2026-11-20'),(11031,28.,'2026-11-20')])
        self.assertEqual(r['capital']['put_collateral'],12400)
        # Exercise the real writer with these REAL observations, but only in this
        # temp integration directory. Historical proposals never enter today's queue.
        account=initial_account(real['calendar']['as_of'])
        state=next_state(read_state(self.root),r['orders'],account,hypothetical=True)
        publish_orders(self.root,r['orders'],course_state=state)
        self.assertEqual(read_orders(self.root),r['orders'])
        self.assertEqual((self.root/'open_orders.json').read_bytes(),(self.root/'mkt/open_orders.json').read_bytes())
        self.assertEqual(read_state(self.root)['unconfirmed_orders'],r['orders'])
        self.assertFalse((self.root/'mkt/positions.json').exists())
