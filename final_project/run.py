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
from .verify_conids import verified_mapping
from lseg_chart.update import safe_failure_detail


def run(root, now, provider=fetch_market, *, replay=False):
    root = Path(root)
    stamp = now.isoformat()
    report = {'schema_version': 1, 'mode': 'live', 'status': 'blocked', 'attempted_at': stamp,
              'successful_at': None, 'market_data_retrieved_at': None,
              'source': 'LSEG Data Platform', 'orders_updated': False, 'errors': [],
              'decisions': [], 'capital': None, 'calendar': None,
              'strategy_revision': STRATEGY_REVISION,
              'evaluation_kind': 'retained_market_replay' if replay else 'fresh_api'}
    status_path = root/'docs/data/strategy_status.json'
    if status_path.exists():
        report['successful_at'] = json.loads(status_path.read_text()).get('successful_at')
    try:
        old = read_orders(root)
        if replay:
            # Explicit audit only: preserve the original dates, raw response and
            # production queue. Never silently use a snapshot after an API error.
            market = json.loads((root/'docs/data/market_snapshot.json').read_text())
            report['calendar'] = market['calendar']
        else:
            report['calendar'] = context(now)
            market = provider(report['calendar'], stamp)
        if market.get('mode') != 'live' or market.get('source') != 'LSEG Data Platform':
            raise ValueError('Non-live provider forbidden in production publication')
        report['market_data_retrieved_at'] = market['retrieved_at']
        report['market_snapshot_sha256'] = digest(market)
        if not replay:
            atomic_json(root/'docs/data/market_snapshot.json', market)
        account_path = root/'mkt/positions.json'
        account = json.loads(account_path.read_text()) if account_path.exists() else None
        course_path = root/'price_history.json'
        conids = conids_from_course(json.loads(course_path.read_text())) if course_path.exists() else {}
        result = evaluate(market, account, conids, old)
        report.update({k: v for k, v in result.items() if k != 'orders'})
        report['account_status'] = 'Available' if account else 'Missing mkt/positions.json; no account balance assumed'
        report['conid_status'] = {t: conids.get(t) for t in UNIVERSE}
        verification = root/'docs/data/conid_verification.json'
        if verification.exists():
            try:
                report['ibkr_verified_conids'] = verified_mapping(json.loads(verification.read_text()))
            except (ValueError, KeyError, TypeError):
                report['ibkr_verified_conids'] = None
        report['pipeline_audit'] = {
            'first_blocking_stage': 'account/pending validation' if result['capital'] is None else None,
            'account_present': account_path.exists(),
            'course_conids_missing': [t for t in UNIVERSE if t not in conids],
            'resolver_status': 'Professor documentation: Sanji does not resolve orders yet. This is not a JSON-generation requirement.',
            'production_account_assumed': False,
        }
        report['data_quality'] = {t: {k: v for k, v in d.items() if k in (
            'ric', 'errors', 'candidate_count', 'options_status', 'delta_status', 'exclusions')}
                                 for t, d in market['tickers'].items()}
        if result['status'] == 'success':
            report['proposed_order_count'] = len(result['orders'])
            if not replay:
                publish_orders(root, result['orders'])
                report['orders_updated'] = True
                report['successful_at'] = stamp
    except Exception as e:
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
    args = p.parse_args()
    return run(args.root, datetime.now(timezone.utc), replay=args.replay)


if __name__ == '__main__':
    sys.exit(main())
