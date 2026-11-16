"""Strict subset of the public Sanji schema: explicit listed strike and expiry."""
from datetime import date
import json
import math
import os
from pathlib import Path
import tempfile

KEYS = {'id', 'for', 'order_type', 'action', 'qty', 'underlying', 'contract', 'expiry', 'strike', 'ref'}


def validate(orders):
    if not isinstance(orders, list):
        raise ValueError('Orders must be a JSON array')
    ids = set()
    for o in orders:
        if not isinstance(o, dict) or set(o) != KEYS:
            raise ValueError('Unsupported or missing Sanji order fields')
        if not isinstance(o['id'], str) or not o['id'] or o['id'] in ids:
            raise ValueError('Missing or duplicate order ID')
        ids.add(o['id'])
        for k in ('for', 'expiry'):
            if not isinstance(o[k], str) or str(date.fromisoformat(o[k])) != o[k]:
                raise ValueError('Noncanonical session or expiry date')
        dte = (date.fromisoformat(o['expiry'])-date.fromisoformat(o['for'])).days
        if not 3 <= dte <= 10:
            raise ValueError('Expiry outside 3–10 calendar DTE')
        if o['order_type'] != 'mkt' or o['action'] != 'SHT' or o['ref'] != 'prev_close':
            raise ValueError('Only declared market short-open orders are supported')
        if type(o['qty']) is not int or o['qty'] != 1:
            raise ValueError('Exactly one contract per order')
        if type(o['underlying']) is not int or o['underlying'] <= 0:
            raise ValueError('Underlying must be a verified numeric conid')
        if o['contract'] not in ('put', 'call'):
            raise ValueError('Invalid option type')
        if type(o['strike']) not in (float, int) or not math.isfinite(o['strike']) or o['strike'] <= 0:
            raise ValueError('Explicit positive strike required')
    return orders


def make_order(ticker, phase, session, conid, contract):
    return validate([dict(id=f'fin535-wheel-{ticker.lower()}-{phase}-{session}',
                         **{'for': session}, order_type='mkt', action='SHT', qty=1,
                         underlying=conid, contract=phase, expiry=contract['expiry'],
                         strike=contract['strike'], ref='prev_close')])[0]


def atomic_json(path, payload):
    path = Path(path)
    content = json.dumps(payload, indent=2, allow_nan=False) + '\n'
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as f:
        temp = f.name
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)


def read_orders(root):
    paths = [Path(root)/'open_orders.json', Path(root)/'mkt/open_orders.json']
    if any(not p.exists() for p in paths):
        raise ValueError('Both order paths must exist before running')
    if paths[0].read_bytes() != paths[1].read_bytes():
        raise ValueError('Root and mkt order files disagree; refusing to choose one')
    return validate(json.loads(paths[0].read_text()))


def publish_orders(root, orders):
    validate(orders)  # Validate the complete batch BEFORE either write.
    # Git commits publish both together. In-process write failure restores both.
    paths = [Path(root)/'open_orders.json', Path(root)/'mkt/open_orders.json']
    old = [p.read_text() for p in paths]
    try:
        for p in paths:
            atomic_json(p, orders)
        read_orders(root)
    except Exception:
        for p, s in zip(paths, old):
            atomic_json(p, json.loads(s))
        raise
