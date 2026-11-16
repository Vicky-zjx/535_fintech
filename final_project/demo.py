"""Isolated real-market replay with hypothetical books; NEVER publishes Sanji orders."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from .data_provider import digest
from .sanji_orders import atomic_json, validate
from .strategy import evaluate, indicators
from .strategy_config import UNIVERSE, ILLUSTRATIVE_CAPITAL, STRATEGY_REVISION
from .verify_conids import verified_mapping


def examples(market):
    as_of = market['calendar']['as_of']
    closes = {t: indicators(market['tickers'][t]['history'], as_of)['close'] for t in UNIVERSE}
    flat = dict(schema_version=1, source='HYPOTHETICAL_DEMONSTRATION', as_of=as_of,
                currency='USD', cash=float(ILLUSTRATIVE_CAPITAL), equity=float(ILLUSTRATIVE_CAPITAL),
                positions=[], resolved_order_ids=[])
    held = deepcopy(flat)
    held['positions'] = [dict(ticker=t, kind='stock', quantity=100, cost_basis=c) for t, c in closes.items()]
    held['cash'] -= sum(100*c for c in closes.values())
    return [('cash_start', 'Hypothetical $40,000 cash-only starting book', flat),
            ('covered_inventory', 'Independent hypothetical $40,000 book: 100 shares of each ticker; '
             'basis equals its observed close; remaining funds held as cash. These are assumed holdings, '
             'not simulated purchases, actual assignments, or a continuation of the cash-start run.', held)]


def build(root, now):
    root = Path(root)
    production = [root/'open_orders.json', root/'mkt/open_orders.json']
    before = [p.read_bytes() for p in production]
    market = json.loads((root/'docs/data/market_snapshot.json').read_text())
    if market.get('mode') != 'live' or market.get('source') != 'LSEG Data Platform':
        raise ValueError('Demonstration requires a retained real LSEG response, never synthetic fixtures')
    evidence = json.loads((root/'docs/data/conid_verification.json').read_text())
    ids = verified_mapping(evidence)
    cases = examples(market)
    report = dict(schema_version=1, mode='demonstration', generated_at=now.isoformat(),
                  strategy_revision=STRATEGY_REVISION,
                  label='DEMONSTRATION ONLY — hypothetical accounts, not actual Sanji account orders',
                  market_source='Retained real LSEG API response replay; not a new query or backtest',
                  market_retrieved_at=market['retrieved_at'], market_snapshot_sha256=digest(market),
                  calendar=market['calendar'], starting_capital=ILLUSTRATIVE_CAPITAL,
                  conids=ids, scenarios=[], production_orders_changed=False,
                  production_order_hashes=[hashlib.sha256(x).hexdigest() for x in before])
    demo_market = deepcopy(market)
    demo_market['mode'] = 'demonstration'
    for name, description, account in cases:
        result = evaluate(demo_market, account, ids, [])
        orders = result.pop('orders')
        if orders is not None:
            validate(orders)
        item = dict(id=name, description=description, account=account, **result,
                    proposed_orders=orders, order_count=len(orders) if orders is not None else None)
        report['scenarios'].append(item)
    # Guard against accidental changes even if future helper code is modified.
    if [p.read_bytes() for p in production] != before:
        raise RuntimeError('Production orders changed during isolated demonstration')
    atomic_json(root/'docs/data/demo_status.json', report)
    for s in report['scenarios']:
        # JSON null denotes blocked generation; never leave an older example queue.
        atomic_json(root/f"docs/data/demo_{s['id']}_orders.json", s['proposed_orders'])
    print(json.dumps({'mode': report['mode'], 'production_orders_changed': False,
                      'scenarios': [{k: s[k] for k in ('id', 'status', 'order_count')} for s in report['scenarios']]}, indent=2))
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = p.parse_args()
    build(args.root, datetime.now(timezone.utc))
