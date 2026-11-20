"""Course proposal assumptions and durable commitments, NEVER a Sanji account.

An unanswered proposal remains a contingent obligation even after its order date
or expiry. Only authoritative resolution IDs release it; no fills are inferred.
"""
from copy import deepcopy
from datetime import date, timedelta
import json
from pathlib import Path
from .sanji_orders import validate
from .strategy_config import ILLUSTRATIVE_CAPITAL

STATE_PATH = 'course/proposal_state.json'
ASSUMPTIONS = dict(starting_cash=ILLUSTRATIVE_CAPITAL, currency='USD',
                   initial_stock_holdings=0, initial_short_options=0, leverage=False)
INITIAL_ACCOUNT_POLICY = {
    'scope': 'course_simulation_only',
    'initial_inventory': {'shares': 0, 'open_puts': 0, 'open_calls': 0},
    'inventory_authority': 'Professor clarification, as supplied by the student',
    'inventory_evidence': 'You start with no positions. Yes, cash only initially.',
    'starting_cash': ILLUSTRATIVE_CAPITAL,
    'currency': 'USD',
    'cash_authority': 'Student-selected and explicitly authorized simulation capital',
    'professor_confirmed_cash_amount': False,
    'official_sanji_balance': False,
    'initial_positions_file_required': False,
    'subsequent_cycles': 'Use authoritative account/position records and order outcomes; never infer fills or assignments',
}


def initial_policy():
    """Evidence about a starting scenario, never a current account statement."""
    return deepcopy(INITIAL_ACCOUNT_POLICY)


def review_initial_proposals(market, conids, pending, state):
    """Read-only initial-cycle check. Never releases a reservation or writes an order.

    Only before the proposal's first target session may a flat-start selection be
    compared with that proposal. Older commitments make a fresh-flat replay invalid.
    """
    from .strategy import evaluate
    from .strategy_config import PER_NAME, TOTAL_EXPOSURE, RESERVE
    target = market['calendar']['target_session']
    if (state['authoritative_account_seen'] or
            any(o['for'] != target or not o['id'].startswith('fin535-course-') for o in pending) or
            any(p['for'] != target for p in state['put_proposal_history'])):
        return {'status': 'not_initial_cycle',
                'reason': 'Earlier proposals or an authoritative book exist; no reset to an empty account',
                'orders_written': False, 'fills_inferred': False}
    result = evaluate(market, initial_account(market['calendar']['as_of']), conids, [], course_proposal=True)
    proposed = result['orders']
    checked = {o['id']: o for o in proposed or []}
    matches = proposed is not None and all(checked.get(o['id']) == o for o in pending)
    return {
        'status': 'validated' if result['status'] == 'success' and matches else 'blocked',
        'scope': 'Initial-cycle selection/collateral audit only; the actual planner still reserves every pending proposal',
        'signal_date': market['calendar']['as_of'], 'target_session': target,
        'market_retrieved_at': market['retrieved_at'],
        'starting_cash': ILLUSTRATIVE_CAPITAL,
        'initial_inventory': deepcopy(INITIAL_ACCOUNT_POLICY['initial_inventory']),
        'proposals': proposed,
        'decisions': [{k: v for k, v in d.items() if k in (
            'ticker', 'decision', 'category', 'technical_status', 'filters', 'close',
            'sma20', 'sma50', 'hv20', 'r5', 'reasons', 'candidate')}
            for d in result['decisions']],
        'capital': result['capital'],
        'existing_proposals_match': matches,
        'collateral_by_proposal': [{'id': o['id'], 'underlying': o['underlying'],
                                  'strike': o['strike'], 'qty': o['qty'],
                                  'collateral': o['strike'] * 100 * o['qty']}
                                 for o in proposed or [] if o['contract'] == 'put'],
        'limits': {'per_ticker': PER_NAME * ILLUSTRATIVE_CAPITAL,
                   'total_exposure': TOTAL_EXPOSURE * ILLUSTRATIVE_CAPITAL,
                   'minimum_reserve': RESERVE * ILLUSTRATIVE_CAPITAL},
        'orders_written': False, 'fills_inferred': False,
    }


def trading_week(session):
    day = date.fromisoformat(session)
    return str(day-timedelta(days=day.weekday()))


def proposal_history(history, orders):
    """Durable proposal evidence, NOT fills. Retained even after resolution."""
    if not isinstance(history, list):
        raise ValueError('Invalid weekly put proposal history')
    known = {}
    for p in history:
        if (not isinstance(p, dict) or set(p) != {'id', 'underlying', 'for', 'week'}
                or not isinstance(p['id'], str) or not p['id']
                or type(p['underlying']) is not int or p['underlying'] <= 0
                or p['week'] != trading_week(p['for'])):
            raise ValueError('Invalid weekly put proposal evidence')
        if p['id'] in known and known[p['id']] != p:
            raise ValueError('Conflicting weekly put proposal evidence')
        known[p['id']] = p
    validate(orders)
    for o in orders:
        if o['contract'] != 'put':
            continue
        p = {k: o[k] for k in ('id', 'underlying', 'for')}
        p['week'] = trading_week(o['for'])
        if p['id'] in known and known[p['id']] != p:
            raise ValueError('Conflicting weekly put proposal evidence')
        known[p['id']] = p
    # Legacy duplicate evidence is retained (and locks the week), not erased.
    return sorted(known.values(), key=lambda p: (p['for'], p['id']))


def initial_account(as_of):
    return dict(schema_version=1, source='COURSE_PROPOSAL', as_of=as_of,
                currency='USD', cash=float(ILLUSTRATIVE_CAPITAL), equity=float(ILLUSTRATIVE_CAPITAL),
                positions=[], resolved_order_ids=[])


def read_state(root):
    path = Path(root)/STATE_PATH
    from .lifecycle import read_history
    history = read_history(root)
    if not path.exists() and history['proposals']:
        raise ValueError('Commitment state missing despite durable history; no initial cash reset')
    state = json.loads(path.read_text()) if path.exists() else dict(
        schema_version=1, mode='course_proposal_commitments', assumptions=deepcopy(ASSUMPTIONS),
        authoritative_account_seen=False, unconfirmed_orders=[])
    if (state.get('schema_version') != 1 or state.get('mode') != 'course_proposal_commitments'
            or state.get('assumptions') != ASSUMPTIONS
            or type(state.get('authoritative_account_seen')) is not bool):
        raise ValueError('Invalid course commitment state; never reset it to reclaim capital')
    validate(state['unconfirmed_orders'])
    if any(not o['id'].startswith(('fin535-course-', 'fin535-wheel-')) for o in state['unconfirmed_orders']):
        raise ValueError('Course state contains unidentified obligations')
    known = {o['id']: o for o in state['unconfirmed_orders']}
    for record in history['proposals']:
        o = record['order']
        if (record['resolution'] is not None or o['id'].startswith('fin535-wheel-')) and not state['authoritative_account_seen']:
            raise ValueError('Authoritative history cannot revert to a hypothetical initial account')
        if record['resolution'] is not None:
            if o['id'] in known:
                raise ValueError('Resolved history conflicts with pending state; reconciliation required')
            continue
        if o['id'] in known and known[o['id']] != o:
            raise ValueError('Durable history conflicts with proposal state')
        known[o['id']] = o
    state['unconfirmed_orders'] = validate(list(known.values()))
    state['put_proposal_history'] = proposal_history(
        proposal_history(state.get('put_proposal_history', []), [r['order'] for r in history['proposals']]),
        state['unconfirmed_orders'])
    return state


def pending_orders(state, queue, *, hypothetical):
    known = {o['id']: o for o in state['unconfirmed_orders']}
    if hypothetical:
        if state['authoritative_account_seen']:
            raise ValueError('Authoritative account disappeared; cannot reset to hypothetical cash')
        if any(known.get(o['id']) != o for o in queue):
            raise ValueError('Existing queue is not reconciled with course commitments; no flat reset allowed')
    for order in queue:
        if order['id'] in known and known[order['id']] != order:
            raise ValueError('Conflicting order content for an existing proposal ID')
        known[order['id']] = order
    return validate(list(known.values()))


def next_state(state, orders, account, *, hypothetical):
    updated = deepcopy(state)
    updated['put_proposal_history'] = proposal_history(
        proposal_history(state.get('put_proposal_history', []), state['unconfirmed_orders']), orders)
    resolved = set(account.get('resolved_order_ids', []))
    known = {o['id']: o for o in state['unconfirmed_orders'] if o['id'] not in resolved}
    for order in orders:
        if order['id'].startswith(('fin535-course-', 'fin535-wheel-')):
            if order['id'] in known and known[order['id']] != order:
                raise ValueError('Cannot change the terms of an issued course proposal')
            known[order['id']] = order
    updated['unconfirmed_orders'] = validate(list(known.values()))
    updated['authoritative_account_seen'] |= not hypothetical
    return updated
