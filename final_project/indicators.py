"""Shared, gap-aware indicators. Dates are completed exchange sessions, not rows."""
import math
import statistics
from .strategy_config import MAX_HV, MIN_R5


def valid_close(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


class IndicatorUnavailable(ValueError):
    def __init__(self, reason, diagnostics):
        super().__init__(reason)
        self.diagnostics = diagnostics


def compute(observed, sessions):
    """Latest 50/20 valid closes and 20 adjacent-session returns within 55 sessions.

    Historical analysis and the nightly planner call this exact implementation.
    R5 is still five EXCHANGE sessions, not five observed rows.
    """
    dates = list(sessions[-55:])
    values = [observed.get(d) for d in dates]
    valid = [(d, v) for d, v in zip(dates, values) if valid_close(v)]
    pairs = [(dates[i-1], dates[i], math.log(values[i]/values[i-1]))
             for i in range(1, len(dates)) if valid_close(values[i-1]) and valid_close(values[i])][-20:]
    quality = dict(window_start=dates[0] if dates else None, window_end=dates[-1] if dates else None,
                   expected_sessions=len(dates), valid_closes=len(valid),
                   missing_dates=[d for d, v in zip(dates, values) if not valid_close(v)],
                   sma20_dates=[d for d, _ in valid[-20:]], sma50_dates=[d for d, _ in valid[-50:]],
                   hv20_return_pairs=[[a, b] for a, b, _ in pairs],
                   r5_anchor_date=dates[-6] if len(dates) >= 6 else None)
    result = dict(close=values[-1] if values and valid_close(values[-1]) else None,
                  price_date=dates[-1] if values and valid_close(values[-1]) else None,
                  observation_window=quality)
    if result['close'] is None:
        raise IndicatorUnavailable('Latest completed exchange session close is missing/stale', result)
    if len(valid) < 50:
        raise IndicatorUnavailable('Require at least 50 valid closing observations within the latest 55 completed exchange sessions', result)
    if len(pairs) < 20:
        raise IndicatorUnavailable('HV20 requires 20 valid adjacent-session log returns within the latest 55 sessions', result)
    if not valid_close(values[-6]):
        raise IndicatorUnavailable('Five-day return unavailable: close five exchange sessions earlier is missing', result)
    result.update(sma20=statistics.mean(v for _, v in valid[-20:]),
                  sma50=statistics.mean(v for _, v in valid[-50:]),
                  hv20=statistics.stdev(v for _, _, v in pairs)*math.sqrt(252),
                  r5=values[-1]/values[-6]-1)
    result['filters'] = dict(trend=result['close'] >= result['sma50'] and result['sma20'] >= result['sma50'],
                           volatility=result['hv20'] <= MAX_HV, sudden_drop=result['r5'] >= MIN_R5)
    return result
