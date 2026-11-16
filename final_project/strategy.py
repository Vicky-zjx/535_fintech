"""Pure deterministic strategy. No IO, fabricated quotes, or simulated fills."""
from datetime import date
import math
from .calendar import required_sessions
from .indicators import compute, IndicatorUnavailable
from .course import trading_week, proposal_history
from .portfolio import validate_account, capital_check
from .sanji_orders import validate, make_order
from .strategy_config import UNIVERSE


def indicators(history, as_of):
    expected = required_sessions(as_of, 55)
    observed = {}
    for row in history:
        d, c = row['date'], row['close']
        if d > as_of:
            raise ValueError('Future or incomplete close in signal input')
        if d in observed and observed[d] != c:
            raise ValueError('Conflicting duplicate closing prices')
        observed[d] = c
    return compute(observed, expected)


def select_contract(contracts, phase, session, close, cost_basis, as_of):
    valid = [c for c in contracts if c['type'] == phase and c.get('terms_verified') is True
             and c.get('multiplier') == 100 and c.get('observed_on') == as_of
             and 3 <= (date.fromisoformat(c['expiry'])-date.fromisoformat(session)).days <= 10]
    if not valid:
        return None, 'No observed standard expiry within 3–10 DTE; candidate set may be incomplete'
    expiry = min({c['expiry'] for c in valid}, key=lambda e: (abs((date.fromisoformat(e)-date.fromisoformat(session)).days-7), e))
    valid = [c for c in valid if c['expiry'] == expiry]
    if phase == 'put':
        valid = [c for c in valid if 0 < c['strike'] < close]
    else:
        if cost_basis is None:
            return None, 'Stock cost basis unavailable; call blocked'
        valid = [c for c in valid if c['strike'] >= max(1.01*cost_basis, 1.02*close)]
    if not valid:
        return None, 'No observed standard contract satisfies DTE/strike constraints; candidate set may be incomplete'
    near = valid
    reliable = [c for c in near if c.get('delta_date') == as_of and type(c.get('delta')) in (int, float)
                and math.isfinite(c['delta']) and ((-1 < c['delta'] < 0) if phase == 'put' else (0 < c['delta'] < 1))]
    # Partial delta coverage can bias selection: fallback uses the whole observed slice.
    if len(reliable) == len(near):
        chosen = min(reliable, key=lambda c: (abs(abs(c['delta'])-.25), c['strike'] if phase == 'put' else -c['strike'], c['ric']))
        method = 'Observed same-session delta closest to absolute 0.25'
    elif phase == 'put':
        chosen = min(near, key=lambda c: (abs(c['strike']-.97*close), c['strike'], c['ric']))
        method = 'Fallback: observed strike nearest 3% OTM; not 25-delta'
    else:
        all_strikes = sorted({c['strike'] for c in contracts if c['type'] == 'call' and c['expiry'] == expiry
                              and c.get('terms_verified') is True and c.get('observed_on') == as_of})
        atm = min(all_strikes, key=lambda k: (abs(k-close), k))
        index = all_strikes.index(atm)+2
        if index >= len(all_strikes):
            return None, 'Two-strikes-OTM fallback unavailable in observed strikes'
        selected = [c for c in near if c['strike'] == all_strikes[index]]
        if not selected:
            return None, 'Two-strikes-OTM fallback fails cost-basis/2%-above-close constraints'
        chosen = min(selected, key=lambda c: c['ric'])
        method = 'Fallback: two observed strikes above ATM; both price floors checked'
    return dict(chosen, selection_method=method), None


def evaluate(market, account, conids, pending, *, course_proposal=False, put_history=None):
    ctx = market['calendar']
    as_of, session = ctx['as_of'], ctx['target_session']
    decisions = []
    errors = []
    warnings = []
    for t in UNIVERSE:
        d = {'ticker': t, 'decision': 'No Trade', 'eligible': False, 'reasons': [],
             'category': 'Data unavailable', 'technical_status': 'Data unavailable'}
        data = market['tickers'].get(t, {})
        try:
            if data.get('identity_verified') is not True:
                raise ValueError('RIC-to-ticker identity not verified by LSEG')
            d.update(indicators(data.get('history', []), as_of))
            d['technical_status'] = 'Technical filter passed' if all(d['filters'].values()) else 'Technical filter failed'
            d['category'] = d['technical_status']
        except ValueError as e:
            if isinstance(e, IndicatorUnavailable):
                d.update(e.diagnostics)
            d['reasons'].append(str(e))
            warnings.append(f'{t}: {e}')
        decisions.append(d)
    by_ticker = {d['ticker']: d for d in decisions}
    try:
        states, cash, equity = validate_account(account, as_of, {d['ticker']: d.get('close') for d in decisions})
        expected = {'live': 'Sanji', 'test': 'TEST_FIXTURE',
                    'demonstration': 'HYPOTHETICAL_DEMONSTRATION'}.get(market.get('mode'))
        if course_proposal:
            if market.get('mode') not in ('live', 'test'):
                raise ValueError('Course proposal requires real market inputs (or an isolated unit fixture)')
            expected = 'COURSE_PROPOSAL'
        if expected is None or account.get('source') != expected:
            raise ValueError('Test account is forbidden in a live run; market/account modes must match')
        resolved = account.get('resolved_order_ids', [])
        if not isinstance(resolved, list) or any(not isinstance(i, str) for i in resolved):
            raise ValueError('Invalid resolved order IDs')
        validate(pending)
        issued = proposal_history(put_history or [], pending)
        inverse = {v: t for t, v in conids.items()}
        if len(inverse) != len(conids):
            raise ValueError('Duplicate conid mappings')
        keep = []
        pending_tickers = set()
        for o in pending:
            if o['id'] in resolved:
                continue
            uncertain_course = o['id'].startswith('fin535-course-')
            if o['for'] <= as_of and not uncertain_course:
                continue  # A reconciled authoritative book includes prior-session changes.
            t = inverse.get(o['underlying'])
            if t is None or t in pending_tickers:
                raise ValueError('Unknown/duplicate pending obligation')
            s = states[t]
            if o['contract'] == 'put':
                if s['shares'] or s['put'] or s['call']:
                    raise ValueError('Pending put conflicts with current book')
                s['collateral'] += 100*o['strike']
                s['exposure'] += 100*o['strike']
            elif s['shares'] < 100 or s['call'] or s['put']:
                raise ValueError('Pending call lacks unencumbered coverage')
            if o['for'] > as_of:
                keep.append(o)
            pending_tickers.add(t)
    except (ValueError, TypeError, KeyError) as e:
        errors.append(str(e))
        for d in decisions:
            d['reasons'].append('Account/pending-order validation blocked: '+str(e))
        return {'status': 'blocked', 'errors': errors, 'decisions': decisions, 'orders': None, 'capital': None}
    base = capital_check(states, cash, equity)
    if not base['passed']:
        errors += ['Existing portfolio/commitments: '+r for r in base['reasons']]
    if all(d['technical_status'] == 'Data unavailable' for d in decisions):
        errors.append('All stock indicators unavailable; prior order files preserved')
    candidates = []
    for d in decisions:
        t = d['ticker']; s = states[t]; data = market['tickers'].get(t, {})
        d['position'] = {k: s[k] for k in ('shares', 'put', 'call', 'cost_basis')}
        if t in pending_tickers:
            d['category'] = 'Already proposed'
            d['reasons'].append('Unconfirmed proposal/active pending order: ticker locked and collateral reserved; no duplicate or assumed fill')
            continue
        if s['put'] or s['call']:
            d['category'] = 'Position protection'
            d['reasons'].append('Existing short option; wait for Sanji expiry/assignment')
            continue
        phase = 'call' if s['shares'] >= 100 else 'put'
        if s['shares'] and s['shares'] < 100:
            d['category'] = 'Position protection'
            d['reasons'].append('Partial share position: no new put and insufficient call coverage')
            continue
        if d['reasons']:
            continue
        if phase == 'put':
            if any(p['underlying'] == conids.get(t) and p['week'] == trading_week(session) for p in issued):
                d['category'] = 'Already proposed'
                d['reasons'].append('A put was already proposed for this ticker/trading week; resolution does not reset the weekly cap')
                continue
            d['reasons'] += [f'{k} filter failed' for k, ok in d['filters'].items() if not ok]
            if d['reasons']:
                continue
        if type(conids.get(t)) is not int or conids[t] <= 0:
            d['category'] = 'Data unavailable'
            d['reasons'].append('Course conid mapping missing/unverified')
            warnings.append(f'{t}: Course conid mapping missing/unverified')
            continue
        if data.get('options_status') != 'observed':
            d['category'] = 'Option unavailable'
            d['reasons'].append('Option candidate data unavailable; not evidence that no options exist')
            warnings.append(f'{t}: Option candidate data unavailable')
            continue
        chosen, reason = select_contract(data['contracts'], phase, session, d['close'], s['cost_basis'], as_of)
        if reason:
            d['category'] = 'Option unavailable'
            d['reasons'].append(reason)
            continue
        d['candidate'] = chosen
        order = make_order(t, phase, session, conids[t], chosen)
        if course_proposal:
            order['id'] = order['id'].replace('fin535-wheel-', 'fin535-course-')
        if market.get('mode') == 'demonstration':
            order['id'] = order['id'].replace('fin535-wheel-', 'fin535-demo-')
        if order['id'] in resolved:
            d['category'] = 'Already proposed'
            d['reasons'].append('This deterministic order ID was already resolved by Sanji')
            continue
        candidates.append((phase, d['hv20'], t, chosen, order))
    # Calls add no collateral; competing puts sorted by ascending historical volatility.
    orders = list(keep)
    for phase, hv, t, c, o in sorted(candidates, key=lambda x: (x[0] != 'call', x[1], x[2])):
        d = by_ticker[t]
        check = capital_check(states, cash, equity, t, c['strike']*100 if phase == 'put' else 0.)
        d['capital_check'] = check
        if not check['passed']:
            d['category'] = 'Capital limit reached'
            d['reasons'] += check['reasons']
            continue
        if phase == 'put':
            states[t]['collateral'] += c['strike']*100
            states[t]['exposure'] += c['strike']*100
        d['eligible'] = True
        d['category'] = 'Proposed order'
        d['decision'] = 'Sell Put' if phase == 'put' else 'Sell Covered Call'
        d['reasons'].append(c['selection_method'])
        orders.append(o)
    if errors:
        for d in decisions:
            if d['eligible']:
                d['decision'] = 'No Trade'; d['eligible'] = False
                d['reasons'].append('Batch blocked by missing inputs; prior order files unchanged')
    return {'status': 'blocked' if errors else 'success', 'errors': errors, 'warnings': warnings,
            'decisions': decisions, 'orders': None if errors else validate(orders),
            'capital': base if errors else capital_check(states, cash, equity), 'capital_before': base}
