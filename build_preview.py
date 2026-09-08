"""Build the final standalone GitHub Pages site from the cached real LSEG pull."""

from html import escape
from pathlib import Path

import pandas as pd

from option_surface_plots import (
    candlestick_figure,
    coverage_heatmap,
    data_availability_figure,
    mid_vs_trade_figure,
    price_surface_figure,
)
from option_surface_utils import (
    attach_underlying,
    available_cp_values,
    best_coverage_asof,
    flatten_lseg_options,
    load_payload,
    pivot_trade_mid,
    select_asof_rows,
    summarize_sparsity,
)


PLOT_CONFIG = {
    "displaylogo": False,
    "responsive": True,
    "scrollZoom": True,
    "showTips": False,
}


def _plot_html(fig, *, div_id: str, include_plotlyjs: bool = False) -> str:
    return fig.to_html(
        full_html=False,
        include_plotlyjs="cdn" if include_plotlyjs else False,
        config=PLOT_CONFIG,
        div_id=div_id,
    )


def _metric_card(kicker: str, value: str, label: str, note: str, tone: str) -> str:
    return f"""
    <article class="metric-card metric-{tone}">
      <div class="metric-kicker">{escape(kicker)}</div>
      <div class="metric-value">{escape(value)}</div>
      <div class="metric-label">{escape(label)}</div>
      <div class="metric-note">{escape(note)}</div>
    </article>
    """


def main() -> Path:
    base_dir = Path(__file__).resolve().parent
    primary_cache = base_dir / "option_pipeline_data.pkl"
    if not primary_cache.exists():
        raise FileNotFoundError(
            f"Real LSEG cache not found at {primary_cache}; refusing to build a synthetic page."
        )

    payload = load_payload(str(primary_cache))
    if payload.get("synthetic"):
        raise RuntimeError("Refusing to build index.html from a synthetic payload.")

    # Keep the assignment pipeline intact: parse RICs, tidy to contract/date rows,
    # attach real underlying history, then put both option fields on the same row.
    tidy = flatten_lseg_options(payload["options"])
    tidy = attach_underlying(tidy, payload["stock"])
    wide = select_asof_rows(pivot_trade_mid(tidy))
    ticker = str(payload.get("ticker", "UUUU"))

    asof = best_coverage_asof(wide)
    if asof is None:
        raise RuntimeError("The real cache contains no date with MID_PRICE or TRDPRC_1 observations.")
    asof_rows = select_asof_rows(wide, asof=asof)
    stats = summarize_sparsity(asof_rows)

    available_sides = available_cp_values(wide, asof=asof)
    if not available_sides:
        raise RuntimeError("The selected real-data date has no usable call or put observations.")
    display_cp = available_sides[0]
    side_labels = {"C": "Calls", "P": "Puts"}
    available_side_names = [side_labels[side] for side in available_sides]

    fig_stock = candlestick_figure(payload["stock"], ticker)
    surface_figures = [
        price_surface_figure(wide, asof, cp=side, ticker=ticker)
        for side in available_sides
    ]
    # Metrics, scatter, and availability all receive the exact same as-of slice.
    fig_compare = mid_vs_trade_figure(wide, asof=asof, ticker=ticker)
    fig_availability = data_availability_figure(wide, asof=asof, ticker=ticker)
    fig_heat_mid = coverage_heatmap(wide, asof, cp=display_cp, field="MID_PRICE")
    fig_heat_trade = coverage_heatmap(wide, asof, cp=display_cp, field="TRDPRC_1")

    asof_txt = str(pd.Timestamp(asof).date())
    fetched_at = payload.get("fetched_at")
    fetched_markup = (
        f'<span>Fetched {escape(str(fetched_at))}</span>' if fetched_at else ""
    )
    side_note = " + ".join(available_side_names)

    median_abs = stats["median_abs_diff"]
    median_abs_txt = "n/a" if median_abs is None else f"${median_abs:.3f}"
    median_rel = stats["median_rel_diff_pct"]
    median_rel_txt = "n/a" if median_rel is None else f"{median_rel:.1f}%"
    pct_mid_no_trade = f"{stats['pct_mid_no_trade']:.1f}%"

    stock_html = _plot_html(fig_stock, div_id="market-context", include_plotlyjs=True)
    surface_html = "\n".join(
        f'<div class="chart-frame centerpiece">{_plot_html(fig, div_id=f"option-cloud-{side.lower()}")}</div>'
        for side, fig in zip(available_sides, surface_figures)
    )
    compare_html = _plot_html(fig_compare, div_id="mark-vs-trade")
    availability_html = _plot_html(fig_availability, div_id="data-availability")
    heat_mid_html = _plot_html(fig_heat_mid, div_id="mid-price-coverage")
    heat_trade_html = _plot_html(fig_heat_trade, div_id="trade-print-coverage")

    calls_only_note = ""
    if available_sides == ["C"]:
        calls_only_note = (
            '<p class="data-boundary"><strong>Calls only.</strong> No usable Put observations '
            "exist in this real-data slice, so no empty Put panel is shown.</p>"
        )

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="A real-data study of UUUU option price availability, marks, and trade prints.">
  <title>Option Market Observatory</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #0a131f;
      --panel: #101c2a;
      --panel-2: #0d1825;
      --border: #223346;
      --grid: #26394c;
      --text: #e8eff6;
      --muted: #8a9caf;
      --mid: #74d6f4;
      --trade: #ff7b68;
      --missing: #3b4959;
      --max: 1440px;
    }}
    * {{ box-sizing: border-box; }}
    html {{ scroll-behavior: smooth; background: var(--bg); }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      font-variant-numeric: tabular-nums;
      line-height: 1.5;
    }}
    .shell {{ width: min(var(--max), calc(100% - 48px)); margin: 0 auto; }}
    .hero {{
      padding: 34px 0 56px;
      background: #0b1623;
      border-bottom: 1px solid var(--border);
    }}
    .hero-topline {{
      display: flex;
      justify-content: space-between;
      gap: 20px;
      color: var(--muted);
      font-size: 11px;
      font-weight: 700;
      letter-spacing: .18em;
      text-transform: uppercase;
    }}
    .real-badge {{ color: var(--mid); }}
    .hero-grid {{
      display: grid;
      grid-template-columns: minmax(0, 1.55fr) minmax(280px, .45fr);
      gap: 72px;
      align-items: end;
      margin-top: 64px;
    }}
    h1 {{
      max-width: 980px;
      margin: 0;
      color: var(--text);
      font-size: clamp(46px, 7vw, 100px);
      font-weight: 640;
      letter-spacing: -.055em;
      line-height: .9;
    }}
    .subtitle {{
      max-width: 780px;
      margin: 28px 0 0;
      color: #bcc9d6;
      font-size: clamp(18px, 2vw, 27px);
      letter-spacing: -.015em;
    }}
    .meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px 20px;
      margin-top: 24px;
      color: var(--muted);
      font-family: "SFMono-Regular", Consolas, monospace;
      font-size: 12px;
    }}
    .meta span {{ position: relative; }}
    .meta span:not(:last-child)::after {{
      content: "·";
      position: absolute;
      right: -13px;
      color: #53677b;
    }}
    .signal-key {{
      padding: 22px 0 4px 24px;
      border-left: 1px solid var(--border);
    }}
    .signal-key h2 {{
      margin: 0 0 16px;
      color: var(--muted);
      font-size: 11px;
      letter-spacing: .18em;
      text-transform: uppercase;
    }}
    .key-row {{ display: flex; align-items: center; gap: 11px; margin: 11px 0; color: #c8d4df; font-size: 13px; }}
    .key-dot {{ width: 9px; height: 9px; border-radius: 50%; flex: 0 0 auto; }}
    .key-mid {{ background: var(--mid); }}
    .key-trade {{ background: var(--trade); transform: rotate(45deg); border-radius: 1px; }}
    .key-missing {{ background: var(--missing); }}
    main {{ padding-bottom: 88px; }}
    section {{ padding: 76px 0; border-bottom: 1px solid var(--border); }}
    .section-head {{
      display: grid;
      grid-template-columns: minmax(150px, .35fr) minmax(0, 1.65fr);
      gap: 48px;
      margin-bottom: 30px;
      align-items: start;
    }}
    .section-index {{
      color: var(--muted);
      font-family: "SFMono-Regular", Consolas, monospace;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: .16em;
      text-transform: uppercase;
    }}
    .section-copy h2 {{
      margin: -7px 0 10px;
      color: var(--text);
      font-size: clamp(30px, 4vw, 52px);
      font-weight: 560;
      letter-spacing: -.035em;
      line-height: 1.05;
    }}
    .section-copy p {{ max-width: 820px; margin: 0; color: var(--muted); font-size: 15px; }}
    .snapshot {{ padding-top: 64px; }}
    .snapshot-title {{
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 24px;
      margin-bottom: 24px;
    }}
    .snapshot-title h2 {{ margin: 0; font-size: 13px; letter-spacing: .18em; text-transform: uppercase; }}
    .snapshot-title span {{ color: var(--muted); font-size: 12px; }}
    .primary-metrics {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; }}
    .secondary-metrics {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; margin-top: 16px; }}
    .metric-card {{
      min-height: 178px;
      padding: 24px;
      background: var(--panel);
      border: 1px solid var(--border);
      border-top: 3px solid var(--missing);
    }}
    .secondary-metrics .metric-card {{ min-height: 122px; display: grid; grid-template-columns: 1fr auto; align-items: end; gap: 10px 28px; }}
    .metric-mid {{ border-top-color: var(--mid); }}
    .metric-trade {{ border-top-color: var(--trade); }}
    .metric-neutral {{ border-top-color: #8fa6b9; }}
    .metric-kicker {{ color: var(--muted); font-size: 10px; font-weight: 750; letter-spacing: .16em; text-transform: uppercase; }}
    .metric-value {{ margin-top: 18px; color: var(--text); font-size: clamp(36px, 4vw, 58px); font-weight: 620; letter-spacing: -.04em; line-height: .95; }}
    .metric-mid .metric-value {{ color: var(--mid); }}
    .metric-trade .metric-value {{ color: var(--trade); }}
    .metric-label {{ margin-top: 14px; color: #ccd7e1; font-size: 14px; font-weight: 620; }}
    .metric-note {{ margin-top: 5px; color: var(--muted); font-size: 12px; }}
    .secondary-metrics .metric-value {{ grid-row: 1 / 4; grid-column: 2; margin: 0; font-size: 38px; }}
    .chart-frame {{
      width: 100%;
      overflow: hidden;
      background: var(--panel);
      border: 1px solid var(--border);
      padding: 14px;
    }}
    .chart-frame + .chart-frame {{ margin-top: 16px; }}
    .centerpiece {{ border-color: #2d455a; padding: 18px; }}
    .plotly-graph-div {{ width: 100% !important; }}
    .data-boundary, .interpolation-note {{
      margin: 16px 0 0;
      padding: 13px 16px;
      color: var(--muted);
      background: var(--panel-2);
      border: 1px solid var(--border);
      font-size: 12px;
    }}
    .data-boundary strong {{ color: var(--mid); }}
    .interpolation-note {{ margin: 0 0 16px; border-left: 3px solid #71879b; }}
    .interpolation-note strong {{ color: #cbd7e1; }}
    .heatmap-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 16px; }}
    .interpretation-list {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }}
    .interpretation-item {{
      min-height: 190px;
      padding: 24px;
      background: var(--panel);
      border: 1px solid var(--border);
    }}
    .interpretation-number {{ color: var(--mid); font-family: "SFMono-Regular", Consolas, monospace; font-size: 12px; }}
    .interpretation-item h3 {{ margin: 32px 0 10px; color: var(--text); font-size: 14px; letter-spacing: .08em; text-transform: uppercase; }}
    .interpretation-item p {{ margin: 0; color: #afbdca; font-size: 14px; }}
    footer {{ display: flex; justify-content: space-between; gap: 24px; padding-top: 28px; color: var(--muted); font-size: 11px; }}
    @media (max-width: 900px) {{
      .shell {{ width: min(100% - 28px, var(--max)); }}
      .hero-grid, .section-head {{ grid-template-columns: 1fr; gap: 26px; }}
      .hero-grid {{ margin-top: 44px; }}
      .signal-key {{ padding-left: 0; border-left: 0; border-top: 1px solid var(--border); padding-top: 18px; }}
      .primary-metrics, .interpretation-list {{ grid-template-columns: 1fr; }}
      .secondary-metrics, .heatmap-grid {{ grid-template-columns: 1fr; }}
      section {{ padding: 56px 0; }}
    }}
    @media (max-width: 560px) {{
      .hero {{ padding-top: 24px; }}
      h1 {{ font-size: 44px; }}
      .hero-topline {{ flex-direction: column; gap: 6px; }}
      .chart-frame {{ padding: 4px; overflow-x: auto; }}
      footer {{ flex-direction: column; }}
    }}
  </style>
</head>
<body>
  <header class="hero">
    <div class="shell">
      <div class="hero-topline">
        <span>Assignment 1.1 · Option Surface Lab</span>
        <span class="real-badge">Real LSEG observations</span>
      </div>
      <div class="hero-grid">
        <div>
          <h1>OPTION MARKET<br>OBSERVATORY</h1>
          <p class="subtitle">Mapping where the option market exists — and where it does not.</p>
          <div class="meta">
            <span>{escape(ticker)}</span>
            <span>As-of {asof_txt}</span>
            <span>LSEG cached data</span>
            {fetched_markup}
          </div>
        </div>
        <aside class="signal-key" aria-label="Visual encoding">
          <h2>Observation key</h2>
          <div class="key-row"><span class="key-dot key-mid"></span><span>MID_PRICE · closing midpoint</span></div>
          <div class="key-row"><span class="key-dot key-trade"></span><span>TRDPRC_1 · last print</span></div>
          <div class="key-row"><span class="key-dot key-missing"></span><span>Unavailable · remains missing</span></div>
        </aside>
      </div>
    </div>
  </header>

  <main class="shell">
    <section class="snapshot" aria-labelledby="snapshot-heading">
      <div class="snapshot-title">
        <h2 id="snapshot-heading">Market Snapshot</h2>
        <span>{escape(side_note)} · same {asof_txt} slice throughout</span>
      </div>
      <div class="primary-metrics">
        {_metric_card('Market coverage', str(stats['n_quotes']), 'Listed series', 'Contracts with at least one reported option field', 'mid')}
        {_metric_card('Liquidity gap', pct_mid_no_trade, 'Mid, no print', f"{stats['n_mid_only']} of {stats['n_quotes']} listed series", 'trade')}
        {_metric_card('Price disagreement', median_abs_txt, 'Median |MID_PRICE − TRDPRC_1|', f"Calculated only where both fields exist (n={stats['n_both']})", 'neutral')}
      </div>
      <div class="secondary-metrics">
        {_metric_card('Paired observations', str(stats['n_both']), 'Both mid & print', 'Same contract and same as-of date', 'neutral')}
        {_metric_card('Relative disagreement', median_rel_txt, 'Median relative gap', 'Absolute gap divided by MID_PRICE', 'neutral')}
      </div>
    </section>

    <section aria-labelledby="context-heading">
      <div class="section-head">
        <div class="section-index">01 · Market Context</div>
        <div class="section-copy">
          <h2 id="context-heading">Underlying price context</h2>
          <p>The real UUUU OHLC path shows where listed option strikes sit relative to the underlying spot range.</p>
        </div>
      </div>
      <div class="chart-frame">{stock_html}</div>
    </section>

    <section aria-labelledby="cloud-heading">
      <div class="section-head">
        <div class="section-index">02 · Option Cloud</div>
        <div class="section-copy">
          <h2 id="cloud-heading">Observed prices in three dimensions</h2>
          <p>Strike, days to expiry, and option price reveal a sparse cloud. Ice-blue midpoints and coral trade prints are the real observations.</p>
        </div>
      </div>
      <div class="interpolation-note"><strong>Interpolated visualization — not an executable market price.</strong> The neutral sheet is only a low-opacity guide; it does not fill or replace missing raw observations.</div>
      {surface_html}
      {calls_only_note}
    </section>

    <section aria-labelledby="compare-heading">
      <div class="section-head">
        <div class="section-index">03 · Mid Price vs Last Trade</div>
        <div class="section-copy">
          <h2 id="compare-heading">Mark vs trade</h2>
          <p>How far is the closing midpoint from the last actual print? Every point below uses a contract with both real fields on {asof_txt}.</p>
        </div>
      </div>
      <div class="chart-frame">{compare_html}</div>
    </section>

    <section aria-labelledby="availability-heading">
      <div class="section-head">
        <div class="section-index">04 · Data Availability</div>
        <div class="section-copy">
          <h2 id="availability-heading">Three market states</h2>
          <p>Quote only, quote plus trade, and trade only are mutually exclusive states. A missing field stays missing; it is never treated as zero.</p>
        </div>
      </div>
      <div class="chart-frame">{availability_html}</div>
      <div class="heatmap-grid">
        <div class="chart-frame">{heat_mid_html}</div>
        <div class="chart-frame">{heat_trade_html}</div>
      </div>
      <p class="data-boundary">Coverage maps show {escape(side_labels[display_cp])} because that is the real option side available for this selected date.</p>
    </section>

    <section aria-labelledby="interpretation-heading">
      <div class="section-head">
        <div class="section-index">05 · What the Data Says</div>
        <div class="section-copy">
          <h2 id="interpretation-heading">Reading the gaps</h2>
          <p>Three takeaways from the observed cloud and its missing cells.</p>
        </div>
      </div>
      <div class="interpretation-list">
        <article class="interpretation-item">
          <span class="interpretation-number">01</span>
          <h3>Density</h3>
          <p>The cloud is densest near the money and at shorter DTE, while the far wings and longer expiries are mostly empty.</p>
        </article>
        <article class="interpretation-item">
          <span class="interpretation-number">02</span>
          <h3>Interpolation risk</h3>
          <p>On UUUU's $0.50 strike grid, filling empty cells can connect contracts with no observed price and suggest false liquidity.</p>
        </article>
        <article class="interpretation-item">
          <span class="interpretation-number">03</span>
          <h3>Field choice</h3>
          <p>Next week I will use MID_PRICE as the mark and TRDPRC_1 as evidence that an actual trade printed.</p>
        </article>
      </div>
    </section>

    <footer>
      <span>Assignment 1.1 · Option Surface Lab</span>
      <span>Static GitHub Pages build · real cached LSEG data · no Python backend</span>
    </footer>
  </main>
</body>
</html>
"""

    html = "\n".join(line.rstrip() for line in html.splitlines()) + "\n"
    out = base_dir / "options_surface_preview.html"
    index = base_dir / "index.html"
    out.write_text(html, encoding="utf-8")
    index.write_text(html, encoding="utf-8")
    print(
        f"Wrote {out.name} and {index.name}  asof={asof_txt}  "
        f"quotes={stats['n_quotes']}  paired={stats['n_both']}  synthetic=False"
    )
    return out


if __name__ == "__main__":
    main()
