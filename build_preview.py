"""Generate a standalone HTML preview of the surface lab (no Reflex required)."""

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from option_surface_plots import (
    candlestick_figure,
    coverage_heatmap,
    price_surface_figure,
    mid_vs_trade_figure,
)
from option_surface_utils import (
    attach_underlying,
    flatten_lseg_options,
    load_payload,
    select_asof_rows,
    summarize_sparsity,
    pivot_trade_mid,
)


def main() -> Path:
    base_dir = Path(__file__).resolve().parent
    primary_cache = base_dir / "option_pipeline_data.pkl"
    fallback_cache = base_dir / "option_pipeline_data.synthetic.pkl"
    payload = load_payload(str(primary_cache if primary_cache.exists() else fallback_cache))
    tidy = flatten_lseg_options(payload["options"])
    tidy = attach_underlying(tidy, payload["stock"])
    wide = select_asof_rows(pivot_trade_mid(tidy))
    ticker = payload.get("ticker", "UUUU")

    asof = wide["date"].max() if len(wide) else None
    asof_rows = select_asof_rows(wide, asof=asof)
    stats = summarize_sparsity(asof_rows)

    fig_px = price_surface_figure(wide, asof, cp="C", ticker=ticker)
    fig_px_p = price_surface_figure(wide, asof, cp="P", ticker=ticker)
    fig_cmp = mid_vs_trade_figure(asof_rows, ticker=ticker)
    fig_hm_s = coverage_heatmap(wide, asof, cp="C", field="MID_PRICE")
    fig_hm_t = coverage_heatmap(wide, asof, cp="C", field="TRDPRC_1")
    fig_cs = candlestick_figure(payload["stock"], ticker)

    out = Path(__file__).resolve().parent / "options_surface_preview.html"

    med = stats["median_abs_diff"]
    med_txt = "n/a" if med is None else f"${med:.3f}"
    rel = stats["median_rel_diff_pct"]
    rel_txt = "n/a" if rel is None else f"{rel:.1f}%"

    banner = f"""
    <div style="font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
                background:#0d1117; color:#e6edf3; padding:28px 32px 8px 32px;">
      <div style="color:#00ffcc; letter-spacing:2px; font-size:22px; font-weight:700;">
        OPTIONS SURFACE LAB — PREVIEW
      </div>
      <p style="color:#8b949e; max-width:820px; line-height:1.5;">
        As-of <span style="color:#e6edf3;">{pd.Timestamp(asof).date() if asof is not None else 'n/a'}</span>
        for <span style="color:#39d353;">{ticker}</span>
        {'(synthetic panel — drop option_pipeline_data.pkl next to this file to use your LSEG pull)'
          if payload.get('synthetic') else '(loaded from option_pipeline_data.pkl)'}.
        Cyan marks are closing <b>MID_PRICE</b>. Magenta diamonds are <b>TRDPRC_1</b> prints.
        The interpolated sheet is a convenience, not a market.
      </p>
      <div style="display:flex; gap:16px; flex-wrap:wrap; margin:12px 0 8px 0;">
        {_card('Series on this date', stats['n_quotes'])}
        {_card('Mid, no print', f"{stats['n_mid_only']} ({stats['pct_mid_no_trade']:.0f}%)")}
        {_card('Both mid &amp; print', stats['n_both'])}
        {_card('Median |mid − trade|', med_txt)}
        {_card('Median relative gap', rel_txt)}
      </div>
      <div style="border-left:4px solid #00ffcc; background:#111820; padding:12px 16px;
                  max-width:820px; line-height:1.55;">
        <div style="color:#00ffcc; font-weight:700; letter-spacing:1px;">READING THE CLOUD</div>
        <div style="color:#e6edf3;">The price cloud is densest near the money and at short DTE, while the far wings and longer expiries are mostly empty.</div>
        <div style="color:#e6edf3;">On a $0.50 strike grid for UUUU, interpolating across empty cells bridges contracts with no observed price and invents a false fill or liquidity signal.</div>
        <div style="color:#e6edf3;">Next week I will treat MID_PRICE as the mark and TRDPRC_1 as evidence that someone actually traded.</div>
      </div>
    </div>
    """

    parts = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        "<title>Options Surface Lab Preview</title>",
        "<style>body{margin:0;background:#0d1117;}</style></head><body>",
        banner,
    ]
    for fig in (fig_cs, fig_px, fig_px_p, fig_cmp, fig_hm_s, fig_hm_t):
        parts.append(fig.to_html(full_html=False, include_plotlyjs="cdn"))
    parts.append("</body></html>")
    html = "\n".join(parts)
    out.write_text(html, encoding="utf-8")
    index = out.with_name("index.html")
    index.write_text(html, encoding="utf-8")
    print(f"Wrote {out} and {index}  asof={asof}  quotes={stats['n_quotes']}  synthetic={payload.get('synthetic')}")
    return out


def _card(label: str, value) -> str:
    return (
        "<div style='background:#161b22;border:1px solid #30363d;border-radius:8px;"
        "padding:12px 16px;min-width:140px;'>"
        f"<div style='color:#8b949e;font-size:12px;'>{label}</div>"
        f"<div style='color:#00ffcc;font-size:22px;font-weight:700;'>{value}</div>"
        "</div>"
    )


if __name__ == "__main__":
    main()
