"""
Options Surface Lab — Reflex app

Paste this in place of the current app module (or run it as the Reflex entry).
It reuses the existing LSEG pickle cache when present, otherwise synthesizes
a sparse UUUU-like panel so students can still plot something tonight.

Teaching targets this week
--------------------------
1. Listed options are a sparse cloud, not a filled sheet.
2. MID_PRICE (closing quote mark) is not TRDPRC_1 (last trade).
3. An interpolated "surface" is an assumption you are imposing on holes.
"""

from __future__ import annotations

import pickle
import datetime
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import reflex as rx

try:
    from options_surface_lab.option_surface_utils import (
        attach_underlying,
        available_cp_values,
        best_coverage_asof,
        flatten_lseg_options,
        has_option_field,
        pivot_trade_mid,
        select_asof_rows,
        summarize_sparsity,
        synthesize_demo_payload,
    )
    from options_surface_lab.option_surface_plots import (
        candlestick_figure,
        coverage_heatmap,
        price_surface_figure,
        mid_vs_trade_figure,
    )
except ModuleNotFoundError:
    # Also support running this file directly from the repository root.
    from option_surface_utils import (
        attach_underlying,
        available_cp_values,
        best_coverage_asof,
        flatten_lseg_options,
        has_option_field,
        pivot_trade_mid,
        select_asof_rows,
        summarize_sparsity,
        synthesize_demo_payload,
    )
    from option_surface_plots import (
        candlestick_figure,
        coverage_heatmap,
        price_surface_figure,
        mid_vs_trade_figure,
    )

warnings.filterwarnings("ignore", category=FutureWarning, module="lseg.data")

APP_DIR = Path(__file__).resolve().parent
CACHE_FILE = APP_DIR / "option_pipeline_data.pkl"
ticker_stock = "UUUU.K"
ticker_root = "UUUU"
weeks_back = 12
strike_step = 0.50
batch_size = 25


def load_or_fetch_pipeline_data(
    ticker_stock: str = "UUUU.K",
    ticker_root: str = "UUUU",
    weeks_back: int = 12,
    strike_step: float = 0.50,
    batch_size: int = 25,
) -> dict:
    """
    Cache-first loader. Only talks to LSEG when the real pickle is missing.
    The synthetic panel is a last-resort local fallback, never the preferred
    dataset when a real pull is available.
    """
    cache_path = Path(CACHE_FILE)
    if cache_path.exists():
        print(f"Loading cached dataset from {cache_path}...")
        try:
            with cache_path.open("rb") as f:
                payload = pickle.load(f)
        except Exception as exc:
            print(f"Could not read {cache_path}: {exc}. A fresh LSEG pull will be attempted.")
        else:
            if has_option_field(payload.get("options"), "MID_PRICE"):
                payload.setdefault("synthetic", False)
                return payload
            print(f"Cached frame {cache_path} has no MID_PRICE. A fresh LSEG pull will be attempted.")

    try:
        import lseg.data as ld
    except Exception:
        print("No cache and no lseg.data — synthesizing a demo panel.")
        return synthesize_demo_payload(ticker_root=ticker_root, ticker_stock=ticker_stock)

    print("Cache not found. Initializing LSEG data pull...")
    try:
        ld.open_session()
    except Exception as exc:
        print(f"Could not open LSEG session ({exc}) — synthesizing a demo panel.")
        return synthesize_demo_payload(ticker_root=ticker_root, ticker_stock=ticker_stock)

    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(weeks=weeks_back)
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    try:
        df_stock = ld.get_history(
            universe=[ticker_stock],
            fields=["OPEN_PRC", "HIGH_1", "LOW_1", "TRDPRC_1"],
            start=start_str,
            end=end_str,
            interval="daily",
        )
    except Exception as exc:
        try:
            ld.close_session()
        finally:
            print(f"LSEG stock pull failed ({exc}) — synthesizing a demo panel.")
        return synthesize_demo_payload(ticker_root=ticker_root, ticker_stock=ticker_stock)

    if df_stock is None or df_stock.empty:
        ld.close_session()
        print("LSEG returned no underlying history — synthesizing a demo panel.")
        return synthesize_demo_payload(ticker_root=ticker_root, ticker_stock=ticker_stock)

    low_price = float(df_stock["LOW_1"].min())
    high_price = float(df_stock["HIGH_1"].max())

    min_strike = np.floor(low_price / strike_step) * strike_step
    max_strike = np.ceil(high_price / strike_step) * strike_step
    strikes = np.arange(min_strike, max_strike + strike_step, strike_step)
    friday_dates = pd.date_range(start=start_str, end=end_str, freq="W-FRI")

    candidate_rics = []
    for d in friday_dates:
        year_str = d.strftime("%y")
        day_str = d.strftime("%d")
        month_num = d.month
        call_code = chr(ord("A") + month_num - 1)
        put_code = chr(ord("M") + month_num - 1)
        for strike in strikes:
            strike_str = f"{int(round(strike * 100)):05d}"
            call_base = f"{ticker_root.upper()}{call_code}{day_str}{year_str}{strike_str}.U"
            candidate_rics.append(f"{call_base}^{call_code}{year_str}")
            put_base = f"{ticker_root.upper()}{put_code}{day_str}{year_str}{strike_str}.U"
            candidate_rics.append(f"{put_base}^{put_code}{year_str}")

    batches = [candidate_rics[i : i + batch_size] for i in range(0, len(candidate_rics), batch_size)]
    history_frames = []
    fields = ["TRDPRC_1", "MID_PRICE"]

    for batch in batches:
        try:
            df_batch = ld.get_history(
                universe=batch,
                fields=fields,
                start=start_str,
                end=end_str,
                interval="daily",
            )
            if df_batch is not None and not df_batch.empty:
                df_clean = df_batch.dropna(how="all", axis=1)
                if not df_clean.empty:
                    history_frames.append(df_clean)
        except Exception:
            for single_ric in batch:
                try:
                    df_single = ld.get_history(
                        universe=[single_ric],
                        fields=fields,
                        start=start_str,
                        end=end_str,
                        interval="daily",
                    )
                    if (
                        df_single is not None
                        and not df_single.empty
                        and not df_single.dropna(how="all").empty
                    ):
                        history_frames.append(df_single)
                except Exception:
                    continue

    ld.close_session()

    df_options = pd.DataFrame()
    if history_frames:
        df_options = pd.concat(history_frames, axis=1)
        df_options = df_options.loc[:, ~df_options.columns.duplicated()]

    data_payload = {
        "stock": df_stock,
        "options": df_options,
        "ticker": ticker_root,
        "fetched_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "synthetic": False,
    }
    with Path(CACHE_FILE).open("wb") as f:
        pickle.dump(data_payload, f)
    print(f"Data pipeline complete. Results cached to {CACHE_FILE}.")
    return data_payload


def _prepare(payload: dict) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    tidy = flatten_lseg_options(payload["options"])
    tidy = attach_underlying(tidy, payload["stock"])
    wide = select_asof_rows(pivot_trade_mid(tidy))
    return tidy, wide, payload


class State(rx.State):
    ticker: str = "UUUU"
    status_msg: str = "Ready"
    option_count: int = 0
    n_quotes: int = 0
    n_mid_only: int = 0
    n_both: int = 0
    pct_mid_no_trade: str = "—"
    median_gap: str = "—"
    data_note: str = ""
    asof: str = ""
    asof_options: list[str] = []
    cp_options: list[str] = ["C"]
    cp: str = "C"
    show_trade: bool = True
    show_mid: bool = True
    show_sheet: bool = True

    fig_stock: go.Figure = go.Figure()
    fig_surface: go.Figure = go.Figure()
    fig_compare: go.Figure = go.Figure()
    fig_heat_mid: go.Figure = go.Figure()
    fig_heat_trade: go.Figure = go.Figure()

    _wide: pd.DataFrame | None = None
    _stock: pd.DataFrame | None = None

    def load_data(self):
        self.status_msg = "Checking local cache / fetching data..."
        payload = load_or_fetch_pipeline_data()
        tidy, wide, payload = _prepare(payload)

        self._wide = wide
        self._stock = payload["stock"]
        self.ticker = payload.get("ticker", "UUUU")
        self.option_count = int(wide["ric"].nunique()) if len(wide) else 0
        self.data_note = (
            "SYNTHETIC panel — place option_pipeline_data.pkl next to the app to use LSEG"
            if payload.get("synthetic")
            else f"LSEG cache from {payload.get('fetched_at', '?')}"
        )

        dates = sorted({d.strftime("%Y-%m-%d") for d in wide["date"]}) if len(wide) else []
        self.asof_options = dates
        best_asof = best_coverage_asof(wide)
        self.asof = best_asof.strftime("%Y-%m-%d") if best_asof is not None else ""
        self._sync_cp_options()

        self.fig_stock = candlestick_figure(payload["stock"], self.ticker)
        self._rebuild_option_figs()
        self.status_msg = f"Loaded {self.option_count} series"

    def set_cp(self, value: str):
        if value in self.cp_options:
            self.cp = value
        self._rebuild_option_figs()

    def set_asof(self, value: str):
        self.asof = value
        self._sync_cp_options()
        self._rebuild_option_figs()

    def toggle_trade(self, value: bool):
        self.show_trade = value
        self._rebuild_option_figs()

    def toggle_mid(self, value: bool):
        self.show_mid = value
        self._rebuild_option_figs()

    def toggle_sheet(self, value: bool):
        self.show_sheet = value
        self._rebuild_option_figs()

    def _sync_cp_options(self):
        available = available_cp_values(self._wide, asof=self.asof)
        self.cp_options = available or ["C"]
        if self.cp not in self.cp_options:
            self.cp = self.cp_options[0]

    def _rebuild_option_figs(self):
        wide = self._wide
        if wide is None or wide.empty or not self.asof:
            empty = go.Figure()
            empty.update_layout(template="plotly_dark", paper_bgcolor="#0d1117")
            self.fig_surface = empty
            self.fig_compare = empty
            self.fig_heat_mid = empty
            self.fig_heat_trade = empty
            return

        asof = self.asof
        sl = select_asof_rows(wide, asof=asof)
        self._sync_cp_options()
        stats = summarize_sparsity(sl)
        self.n_quotes = stats["n_quotes"]
        self.n_mid_only = stats["n_mid_only"]
        self.n_both = stats["n_both"]
        self.pct_mid_no_trade = f"{stats['pct_mid_no_trade']:.0f}%"
        if stats["median_abs_diff"] is None:
            self.median_gap = "n/a"
        else:
            rel = stats["median_rel_diff_pct"]
            self.median_gap = f"${stats['median_abs_diff']:.3f}" + (
                f" ({rel:.1f}%)" if rel is not None else ""
            )

        self.fig_surface = price_surface_figure(
            wide,
            asof,
            cp=self.cp,
            show_trade=self.show_trade,
            show_mid=self.show_mid,
            show_interpolated=self.show_sheet,
            ticker=self.ticker,
        )
        self.fig_compare = mid_vs_trade_figure(sl, ticker=self.ticker)
        self.fig_heat_mid = coverage_heatmap(wide, asof, cp=self.cp, field="MID_PRICE")
        self.fig_heat_trade = coverage_heatmap(wide, asof, cp=self.cp, field="TRDPRC_1")


def _metric(label: str, value) -> rx.Component:
    return rx.card(
        rx.text(label, size="2", color="#8b949e"),
        rx.text(value, size="6", color="#00ffcc", weight="bold"),
        bg="#161b22",
        border="1px solid #30363d",
        padding="1rem",
    )


def index() -> rx.Component:
    return rx.container(
        rx.vstack(
            rx.hstack(
                rx.heading(
                    "OPTIONS SURFACE LAB",
                    size="8",
                    color="#00ffcc",
                    style={"letter_spacing": "2px"},
                ),
                rx.spacer(),
                rx.badge(State.status_msg, color_scheme="cyan", variant="solid"),
                width="100%",
                align="center",
                padding_y="1rem",
            ),
            rx.text(State.data_note, color="#8b949e", size="2"),
            rx.hstack(
                _metric("Underlying", State.ticker),
                _metric("Option series", State.option_count),
                _metric("Quotes on as-of date", State.n_quotes),
                _metric("Mid with no print", State.n_mid_only),
                _metric("Mid with no print (%)", State.pct_mid_no_trade),
                _metric("Median |mid − trade|", State.median_gap),
                rx.button(
                    "Reload data",
                    on_click=State.load_data,
                    bg="#238636",
                    color="#ffffff",
                    _hover={"bg": "#2ea043"},
                    size="3",
                ),
                spacing="4",
                width="100%",
                align="center",
                wrap="wrap",
            ),
            rx.box(
                rx.plotly(data=State.fig_stock, style={"width": "100%", "height": "420px"}),
                width="100%",
                bg="#161b22",
                border="1px solid #30363d",
                border_radius="8px",
                padding="1rem",
            ),
            rx.hstack(
                rx.text("As-of date", color="#8b949e", size="2"),
                rx.select(
                    State.asof_options,
                    value=State.asof,
                    on_change=State.set_asof,
                    size="2",
                ),
                rx.text("Side", color="#8b949e", size="2"),
                rx.select(
                    State.cp_options,
                    value=State.cp,
                    on_change=State.set_cp,
                    size="2",
                ),
                rx.switch(checked=State.show_mid, on_change=State.toggle_mid),
                rx.text("MID_PRICE", color="#00ffcc", size="2"),
                rx.switch(checked=State.show_trade, on_change=State.toggle_trade),
                rx.text("TRDPRC_1", color="#ff0055", size="2"),
                rx.switch(checked=State.show_sheet, on_change=State.toggle_sheet),
                rx.text("Interpolated sheet", color="#8b949e", size="2"),
                spacing="3",
                align="center",
                wrap="wrap",
                width="100%",
            ),
            rx.text(
                "Cyan dots = closing MID_PRICE. Magenta diamonds = last trade. "
                "The translucent sheet is linearly interpolated and will happily "
                "invent prices in strikes that never printed. Turn it off.",
                color="#8b949e",
                size="2",
            ),
            rx.box(
                rx.plotly(data=State.fig_surface, style={"width": "100%", "height": "640px"}),
                width="100%",
                bg="#161b22",
                border="1px solid #30363d",
                border_radius="8px",
                padding="1rem",
            ),
            rx.vstack(
                rx.text(
                    "READING THE CLOUD",
                    color="#00ffcc",
                    size="2",
                    weight="bold",
                    style={"letter_spacing": "1px"},
                ),
                rx.text(
                    "The price cloud is densest near the money and at short DTE, while the far wings and longer expiries are mostly empty.",
                    color="#e6edf3",
                    size="3",
                ),
                rx.text(
                    "On a $0.50 strike grid for UUUU, interpolating across empty cells bridges contracts with no observed price and invents a false fill or liquidity signal.",
                    color="#e6edf3",
                    size="3",
                ),
                rx.text(
                    "Next week I will treat MID_PRICE as the mark and TRDPRC_1 as evidence that someone actually traded.",
                    color="#e6edf3",
                    size="3",
                ),
                width="100%",
                bg="#111820",
                border="1px solid #24434a",
                border_left="4px solid #00ffcc",
                border_radius="8px",
                padding="1rem 1.25rem",
                spacing="2",
            ),
            rx.box(
                rx.plotly(data=State.fig_compare, style={"width": "100%", "height": "460px"}),
                width="100%",
                bg="#161b22",
                border="1px solid #30363d",
                border_radius="8px",
                padding="1rem",
            ),
            rx.hstack(
                rx.box(
                    rx.plotly(
                        data=State.fig_heat_mid,
                        style={"width": "100%", "height": "380px"},
                    ),
                    width="50%",
                    bg="#161b22",
                    border="1px solid #30363d",
                    border_radius="8px",
                    padding="0.5rem",
                ),
                rx.box(
                    rx.plotly(
                        data=State.fig_heat_trade,
                        style={"width": "100%", "height": "380px"},
                    ),
                    width="50%",
                    bg="#161b22",
                    border="1px solid #30363d",
                    border_radius="8px",
                    padding="0.5rem",
                ),
                width="100%",
                spacing="3",
            ),
            spacing="5",
            width="100%",
        ),
        on_mount=State.load_data,
        background_color="#0d1117",
        min_height="100vh",
        max_width="100%",
        padding="2rem",
    )


app = rx.App()
app.add_page(index)
