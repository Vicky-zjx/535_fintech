"""The one source of strategy configuration; all timestamps are bar ends."""

from dataclasses import asdict, dataclass
from datetime import date, time
import math

ENTRY_TIME = "11:00"
INITIAL_CASH = 30_000.0


@dataclass(frozen=True)
class Config:
    ticker: str = "AAPL"
    stock_ric: str = "AAPL.O"
    start: str = "2026-07-06"
    end: str = "2026-09-11"
    entry_time: str = ENTRY_TIME
    initial_cash: float = INITIAL_CASH
    timezone: str = "America/New_York"
    bar_minutes: int = 60
    target_otm: float = 0.05
    validation_moneyness: float = 0.05
    expiry_time: str = "16:00"

    def __post_init__(self):
        if not math.isfinite(self.initial_cash) or self.initial_cash <= 0:
            raise ValueError("INITIAL_CASH must be positive and finite")
        if self.bar_minutes != 60:
            raise ValueError("This implementation requires matched 60-minute bars")
        if not math.isfinite(self.target_otm) or self.target_otm < 0:
            raise ValueError("Target OTM must be finite and nonnegative")
        clock = time.fromisoformat(self.entry_time)
        if clock.minute != 0 or clock.second != 0 or not 10 <= clock.hour < 16:
            raise ValueError("ENTRY_TIME must be a completed regular-session hourly bar end before 16:00")
        if date.fromisoformat(self.start) > date.fromisoformat(self.end):
            raise ValueError("Backtest start must not follow end")

    def to_dict(self):
        return asdict(self)
