"""Plotly figures for the options surface lab."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

try:
    from .option_surface_utils import paired_quote_rows, select_asof_rows, summarize_sparsity, surface_grid
except ImportError:
    # Keep standalone execution from the repository root working too.
    from option_surface_utils import paired_quote_rows, select_asof_rows, summarize_sparsity, surface_grid


BG = "#0A131F"
PANEL = "#101C2A"
PLOT = "#0D1825"
BORDER = "#223346"
GRID = "#26394C"
TEXT = "#E8EFF6"
MUTED = "#8A9CAF"
MID = "#74D6F4"
TRADE = "#FF7B68"
MISSING = "#3B4959"
PUT = "#B8A9D9"


DARK = dict(
    template="plotly_dark",
    paper_bgcolor=PANEL,
    plot_bgcolor=PLOT,
    font=dict(color=TEXT, family="Inter, ui-sans-serif, system-ui, sans-serif"),
)


def candlestick_figure(df_stock: pd.DataFrame, ticker: str) -> go.Figure:
    fig = go.Figure(
        data=[
            go.Candlestick(
                x=df_stock.index,
                open=df_stock["OPEN_PRC"],
                high=df_stock["HIGH_1"],
                low=df_stock["LOW_1"],
                close=df_stock["TRDPRC_1"],
                increasing_line_color=MID,
                increasing_fillcolor=MID,
                decreasing_line_color=TRADE,
                decreasing_fillcolor=TRADE,
                name=ticker,
            )
        ]
    )
    fig.update_layout(
        **DARK,
        title=dict(
            text=f"{ticker} · DAILY OHLC",
            font=dict(size=15, color=TEXT),
            x=0.0,
            xanchor="left",
        ),
        xaxis=dict(
            gridcolor=GRID,
            linecolor=BORDER,
            zeroline=False,
            rangeslider=dict(visible=False),
        ),
        yaxis=dict(
            gridcolor=GRID,
            linecolor=BORDER,
            zeroline=False,
            title="Underlying price ($)",
        ),
        margin=dict(l=54, r=24, t=62, b=42),
        height=420,
        hoverlabel=dict(bgcolor=PANEL, bordercolor=BORDER, font=dict(color=TEXT)),
        annotations=[
            dict(
                text="Cached LSEG history · the close uses TRDPRC_1, not an option midpoint",
                xref="paper",
                yref="paper",
                x=0.0,
                y=1.04,
                showarrow=False,
                font=dict(size=11, color=MUTED),
            )
        ],
    )
    return fig


def _slice_wide(wide: pd.DataFrame, asof, cp: str) -> pd.DataFrame:
    return select_asof_rows(wide, asof=asof, cp=cp)


def price_surface_figure(
    wide: pd.DataFrame,
    asof,
    cp: str = "C",
    show_trade: bool = True,
    show_mid: bool = True,
    show_interpolated: bool = True,
    ticker: str = "UUUU",
) -> go.Figure:
    sl = _slice_wide(wide, asof, cp)
    fig = go.Figure()

    if sl.empty:
        fig.update_layout(
            **DARK,
            title=dict(
                text="No real observations are available for this selection",
                font=dict(size=16),
            ),
            height=620,
        )
        return fig

    spot = sl["spot"].dropna()
    spot_val = float(spot.median()) if len(spot) else None
    cp_label = {"C": "Calls", "P": "Puts", "B": "Puts + Calls"}.get(cp, cp)
    asof_txt = str(pd.Timestamp(asof).date()) if asof is not None else "all dates"
    spot_txt = f"  ·  spot ${spot_val:.2f}" if spot_val is not None else ""

    def _axis(title: str) -> dict:
        return dict(
            title=dict(text=title, font=dict(size=12)),
            backgroundcolor=PLOT,
            gridcolor=GRID,
            linecolor=BORDER,
            showbackground=True,
            zeroline=False,
            tickfont=dict(size=10, color=MUTED),
        )

    if show_mid and sl["MID_PRICE"].notna().any():
        s = sl.dropna(subset=["MID_PRICE"])
        if show_interpolated:
            grid = surface_grid(s, "MID_PRICE")
            if grid is not None:
                fig.add_trace(
                    go.Surface(
                        x=grid["x"],
                        y=grid["y"],
                        z=grid["z"],
                        name="Interpolated visualization",
                        colorscale=[
                            [0.0, "#7890A4"],
                            [1.0, "#7890A4"],
                        ],
                        opacity=0.28,
                        showscale=False,
                        showlegend=True,
                        legendrank=30,
                        hoverinfo="skip",
                        connectgaps=False,
                        lighting=dict(
                            ambient=1.0,
                            diffuse=0.0,
                            roughness=1.0,
                            specular=0.0,
                            fresnel=0.0,
                        ),
                        contours=dict(
                            x=dict(show=False),
                            y=dict(show=False),
                            z=dict(show=False),
                        ),
                    )
                )
        fig.add_trace(
            go.Scatter3d(
                x=s["strike"],
                y=s["dte"],
                z=s["MID_PRICE"],
                mode="markers",
                name="MID_PRICE · closing midpoint",
                legendrank=10,
                marker=dict(
                    size=5,
                    color=MID,
                    opacity=0.96,
                    symbol="circle",
                    line=dict(width=0.7, color="#C5F2FF"),
                ),
                hovertemplate=(
                    "<b>MID_PRICE</b> $%{z:.3f}<br>K=%{x:.2f}<br>DTE=%{y}"
                    "<br>%{customdata[0]}<extra></extra>"
                ),
                customdata=np.stack([s["ric"].astype(str), s["cp"].astype(str)], axis=1),
            )
        )

    if show_trade and sl["TRDPRC_1"].notna().any():
        t = sl.dropna(subset=["TRDPRC_1"])
        fig.add_trace(
            go.Scatter3d(
                x=t["strike"],
                y=t["dte"],
                z=t["TRDPRC_1"],
                mode="markers",
                name="TRDPRC_1 · last print",
                legendrank=20,
                marker=dict(
                    size=6.5,
                    color=TRADE,
                    opacity=1.0,
                    symbol="diamond",
                    line=dict(width=0.8, color="#FFD0C8"),
                ),
                hovertemplate=(
                    "<b>TRDPRC_1</b> $%{z:.3f}<br>K=%{x:.2f}<br>DTE=%{y}"
                    "<br>%{customdata[0]}<extra></extra>"
                ),
                customdata=np.stack([t["ric"].astype(str), t["cp"].astype(str)], axis=1),
            )
        )

    fig.update_layout(
        **DARK,
        title=dict(
            text=f"{ticker} {cp_label} · {asof_txt}{spot_txt}",
            font=dict(size=16, color=TEXT),
            x=0.0,
            xanchor="left",
            y=0.98,
            yanchor="top",
        ),
        scene=dict(
            xaxis=_axis("Strike ($)"),
            # near-dated in front: reverse DTE so 0 sits toward the viewer
            yaxis={**_axis("Days to expiry"), "autorange": "reversed"},
            zaxis=_axis("Option price ($)"),
            bgcolor=PANEL,
            aspectmode="manual",
            aspectratio=dict(x=1.15, y=1.0, z=0.7),
            camera=dict(
                eye=dict(x=1.15, y=-1.05, z=0.7),
                center=dict(x=0, y=0, z=-0.05),
            ),
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=0.995,
            x=1.0,
            xanchor="right",
            bgcolor=PANEL,
            bordercolor=BORDER,
            borderwidth=1,
            font=dict(size=11),
            itemsizing="constant",
        ),
        height=640,
        margin=dict(l=10, r=10, t=82, b=10),
        hoverlabel=dict(bgcolor=PANEL, bordercolor=BORDER, font=dict(color=TEXT)),
        annotations=[
            dict(
                text="Interpolated visualization — not an executable market price",
                xref="paper",
                yref="paper",
                x=0.0,
                y=1.01,
                xanchor="left",
                yanchor="bottom",
                showarrow=False,
                font=dict(size=11, color=MUTED),
            )
        ],
    )
    return fig


def mid_vs_trade_figure(
    wide: pd.DataFrame,
    asof=None,
    ticker: str = "UUUU",
    cp: str | None = None,
) -> go.Figure:
    sl = select_asof_rows(wide, asof=asof, cp=cp)
    both = paired_quote_rows(sl)
    fig = go.Figure()

    if len(both):
        sides = [side for side in ("C", "P") if (both["cp"] == side).any()]
        grouped = sides if len(sides) > 1 else [sides[0] if sides else None]
        for side in grouped:
            points = both if side is None else both.loc[both["cp"].eq(side)]
            label = {"C": "Calls", "P": "Puts"}.get(side, "Paired observations")
            fig.add_trace(
                go.Scatter(
                    x=points["TRDPRC_1"],
                    y=points["MID_PRICE"],
                    mode="markers",
                    marker=dict(
                        size=8,
                        color=MID if side != "P" else PUT,
                        opacity=0.9,
                        symbol="circle" if side != "P" else "diamond",
                        line=dict(color=TRADE, width=1.0),
                    ),
                    customdata=np.stack(
                        [
                            points["ric"].astype(str),
                            points["strike"],
                            points["dte"],
                            points["cp"],
                        ],
                        axis=1,
                    ),
                    hovertemplate=(
                        "<b>TRDPRC_1</b> $%{x:.3f}<br><b>MID_PRICE</b> $%{y:.3f}"
                        "<br>%{customdata[3]} · K=%{customdata[1]:.2f} · DTE=%{customdata[2]}"
                        "<br>%{customdata[0]}<extra></extra>"
                    ),
                    name=label,
                    showlegend=len(sides) > 1,
                )
            )
        lo = float(min(both["TRDPRC_1"].min(), both["MID_PRICE"].min()))
        hi = float(max(both["TRDPRC_1"].max(), both["MID_PRICE"].max()))
        pad = (hi - lo) * 0.06 if hi > lo else 0.05
        fig.add_trace(
            go.Scatter(
                x=[lo - pad, hi + pad],
                y=[lo - pad, hi + pad],
                mode="lines",
                line=dict(color=MUTED, dash="dash", width=1.25),
                name="Parity · y = x",
                showlegend=True,
                hoverinfo="skip",
            )
        )
        fig.update_xaxes(range=[lo - pad, hi + pad])
        fig.update_yaxes(range=[lo - pad, hi + pad])
    else:
        fig.add_annotation(
            text="No contracts contain both real MID_PRICE and TRDPRC_1 values in this slice.",
            x=0.5,
            y=0.5,
            xref="paper",
            yref="paper",
            showarrow=False,
            font=dict(color=MUTED, size=13),
        )

    selected_date = pd.Timestamp(asof).date() if asof is not None else None
    if selected_date is None and len(sl) and "date" in sl.columns:
        dates = sl["date"].dropna()
        selected_date = pd.Timestamp(dates.iloc[0]).date() if len(dates) else None
    asof_txt = str(selected_date) if selected_date is not None else "all dates"
    fig.update_layout(
        **DARK,
        title=dict(
            text="MARK VS TRADE",
            font=dict(size=15, color=TEXT),
            x=0.0,
            xanchor="left",
            y=0.98,
            yanchor="top",
        ),
        xaxis=dict(
            title="TRDPRC_1 · last actual print ($)",
            gridcolor=GRID,
            linecolor=BORDER,
            zeroline=False,
        ),
        yaxis=dict(
            title="MID_PRICE · closing midpoint ($)",
            gridcolor=GRID,
            linecolor=BORDER,
            zeroline=False,
        ),
        height=500,
        margin=dict(l=68, r=24, t=80, b=62),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.0,
            x=1.0,
            xanchor="right",
            font=dict(size=11),
            bgcolor=PANEL,
            bordercolor=BORDER,
            borderwidth=1,
        ),
        hoverlabel=dict(bgcolor=PANEL, bordercolor=BORDER, font=dict(color=TEXT)),
        annotations=[
            dict(
                text=(
                    "How far is the closing midpoint from the last actual print? "
                    f"· {ticker} · {asof_txt} · {len(both)} paired contracts"
                ),
                xref="paper",
                yref="paper",
                x=0.0,
                y=1.035,
                xanchor="left",
                yanchor="bottom",
                showarrow=False,
                font=dict(size=11, color=MUTED),
            )
        ],
    )
    return fig


def data_availability_figure(
    wide: pd.DataFrame,
    asof=None,
    ticker: str = "UUUU",
    cp: str | None = None,
) -> go.Figure:
    """Show mutually exclusive real-data states without treating missing as zero."""
    sl = select_asof_rows(wide, asof=asof, cp=cp)
    stats = summarize_sparsity(sl)
    labels = [
        "<b>QUOTE ONLY</b><br>MID_PRICE available · no trade",
        "<b>QUOTE + TRADE</b><br>Both fields available",
        "<b>TRADE ONLY</b><br>TRDPRC_1 available · no midpoint",
    ]
    counts = [stats["n_mid_only"], stats["n_both"], stats["n_trade_only"]]
    descriptions = [
        "Closing midpoint exists; no trade print was reported",
        "Both real fields exist for the same contract and date",
        "Trade print exists; closing midpoint is unavailable",
    ]
    total = max(stats["n_quotes"], 1)
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=[total, total, total],
            y=labels,
            orientation="h",
            marker=dict(color=MISSING, opacity=0.28),
            width=0.55,
            hoverinfo="skip",
            showlegend=False,
        )
    )
    fig.add_trace(
        go.Bar(
            x=counts,
            y=labels,
            orientation="h",
            marker=dict(
                color=[MID, "#B7CBD8", TRADE],
                line=dict(color=["#BDEFFF", "#E8EFF6", "#FFD0C8"], width=0.8),
            ),
            width=0.55,
            text=[f"<b>{count}</b> contracts" for count in counts],
            textposition="outside",
            textfont=dict(color=TEXT, size=13),
            customdata=np.array(descriptions)[:, None],
            hovertemplate="%{customdata[0]}<br><b>%{x} contracts</b><extra></extra>",
            showlegend=False,
            cliponaxis=False,
        )
    )

    selected_date = pd.Timestamp(asof).date() if asof is not None else None
    if selected_date is None and len(sl) and "date" in sl.columns:
        dates = sl["date"].dropna()
        selected_date = pd.Timestamp(dates.iloc[0]).date() if len(dates) else None
    asof_txt = str(selected_date) if selected_date is not None else "all dates"
    fig.update_layout(
        **DARK,
        title=dict(
            text=f"REAL FIELD AVAILABILITY · {ticker} · {asof_txt}",
            font=dict(size=15, color=TEXT),
            x=0.0,
            xanchor="left",
        ),
        barmode="overlay",
        bargap=0.4,
        xaxis=dict(
            title="Contracts in the selected date slice",
            range=[0, total * 1.18],
            gridcolor=GRID,
            linecolor=BORDER,
            zeroline=False,
            tickfont=dict(color=MUTED),
        ),
        yaxis=dict(
            autorange="reversed",
            gridcolor="rgba(0,0,0,0)",
            tickfont=dict(color=TEXT, size=12),
            automargin=True,
        ),
        height=390,
        margin=dict(l=250, r=82, t=84, b=54),
        hoverlabel=dict(bgcolor=PANEL, bordercolor=BORDER, font=dict(color=TEXT)),
        annotations=[
            dict(
                text=(
                    "Three mutually exclusive market states · gray tracks show the selected "
                    "series universe, never zero-valued prices"
                ),
                xref="paper",
                yref="paper",
                x=0.0,
                y=1.04,
                xanchor="left",
                yanchor="bottom",
                showarrow=False,
                font=dict(size=11, color=MUTED),
            )
        ],
    )
    return fig


def coverage_heatmap(wide: pd.DataFrame, asof, cp: str = "C", field: str = "MID_PRICE") -> go.Figure:
    """2D occupancy grid: which (strike, expiry) cells actually have a number."""
    sl = _slice_wide(wide, asof, cp)
    if sl.empty:
        return go.Figure().update_layout(
            **DARK,
            title=dict(text="No real observations are available", font=dict(size=15)),
            height=380,
        )

    sl = sl.copy()
    sl["expiry_label"] = sl["expiry"].dt.strftime("%b ") + sl["expiry"].dt.day.astype(int).astype(str)
    val = sl[field] if field in sl.columns else sl["MID_PRICE"]
    sl["_hit"] = val.notna().astype(int)
    pivot = sl.pivot_table(index="expiry_label", columns="strike", values="_hit", aggfunc="max")
    # keep expiry order chronological, not alpha on "Oct"/"Sep"
    order = (
        sl.drop_duplicates("expiry_label")
        .sort_values("expiry")["expiry_label"]
        .tolist()
    )
    pivot = pivot.reindex(order, axis=0)
    pivot = pivot.reindex(sorted(pivot.columns), axis=1)

    accent = MID if field == "MID_PRICE" else TRADE
    fig = go.Figure(
        data=go.Heatmap(
            z=pivot.values,
            x=[f"{c:.2f}" for c in pivot.columns],
            y=list(pivot.index),
            colorscale=[
                [0.0, MISSING],
                [0.4999, MISSING],
                [0.5, accent],
                [1.0, accent],
            ],
            zmin=0,
            zmax=1,
            showscale=False,
            xgap=3,
            ygap=3,
            hovertemplate=(
                f"<b>{field}</b><br>K=%{{x}} · expiry=%{{y}}"
                "<br>observed=%{z}<extra></extra>"
            ),
        )
    )
    fig.update_layout(
        **DARK,
        title=dict(
            text=f"{field} COVERAGE",
            font=dict(size=15, color=TEXT),
            x=0.0,
            xanchor="left",
            y=0.98,
            yanchor="top",
        ),
        xaxis=dict(
            title="Strike ($)",
            gridcolor=GRID,
            linecolor=BORDER,
            tickangle=-45,
            tickfont=dict(size=10, color=MUTED),
            title_font=dict(size=12),
        ),
        yaxis=dict(
            title="Expiry",
            gridcolor=GRID,
            linecolor=BORDER,
            tickfont=dict(size=11, color=MUTED),
            title_font=dict(size=12),
        ),
        height=380,
        margin=dict(l=76, r=18, t=76, b=58),
        hoverlabel=dict(bgcolor=PANEL, bordercolor=BORDER, font=dict(color=TEXT)),
        annotations=[
            dict(
                text="Bright cell = a real observation · muted cell = unavailable, not zero",
                xref="paper",
                yref="paper",
                x=0.0,
                y=1.04,
                xanchor="left",
                yanchor="bottom",
                showarrow=False,
                font=dict(size=11, color=MUTED),
            )
        ],
    )
    return fig
