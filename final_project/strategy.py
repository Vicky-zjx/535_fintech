"""Pure deterministic strategy. No IO, fabricated quotes, or simulated fills."""
from datetime import date
import math
import statistics
from .calendar import required_sessions
from .portfolio import validate_account, capital_check
from .sanji_orders import validate, make_order
from .strategy_config import UNIVERSE, MAX_HV, MIN_R5


def indicators(history, as_of):
    expected = required_sessions(as_of)
    observed = {}
    for row in history:
        d, c = row['date'], row['close']
        if d > as_of:
            raise ValueError('Future or incomplete close in signal input')
        if d in observed and observed[d] != c:
            raise ValueError('Conflicting duplicate closing prices')
        observed[d] = c
    values = [observed.get(d) for d in expected]
    if len(values) != 50 or any(type(x) not in (int, float) or not math.isfinite(x) or x <= 0 for x in values):
        raise ValueError('Missing/stale close: require 50 consecutive completed exchange sessions')
    logs = [math.log(b/a) for a, b in zip(values[-21:-1], values[-20:])]
    result = dict(close=values[-1], price_date=as_of, sma20=statistics.mean(values[-20:]),
                  sma50=statistics.mean(values), hv20=statistics.stdev(logs)*math.sqrt(252),
                  r5=values[-1]/values[-6]-1)
    result['filters'] = {'trend': result['close'] >= result['sma50'] and result['sma20'] >= result['sma50'],
                         'volatility': result['hv20'] <= MAX_HV, 'sudden_drop': result['r5'] >= MIN_R5}
    return result


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


def evaluate(market, account, conids, pending):
    ctx = market['calendar']
    as_of, session = ctx['as_of'], ctx['target_session']
    decisions = []
    errors = []
    for t in UNIVERSE:
        d = {'ticker': t, 'decision': 'No Trade', 'eligible': False, 'reasons': []}
        data = market['tickers'].get(t, {})
        try:
            if data.get('identity_verified') is not True:
                raise ValueError('RIC-to-ticker identity not verified by LSEG')
            d.update(indicators(data.get('history', []), as_of))
        except ValueError as e:
            d['reasons'].append(str(e))
            errors.append(f'{t}: {e}')
        decisions.append(d)
    by_ticker = {d['ticker']: d for d in decisions}
    try:
        states, cash, equity = validate_account(account, as_of, {d['ticker']: d.get('close') for d in decisions})
        expected = {'live': 'Sanji', 'test': 'TEST_FIXTURE',
                    'demonstration': 'HYPOTHETICAL_DEMONSTRATION'}.get(market.get('mode'))
        if expected is None or account.get('source') != expected:
            raise ValueError('Test account is forbidden in a live run; market/account modes must match')
        resolved = account.get('resolved_order_ids', [])
        if not isinstance(resolved, list) or any(not isinstance(i, str) for i in resolved):
            raise ValueError('Invalid resolved order IDs')
        validate(pending)
        inverse = {v: t for t, v in conids.items()}
        if len(inverse) != len(conids):
            raise ValueError('Duplicate conid mappings')
        keep = []
        pending_tickers = set()
        for o in pending:
            if o['id'] in resolved or o['for'] <= as_of:
                continue  # Dated Sanji orders cannot fill in a later session.
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
            keep.append(o)
            pending_tickers.add(t)
    except (ValueError, TypeError, KeyError) as e:
        errors.append(str(e))
        for d in decisions:
            d['reasons'].append('Account/pending-order validation blocked: '+str(e))
        return {'status': 'blocked', 'errors': errors, 'decisions': decisions, 'orders': None, 'capital': None}
    base = capital_check(states, cash, equity)
    candidates = []
    for d in decisions:
        t = d['ticker']; s = states[t]; data = market['tickers'].get(t, {})
        d['position'] = {k: s[k] for k in ('shares', 'put', 'call', 'cost_basis')}
        if t in pending_tickers:
            d['reasons'].append('Existing pending order retained; no duplicate')
            continue
        if s['put'] or s['call']:
            d['reasons'].append('Existing short option; wait for Sanji expiry/assignment')
            continue
        phase = 'call' if s['shares'] >= 100 else 'put'
        if s['shares'] and s['shares'] < 100:
            d['reasons'].append('Partial share position: no new put and insufficient call coverage')
            continue
        if d['reasons']:
            continue
        if phase == 'put':
            if not ctx['first_session_of_week']:
                d['reasons'].append('Next session is not the first trading session of the week')
            d['reasons'] += [f'{k} filter failed' for k, ok in d['filters'].items() if not ok]
            if d['reasons']:
                continue
        if type(conids.get(t)) is not int or conids[t] <= 0:
            d['reasons'].append('Course conid mapping missing/unverified')
            errors.append(f'{t}: Course conid mapping missing/unverified')
            continue
        if data.get('options_status') != 'observed':
            d['reasons'].append('Option candidate data unavailable; not evidence that no options exist')
            errors.append(f'{t}: Option candidate data unavailable')
            continue
        chosen, reason = select_contract(data['contracts'], phase, session, d['close'], s['cost_basis'], as_of)
        if reason:
            d['reasons'].append(reason)
            continue
        d['candidate'] = chosen
        if phase == 'put':
            earnings = data.get('earnings', {})
            if earnings.get('reliable') is not True or earnings.get('known_on') != as_of or earnings.get('through', '') < chosen['expiry']:
                d['reasons'].append('Earnings calendar unknown/unreliable; put blocked')
                continue
            if any(session <= e <= chosen['expiry'] for e in earnings.get('dates', [])):
                d['reasons'].append('Earnings blackout includes entry through expiry')
                continue
        order = make_order(t, phase, session, conids[t], chosen)
        if market.get('mode') == 'demonstration':
            order['id'] = order['id'].replace('fin535-wheel-', 'fin535-demo-')
        if order['id'] in resolved:
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
            d['reasons'] += check['reasons']
            continue
        if phase == 'put':
            states[t]['collateral'] += c['strike']*100
            states[t]['exposure'] += c['strike']*100
        d['eligible'] = True
        d['decision'] = 'Sell Put' if phase == 'put' else 'Sell Covered Call'
        d['reasons'].append(c['selection_method'])
        orders.append(o)
    if errors:
        for d in decisions:
            if d['eligible']:
                d['decision'] = 'No Trade'; d['eligible'] = False
                d['reasons'].append('Batch blocked by missing inputs; prior order files unchanged')
    return {'status': 'blocked' if errors else 'success', 'errors': errors,
            'decisions': decisions, 'orders': None if errors else validate(orders),
            'capital': base if errors else capital_check(states, cash, equity), 'capital_before': base}
