"""Offline publication contract: orders, diagnostics, links and editable SVG."""
from html.parser import HTMLParser
import json
import math
from pathlib import Path
from urllib.parse import urlsplit, unquote
import xml.etree.ElementTree as ET
from .sanji_orders import read_orders, validate
from .data_provider import digest
from .strategy_config import STRATEGY_REVISION
from .verify_conids import resolve_identifiers


class Links(HTMLParser):
    def __init__(self):
        super().__init__(); self.links = []
    def handle_starttag(self, tag, attrs):
        self.links += [(k, v) for k, v in attrs if k in ('href', 'src') and v]


def equivalent_observations(actual, expected):
    """Allow floating-point roundoff across CPUs, never changed counts/flags/dates."""
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, float):
        return math.isfinite(actual) and math.isfinite(expected) and math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12)
    if isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(equivalent_observations(actual[k], v) for k, v in expected.items())
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(equivalent_observations(a, e) for a, e in zip(actual, expected))
    return actual == expected


def check(root):
    root = Path(root)
    orders = read_orders(root)
    status = json.loads((root/'docs/data/strategy_status.json').read_text())
    evidence = json.loads((root/'docs/data/conid_verification.json').read_text())
    verified_ids, _ = resolve_identifiers(evidence, json.loads((root/'price_history.json').read_text()) if (root/'price_history.json').exists() else {})
    if status.get('strategy_revision') != STRATEGY_REVISION:
        raise ValueError('Re-evaluate diagnostics under the current strategy revision')
    if ('earnings_unreliable' in status.get('pipeline_audit', {}) or
            any('earnings' in d for d in status.get('data_quality', {}).values())):
        raise ValueError('Removed earnings inputs must not appear as current diagnostics')
    if status.get('evaluation_kind') == 'retained_market_replay' and status.get('orders_updated'):
        raise ValueError('Historical replay must not publish production orders')
    if status['mode'] != 'live' or status['status'] not in ('not_run', 'blocked', 'success'):
        raise ValueError('Public site cannot publish test-mode strategy decisions')
    if status.get('orders_updated') and status['status'] != 'success':
        raise ValueError('A blocked run must not claim updated orders')
    if status['order_count'] != len(orders):
        raise ValueError('Displayed order count disagrees with canonical file')
    if status.get('orders_sha256') != digest(orders):
        raise ValueError('Order content hash disagrees with published diagnostics')
    if any(o['id'].startswith('fin535-demo-') for o in orders):
        raise ValueError('Demonstration order in production queue')
    lifecycle_path = root/'docs/data/order_lifecycle.json'
    if lifecycle_path.exists():
        from .lifecycle import read_history, advance_history, project, conditional_preview
        from .course import read_state
        state = read_state(root)
        history = read_history(root)
        if history != advance_history(history, state['unconfirmed_orders'] + orders):
            raise ValueError('Published proposals missing from durable history')
        expected = project(history, status, orders)
        expected['conditional_preview'] = conditional_preview(root, status, state)
        if not equivalent_observations(json.loads(lifecycle_path.read_text()), expected):
            raise ValueError('Lifecycle history/preview does not independently reproduce')
    if status.get('account_mode') == 'course_proposal' and status['status'] == 'success':
        from .course import initial_account, initial_policy, review_initial_proposals, read_state, ASSUMPTIONS
        from .strategy import evaluate
        market = json.loads((root/'docs/data/market_snapshot.json').read_text())
        if status.get('conid_status') != verified_ids:
            raise ValueError('Published proposal conids differ from verified stock identities')
        if (market.get('source') != 'LSEG Data Platform' or market.get('mode') != 'live'
                or digest(market) != status.get('market_snapshot_sha256')
                or status.get('account_assumptions') != ASSUMPTIONS):
            raise ValueError('Course proposal provenance/assumptions do not match')
        recomputed = evaluate(market, initial_account(market['calendar']['as_of']),
                             status['conid_status'], status['pending_orders_before'], course_proposal=True,
                             put_history=status['put_proposal_history_before'])
        for key in ('status', 'decisions', 'capital', 'capital_before'):
            if not equivalent_observations(status.get(key), recomputed.get(key)):
                raise ValueError('Course decisions/capital do not independently reproduce: '+key)
        if recomputed['orders'] != status.get('evaluated_orders'):
            raise ValueError('Proposed JSON differs from actual model decisions')
        if 'initial_account_policy' in status:
            if status['initial_account_policy'] != initial_policy():
                raise ValueError('Initial inventory/capital authority is inconsistent')
            expected_review = review_initial_proposals(market, status['conid_status'], status['pending_orders_before'],
                {'authoritative_account_seen': False, 'put_proposal_history': status['put_proposal_history_before']})
            if not equivalent_observations(status.get('initial_cycle_review'), expected_review):
                raise ValueError('Initial-cycle proposal/collateral audit does not reproduce')
        if status.get('orders_updated'):
            if orders != recomputed['orders'] or any(o['for'] != market['calendar']['target_session'] for o in orders):
                raise ValueError('Published course queue differs from evaluated upcoming-session proposals')
            state = read_state(root)
            if any(o not in state['unconfirmed_orders'] for o in orders):
                raise ValueError('Published course proposal has no durable commitment record')
            if status.get('unconfirmed_proposal_count') != len(state['unconfirmed_orders']):
                raise ValueError('Unconfirmed commitment count disagrees with state')
    demo_path = root/'docs/data/demo_status.json'
    if demo_path.exists():
        demo = json.loads(demo_path.read_text())
        if demo.get('strategy_revision') != STRATEGY_REVISION:
            raise ValueError('Rebuild demonstrations under the current strategy revision')
        if demo['mode'] != 'demonstration' or demo['production_orders_changed'] is not False:
            raise ValueError('Demonstration isolation/label missing')
        market = json.loads((root/'docs/data/market_snapshot.json').read_text())
        if demo['market_snapshot_sha256'] != digest(market):
            raise ValueError('Demonstration does not match retained real market snapshot')
        for scenario in demo['scenarios']:
            proposed = scenario['proposed_orders']
            saved = json.loads((root/f"docs/data/demo_{scenario['id']}_orders.json").read_text())
            if saved != proposed:
                raise ValueError('Demonstration download disagrees with report')
            if proposed is None:
                continue
            validate(proposed)
            if any(not o['id'].startswith('fin535-demo-') for o in proposed):
                raise ValueError('Demo orders need independent identifiers')
            if saved != proposed or len(proposed) != scenario['order_count']:
                raise ValueError('Demonstration JSON/count mismatch')
    entry_path = root/'docs/data/entry_demo_status.json'
    if entry_path.exists():
        entry = json.loads(entry_path.read_text())
        snapshot = json.loads((root/'docs/data/entry_example_market.json').read_text())
        if entry['mode'] != 'demonstration' or entry['production_orders_changed'] or entry['market_snapshot_sha256'] != digest(snapshot):
            raise ValueError('Invalid isolated weekly-entry example provenance')
        for s in entry['scenarios']:
            saved = json.loads((root/f"docs/data/entry_demo_{s['id']}_orders.json").read_text())
            if saved != s['proposed_orders'] or (saved is not None and len(saved) != s['order_count']):
                raise ValueError('Weekly-entry example download mismatch')
            if saved is not None:
                validate(saved)
                if any(not o['id'].startswith('fin535-demo-') for o in saved):
                    raise ValueError('Entry example must not claim production IDs')
    historical_path = root/'docs/data/historical_signals.json'
    if historical_path.exists():
        from .historical import analyze
        market = json.loads((root/'docs/data/market_snapshot.json').read_text())
        historical = json.loads(historical_path.read_text())
        if historical['market_snapshot_sha256'] != digest(market):
            raise ValueError('Historical analysis snapshot mismatch')
        expected = analyze(market)
        if any(not equivalent_observations(historical.get(k), v) for k,v in expected.items()):
            raise ValueError('Historical statistics do not reproduce from real observations')
    html = (root/'docs/index.html').read_text()
    if '<html lang="en">' not in html:
        raise ValueError('English page language required')
    if any('\u4e00' <= c <= '\u9fff' for c in html):
        raise ValueError('Non-English public text')
    links = Links(); links.feed(html)
    for _, url in links.links:
        u = urlsplit(url)
        if u.scheme or u.netloc or not u.path:
            continue
        # Only absent before a first API response; link stays hidden until then.
        if u.path == 'data/market_snapshot.json' and not status.get('market_snapshot_sha256'):
            continue
        target = (root/'docs'/unquote(u.path)).resolve()
        if not target.is_relative_to(root.resolve()) or not target.exists():
            raise ValueError('Missing/unsafe publication link: '+url)
    svg = ET.parse(root/'docs/assets/strategy-workflow.svg').getroot()
    if svg.tag != '{http://www.w3.org/2000/svg}svg' or not svg.attrib.get('viewBox'):
        raise ValueError('Invalid editable SVG')
    print('Publication valid: identical Sanji JSON, English page, local links, accessible SVG')


if __name__ == '__main__':
    check(Path(__file__).resolve().parents[1])
