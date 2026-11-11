"""Compact, instrument-independent page rendered from the same API payload."""
from html import escape
from pathlib import Path


def render(payload, figure, output: Path):
    ric = escape(payload["instrument"])
    chart = figure.to_html(full_html=False, include_plotlyjs="../covered-call/assets/plotly.min.js",
                           div_id="lseg-api-chart", config={"responsive": True, "displaylogo": False})
    received = escape(payload["retrieved_at_utc"])
    count = payload["valid_prices"]
    latest = payload["last_close_usd"]
    day = escape(payload["last_price_date"])
    first = escape(payload["first_price_date"])
    html = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{ric} · LSEG API</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f5f4f0;color:#182c38;font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}main{{max-width:1120px;margin:auto;padding:38px 24px}}header{{display:flex;justify-content:space-between;gap:20px;font-size:12px;color:#526b6b}}a{{color:inherit}}h1{{font-family:Georgia,serif;font-size:clamp(36px,5vw,60px);font-weight:400;letter-spacing:-.035em;margin:30px 0 4px}}.sub{{margin:0;color:#5a6c74}}.stats{{display:flex;flex-wrap:wrap;gap:26px;margin:25px 0;padding:18px 0;border-top:1px solid #d8dedf;border-bottom:1px solid #d8dedf}}.stats span{{color:#5a6c74;font-size:12px}}.stats strong{{color:#167765;font-size:24px;margin-right:8px}}.chart{{background:white;border:1px solid #d8dedf}}.note{{color:#5a6c74;font-size:12px;margin-top:18px;overflow-wrap:anywhere}}code{{font-size:12px}}footer{{margin-top:22px;font-size:12px}}
</style></head><body><main>
<header><span>FIN 535 / LSEG API</span><nav><a href="../lseg-live/">Data Lab ↗</a> · <a href="../">Course home ↗</a></nav></header>
<h1>{ric} daily close.</h1><p class="sub">Real API response · {ric} · USD · {first} — {day}</p>
<div class="stats"><span><strong>${latest:,.2f}</strong>latest returned close</span><span><strong>{count}</strong>real observations</span><span><strong>{payload['returned_null_prices']}</strong>returned nulls</span></div>
<div class="chart">{chart}</div>
<p class="note">Fetched directly from LSEG Data Platform at {received}. Fields: <code>TR.PriceClose.date</code> and <code>TR.PriceClose</code>. The query does not read an old market-data cache. Historical daily prices, not a real-time quote; no interpolation, forward filling or zero substitution.</p>
<footer><a href="../lseg-live/data.json">Query response &amp; provenance JSON</a> · Change <code>RIC</code> in <code>lseg_chart/update.py</code>, then push to main or run <code>.venv/bin/python -m lseg_chart.local_api</code>. Both pages update only after a successful query; opening this page does not query LSEG.</footer>
</main></body></html>'''
    output.mkdir(parents=True, exist_ok=True)
    (output / "index.html").write_text(html, encoding="utf-8")
