"""Supplemental comparisons; never change the three original account runs.

Capital at a state = put strike collateral + gross stock acquisition cost.
Use each session's peak across modeled before/after/EOD states, then the
arithmetic mean across ALL sessions. This counts expiry-day capital before
release, without adding two mutually exclusive positions together.
"""
from copy import deepcopy
import hashlib
import json
import math
import statistics
from .metrics import calculate


def equal(a, b, label='reconciliation'):
    if a is None or b is None or not math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-6):
        raise ValueError(f'{label}: {a} != {b}')


def fingerprint(book):
    return hashlib.sha256(json.dumps(book, sort_keys=True, allow_nan=False).encode()).hexdigest()


def committed(state):
    p = state['option']
    collateral = p['strike'] * p['multiplier'] * p['quantity'] if p and p['cp'] == 'P' else 0.
    equal(state['reserved_cash'], collateral, 'put collateral')
    equal(state['buying_power'], state['cash'] - collateral, 'unreserved cash')
    if p and p['cp'] == 'P' and state['shares']:
        raise ValueError('Unexpected simultaneous stock and put exposure')
    if p and p['cp'] == 'C' and state['shares'] < p['quantity'] * p['multiplier']:
        raise ValueError('Uncovered call')
    if state['shares'] and state['share_acquisition_cost'] is None:
        raise ValueError('Missing share cost basis')
    stock_cost = state['shares'] * (state['share_acquisition_cost'] or 0.)
    capital = collateral + stock_cost
    if state['equity'] is not None:
        # Shares at cost plus their unrealized P&L recovers marked stock value.
        equal(state['equity'], state['buying_power'] + capital + state['unrealized_stock_pnl']
              + state['dividend_receivable'] - state['option_liability'], 'capital-to-NAV bridge')
    return capital


def capital_summary(run, initial):
    daily = []
    for row in run['ledger']:
        states = [s for s in run['snapshots'] if s['date'] == row['date']]
        if not states:
            raise ValueError('Missing session snapshots')
        peak_state = max(states, key=committed)
        eod = next(s for s in states if s['phase'] == 'EOD')
        for field in ('cash', 'reserved_cash', 'buying_power', 'shares', 'share_acquisition_cost', 'equity'):
            if eod[field] != row[field]:
                raise ValueError('EOD snapshot/ledger mismatch: ' + field)
        daily.append(dict(date=row['date'], peak_committed=committed(peak_state),
            peak_snapshot_id=peak_state['snapshot_id'], eod_committed=committed(row),
            eod_cash=row['cash'], eod_reserved_cash=row['reserved_cash'],
            eod_unreserved_cash=row['buying_power'], eod_shares=row['shares'],
            equity=row['equity']))
    average = statistics.mean(r['peak_committed'] for r in daily)
    with_stock = sum(r['shares'] > 0 for r in run['ledger'])
    n = len(daily)
    pnl = run['metrics']['net_pnl']
    return dict(average_committed=average,
        average_eod_committed=statistics.mean(r['eod_committed'] for r in daily),
        return_on_average_committed=pnl / average if pnl is not None and average > 0 else None,
        utilization=average / initial,
        average_cash=statistics.mean(r['eod_cash'] for r in daily),
        average_reserved_cash=statistics.mean(r['eod_reserved_cash'] for r in daily),
        average_unreserved_cash=statistics.mean(r['eod_unreserved_cash'] for r in daily),
        sessions=n, sessions_with_shares=with_stock, sessions_without_shares=n-with_stock,
        share_session_fraction=with_stock/n, no_share_session_fraction=(n-with_stock)/n,
        account_return=run['metrics']['total_return'], net_pnl=pnl, daily=daily)


def fixed_share_benchmark(book, shares=100):
    """Rescale the real stock-only benchmark's per-share cash flows, not returns.

    Same initial $50k, same purchase print, linear per-share costs and dividends,
    same unadjusted marks, zero cash interest; no new price or execution assumed.
    """
    original = next(r for r in book['runs'] if r['strategy'] == 'buy_hold')
    cfg = book['config']; initial = cfg['initial_cash']
    buys = [e for e in original['events'] if e['event_type'] == 'STOCK_BUY']
    if len(buys) != 1 or shares <= 0 or not isinstance(shares, int) or cfg['cash_interest'] != 0:
        raise ValueError('Requires one stock purchase, integer shares and zero cash interest')
    if any(e['event_type'] not in ('STOCK_BUY', 'DIVIDEND_ENTITLEMENT', 'DIVIDEND_PAYMENT') for e in original['events']):
        raise ValueError('Benchmark contains unsupported transactions')
    buy = buys[0]; ratio = shares / buy['quantity']
    if shares * buy['fill_price'] * (1 + cfg['stock_slippage_bps'] / 10000) > initial:
        raise ValueError('Fixed-share benchmark cannot afford its initial purchase and costs')
    r = deepcopy(original); strategy = 'buy_hold_100'
    amounts = ('stock_value', 'dividend_receivable', 'dividend_income', 'realized_stock_pnl',
               'unrealized_stock_pnl', 'stock_execution_costs', 'realized_pnl_net')

    def state(s):
        if s['option'] or s['reserved_cash'] or s['commissions'] or s['assignment_fees']:
            raise ValueError('Fixed-share comparison must start from a stock-only account')
        s['strategy'] = strategy
        s['shares'] = round(s['shares'] * ratio)
        for key in ('cash', 'economic_cash', 'buying_power', 'equity'):
            if s[key] is not None: s[key] = initial + (s[key] - initial) * ratio
        for key in amounts: s[key] *= ratio
        for key in ('snapshot_id', 'event_id'):
            if s.get(key): s[key] = s[key].replace('buy_hold-', strategy + '-', 1)

    for row in r['ledger']: state(row)
    for row in r['snapshots']: state(row)
    for e in r['events']:
        e['strategy'] = strategy; e['event_id'] = e['event_id'].replace('buy_hold-', strategy+'-', 1)
        for key in ('before', 'after'): state(e[key])
        for key in ('gross_cash_flow', 'net_cash_flow', 'stock_execution_cost', 'realized_pnl_gross'):
            e[key] *= ratio
        for key in ('cash_before', 'cash_after'): e[key] = initial + (e[key]-initial)*ratio
        for key in ('shares_before', 'shares_after', 'quantity'): e[key] = round(e[key]*ratio)
        if e['event_type'] == 'STOCK_BUY':
            e['reason'] = 'Secondary fixed-100-share benchmark: same real entry print, stock costs and dividend rules; residual cash earns zero'
    metrics = calculate(r['ledger'], initial, cfg['start'], cfg['end'], cfg['risk_free_rate'])
    r['metrics'].update(metrics)
    for key in ('stock_execution_costs', 'total_costs'): r['metrics'][key] *= ratio
    r['metrics']['benchmark_excess_return'] = metrics['total_return'] - original['metrics']['total_return']
    r['strategy'] = strategy
    r['comparison_note'] = 'Fixed stock size, NOT equal delta, equal invested capital, or the Wheel holding schedule.'
    return r


def adjacent_returns(run, initial):
    previous = initial; result = {}
    for row in run['ledger']:
        nav = row['equity']
        value = nav / previous - 1 if nav is not None and previous is not None and previous > 0 else None
        if value is None:
            if row['daily_return'] is not None: raise ValueError('Return bridges a missing NAV')
        else:
            equal(row['daily_return'], value, 'adjacent-session return')
            result[row['date']] = value
        previous = nav
    return result


def return_statistics(values, risk_free):
    n = len(values)
    sd = statistics.stdev(values) if n > 1 else None
    rf_daily = (1 + risk_free)**(1/252) - 1
    return dict(count=n, annualized_volatility=sd*math.sqrt(252) if sd is not None else None,
        sharpe=(statistics.mean(values)-rf_daily)/sd*math.sqrt(252) if sd else None)


def prefix_drawdown(run, initial):
    peak = initial; minimum = 0.; dates = []
    for row in run['ledger']:
        if row['equity'] is None: break
        peak = max(peak, row['equity']); minimum = min(minimum, row['equity']/peak-1)
        dates.append(row['date'])
    return dict(start=dates[0] if dates else None, end=dates[-1] if dates else None,
                sessions=len(dates), max_drawdown=minimum if dates else None)


def build_research(book):
    initial = book['config']['initial_cash']; rf = book['config']['risk_free_rate']
    fixed = fixed_share_benchmark(book)
    runs = [*book['runs'], fixed]
    key = lambda r: r['strategy'] + ':' + r['fill_model']
    accounts = {key(r): dict(capital=capital_summary(r, initial), prefix=prefix_drawdown(r, initial)) for r in runs}
    by_return = {key(r): adjacent_returns(r, initial) for r in runs}
    common = {}
    for model in ('quoted_side', 'midpoint'):
        keys = ['wheel:'+model, 'buy_hold:quoted_side', 'buy_hold_100:quoted_side']
        dates = sorted(set.intersection(*(set(by_return[k]) for k in keys)))
        common[model] = dict(dates=dates, excluded_dates=sorted(set(book['runs'][0]['ledger'][i]['date'] for i in range(len(book['runs'][0]['ledger'])))-set(dates)),
            accounts={k:return_statistics([by_return[k][d] for d in dates], rf) for k in keys})
    return dict(schema_version=1, source_book_sha256=fingerprint(book), fixed_benchmark=fixed,
        accounts=accounts, common_observations=common,
        methodology={
            'capital':'At each modeled state: reserved put strike × multiplier × quantity + shares × gross acquisition cost. Fees remain expenses in P&L, not stock basis. Covered calls add no collateral. Average the maximum state commitment in each trading session, including pre-expiry states, over ALL sample sessions; this is not a measured continuous intraday maximum.',
            'return':'Endpoint net P&L (including dividends, unrealized liabilities and all costs) / average session-peak committed capital. Descriptive, non-annualized capital efficiency; not a time-weighted portfolio return, leveraged account return or a Sharpe denominator.',
            'utilization':'Average session-peak committed capital / initial account cash. EOD cash = reserved put cash + unreserved cash; averages of those cash fields use EOD snapshots. Stock cost is not its current market value; account equity includes marked stock and option liabilities.',
            'sessions':'Share/no-share percentages use EOD positions. No-share sessions may still contain cash-secured puts; they are not necessarily risk-free or uncommitted.',
            'sharpe':'Exact common dates of valid adjacent-session account returns, initial cash for the first session. (mean daily return − ((1+annual RF)^(1/252)−1)) / sample SD (ddof=1) × sqrt(252). This is a common-observation comparison, not recovered full-period Sharpe.',
            'timestamps':'Event timestamp and embedded/independent before/after states use the same modeled processing time: dividends at 09:30 ET, entries at closing reference, expiry/assignment just after close. mark_date records which observation date is used (prior close for opening dividend events); EOD follows all booked events. These are modeled times, not verified broker payment times.'})
