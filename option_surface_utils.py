"""
Shared utilities for the options surface lab.

Parses LSEG/Refinitiv expired-option history (TRDPRC_1 + MID_PRICE) into a
tidy long table, and can synthesize a realistic sparse panel when the
pickle cache / LSEG session is unavailable.
"""

from __future__ import annotations

import datetime as dt
import pickle
import re
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.interpolate import griddata


# OPRA month codes used in the RIC constructor in the original pipeline
CALL_MONTHS = {chr(ord("A") + i): i + 1 for i in range(12)}
PUT_MONTHS = {chr(ord("M") + i): i + 1 for i in range(12)}
MONTH_CODE_TO_CP = {**{k: "C" for k in CALL_MONTHS}, **{k: "P" for k in PUT_MONTHS}}
MONTH_CODE_TO_MONTH = {**CALL_MONTHS, **PUT_MONTHS}

# UUUUA1502600650.U   or   UUUUA1502600650.U^A26
RIC_RE = re.compile(
    r"^(?P<root>[A-Z]+)(?P<code>[A-X])(?P<day>\d{2})(?P<year>\d{2})"
    r"(?P<strike>\d{5})(?:\.U)?(?:\^[A-X]\d{2})?$",
    re.IGNORECASE,
)

# The Canvas example contains an extra zero before the two-digit year. Keep
# this narrow compatibility pattern so that example can still be inspected,
# while the normal constructor above remains the source of generated RICs.
RIC_EXAMPLE_RE = re.compile(
    r"^(?P<root>[A-Z]+)(?P<code>[A-X])(?P<day>\d{2})0(?P<year>\d{2})"
    r"(?P<strike>\d{5})(?:\.U)?(?:\^[A-X]\d{2})?$",
    re.IGNORECASE,
)

_TIDY_COLUMNS = [
    "date",
    "ric",
    "field",
    "value",
    "root",
    "underlying",
    "cp",
    "put_call",
    "expiry",
    "strike",
    "month_code",
    "dte",
]

_VALUE_FIELDS = {"TRDPRC_1", "MID_PRICE", "SETTLE", "CLOSE", "BID", "ASK"}


def has_option_field(df_options: pd.DataFrame | None, field: str) -> bool:
    """Return whether an option history frame contains a requested field."""
    if df_options is None or df_options.empty:
        return False
    wanted = str(field).upper()
    columns = df_options.columns
    if isinstance(columns, pd.MultiIndex):
        return any(
            str(value).strip().upper() == wanted
            for level in range(columns.nlevels)
            for value in columns.get_level_values(level)
        )
    return any(
        wanted in str(column).upper()
        for column in columns
    )


def parse_option_ric(ric: str) -> dict | None:
    """Extract root, put/call, expiry, strike from an expired OPRA-style RIC."""
    text = str(ric).strip()
    m = RIC_RE.match(text) or RIC_EXAMPLE_RE.match(text)
    if not m:
        return None
    code = m.group("code").upper()
    month = MONTH_CODE_TO_MONTH.get(code)
    cp = MONTH_CODE_TO_CP.get(code)
    if month is None or cp is None:
        return None
    year = 2000 + int(m.group("year"))
    day = int(m.group("day"))
    try:
        expiry = dt.date(year, month, day)
    except ValueError:
        return None
    strike = int(m.group("strike")) / 100.0
    return {
        "ric": text,
        "root": m.group("root").upper(),
        "underlying": m.group("root").upper(),
        "cp": cp,
        "put_call": cp,
        "expiry": expiry,
        "strike": strike,
        "month_code": code,
    }


def flatten_lseg_options(df_options: pd.DataFrame) -> pd.DataFrame:
    """
    Collapse LSEG get_history output into a tidy table.

    LSEG may return:
      - MultiIndex columns (RIC, field)
      - MultiIndex columns (field, RIC)
      - flat columns that are just RICs (single field — not expected here)
    """
    if df_options is None or df_options.empty:
        return pd.DataFrame(columns=_TIDY_COLUMNS)

    frame = df_options.copy()
    frame.index = pd.to_datetime(frame.index, errors="coerce")
    frame = frame.loc[~frame.index.isna()]

    rows = []

    def append_series(ric: str, field: str, series: pd.Series) -> None:
        """Append finite numeric observations from one RIC/field column."""
        parsed = parse_option_ric(ric)
        if parsed is None:
            return
        field = str(field).strip().upper()
        if field not in _VALUE_FIELDS:
            return
        for ts, val in series.dropna().items():
            try:
                num = float(val)
            except (TypeError, ValueError):
                continue
            if not np.isfinite(num):
                continue
            timestamp = pd.Timestamp(ts)
            if pd.isna(timestamp):
                continue
            rows.append(
                {
                    "date": timestamp.normalize(),
                    "ric": str(ric).strip(),
                    "field": field,
                    "value": num,
                    **parsed,
                }
            )
    cols = frame.columns

    if isinstance(cols, pd.MultiIndex):
        # Detect which level is the field name.
        level_values = [set(map(str, cols.get_level_values(i))) for i in range(cols.nlevels)]
        field_level = None
        for i, vals in enumerate(level_values):
            upper = {v.upper() for v in vals}
            if upper & _VALUE_FIELDS:
                field_level = i
                break
        if field_level is None:
            # LSEG's normal shape is (RIC, field), but retain a useful
            # fallback for two-level frames with non-standard field labels.
            field_level = 1 if cols.nlevels > 1 else 0
        ric_level = 1 - field_level if cols.nlevels == 2 else 0

        for col in cols:
            ric = str(col[ric_level])
            field = str(col[field_level]).upper()
            append_series(ric, field, frame[col])
    else:
        # Flat columns — support "RIC | FIELD", "RIC_FIELD", and just RIC.
        for col in cols:
            label = str(col)
            field = "TRDPRC_1"
            ric = label
            pieces = [piece.strip() for piece in re.split(r"\s*[|:]\s*", label, maxsplit=1)]
            if len(pieces) == 2:
                if pieces[0].upper() in _VALUE_FIELDS:
                    field, ric = pieces
                else:
                    ric, field = pieces
            else:
                for candidate in sorted(_VALUE_FIELDS, key=len, reverse=True):
                    suffix = f"_{candidate}"
                    if label.upper().endswith(suffix):
                        ric = label[: -len(suffix)]
                        field = candidate
                        break
            append_series(ric, field, frame[col])

    tidy = pd.DataFrame(rows)
    if tidy.empty:
        return pd.DataFrame(columns=_TIDY_COLUMNS)
    tidy["date"] = pd.to_datetime(tidy["date"])
    tidy["expiry"] = pd.to_datetime(tidy["expiry"])
    tidy["dte"] = (tidy["expiry"] - tidy["date"]).dt.days
    tidy = tidy[tidy["dte"] >= 0].copy()
    return tidy


def attach_underlying(tidy: pd.DataFrame, df_stock: pd.DataFrame) -> pd.DataFrame:
    """Join each option row to that day's underlying close (TRDPRC_1)."""
    if tidy.empty:
        tidy = tidy.copy()
        tidy["spot"] = np.nan
        tidy["moneyness"] = np.nan
        return tidy
    if df_stock is None or df_stock.empty:
        tidy["spot"] = np.nan
        tidy["moneyness"] = np.nan
        return tidy

    stock = df_stock.copy()
    if not isinstance(stock.index, pd.DatetimeIndex):
        stock.index = pd.to_datetime(stock.index)
    close_col = "TRDPRC_1" if "TRDPRC_1" in stock.columns else stock.columns[-1]
    spot = pd.to_numeric(stock[close_col], errors="coerce").dropna()
    spot.index = pd.DatetimeIndex(spot.index).normalize()
    tidy = tidy.copy()
    spot_map = spot.to_dict()
    tidy["spot"] = tidy["date"].map(lambda d: spot_map.get(pd.Timestamp(d).normalize(), np.nan))
    # forward-fill from nearest prior session if exact date missing
    if tidy["spot"].isna().any():
        all_dates = pd.DatetimeIndex(sorted(spot_map.keys()))
        def _nearest_spot(d):
            d = pd.Timestamp(d).normalize()
            if d in spot_map:
                return spot_map[d]
            prior = all_dates[all_dates <= d]
            if len(prior):
                return spot_map[prior[-1]]
            return np.nan
        tidy.loc[tidy["spot"].isna(), "spot"] = tidy.loc[tidy["spot"].isna(), "date"].map(_nearest_spot)

    tidy["moneyness"] = tidy["strike"] / tidy["spot"].replace(0, np.nan)
    return tidy


def pivot_trade_mid(tidy: pd.DataFrame) -> pd.DataFrame:
    """One row per (date, ric) with TRDPRC_1 and MID_PRICE side by side."""
    if tidy.empty:
        columns = [
            "date", "ric", "root", "underlying", "cp", "put_call", "expiry",
            "strike", "dte", "spot", "moneyness", "TRDPRC_1", "MID_PRICE",
            "has_trade", "has_mid", "abs_diff", "rel_diff",
        ]
        return pd.DataFrame(columns=columns)
    keep = tidy[tidy["field"].isin(["TRDPRC_1", "MID_PRICE", "CLOSE"])].copy()
    keep["field"] = keep["field"].replace({"CLOSE": "TRDPRC_1"})
    idx_cols = ["date", "ric", "root", "cp", "expiry", "strike", "dte", "spot", "moneyness"]
    idx_cols = [c for c in idx_cols if c in keep.columns]
    wide = (
        keep.pivot_table(index=idx_cols, columns="field", values="value", aggfunc="last")
        .reset_index()
    )
    wide.columns.name = None
    if "TRDPRC_1" not in wide.columns:
        wide["TRDPRC_1"] = np.nan
    if "MID_PRICE" not in wide.columns:
        wide["MID_PRICE"] = np.nan
    wide["has_trade"] = wide["TRDPRC_1"].notna()
    wide["has_mid"] = wide["MID_PRICE"].notna()
    wide["abs_diff"] = (wide["MID_PRICE"] - wide["TRDPRC_1"]).abs()
    wide["rel_diff"] = wide["abs_diff"] / wide["MID_PRICE"].replace(0, np.nan)
    return wide


def pivot_trade_settle(tidy: pd.DataFrame) -> pd.DataFrame:
    """Backward-compatible alias for older notebooks; use pivot_trade_mid."""
    return pivot_trade_mid(tidy)


def select_asof_rows(
    wide: pd.DataFrame | None,
    asof=None,
    cp: str | None = None,
) -> pd.DataFrame:
    """Select one normalized as-of date and optional call/put filter.

    Every consumer of the surface data uses this helper so date dtype,
    timezone, and call/put matching cannot diverge between metrics and plots.
    """
    if wide is None:
        return pd.DataFrame()
    sl = wide.copy()
    if "date" in sl.columns:
        parsed_dates = pd.to_datetime(sl["date"], errors="coerce", format="mixed")
        if isinstance(parsed_dates.dtype, pd.DatetimeTZDtype):
            parsed_dates = parsed_dates.dt.tz_localize(None)
        sl["date"] = parsed_dates.dt.normalize()

    if asof is not None:
        target = pd.to_datetime([asof], errors="coerce", format="mixed")[0]
        if pd.isna(target):
            return sl.iloc[0:0].copy()
        target = pd.Timestamp(target)
        if target.tzinfo is not None:
            target = target.tz_localize(None)
        target = target.normalize()
        if "date" not in sl.columns:
            return sl.iloc[0:0].copy()
        sl = sl.loc[sl["date"].eq(target)].copy()

    wanted_cp = str(cp or "").strip().upper()
    if wanted_cp not in {"", "B", "ALL"} and "cp" in sl.columns:
        sl = sl.loc[sl["cp"].astype("string").str.upper().eq(wanted_cp)].copy()
    return sl


def paired_quote_rows(
    wide: pd.DataFrame | None,
    asof=None,
    cp: str | None = None,
) -> pd.DataFrame:
    """Return only real rows containing both finite mid and trade values."""
    sl = select_asof_rows(wide, asof=asof, cp=cp)
    required = {"MID_PRICE", "TRDPRC_1"}
    if not required.issubset(sl.columns):
        return sl.iloc[0:0].copy()
    mid = pd.to_numeric(sl["MID_PRICE"], errors="coerce")
    trade = pd.to_numeric(sl["TRDPRC_1"], errors="coerce")
    valid = mid.notna() & trade.notna() & np.isfinite(mid) & np.isfinite(trade)
    paired = sl.loc[valid].copy()
    paired["MID_PRICE"] = mid.loc[valid]
    paired["TRDPRC_1"] = trade.loc[valid]
    return paired


def best_coverage_asof(
    wide: pd.DataFrame | None,
    cp: str | None = None,
):
    """Return the latest date with the largest real mid-or-trade coverage."""
    sl = select_asof_rows(wide, cp=cp)
    if sl.empty or "date" not in sl.columns:
        return None
    if not {"MID_PRICE", "TRDPRC_1"}.issubset(sl.columns):
        return None
    mid = pd.to_numeric(sl["MID_PRICE"], errors="coerce")
    trade = pd.to_numeric(sl["TRDPRC_1"], errors="coerce")
    has_either = (
        (mid.notna() & np.isfinite(mid))
        | (trade.notna() & np.isfinite(trade))
    )
    coverage = has_either.groupby(sl["date"]).sum()
    coverage = coverage[coverage.index.notna()]
    if coverage.empty:
        return None
    max_count = coverage.max()
    return coverage[coverage == max_count].index.max()


def surface_grid(points: pd.DataFrame, value_col: str, n_strike: int = 40, n_dte: int = 30):
    """
    Interpolate a sparse cloud onto a regular grid for a Plotly Surface.
    Returns None if there are too few points.
    """
    required = {"strike", "dte", value_col}
    if points is None or not required.issubset(points.columns):
        return None
    cloud = points.dropna(subset=list(required)).copy()
    cloud = cloud.groupby(["strike", "dte"], as_index=False)[value_col].mean()
    if len(cloud) < 8 or cloud["strike"].nunique() < 2 or cloud["dte"].nunique() < 2:
        return None
    x = cloud["strike"].to_numpy(float)
    y = cloud["dte"].to_numpy(float)
    z = cloud[value_col].to_numpy(float)
    xi = np.linspace(x.min(), x.max(), n_strike)
    yi = np.linspace(max(0, y.min()), y.max(), n_dte)
    XX, YY = np.meshgrid(xi, yi)
    try:
        ZZ = griddata((x, y), z, (XX, YY), method="linear")
    except Exception:
        # A sparse or nearly collinear cloud cannot define a 2D linear
        # surface. Returning no sheet is more honest than extrapolating it.
        return None
    # leave holes as None so Plotly does not invent a sheet over empty wings
    return {"x": xi, "y": yi, "z": ZZ}


def summarize_sparsity(wide: pd.DataFrame, asof=None, cp: str | None = None) -> dict:
    """Classroom-facing counts that make the mid ≠ last-trade point."""
    wide = select_asof_rows(wide, asof=asof, cp=cp)
    if wide is None or wide.empty:
        return {
            "n_quotes": 0,
            "n_trade_only": 0,
            "n_mid_only": 0,
            "n_both": 0,
            "pct_mid_no_trade": 0.0,
            "median_abs_diff": None,
            "median_rel_diff_pct": None,
            "n_dates": 0,
            "n_series": 0,
        }
    n = len(wide)
    mid = pd.to_numeric(wide["MID_PRICE"], errors="coerce")
    trade = pd.to_numeric(wide["TRDPRC_1"], errors="coerce")
    has_mid = mid.notna() & np.isfinite(mid)
    has_trade = trade.notna() & np.isfinite(trade)
    both = has_trade & has_mid
    mid_only = has_mid & ~has_trade
    trade_only = has_trade & ~has_mid
    abs_diff = (mid - trade).abs()
    rel_diff = abs_diff / mid.replace(0, np.nan)
    diffs = abs_diff.loc[both].dropna()
    rel = rel_diff.loc[both].dropna()
    return {
        "n_quotes": int(n),
        "n_trade_only": int(trade_only.sum()),
        "n_mid_only": int(mid_only.sum()),
        "n_both": int(both.sum()),
        "pct_mid_no_trade": float(100.0 * mid_only.mean()) if n else 0.0,
        "median_abs_diff": float(diffs.median()) if len(diffs) else None,
        "median_rel_diff_pct": float(100.0 * rel.median()) if len(rel) else None,
        "n_dates": int(wide["date"].nunique()),
        "n_series": int(wide["ric"].nunique()),
    }


def synthesize_demo_payload(
    ticker_root: str = "UUUU",
    ticker_stock: str = "UUUU.K",
    weeks_back: int = 12,
    seed: int = 7,
) -> dict:
    """
    Build a fake LSEG-shaped payload so the lab runs without credentials.

    Design goals (these are the teaching points):
      * MID_PRICE exists on most listed strikes near the money
      * TRDPRC_1 only prints on a sparse subset (ATM, near-dated)
      * When both exist they are close but not equal
    """
    rng = np.random.default_rng(seed)
    end = dt.date.today()
    start = end - dt.timedelta(weeks=weeks_back)
    bdays = pd.bdate_range(start, end)

    # Geometric-ish random walk around a $8 name (UUUU-like)
    rets = rng.normal(0.0005, 0.035, size=len(bdays))
    close = 8.0 * np.exp(np.cumsum(rets))
    close = np.clip(close, 3.5, 16.0)
    high = close * (1 + rng.uniform(0.005, 0.04, size=len(bdays)))
    low = close * (1 - rng.uniform(0.005, 0.04, size=len(bdays)))
    open_ = close * (1 + rng.normal(0, 0.01, size=len(bdays)))
    df_stock = pd.DataFrame(
        {"OPEN_PRC": open_, "HIGH_1": high, "LOW_1": low, "TRDPRC_1": close},
        index=bdays,
    )

    fridays = pd.date_range(start, end + dt.timedelta(days=40), freq="W-FRI")
    # keep a handful of expiries that overlap the window
    expiries = [d.date() for d in fridays if d.date() >= start]

    strike_step = 0.50
    records = {}
    fields = ["TRDPRC_1", "MID_PRICE"]

    def ric_for(expiry: dt.date, strike: float, cp: str) -> str:
        month_code = chr(ord("A") + expiry.month - 1) if cp == "C" else chr(ord("M") + expiry.month - 1)
        strike_str = f"{int(round(strike * 100)):05d}"
        base = f"{ticker_root}{month_code}{expiry.strftime('%d')}{expiry.strftime('%y')}{strike_str}.U"
        return f"{base}^{month_code}{expiry.strftime('%y')}"

    for expiry in expiries:
        dte_at_start = (expiry - start).days
        if dte_at_start < 0:
            continue
        # strike grid around the path
        path_lo = float(df_stock.loc[df_stock.index.date <= expiry, "LOW_1"].min()) if any(df_stock.index.date <= expiry) else 5.0
        path_hi = float(df_stock.loc[df_stock.index.date <= expiry, "HIGH_1"].max()) if any(df_stock.index.date <= expiry) else 12.0
        lo = np.floor((path_lo - 2) / strike_step) * strike_step
        hi = np.ceil((path_hi + 2) / strike_step) * strike_step
        strikes = np.arange(max(1.0, lo), hi + strike_step, strike_step)

        for strike in strikes:
            for cp in ("C", "P"):
                ric = ric_for(expiry, float(strike), cp)
                for field in fields:
                    records[(ric, field)] = pd.Series(index=bdays, dtype=float)

                for ts, spot in df_stock["TRDPRC_1"].items():
                    dte = (expiry - ts.date()).days
                    if dte < 0:
                        continue
                    # intrinsic + crude time value
                    intrinsic = max(spot - strike, 0.0) if cp == "C" else max(strike - spot, 0.0)
                    t_years = max(dte, 0) / 365.0
                    # rough vol-ish time value, higher when ATM
                    mny = abs(np.log(max(strike, 1e-6) / spot))
                    time_val = spot * 0.55 * np.sqrt(max(t_years, 1 / 365)) * np.exp(-3.2 * mny)
                    mid_price = max(intrinsic + time_val, 0.01)
                    # closing mid is a mark; last trade is noisier / stickier
                    trade = mid_price * rng.normal(1.0, 0.06) + rng.normal(0, 0.02)
                    trade = max(trade, 0.01)

                    # Liquidity mask: the closing mid almost always exists near the money;
                    # prints only when DTE is short or the strike is close to spot.
                    near_money = mny < 0.25
                    listed = mny < 0.55 or dte < 21
                    if not listed:
                        continue
                    records[(ric, "MID_PRICE")].loc[ts] = round(mid_price, 4)

                    p_trade = 0.55 if (near_money and dte <= 21) else 0.18 if near_money else 0.04
                    if dte <= 5 and near_money:
                        p_trade = 0.8
                    if rng.random() < p_trade:
                        records[(ric, "TRDPRC_1")].loc[ts] = round(trade, 4)

    # drop empty series
    live = {k: s.dropna() for k, s in records.items() if s.notna().any()}
    if live:
        df_options = pd.concat(live, axis=1)
        df_options.columns = pd.MultiIndex.from_tuples(df_options.columns, names=["RIC", "Field"])
    else:
        df_options = pd.DataFrame()

    return {
        "stock": df_stock,
        "options": df_options,
        "ticker": ticker_root,
        "fetched_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "synthetic": True,
    }


def load_payload(cache_file: str = "option_pipeline_data.pkl") -> dict:
    """Prefer the real LSEG cache; fall back to a synthetic panel."""
    path = Path(cache_file)
    if path.exists():
        try:
            with path.open("rb") as f:
                payload = pickle.load(f)
        except Exception as exc:
            warnings.warn(
                f"{cache_file} could not be read ({exc}) — using synthetic data.",
                RuntimeWarning,
            )
            return synthesize_demo_payload()
        if not has_option_field(payload.get("options"), "MID_PRICE"):
            warnings.warn(
                f"{cache_file} has no MID_PRICE field — using the updated synthetic panel.",
                RuntimeWarning,
            )
            return synthesize_demo_payload()
        payload.setdefault("synthetic", False)
        return payload
    warnings.warn(
        f"{cache_file} not found — using synthetic UUUU-like options so the lab still runs.",
        RuntimeWarning,
    )
    return synthesize_demo_payload()
