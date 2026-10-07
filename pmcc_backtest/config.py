"""Predeclared research rules, fixed before computing any PMCC performance."""
from dataclasses import asdict, dataclass
from datetime import date
import math


@dataclass(frozen=True)
class Config:
    start: str = '2025-10-01'
    end: str = '2026-09-30'
    stock_ric: str = 'AAPL.O'
    initial_equity: float = 50_000.0
    timezone: str = 'America/New_York'
    long_mode: str = '75%-of-spot strike proxy'
    long_dte_min: int = 365
    long_dte_max: int = 550
    long_dte_target: int = 450
    long_proxy: float = .75
    long_delta_min: float = .70
    long_delta_max: float = .90
    long_delta_target: float = .80
    replace_dte: int = 90
    short_otm: float = .05
    option_commission: float = .65
    stock_slippage_bps: float = 1.0
    borrow_rate: float = .03
    cash_interest: float = 0.0
    assignment_itm: float = .01
    signal_time: str = '09:00'

    def __post_init__(self):
        if date.fromisoformat(self.start) > date.fromisoformat(self.end):
            raise ValueError('Start follows end')
        if self.long_mode not in {'75%-of-spot strike proxy', 'historical delta'}:
            raise ValueError('Fix one supported long selection mode for the whole run')
        if self.timezone != 'America/New_York' or self.signal_time != '09:00':
            raise ValueError('Protocol requires the next-session 09:00 ET signal checkpoint')
        for k in ('initial_equity','option_commission','stock_slippage_bps','borrow_rate','short_otm'):
            if not math.isfinite(getattr(self,k)) or getattr(self,k) < 0:
                raise ValueError(f'Invalid {k}')
        if self.initial_equity <= 0 or self.cash_interest != 0:
            raise ValueError('Positive equity and the declared zero-interest baseline are required')

    def to_dict(self):
        return asdict(self)
