"""RIC construction for standard US equity options, with explicit conventions."""

from datetime import date
from decimal import Decimal
import re


def option_ric(equity_ric: str, expiry: date, strike: float, cp: str = "C", *, expired=True, pad_day=False) -> str:
    root = equity_ric.split(".", 1)[0].upper()
    if not re.fullmatch(r"[A-Z]+", root):
        raise ValueError("Only standard alphabetic equity roots are supported")
    if cp not in {"C", "P"}:
        raise ValueError("cp must be C or P")
    cents = Decimal(str(strike)) * 100
    if cents != cents.to_integral_value() or not 0 < cents < 100000:
        raise ValueError("Strike must fit the standard five-digit cents encoding")
    month = chr(ord("A" if cp == "C" else "M") + expiry.month - 1)
    # LSEG's expiration suffix is A-L even for puts (verified in Assignment 1.1).
    # For this calls-only strategy it is also the same letter as the option code.
    suffix = chr(ord("A") + expiry.month - 1)
    # Default reproduces the assignment's non-padded examples. The live AAPL
    # service required padded days in two paired real tests (2026-08-07/09-04).
    day = f"{expiry.day:02d}" if pad_day else str(expiry.day)
    base = f"{root}{month}{day}{expiry:%y}{int(cents):05d}.U"
    return f"{base}^{suffix}{expiry:%y}" if expired else base
