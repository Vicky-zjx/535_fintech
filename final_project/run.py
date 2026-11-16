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
from .strategy_config import UNIVERSE
from lseg_chart.update import safe_failure_detail


def run(root, now, provider=fetch_market):
    root = Path(root)
    stamp = now.isoformat()
    report = {'schema_version': 1, 'mode': 'live', 'status': 'blocked', 'attempted_at': stamp,
              'successful_at': None, 'market_data_retrieved_at': None,
              'source': 'LSEG Data Platform', 'orders_updated': False, 'errors': [],
              'decisions': [], 'capital': None, 'calendar': None}
    status_path = root/'docs/data/strategy_status.json'
    if status_path.exists():
        report['successful_at'] = json.loads(status_path.read_text()).get('successful_at')
    try:
        report['calendar'] = context(now)
        old = read_orders(root)
        market = provider(report['calendar'], stamp)
        if market.get('mode') != 'live':
            raise ValueError('Non-live provider forbidden in production publication')
        report['market_data_retrieved_at'] = stamp
        report['market_snapshot_sha256'] = digest(market)
        atomic_json(root/'docs/data/market_snapshot.json', market)
        account_path = root/'mkt/positions.json'
        account = json.loads(account_path.read_text()) if account_path.exists() else None
        course_path = root/'price_history.json'
        conids = conids_from_course(json.loads(course_path.read_text())) if course_path.exists() else {}
        result = evaluate(market, account, conids, old)
        report.update({k: v for k, v in result.items() if k != 'orders'})
        report['account_status'] = 'Available' if account else 'Missing mkt/positions.json; no account balance assumed'
        report['conid_status'] = {t: conids.get(t) for t in UNIVERSE}
        report['data_quality'] = {t: {k: v for k, v in d.items() if k in (
            'ric', 'errors', 'candidate_count', 'options_status', 'delta_status', 'earnings', 'exclusions')}
                                 for t, d in market['tickers'].items()}
        if result['status'] == 'success':
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
    args = p.parse_args()
    return run(args.root, datetime.now(timezone.utc))


if __name__ == '__main__':
    sys.exit(main())
