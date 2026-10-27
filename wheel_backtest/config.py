"""Fixed before inspecting Wheel returns; override through a JSON config."""
from dataclasses import asdict, dataclass
from datetime import date
import math


@dataclass(frozen=True)
class Config:
    stock_ric: str = 'AAPL.O'
    start: str = '2026-07-06'
    end: str = '2026-09-30'
    initial_cash: float = 50_000.0
    contracts: int = 1
    selection: str = 'historical_delta'
    put_delta: float = -.25
    call_delta: float = .25
    delta_tolerance: float = .15
    otm_fraction: float = .05
    dte_target: int = 7
    dte_min: int = 3
    dte_max: int = 10
    call_cost_floor: bool = True
    option_commission: float = .65
    stock_slippage_bps: float = 1.0
    assignment_fee: float = 0.0
    assignment_itm: float = .01
    early_assignment: str = 'dividend_call'
    risk_free_rate: float = 0.0
    cash_interest: float = 0.0
    max_relative_spread: float = 1.0

    def __post_init__(self):
        if date.fromisoformat(self.start)>date.fromisoformat(self.end): raise ValueError('Reversed sample')
        if self.contracts!=1: raise ValueError('One standard contract is the supported baseline')
        if not self.stock_ric or not math.isfinite(self.initial_cash) or self.initial_cash<=0: raise ValueError('Positive capital required')
        if self.selection not in ('historical_delta','otm_moneyness'): raise ValueError('Unsupported selection')
        if self.early_assignment not in ('dividend_call','expiry_only'): raise ValueError('Unsupported assignment model')
        if not 0<self.dte_min<=self.dte_target<=self.dte_max: raise ValueError('Invalid DTE window')
        if not -1<self.put_delta<0<self.call_delta<1: raise ValueError('Invalid delta target')
        for k in ('delta_tolerance','otm_fraction','option_commission','stock_slippage_bps','assignment_fee','assignment_itm','risk_free_rate','max_relative_spread'):
            if not math.isfinite(getattr(self,k)) or getattr(self,k)<0: raise ValueError('Invalid '+k)
        if self.otm_fraction>=1 or self.cash_interest!=0: raise ValueError('Invalid moneyness or unsupported interest model')

    def to_dict(self): return asdict(self)
