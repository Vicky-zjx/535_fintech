"""Read-only account adapter. Unknown formats are blocked, never guessed."""
import math
from .strategy_config import UNIVERSE, PER_NAME, TOTAL_EXPOSURE, RESERVE


def number(value, name, minimum=0):
    if type(value) not in (int, float) or not math.isfinite(value) or value < minimum:
        raise ValueError(f'Invalid {name}')
    return float(value)


def validate_account(account, as_of, closes):
    if not isinstance(account, dict) or account.get('schema_version') != 1:
        raise ValueError('Account adapter schema unavailable; raw Sanji format must be verified')
    if account.get('as_of') != as_of or account.get('currency') != 'USD':
        raise ValueError('Missing/stale account date or non-USD account')
    if account.get('source') not in ('Sanji', 'TEST_FIXTURE', 'HYPOTHETICAL_DEMONSTRATION'):
        raise ValueError('Account source is not identified')
    cash = number(account.get('cash'), 'cash (no borrowing)')
    equity = number(account.get('equity'), 'equity', .01)
    positions = account.get('positions')
    if not isinstance(positions, list):
        raise ValueError('Missing complete account positions')
    states = {t: {'shares': 0, 'put': 0, 'call': 0, 'cost_basis': None,
                  'exposure': 0., 'collateral': 0.} for t in UNIVERSE}
    nav = cash
    seen = set()
    for p in positions:
        t, kind = p.get('ticker'), p.get('kind')
        if t not in states or kind not in ('stock', 'put', 'call') or (t, kind) in seen:
            raise ValueError('Unknown, duplicate or unsupported account position; aggregate adapter required')
        seen.add((t, kind))
        qty = p.get('quantity')
        if type(qty) is not int or (kind == 'stock' and qty <= 0) or (kind != 'stock' and qty != -1):
            raise ValueError('Unsupported quantity, leverage or option position')
        s = states[t]
        if kind == 'stock':
            s['shares'] = qty
            s['cost_basis'] = (number(p['cost_basis'], 'stock cost basis', .01)
                               if p.get('cost_basis') is not None else None)
            mv = qty * number(closes.get(t), f'{t} stock close', .01)
            nav += mv
            s['exposure'] += mv
        else:
            if p.get('multiplier') != 100 or p.get('terms_status') != 'standard_verified':
                raise ValueError('Existing obligation multiplier/deliverable not verified')
            from datetime import date
            if date.fromisoformat(p['expiry']) < date.fromisoformat(as_of):
                raise ValueError('Expired option remains in book; wait for Sanji reconciliation')
            strike = number(p.get('strike'), 'held option strike', .01)
            nav -= number(p.get('mark'), 'held option closing mark') * 100
            s[kind] += 1
            if kind == 'put':
                s['collateral'] += strike * 100
                s['exposure'] += strike * 100
    if abs(nav-equity) > 1.:
        raise ValueError('Account NAV does not reconcile to cash plus marked positions (tolerance $1)')
    for s in states.values():
        if s['call'] and s['shares'] < 100:
            raise ValueError('Existing uncovered call')
        if s['put'] and (s['shares'] or s['call']):
            raise ValueError('Conflicting Wheel phases in current account')
    return states, cash, equity


def capital_check(states, cash, equity, ticker=None, additional=0.):
    exposure = sum(s['exposure'] for s in states.values()) + additional
    reserved = sum(s['collateral'] for s in states.values()) + additional
    per = {t: s['exposure'] + (additional if t == ticker else 0.) for t, s in states.items()}
    reasons = []
    if any(x > PER_NAME * equity + 1e-8 for x in per.values()):
        reasons.append('Per-ticker exposure would exceed 30% of equity')
    if exposure > TOTAL_EXPOSURE * equity + 1e-8:
        reasons.append('Portfolio exposure would exceed 70% of equity')
    if cash - reserved < RESERVE * equity - 1e-8:
        reasons.append('Uncommitted cash would fall below 30% of equity')
    return {'passed': not reasons, 'reasons': reasons, 'equity': equity, 'cash': cash,
            'exposure': exposure, 'put_collateral': reserved,
            'uncommitted_cash': cash-reserved, 'by_ticker': per}
