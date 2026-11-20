"""Durable proposal history and read-only lifecycle/conditional-preview reporting.

Elapsed time is NOT an execution outcome. Publicly issued course orders are not
certified sandbox-only: no automatic cancellation, expiry release or cash reset.
"""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path

from .sanji_orders import atomic_json, read_orders, validate

HISTORY_PATH = 'course/proposal_history.json'
REPORT_PATH = 'docs/data/order_lifecycle.json'


def read_history(root):
    path = Path(root)/HISTORY_PATH
    history = json.loads(path.read_text()) if path.exists() else {
        'schema_version': 1, 'kind': 'proposal_history_not_fills', 'proposals': []}
    if (history.get('schema_version') != 1 or history.get('kind') != 'proposal_history_not_fills'
            or not isinstance(history.get('proposals'), list)):
        raise ValueError('Invalid durable proposal history; never discard it')
    validate([r['order'] for r in history['proposals']])
    for r in history['proposals']:
        if set(r) != {'order', 'resolution'}:
            raise ValueError('Invalid proposal history fields')
        resolution = r['resolution']
        if resolution is not None and (set(resolution) != {'status', 'account_as_of', 'source'}
                or resolution['status'] != 'resolved_unspecified' or resolution['source'] != 'Sanji'):
            raise ValueError('Unsupported resolution evidence; do not infer a fill or cancellation')
        if resolution is not None and str(date.fromisoformat(resolution['account_as_of'])) != resolution['account_as_of']:
            raise ValueError('Noncanonical resolution date')
    return history


def advance_history(history, proposals, account=None):
    """Called after account validation for resolutions. Preserve full immutable terms."""
    updated = deepcopy(history)
    known = {r['order']['id']: r for r in updated['proposals']}
    for order in proposals:
        validate([order])
        if order['id'] in known and known[order['id']]['order'] != order:
            raise ValueError('Proposal history terms conflict with an issued ID')
        known.setdefault(order['id'], {'order': deepcopy(order), 'resolution': None})
    if account and account.get('source') == 'Sanji':
        for oid in account.get('resolved_order_ids', []):
            if oid in known and known[oid]['resolution'] is None:
                # An ID alone does not say filled, cancelled, rejected or unfilled.
                known[oid]['resolution'] = {'status': 'resolved_unspecified',
                    'account_as_of': account['as_of'], 'source': 'Sanji'}
    updated['proposals'] = sorted(known.values(), key=lambda r: (r['order']['for'], r['order']['id']))
    return updated


def project(history, status, orders):
    from .data_provider import digest
    from .strategy_config import VERIFIED_CONIDS
    target = (status.get('calendar') or {}).get('target_session')
    as_of = (status.get('calendar') or {}).get('as_of')
    current = {o['id']: o for o in orders}
    rows = []
    for record in history['proposals']:
        o, resolution = record['order'], record['resolution']
        past = bool(as_of and o['for'] <= as_of)
        state = ('authoritative_resolution_unspecified' if resolution else
                 'previous_unconfirmed' if past else 'current_proposed'
                 if o['for'] == target and current.get(o['id']) == o else 'unconfirmed')
        rows.append({'order': o, 'ticker': next((t for t, c in VERIFIED_CONIDS.items() if c == o['underlying']), 'Unmapped'),
                     'status': state, 'execution_status': 'unknown' if resolution is None else 'resolved_outcome_unspecified',
                     'resolution': resolution,
                     'option_expiry_passed': bool(as_of and o['expiry'] < as_of),
                     'reserved_put_collateral': o['strike']*100*o['qty'] if resolution is None and o['contract'] == 'put' else 0,
                     'ticker_locked': resolution is None})
    return {'schema_version': 1, 'scope': 'proposal_lifecycle_not_execution_history',
            'as_of': as_of, 'target_session': target,
            'evaluation_attempted_at': status.get('attempted_at'),
            'market_retrieved_at': status.get('market_data_retrieved_at'),
            'history_sha256': digest(history), 'orders_sha256': digest(orders),
            'status_sha256': digest(status), 'records': rows,
            'automatic_release_enabled': False,
            'non_execution_verified': False,
            'policy': 'Published course proposals may be read by Sanji. No verified never-transmitted guarantee exists; passing the order date or option expiry does not release a reservation. Explicit reconciled outcomes are required. Isolated previews never write orders or release actual commitments.',
            'outcome_evidence': 'No native fills/cancellation schema is assumed. A validated Sanji book may resolve an ID, but without a typed outcome its history remains resolved — outcome unspecified, never labelled filled, cancelled, rejected or expired unexecuted.'}


def conditional_preview(root, status, state):
    """A counterfactual branch, NOT the ongoing book or a new flat-start reset.

    Retain actual weekly proposal history even in this branch. Never forecast new
    prices, shift the market date, credit premium, or output executable tickets.
    """
    from .course import initial_account
    from .data_provider import digest
    from .strategy import evaluate
    base = {'scope': 'conditional_no_execution_scenario', 'execution_eligible': False,
            'orders_written': False, 'reservations_released': False,
            'assumption': 'Only IF all unresolved proposals were confirmed never executed and no other account activity occurred. This is not established fact or a reset of the ongoing account.',
            'weekly_cap_preserved': True}
    if (status.get('account_mode') != 'course_proposal' or status.get('status') != 'success'
            or state['authoritative_account_seen'] or (Path(root)/'mkt/positions.json').exists()):
        return dict(base, status='unavailable', reason='Requires a successful course-only evaluation; no authoritative book is replaced')
    market = json.loads((Path(root)/'docs/data/market_snapshot.json').read_text())
    if (market.get('mode') != 'live' or market.get('source') != 'LSEG Data Platform'
            or digest(market) != status.get('market_snapshot_sha256')):
        return dict(base, status='unavailable', reason='Real market provenance does not match the evaluated snapshot')
    demo_market = dict(market, mode='demonstration')
    account = initial_account(market['calendar']['as_of'])
    account['source'] = 'HYPOTHETICAL_DEMONSTRATION'
    result = evaluate(demo_market, account, status['conid_status'], [], put_history=state['put_proposal_history'])
    inverse = {v: t for t, v in status['conid_status'].items()}
    return dict(base, status=result['status'], calendar=market['calendar'],
                market_retrieved_at=market['retrieved_at'], market_snapshot_sha256=digest(market),
                capital=result['capital'],
                decisions=[{k: d[k] for k in ('ticker', 'technical_status', 'category', 'reasons')} for d in result['decisions']],
                # Deliberately NOT a Sanji order array; no ID/action/ref/order_type.
                candidates=[{'ticker': inverse[o['underlying']], 'strike': o['strike'],
                             'expiry': o['expiry'], 'contract': o['contract'], 'qty': o['qty']}
                            for o in result['orders'] or []])


def build(root):
    from .course import read_state
    root = Path(root)
    state = read_state(root)
    orders = read_orders(root)
    status = json.loads((root/'docs/data/strategy_status.json').read_text())
    history = advance_history(read_history(root), state['unconfirmed_orders'] + orders)
    report = project(history, status, orders)
    report['conditional_preview'] = conditional_preview(root, status, state)
    atomic_json(root/HISTORY_PATH, history)
    atomic_json(root/REPORT_PATH, report)
    return report


if __name__ == '__main__':
    report = build(Path(__file__).resolve().parents[1])
    print(json.dumps({'proposal_history_count': len(report['records']),
                      'automatic_release_enabled': report['automatic_release_enabled'],
                      'preview_status': report['conditional_preview']['status']}))
