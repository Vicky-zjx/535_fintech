"""Offline publication contract: orders, diagnostics, links and editable SVG."""
from html.parser import HTMLParser
import json
from pathlib import Path
from urllib.parse import urlsplit, unquote
import xml.etree.ElementTree as ET
from .sanji_orders import read_orders, validate
from .data_provider import digest


class Links(HTMLParser):
    def __init__(self):
        super().__init__(); self.links = []
    def handle_starttag(self, tag, attrs):
        self.links += [(k, v) for k, v in attrs if k in ('href', 'src') and v]


def check(root):
    root = Path(root)
    orders = read_orders(root)
    status = json.loads((root/'docs/data/strategy_status.json').read_text())
    if status['mode'] != 'live' or status['status'] not in ('not_run', 'blocked', 'success'):
        raise ValueError('Public site cannot publish test-mode strategy decisions')
    if status.get('orders_updated') and status['status'] != 'success':
        raise ValueError('A blocked run must not claim updated orders')
    if status['order_count'] != len(orders):
        raise ValueError('Displayed order count disagrees with canonical file')
    if any(o['id'].startswith('fin535-demo-') for o in orders):
        raise ValueError('Demonstration order in production queue')
    demo_path = root/'docs/data/demo_status.json'
    if demo_path.exists():
        demo = json.loads(demo_path.read_text())
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
