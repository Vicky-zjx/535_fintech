"""Course proposal assumptions and durable commitments, NEVER a Sanji account.

An unanswered proposal remains a contingent obligation even after its order date
or expiry. Only authoritative resolution IDs release it; no fills are inferred.
"""
from copy import deepcopy
import json
from pathlib import Path
from .sanji_orders import validate
from .strategy_config import ILLUSTRATIVE_CAPITAL

STATE_PATH = 'course/proposal_state.json'
ASSUMPTIONS = dict(starting_cash=ILLUSTRATIVE_CAPITAL, currency='USD',
                   initial_stock_holdings=0, initial_short_options=0, leverage=False)


def initial_account(as_of):
    return dict(schema_version=1, source='COURSE_PROPOSAL', as_of=as_of,
                currency='USD', cash=float(ILLUSTRATIVE_CAPITAL), equity=float(ILLUSTRATIVE_CAPITAL),
                positions=[], resolved_order_ids=[])


def read_state(root):
    path = Path(root)/STATE_PATH
    state = json.loads(path.read_text()) if path.exists() else dict(
        schema_version=1, mode='course_proposal_commitments', assumptions=deepcopy(ASSUMPTIONS),
        authoritative_account_seen=False, unconfirmed_orders=[])
    if (state.get('schema_version') != 1 or state.get('mode') != 'course_proposal_commitments'
            or state.get('assumptions') != ASSUMPTIONS
            or type(state.get('authoritative_account_seen')) is not bool):
        raise ValueError('Invalid course commitment state; never reset it to reclaim capital')
    validate(state['unconfirmed_orders'])
    if any(not o['id'].startswith('fin535-course-') for o in state['unconfirmed_orders']):
        raise ValueError('Course state contains unidentified obligations')
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
    resolved = set(account.get('resolved_order_ids', []))
    known = {o['id']: o for o in state['unconfirmed_orders'] if o['id'] not in resolved}
    for order in orders:
        if order['id'].startswith('fin535-course-'):
            if order['id'] in known and known[order['id']] != order:
                raise ValueError('Cannot change the terms of an issued course proposal')
            known[order['id']] = order
    updated['unconfirmed_orders'] = validate(list(known.values()))
    updated['authoritative_account_seen'] |= not hypothetical
    return updated
