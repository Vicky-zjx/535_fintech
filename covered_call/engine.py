"""Chronological, event-driven covered calls; never uses a future row for a decision."""

from collections import defaultdict
from datetime import timedelta
import math
import numpy as np
import pandas as pd

from .accounting import Account, finite, midpoint
from .config import Config
from .ingest import validate_bars
from .universe import available_contracts, observed_contracts


def local_timestamp(day, time, config):
    return pd.Timestamp(f"{day} {time}", tz=config.timezone)


def run_backtest(stock, options, config=Config()):
    validate_bars(stock, options, config)
    contracts = observed_contracts(options)
    stock_at = {pd.Timestamp(r["timestamp"]): r for r in stock}
    options_at = defaultdict(list)
    for row in options:
        options_at[pd.Timestamp(row["timestamp"])].append(row)
    start = local_timestamp(config.start, "00:00", config)
    end = local_timestamp(config.end, "23:59", config)
    # Explicit decision and expiry clocks also exist when the feed has no row.
    weekdays = pd.date_range(config.start, config.end, freq="B")
    timeline = {t for t in stock_at if start <= t <= end}
    timeline.update(t for t in options_at if start <= t <= end)
    timeline.update(local_timestamp(d.date(), config.entry_time, config) for d in weekdays if d.weekday() == 0)
    timeline.update(local_timestamp(d.date(), config.expiry_time, config) for d in weekdays if d.weekday() == 4)
    timeline.add(local_timestamp(config.start, "09:30", config))

    account = Account(config.initial_cash)
    blotter, ledger, decisions = [], [], []
    stock_mark = stock_source = None
    quote_marks = {}
    for row in sorted(options, key=lambda r: r['timestamp']):
        ts = pd.Timestamp(row['timestamp'])
        if ts >= start:
            continue
        mid = midpoint(row)
        if mid is not None:
            quote_marks[row['ric']] = (mid, ts)
    status = "complete"

    def snapshot(ts, phase, event_id=None):
        opt_value, opt_source = (None, None)
        if account.call:
            opt_value, opt_source = quote_marks[account.call["instrument"]]
        row = account.valuation(stock_mark, opt_value)
        row.update(timestamp=ts.isoformat(), phase=phase, event_id=event_id,
                   stock_mark_timestamp=stock_source.isoformat() if stock_source is not None else None,
                   option_mark_timestamp=opt_source.isoformat() if opt_source is not None else None,
                   stock_mark_stale=bool(account.shares and stock_source != ts),
                   option_mark_stale=bool(account.call and opt_source != ts),
                   margin_breach=row["available_funds"] < -1e-8 or row["excess"] < -1e-8)
        ledger.append(row)

    def book(ts, action, instrument, quantity, fill, delta, note, strike=None, expiry=None, limit=None, bid=None, ask=None):
        event = dict(id=len(blotter)+1, timestamp=ts.isoformat(), instrument=instrument,
                     action=action, quantity=quantity, strike=strike, expiry=expiry,
                     limit_price=limit, fill_price=fill, cash_delta=delta, note=note,
                     bid=bid, ask=ask)
        account.book(event)
        event["cash_after"] = account.cash
        blotter.append(event)
        snapshot(ts, f"after_{action.lower()}", event["id"])

    for ts in sorted(timeline):
        local = ts.tz_convert(config.timezone)
        if not ("09:30" <= local.strftime("%H:%M") <= "16:00"):
            continue
        stock_row = stock_at.get(ts)
        if stock_row and finite(stock_row["print"]) and stock_row["print"] > 0:
            stock_mark, stock_source = float(stock_row["print"]), ts
        current_options = {}
        for row in options_at.get(ts, []):
            current_options[row["ric"]] = row
            mid = midpoint(row)
            if mid is not None:
                quote_marks[row["ric"]] = (mid, ts)

        if account.call and local.date() >= pd.Timestamp(account.call["expiry"]).date() and local.strftime("%H:%M") == config.expiry_time:
            if stock_source != ts:
                decisions.append(dict(timestamp=ts.isoformat(), outcome="unresolved", reason="Missing expiry stock print; assignment cannot be inferred from an earlier or future price."))
                snapshot(ts, "unresolved_expiry")
                status = "incomplete_expiry_data"
                break
            call = dict(account.call)
            if stock_mark > call["strike"]:
                book(ts, "ASSIGN", call["instrument"], 1, call["strike"], 100*call["strike"],
                     f"Expiry stock print {stock_mark:.4f} > strike {call['strike']:.2f}: deliver 100 shares at strike; shares and call become zero.",
                     call["strike"], call["expiry"])
            else:
                book(ts, "EXPIRE", call["instrument"], 1, 0.0, 0.0,
                     f"Expiry stock print {stock_mark:.4f} <= strike {call['strike']:.2f}: expire at zero; retain 100 shares.",
                     call["strike"], call["expiry"])

        if local.weekday() == 0 and local.strftime("%H:%M") == config.entry_time:
            expiry = (local.date() + timedelta(days=4)).isoformat()
            observed = available_contracts(contracts, expiry, ts)
            decision = dict(timestamp=ts.isoformat(), expiry=expiry, outcome="skipped", reason="", spot=None, target=None,
                            selected_strike=None, ric=None,
                            observed_strikes=sorted({r['strike'] for r in observed}),
                            eligible_strikes=[], selected_first_observed_at=None, selected_evidence=None)
            decisions.append(decision)
            if account.call:
                decision["reason"] = "An existing call is still open; a second short call is forbidden."
            elif stock_source != ts:
                decision["reason"] = "No stock print at the exact Monday bar end (holiday or missing data); no later fill."
            else:
                decision.update(spot=stock_mark, target=stock_mark * (1+config.target_otm))
                candidates = available_contracts(observed, expiry, ts, decision['target'])
                decision['eligible_strikes'] = sorted({r['strike'] for r in candidates})
                if account.shares == 0:
                    proposed_available = account.cash - 0.5 * 100 * stock_mark
                    if proposed_available < -1e-8:
                        decision["reason"] = f"Reg T rejected stock purchase: prospective available funds ${proposed_available:.2f}."
                        snapshot(ts, "rejected_entry")
                        continue
                    book(ts, "BUY", config.stock_ric, 100, stock_mark, -100*stock_mark,
                         "Flat on Monday -> buy exactly 100 shares at the observed stock print; Reg T checked before booking.")
                if not candidates:
                    decision["reason"] = "No observed same-Friday call at or above the target has quote/print evidence by entry. Coverage is incomplete; this does not mean no such listed strike exists. Shares are retained."
                else:
                    chosen = candidates[0]
                    decision.update(selected_strike=chosen["strike"], ric=chosen["ric"],
                                    selected_first_observed_at=chosen['first_observed_at'],
                                    selected_evidence=chosen['evidence'])
                    row = current_options.get(chosen["ric"])
                    mid = midpoint(row)
                    if mid is None:
                        decision["reason"] = "Selected observed strike has missing, negative, or crossed BID/ASK at entry; skip option without substituting another strike or a future quote."
                    elif account.valuation(stock_mark, None)["available_funds"] < -1e-8:
                        decision["reason"] = "Reg T rejected call entry: available funds are negative."
                    else:
                        book(ts, "SELL", chosen["ric"], 1, mid, 100*mid,
                             f"5% OTM target {decision['target']:.4f} -> smallest qualifying observed strike {chosen['strike']:.2f}; simulated limit fill at same-bar (BID+ASK)/2.",
                             chosen["strike"], expiry, limit=mid, bid=row["bid"], ask=row["ask"])
                        decision.update(outcome="filled", reason="Smallest qualifying observed strike; valid same-bar midpoint; covered and Reg T admissible.")
            snapshot(ts, "entry_decision")
        else:
            snapshot(ts, "bar_close")

    if account.call and status == "complete":
        status = "incomplete_open_option"
    reconciliation = audit(blotter, ledger, config)
    validation = mid_trade_validation(stock, options, config)
    calls = [r for r in blotter if r["action"] == "SELL"]
    assigns = [r for r in blotter if r["action"] == "ASSIGN"]
    expires = [r for r in blotter if r["action"] == "EXPIRE"]
    end_nav = ledger[-1]["nav"] if ledger else config.initial_cash
    peak = config.initial_cash
    max_dd = 0.0
    for row in ledger:
        peak = max(peak, row["nav"])
        if peak > 0:
            max_dd = min(max_dd, row["nav"] / peak - 1)
    metrics = dict(starting_nav=config.initial_cash, ending_nav=end_nav,
                   total_return=end_nav/config.initial_cash-1,
                   premium_collected=sum(r["cash_delta"] for r in calls), calls_sold=len(calls),
                   expired=len(expires), assigned=len(assigns),
                   skipped_weeks=sum(r["outcome"] == "skipped" for r in decisions),
                   assignment_rate=len(assigns)/len(calls) if calls else None,
                   max_drawdown=max_dd, ending_cash=account.cash, ending_shares=account.shares,
                   ending_short_calls=-1 if account.call else 0,
                   stale_option_marks=sum(r["option_mark_stale"] for r in ledger),
                   stale_stock_marks=sum(r["stock_mark_stale"] for r in ledger),
                   margin_breach_rows=sum(r["margin_breach"] for r in ledger))
    return dict(status=status, config=config.to_dict(), metrics=metrics, blotter=blotter,
                ledger=ledger, decisions=decisions, validation=validation, audit=reconciliation)


def audit(blotter, ledger, config):
    cash = config.initial_cash
    event_cash = {0: cash}
    for event in blotter:
        cash += event["cash_delta"]
        assert math.isclose(cash, event["cash_after"], abs_tol=1e-7)
        event_cash[event["id"]] = cash
    current_id = 0
    for row in ledger:
        if row["event_id"]:
            current_id = row["event_id"]
        assert math.isclose(row["cash"], event_cash[current_id], abs_tol=1e-7)
        assert row["shares"] in (0, 100)
        assert row["short_call_quantity"] in (0, -1)
        assert not row["short_call_quantity"] or row["shares"] == 100
        assert math.isclose(row["nav"], row["cash"] + row["stock_mv"] + row["option_mv"], abs_tol=1e-7)
        assert math.isclose(row["initial_margin"], 0.5 * row["lmv"], abs_tol=1e-7)
        assert math.isclose(row["maintenance_margin"], 0.25 * row["lmv"], abs_tol=1e-7)
        for source in ("stock_mark_timestamp", "option_mark_timestamp"):
            assert row[source] is None or pd.Timestamp(row[source]) <= pd.Timestamp(row["timestamp"])
    return dict(passed=True, booked_events=len(blotter), ledger_rows=len(ledger),
                cash_reconciled=cash, checks=["Cash reconciles to blotter", "NAV = cash + stock MV + negative short-call MV", "100 shares / one covered call maximum", "50% initial / 25% maintenance", "Mark source timestamps never exceed ledger timestamps"])


def mid_trade_validation(stock, options, config):
    stock_at = {pd.Timestamp(r["timestamp"]): r for r in stock}
    points = []
    for row in options:
        s = stock_at.get(pd.Timestamp(row["timestamp"]))
        mid = midpoint(row)
        if not s or not finite(s["print"]) or s["print"] <= 0 or mid is None or not finite(row["print"]) or row["print"] < 0:
            continue
        if abs(row["strike"] / s["print"] - 1) > config.validation_moneyness:
            continue
        points.append(dict(timestamp=row["timestamp"], ric=row["ric"], strike=row["strike"],
                           mid=mid, trade=row["print"], bid=row["bid"], ask=row["ask"]))
    fit = None
    if len(points) >= 3:
        x = np.array([r["mid"] for r in points])
        y = np.array([r["trade"] for r in points])
        if np.ptp(x) > 0 and np.ptp(y) > 0:
            slope, intercept = np.polyfit(x, y, 1)
            r2 = 1 - float(np.sum((y-(slope*x+intercept))**2) / np.sum((y-y.mean())**2))
            fit = dict(slope=float(slope), intercept=float(intercept), r2=r2,
                       median_abs_gap=float(np.median(np.abs(x-y))))
    return dict(points=points, count=len(points), fit=fit,
                definition="Same hourly bar: finite valid BID and ASK, actual TRDPRC_1, and |strike/stock print - 1| <= 5%. Mid is X; TRDPRC_1 is Y.")
