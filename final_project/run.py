"""Nightly coordinator. Failure updates diagnostics, NEVER replaces order files."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from .calendar import context
from .data_provider import fetch_market, conids_from_course, digest
from .sanji_orders import atomic_json, read_orders, publish_orders
from .strategy import evaluate
from .strategy_config import UNIVERSE, STRATEGY_REVISION
from .verify_conids import resolve_identifiers
from .course import initial_account, read_state, pending_orders, next_state, ASSUMPTIONS
from lseg_chart.update import safe_failure_detail


def run(root, now, provider=fetch_market, *, replay=False, mode='course'):
    root = Path(root)
    stamp = now.isoformat()
    report = {'schema_version': 1, 'mode': 'live', 'status': 'blocked', 'attempted_at': stamp,
              'successful_at': None, 'market_data_retrieved_at': None,
              'source': 'LSEG Data Platform', 'orders_updated': False, 'errors': [],
              'decisions': [], 'capital': None, 'calendar': None,
              'strategy_revision': STRATEGY_REVISION,
              'requested_mode': mode, 'account_mode': None,
              'outcome': 'missing_inputs', 'evaluated_orders': None,
              'evaluation_kind': 'retained_market_replay' if replay else 'fresh_api'}
    status_path = root/'docs/data/strategy_status.json'
    if status_path.exists():
        report['successful_at'] = json.loads(status_path.read_text()).get('successful_at')
    try:
        if mode not in ('course', 'authoritative'):
            raise ValueError('Unknown order-generation mode')
        old = read_orders(root)
        state = read_state(root)
        if replay:
            # Explicit audit only: preserve the original dates, raw response and
            # production queue. Never silently use a snapshot after an API error.
            market = json.loads((root/'docs/data/market_snapshot.json').read_text())
            report['calendar'] = market['calendar']
        else:
            report['calendar'] = context(now)
            market = provider(report['calendar'], stamp)
            if market.get('calendar') != report['calendar']:
                raise ValueError('Provider calendar differs from the actual upcoming session')
        if market.get('mode') != 'live' or market.get('source') != 'LSEG Data Platform':
            raise ValueError('Non-live provider forbidden in production publication')
        report['market_data_retrieved_at'] = market['retrieved_at']
        report['market_snapshot_sha256'] = digest(market)
        if not replay:
            atomic_json(root/'docs/data/market_snapshot.json', market)
        account_path = root/'mkt/positions.json'
        account = json.loads(account_path.read_text()) if account_path.exists() else None
        hypothetical = mode == 'course' and not account_path.exists()
        report['account_mode'] = 'course_proposal' if hypothetical else 'authoritative'
        report['authoritative_account_available'] = account_path.exists()
        report['account_status'] = ('Unavailable; explicit course proposal assumptions used, not an official account'
                                    if hypothetical else 'Available' if account_path.exists()
                                    else 'Missing mkt/positions.json; authoritative mode requires it')
        report['account_assumptions'] = ASSUMPTIONS if hypothetical else None
        if hypothetical:
            account = initial_account(market['calendar']['as_of'])
        pending = pending_orders(state, old, hypothetical=hypothetical)
        if any(o['for'] > market['calendar']['target_session'] for o in pending):
            raise ValueError('Future-dated queue beyond the upcoming session requires review')
        report['pending_orders_before'] = pending
        report['course_state_before_sha256'] = digest(state)
        course_path = root/'price_history.json'
        verification = root/'docs/data/conid_verification.json'
        evidence = json.loads(verification.read_text()) if verification.exists() else {}
        conids, coverage = resolve_identifiers(evidence,
            json.loads(course_path.read_text()) if course_path.exists() else {})
        report['conid_status'] = conids
        report['identifier_audit'] = coverage
        report['identifier_verified_at'] = evidence['retrieved_at']
        result = evaluate(market, account, conids, pending, course_proposal=hypothetical)
        report.update({k: v for k, v in result.items() if k != 'orders'})
        report['evaluated_orders'] = result['orders']
        unresolved = [o for o in pending if o['id'].startswith('fin535-course-')
                      and o['id'] not in (account or {}).get('resolved_order_ids', [])]
        report['unconfirmed_proposal_count'] = len(unresolved)
        report['past_unconfirmed_proposal_count'] = sum(o['for'] <= market['calendar']['as_of'] for o in unresolved)
        report['pipeline_audit'] = {
            'first_blocking_stage': ('account/pending validation' if result['capital'] is None
                                     else 'market/identifier validation' if result['status'] == 'blocked' else None),
            'account_present': account_path.exists(),
            'course_coverage_unconfirmed': [t for t, d in coverage.items() if d['course_binding'] != 'confirmed'],
            'course_coverage_role': 'Execution readiness, not stock-identity validation; no fill is claimed',
            'resolver_status': 'Professor documentation: Sanji does not resolve orders yet. This is not a JSON-generation requirement.',
            'production_account_assumed': False,
        }
        report['data_quality'] = {t: {k: v for k, v in d.items() if k in (
            'ric', 'errors', 'candidate_count', 'options_status', 'delta_status', 'exclusions', 'close_recheck_status')}
                                 for t, d in market['tickers'].items()}
        if result['status'] == 'success':
            report['proposed_order_count'] = len(result['orders'])
            report['new_order_ids'] = [o['id'] for o in result['orders'] if o['id'] not in {p['id'] for p in pending}]
            report['outcome'] = ('proposals_available' if result['orders'] else
                                 'awaiting_order_confirmation' if unresolved else 'no_eligible_trades')
            if not replay:
                updated = next_state(state, result['orders'], account, hypothetical=hypothetical)
                publish_orders(root, result['orders'], course_state=updated)
                report['orders_updated'] = True
                report['order_files_changed'] = old != result['orders']
                report['unconfirmed_proposal_count'] = len(updated['unconfirmed_orders'])
                report['successful_at'] = stamp
    except Exception as e:
        report['status'] = 'blocked'
        report['outcome'] = 'missing_inputs'
        report['errors'].append(safe_failure_detail(e, os.environ))
    # No raw account positions/fills or private account IDs are published.
    try:
        retained = read_orders(root)
        report['order_count'] = len(retained)
        report['orders_sha256'] = digest(retained)
    except Exception:
        report['order_count'] = None
        report['errors'].append('Order mirror validation failed; manual review required; neither file changed')
    atomic_json(status_path, report)
    print(json.dumps({k: report[k] for k in ('status', 'calendar', 'order_count', 'orders_updated', 'errors')}, indent=2))
    for d in report['decisions']:
        print(d['ticker'], d['decision'], '; '.join(d['reasons']))
    return 0 if report['status'] == 'success' else 2


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument('--replay', action='store_true',
                   help='Audit the retained real snapshot; no API calls or production-order writes')
    p.add_argument('--mode', choices=('course', 'authoritative'), default='course',
                   help='Course uses disclosed starting assumptions ONLY when no official account exists')
    args = p.parse_args()
    return run(args.root, datetime.now(timezone.utc), replay=args.replay, mode=args.mode)


if __name__ == '__main__':
    sys.exit(main())
