"use strict";
// Read-only interpretation of published, engine-validated evidence. No orders,
// prices, positions, fills, NAVs, or performance series are created here.
(() => {
  const tickers = ["BAC", "KO", "PFE", "F"];
  const finite = v => typeof v === "number" && Number.isFinite(v);
  const pct = v => (100 * v).toFixed(2) + "%";
  const money = v => new Intl.NumberFormat("en-US", {style: "currency", currency: "USD"}).format(v);
  const names = xs => xs.length ? xs.join(" and ") : "none";
  const closeEnough = (a, b) => finite(a) && finite(b) && Math.abs(a - b) < 1e-6;
  function signalEvidence(s) {
    if (s?.mode !== "live" || s.source !== "LSEG Data Platform" ||
        !s.market_data_retrieved_at || !s.market_snapshot_sha256 || !s.calendar?.as_of)
      throw Error("No verified market evaluation is attached to this attempt. Retained older snapshots must be reviewed with their own dates; they are not a current signal.");
    const rows = tickers.map(ticker => {
      const matches = (s.decisions || []).filter(d => d.ticker === ticker);
      const d = matches[0];
      if (matches.length !== 1 || d.price_date !== s.calendar.as_of ||
          !["close", "sma20", "sma50", "hv20", "r5"].every(k => finite(d[k])) ||
          d.close <= 0 || d.sma20 <= 0 || d.sma50 <= 0 || d.hv20 < 0)
        throw Error("The four-stock signal comparison requires dated, valid observations for every ticker; missing values are not failed filters.");
      const expected = {trend: d.close >= d.sma50 && d.sma20 >= d.sma50,
        volatility: d.hv20 <= .45, sudden_drop: d.r5 >= -.08};
      if (Object.entries(expected).some(([k, v]) => d.filters?.[k] !== v))
        throw Error("Saved filter flags disagree with their indicators; interpretation withheld pending reconciliation.");
      const failed = Object.keys(expected).filter(k => !expected[k]);
      const q = s.data_quality?.[ticker] || {};
      return {...d, technical: failed.length === 0, failed,
        distance: d.close / d.sma50 - 1,
        earningsVerified: q.earnings?.reliable === true,
        candidateCount: Number.isInteger(q.candidate_count) ? q.candidate_count : null};
    });
    return {asOf: s.calendar.as_of, retrievedAt: s.market_data_retrieved_at,
      target: s.calendar.target_session, rows,
      passed: rows.filter(d => d.technical).map(d => d.ticker),
      trendFailed: rows.filter(d => !d.filters.trend).map(d => d.ticker),
      earningsUnknown: rows.filter(d => !d.earningsVerified).map(d => d.ticker),
      allVolatilityPass: rows.every(d => d.filters.volatility),
      allDropPass: rows.every(d => d.filters.sudden_drop)};
  }
  function signalParagraphs(e) {
    const overview = `At the ${e.asOf} completed close, ${names(e.passed)} passed all three new-put technical filters. ` +
      (e.allVolatilityPass && e.allDropPass
        ? `All four stocks passed HV20 and the five-day decline limit. ${e.trendFailed.length ? `Trend was the separating technical gate: ${names(e.trendFailed)} failed it.` : "No technical filter separated the four names on this date."}`
        : `The individual rejections below identify which gates mattered; the conclusion is recomputed from each saved evaluation.`) +
      " These are conditional screens for a flat account, not approved orders or evidence of investment returns.";
    const paragraphs = e.rows.map(d => {
      const failed = [];
      if (d.close < d.sma50) failed.push("close below SMA50");
      if (d.sma20 < d.sma50) failed.push("SMA20 below SMA50");
      const trend = d.filters.trend
        ? `passed trend, with its close ${pct(d.distance)} above SMA50`
        : `failed trend (${failed.join("; ")})`;
      const interpretation = !d.filters.trend && d.r5 > 0
        ? "The recent bounce has not repaired the medium-term screen; a positive five-day return alone is insufficient."
        : d.filters.trend && d.r5 < 0
          ? "A recent pullback can coexist with a passing medium-term trend. The moving-average buffer is not a forecast or downside protection."
          : d.filters.trend
            ? "Alignment supports conditional put consideration, but does not establish that an option premium compensates for its risk."
            : "Both horizons matter: staying inside the sudden-drop limit does not override weak trend alignment.";
      return `${d.ticker} ${trend}. HV20 was ${pct(d.hv20)} (${d.filters.volatility ? "passed" : "failed"} the 45% ceiling); R5 was ${pct(d.r5)} (${d.filters.sudden_drop ? "passed" : "failed"} the −8% floor). ${interpretation}`;
    });
    return [overview, ...paragraphs,
      "A single quiet snapshot cannot show that volatility and drop filters are redundant. Their incremental value requires point-in-time replay across stressed and recovering markets, including opportunities rejected by each gate. This observation demonstrates screening behavior, not avoided losses or profitability."];
  }
  function hypotheticalCapital(demo) {
    if (demo?.mode !== "demonstration" || demo.production_orders_changed !== false ||
        !demo.market_snapshot_sha256 || !demo.market_retrieved_at)
      throw Error("A labeled, isolated demonstration with real-market provenance is required.");
    const s = demo.scenarios?.find(x => x.id === "covered_inventory");
    const c = s?.capital, a = s?.account;
    if (!c || !a || a.source !== "HYPOTHETICAL_DEMONSTRATION" || s.status !== "success" ||
        c.passed !== true || a.as_of !== demo.calendar?.as_of ||
        ![c.equity, c.cash, c.exposure, c.put_collateral, c.uncommitted_cash].every(finite) ||
        c.equity <= 0 || c.put_collateral !== 0 || c.cash < 0 || c.exposure < 0 ||
        a.positions?.length !== 4 || a.positions.some(p => p.kind !== "stock" || p.quantity !== 100) ||
        new Set(a.positions.map(p => p.ticker)).size !== 4 ||
        !tickers.every(t => a.positions.some(p => p.ticker === t)) ||
        !closeEnough(c.equity, a.equity) || !closeEnough(c.cash, a.cash) ||
        !closeEnough(c.cash, c.uncommitted_cash) || !closeEnough(c.exposure + c.cash, c.equity) ||
        !closeEnough(tickers.reduce((n,t) => n + c.by_ticker?.[t], 0), c.exposure) ||
        tickers.some(t => !finite(c.by_ticker[t]) || c.by_ticker[t] < 0 || c.by_ticker[t] > .3*c.equity+1e-8) ||
        c.exposure > .7*c.equity+1e-8 || c.uncommitted_cash < .3*c.equity-1e-8)
      throw Error("The stock-only hypothetical allocation does not reconcile; no capital figure is inferred.");
    return {asOf: demo.calendar.as_of, retrievedAt: demo.market_retrieved_at,
      exposure: c.exposure, cash: c.cash, equity: c.equity, reserve: .3*c.equity,
      utilization: c.exposure/c.equity, cashFraction: c.cash/c.equity, byTicker: c.by_ticker,
      paragraph: `Hypothetical covered inventory on ${demo.calendar.as_of}: ${money(c.exposure)} in stocks / ${money(c.equity)} equity = ${pct(c.exposure/c.equity)} utilization. Uncommitted cash is ${money(c.cash)} (${pct(c.cash/c.equity)}), above the ${money(.3*c.equity)} minimum reserve. The snapshot assumes 100 shares of each stock, no short options, and bases equal to observed closes. Quantities, bases and starting wealth are assumptions; prices are retained LSEG observations. This is neither actual Sanji capital nor a period-average denominator, and no return can be inferred.`};
  }
  const api = {signalEvidence, signalParagraphs, hypotheticalCapital};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (typeof window !== "undefined") window.FinalAnalysis = api;
})();
