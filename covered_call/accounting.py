"""Cash changes only through book(); prices change valuation, never cash."""

from dataclasses import dataclass
import math


def finite(value):
    try:
        return value is not None and math.isfinite(float(value))
    except (ValueError, TypeError):
        return False


def midpoint(row):
    if row is None or not all(finite(row.get(k)) for k in ("bid", "ask")):
        return None
    bid, ask = float(row["bid"]), float(row["ask"])
    if bid < 0 or ask <= 0 or ask < bid:
        return None
    return (bid + ask) / 2


@dataclass
class Account:
    cash: float
    shares: int = 0
    call: dict | None = None

    def check(self):
        assert self.shares in (0, 100), "Shares must be 0 or 100"
        assert self.call is None or self.shares == 100, "Short call must be covered"
        assert finite(self.cash), "Non-finite cash"

    def book(self, event):
        action = event["action"]
        if action == "BUY":
            assert self.shares == 0 and self.call is None and event["quantity"] == 100
            assert math.isclose(event["cash_delta"], -100 * event["fill_price"])
            self.shares = 100
        elif action == "SELL":
            assert self.shares == 100 and self.call is None and event["quantity"] == 1
            assert math.isclose(event["cash_delta"], 100 * event["fill_price"])
            self.call = {key: event[key] for key in ("instrument", "strike", "expiry")}
        elif action == "EXPIRE":
            assert self.call is not None and event["cash_delta"] == 0
            self.call = None
        elif action == "ASSIGN":
            assert self.call is not None and self.shares == 100
            assert math.isclose(event["cash_delta"], 100 * self.call["strike"])
            self.shares = 0
            self.call = None
        else:
            raise ValueError(f"Unsupported blotter action: {action}")
        self.cash += event["cash_delta"]
        self.check()

    def valuation(self, stock_mark, option_mark):
        self.check()
        if self.shares and not finite(stock_mark):
            raise ValueError("Cannot value held stock without a past or current real mark")
        if self.call and not finite(option_mark):
            raise ValueError("Cannot value held option without a past or current real mark")
        lmv = self.shares * float(stock_mark) if self.shares else 0.0
        option_mv = -100 * float(option_mark) if self.call else 0.0
        nav = self.cash + lmv + option_mv
        initial = 0.5 * lmv
        maintenance = 0.25 * lmv
        return dict(cash=self.cash, shares=self.shares, stock_mark=stock_mark,
                    stock_mv=lmv, lmv=lmv, short_call_quantity=-1 if self.call else 0,
                    call_ric=self.call["instrument"] if self.call else None,
                    call_strike=self.call["strike"] if self.call else None,
                    call_expiry=self.call["expiry"] if self.call else None,
                    option_mark=option_mark if self.call else None, option_mv=option_mv,
                    nav=nav, initial_margin=initial, maintenance_margin=maintenance,
                    available_funds=nav-initial, excess=nav-maintenance)
