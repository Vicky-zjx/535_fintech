"""Audit retained real discovery snapshots, never infer historical option returns."""
import json
import math
from pathlib import Path
from final_project.data_provider import digest
from final_project.strategy_config import UNIVERSE


def finite(value):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)


def audit(root):
    snapshots = []
    for filename in ('docs/data/market_snapshot.json', 'docs/data/entry_example_market.json'):
        p = Path(root)/filename
        if not p.exists():
            snapshots.append(dict(path=filename, status='not_available'))
            continue
        m = json.loads(p.read_text())
        if m.get('source') != 'LSEG Data Platform':
            raise ValueError('Option audit requires real LSEG snapshots')
        counts = {}
        for ticker in UNIVERSE:
            contracts = m['tickers'][ticker]['contracts']
            pairs = [c for c in contracts if finite(c.get('bid')) and finite(c.get('ask'))
                     and 0 <= c['bid'] <= c['ask'] and c['ask'] > 0]
            counts[ticker] = dict(contracts=len(contracts), puts=sum(c['type']=='put' for c in contracts),
                                 bid_ask_pairs=len(pairs),
                                 dated_deltas=sum(finite(c.get('delta')) and bool(c.get('delta_date')) for c in contracts),
                                 expiries=sorted({c['expiry'] for c in contracts}))
        snapshots.append(dict(path=filename, status='inventoried', sha256=digest(m),
                              retrieved_at=m['retrieved_at'], market_date=m['calendar']['as_of'], tickers=counts))
    return dict(status='insufficient_option_data', economic_advantage=None,
                scope='Retained four-stock discovery metadata, not a historical quote panel', snapshots=snapshots,
                missing_requirements=[
                    'A time-of-availability-supported candidate universe on every historical decision date',
                    'Dated entry bid/ask and delta, or the unchanged observed-strike fallback with valid quotes',
                    'Consistent expiry outcomes, terms and underlying prices for both comparison arms',
                    'Matched capital, costs, cash benchmark and accounting for idle/no-trade weeks and data gaps'],
                capability='The existing LSEG connector queries real stock history, current discovery and same-session DELTA_EXCH. Historical option quotes are not collected by that workflow; historical entitlement is not established by this audit.',
                legacy_scope='The audited AAPL and UUUU caches concern different underlyings and cannot supply BAC, KO, PFE or F returns.',
                extension=dict(name='Net economic benefit after forgone premium and costs',
                               status='not_yet_testable', original_registered_condition=False))
