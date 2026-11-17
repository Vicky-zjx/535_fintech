"use strict";
(() => {
  const tickers = ["BAC", "KO", "PFE", "F"];
  const $ = (id) => document.getElementById(id);
  const fmt = (v, percent = false) =>
    typeof v === "number" && Number.isFinite(v)
      ? percent
        ? (v * 100).toFixed(2) + "%"
        : new Intl.NumberFormat("en-US", {
            style: "currency",
            currency: "USD",
          }).format(v)
      : "Unavailable";
  const text = (id, value) => {
    $(id).textContent = value;
  };
  function cell(tr, value, detail) {
    const td = document.createElement("td");
    td.textContent = value;
    if (detail) {
      const small = document.createElement("small");
      small.textContent = detail;
      td.append(small);
    }
    tr.append(td);
  }
  function empty(tbody, columns, message) {
    const tr = document.createElement("tr");
    cell(tr, message);
    tr.firstChild.colSpan = columns;
    tbody.replaceChildren(tr);
  }
  function svgNode(tag, attrs, textValue) {
    const n = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, String(v));
    if (textValue !== undefined) n.textContent = textValue;
    return n;
  }
  function barChart(container, series, label) {
    const el = $(container);
    if (!series.length) return;
    el.replaceChildren();
    const svg = svgNode("svg", {
      viewBox: "0 0 620 250",
      role: "img",
      "aria-label": label,
    });
    const max = Math.max(...series.map((d) => Math.abs(d.value)), 1);
    const signed = series.some((d) => d.value < 0);
    const zero = signed ? 340 : 185;
    const span = signed ? 145 : 280;
    svg.append(svgNode("line", {
      x1: zero, x2: zero, y1: 22, y2: 242, stroke: "#bacbd7",
    }));
    svg.append(svgNode("text", {
      x: zero, y: 16, "text-anchor": "middle", fill: "#526b7d", "font-size": 12,
    }, "0"));
    let y = 28;
    for (const d of series) {
      svg.append(
        svgNode(
          "text",
          { x: 0, y: y + 16, fill: "#526b7d", "font-size": 13 },
          d.label,
        ),
      );
      const w = (span * Math.abs(d.value)) / max;
      const x = d.value < 0 ? zero - w : zero;
      svg.append(
        svgNode("rect", {
          x,
          y: y + 2,
          width: w,
          height: 20,
          fill: d.color || "#32668f",
          rx: 2,
        }),
      );
      svg.append(
        svgNode(
          "text",
          { x: 505, y: y + 17, fill: "#182b3a", "font-size": 12 },
          d.display,
        ),
      );
      y += Math.min(43, 210 / series.length);
    }
    el.append(svg);
  }
  function charts(s) {
    const valid = s.decisions.filter(
      (d) => [d.close,d.sma20,d.sma50].every(v => Number.isFinite(v) && v > 0),
    );
    barChart(
      "signal-chart",
      valid.flatMap((d) => [
        {
          label: d.ticker + " close − SMA50",
          value: (d.close / d.sma50 - 1) * 100,
          display: ((d.close / d.sma50 - 1) * 100).toFixed(1) + "%",
          color: "#32668f",
        },
        {
          label: d.ticker + " SMA20 − SMA50",
          value: (d.sma20 / d.sma50 - 1) * 100,
          display: ((d.sma20 / d.sma50 - 1) * 100).toFixed(1) + "%",
          color: "#91adbf",
        },
      ]),
      "Close and SMA20 deviation from SMA50, percent, by ticker",
    );
    if (s.capital) {
      const c = s.capital;
      barChart(
        "capital-chart",
        [
          { label: "Exposure", value: c.exposure, display: fmt(c.exposure) },
          {
            label: "Put collateral",
            value: c.put_collateral,
            display: fmt(c.put_collateral),
            color: "#91adbf",
          },
          {
            label: "Free cash",
            value: c.uncommitted_cash,
            display: fmt(c.uncommitted_cash),
            color: "#4f766e",
          },
          {
            label: "Minimum reserve",
            value: c.equity * 0.3,
            display: fmt(c.equity * 0.3),
            color: "#a8b5be",
          },
        ],
        "Account exposure, put collateral and uncommitted cash in USD. Collateral is included in exposure, not added again.",
      );
    } else {
      text("capital-chart", "Capital checks unavailable for this attempt. No cash balance or zero exposure is assumed beyond the explicitly selected course mode; see the input diagnostics.");
    }
    text("capital-note", s.account_mode === "course_proposal"
      ? "Course proposal budget only: student-authorized $40,000 simulated starting cash, not actual Sanji NAV or a professor-confirmed amount. Initial zero inventory is confirmed; later holdings are not inferred. Exposure includes reserved put collateral, including past proposals with unknown outcomes. No premiums or fills are credited."
      : "Authoritative account mode: stock market value plus put strike collateral, versus uncommitted cash. Collateral is included in exposure, not added twice. Missing account data is not zero.");
  }
  function renderDiscussion(s) {
    let evidence = null;
    const paragraphs = $("signal-discussion");
    paragraphs.replaceChildren();
    try {
      evidence = window.FinalAnalysis.signalEvidence(s);
      text("analysis-source", `Latest verified published evaluation: close ${evidence.asOf}; LSEG response ${evidence.retrievedAt}; target session ${evidence.target}. Retained observations, not a streaming quote or a new API query.`);
      for (const value of window.FinalAnalysis.signalParagraphs(evidence)) {
        const p = document.createElement("p"); p.textContent = value; paragraphs.append(p);
      }
      text("lot-size-note", `At the ${evidence.asOf} close, 100-share reference values were ${evidence.rows.map(d => d.ticker+" "+fmt(d.close*100)).join("; ")}. These compare lot sizes, not actual purchases or selected-put collateral, which depends on strike.`);
      const missing = tickers.filter(t => /unavailable|fallback/i.test(s.data_quality?.[t]?.delta_status || "unavailable"));
      text("selection-evidence", `${evidence.asOf} diagnostics: ${missing.length ? "dated Greeks unavailable or fallback reported for "+missing.join(", ") : "see each ticker's dated Greek diagnostics"}. Incomplete Greek coverage invokes the existing observed-strike fallback, not an estimated delta: nearest 3% OTM put or exactly two observed call strikes above ATM, still subject to both call floors. Changing the selection basis changes the risk comparison; it is not evidence of a 25-delta execution.`);
    } catch (error) {
      const p = document.createElement("p"); p.textContent = "Signal interpretation withheld: " + error.message; paragraphs.append(p);
      text("analysis-source", "No complete, reconciled four-stock interpretation for this attempt. Refer to the dated diagnostics; no older observation is silently presented as current.");
    }
    const missingIds = tickers.filter(t => !Number.isInteger(s.conid_status?.[t]));
    const blocked = s.status !== "success";
    text("pipeline-discussion", blocked
      ? `The order evaluation is blocked${s.pipeline_audit?.first_blocking_stage ? " at "+s.pipeline_audit.first_blocking_stage : " or has not completed"}. Passing a technical screen is not final eligibility. Required market inputs, existing obligations, verified stock identifiers and available collateral must be validated. Missing official account data alone does not block the explicit course proposal mode. The saved “No Trade” labels do not establish a completed no-opportunity evaluation.`
      : "The planner evaluated each stock independently. " + (s.warnings?.length ? "Some inputs remain unavailable; this does not invalidate other stocks with verified inputs and sufficient capital. " : "") + "Proposed orders are not fills, and a successful run with no orders is not a claim of zero investment return. The proposal reasons remain in the monitor and downloadable audit.");
    const rows = [
      ["LSEG market retrieval", s.market_data_retrieved_at ? "Response received "+s.market_data_retrieved_at : "No successful market response attached to this attempt",
        "Market retrieval and individual field entitlements are separate from Sanji account availability. Completed-session indicators can be studied when validated."],
      ["Technical screen", evidence ? evidence.passed.length+" of 4 pass; "+evidence.rows.filter(d=>!d.technical).map(d=>d.ticker+": "+d.failed.join(", ")).join("; ") : "Complete validated comparison unavailable",
        "A failed filter rejects a new put; absent data is not a failed filter. Call decisions follow the confirmed stock position instead."],
      ["Sanji account", s.account_status || "No verified account status",
        s.account_mode === "course_proposal"
          ? "No positions file is needed to establish the professor-confirmed initial zero inventory. The student authorized $40,000 simulated capital, not an official balance. Durable reservations remain; covered calls need confirmed holdings."
          : "Initial zero inventory is professor-confirmed, but simulated capital is not an official balance. Authoritative mode needs a dated, reconciled book for later cycles; invalid records never fall back to the starting scenario."],
      ["Stock identifiers", missingIds.length ? "Missing for "+missingIds.join(", ") : "All four static conids validated against official IBKR evidence",
        "Literal strike/expiry proposals use verified stock identities. Course conflicts block publication; no nightly IBKR login is required."],
      ["Course execution coverage", (s.pipeline_audit?.course_coverage_unconfirmed || []).length ? "Course binding unconfirmed for "+s.pipeline_audit.course_coverage_unconfirmed.join(", ") : "Inspect the separate course coverage audit",
        "Identity verification does not prove Robin contains the contract-opening prices. Coverage and resolver readiness affect execution, not whether the JSON names the correct stock."],
      ["Proposed course orders", blocked ? "Blocked/not run; retained queue is not a new result" : "Validated proposal evaluation completed",
        "An empty queue while blocked is not a successful no-trade run. Only completed evaluation can establish no valid proposals; neither state establishes executions."],
      ["Trading performance", "Pending verified Sanji execution and NAV histories",
        "Returns, net P&L, realized premiums, Sharpe, MDD and assignment frequency cannot be inferred from signals or example orders. No missing metric is replaced with zero."],
    ];
    const table = $("availability-rows"); table.replaceChildren();
    for (const values of rows) {const tr = document.createElement("tr"); values.forEach(v=>cell(tr,v)); table.append(tr);}
  }
  function renderInitialAccount(s) {
    const p = s.initial_account_policy, a = s.initial_cycle_review;
    const tbody = $("initial-collateral-rows");
    empty(tbody, 4, "No verified initial-cycle audit for this attempt.");
    if (!p || p.scope !== "course_simulation_only" || p.starting_cash !== 40000 ||
        p.professor_confirmed_cash_amount !== false || p.official_sanji_balance !== false ||
        p.initial_positions_file_required !== false ||
        ["shares", "open_puts", "open_calls"].some(k => p.initial_inventory?.[k] !== 0)) {
      text("initial-collateral-note", "This diagnostic file does not contain the current initial-account policy. The stated starting scenario is not evidence of later holdings or fills.");
      return;
    }
    text("initial-account-summary", "Professor-confirmed initial inventory: 0 shares, 0 open puts, 0 open calls. Student-selected and explicitly authorized simulated cash: $40,000. The amount is not professor-confirmed and is not an official Sanji balance. An initial positions.json is not required.");
    if (!a || a.status !== "validated" || a.orders_written !== false || a.fills_inferred !== false ||
        a.market_retrieved_at !== s.market_data_retrieved_at || a.signal_date !== s.calendar?.as_of ||
        a.target_session !== s.calendar?.target_session || a.existing_proposals_match !== true ||
        !Array.isArray(a.collateral_by_proposal) || !Array.isArray(a.proposals)) {
      text("initial-collateral-note", a?.status === "not_initial_cycle"
        ? "Not an initial-cycle reset: earlier proposals or an authoritative book exist. Outstanding orders stay reserved until reconciled; no new flat account is assumed."
        : "Initial-cycle selection/collateral review unavailable or inconsistent. No official balance, filled position or released collateral is inferred.");
      return;
    }
    const c = a.capital, total = a.collateral_by_proposal.reduce((sum,r)=>sum+r.collateral,0);
    if (!c || c.passed !== true || c.cash !== 40000 || c.equity !== 40000 ||
        a.proposals.length !== a.collateral_by_proposal.length || !Number.isFinite(total) ||
        a.collateral_by_proposal.some(r=>r.qty!==1 || r.collateral!==100*r.strike || r.collateral>12000 ||
          !a.proposals.some(o=>o.id===r.id&&o.contract==='put'&&o.strike===r.strike&&o.underlying===r.underlying&&o.qty===r.qty)) ||
        Math.abs(total-c.put_collateral)>1e-8 || Math.abs(total-c.exposure)>1e-8 ||
        Math.abs(c.cash-total-c.uncommitted_cash)>1e-8 || total>28000 || c.uncommitted_cash<12000) {
      text("initial-collateral-note", "Initial-cycle capital reconciliation failed; no validated allocation is asserted.");
      return;
    }
    tbody.replaceChildren();
    for (const r of a.collateral_by_proposal) {
      const ticker = Object.entries(s.conid_status || {}).find(([,id])=>id===r.underlying)?.[0] || "Unmapped";
      const tr=document.createElement("tr");
      [ticker+" / "+r.underlying, fmt(r.strike), r.qty, fmt(r.collateral)].forEach(v=>cell(tr,v)); tbody.append(tr);
    }
    if (!a.collateral_by_proposal.length) empty(tbody,4,"No qualifying initial puts in this dated evaluation.");
    text("initial-collateral-note", `Selection rechecked against the real LSEG ${a.signal_date} close for ${a.target_session}. Total proposed collateral ${fmt(total)} (${fmt(total/c.equity,true)}); uncommitted simulated cash ${fmt(c.uncommitted_cash)}. Per-name limit $12,000; total limit $28,000; minimum reserve $12,000. Existing proposals match this initial-cycle check. This audit writes no orders and credits no premiums or fills; the actual planner retains pending reservations.`);
  }
  function render(s, orders, ordersAvailable = true) {
    const good = s.status === "success";
    const course = s.account_mode === "course_proposal";
    const observed = s.market_data_retrieved_at;
    text(
      "run-state",
      good
        ? "Validated evaluation · " + (course ? "course proposals" : "authoritative account")
        : observed
          ? "Market data retrieved · orders blocked"
          : "Live data not yet available",
    );
    if (good) document.querySelector(".run-strip").classList.add("success");
    text(
      "run-time",
      s.attempted_at
        ? (s.evaluation_kind === "retained_market_replay" ? "Retained-data re-evaluation: " : "Latest attempt: ") +
            s.attempted_at.replace("T", " ").replace("+00:00", " UTC")
        : "No verified live evaluation yet",
    );
    text(
      "target-session",
      "Target session: " + (s.calendar?.target_session || "not yet evaluated"),
    );
    text(
      "decision-note",
      observed
        ? "Signals use completed session " +
            s.calendar.as_of +
            (course ? ". Course proposals use student-authorized $40,000 simulated cash and confirmed initial zero inventory, not an official account."
              : ". Authoritative mode requires a fresh, reconciled account and verified identifiers.") +
            (s.evaluation_kind === "retained_market_replay" ? " This is a replay of the original LSEG response, not a new API query; production orders cannot be published by replay." : "")
        : "Only validated inputs appear here. Missing data is not a no-trade signal.",
    );
    const issues = [...(s.errors || []), ...(s.warnings || [])];
    if (!course && s.account_status && s.account_status !== "Available")
      issues.push(s.account_status);
    text("account-mode", course
      ? "COURSE PROPOSAL MODE · Student-authorized simulated starting cash $40,000; professor-confirmed initial stocks 0, puts 0 and calls 0; no leverage. The amount is not professor-confirmed or an official Sanji balance. " +
        (s.unconfirmed_proposal_count ?? 0) + " unconfirmed proposal(s); past proposals keep their ticker locks and collateral reservations. These are proposals, not fills or actual balances."
      : s.account_mode === "authoritative"
        ? "AUTHORITATIVE ACCOUNT MODE · " + s.account_status + ". The planner reads the book; it never writes positions or assumes executions."
        : "Account mode has not been validated for this attempt. Retained orders are not a new result.");
    if (s.conid_status) {
      const missing = tickers.filter((t) => !s.conid_status[t]);
      if (missing.length)
        issues.push("Verified stock conid mappings missing: " + missing.join(", "));
    }
    text("issues", issues.join(" · "));
    const rows = $("decision-rows");
    rows.replaceChildren();
    for (const ticker of tickers) {
      const d = (s.decisions || []).find((x) => x.ticker === ticker) || {
        ticker,
        reasons: ["Live data not yet available"],
      };
      const tr = document.createElement("tr");
      const w = d.observation_window;
      const pairs = w?.hv20_return_pairs || [];
      const coverage = w ? `${w.valid_closes} valid closes / ${w.expected_sessions} sessions; missing: ${w.missing_dates.join(", ") || "none"}. HV: ${pairs.length} adjacent-session returns${pairs.length ? " from "+pairs[0][0]+" to "+pairs.at(-1)[1] : ""}.` : "";
      cell(tr, ticker, (d.price_date || "No validated close") + (coverage ? ". "+coverage : ""));
      for (const k of ["close", "sma20", "sma50", "hv20", "r5"])
        cell(tr, fmt(d[k], k === "hv20" || k === "r5"));
      const p = d.position;
      cell(
        tr,
        p
          ? `${p.shares} shares / ${p.put} put / ${p.call} call${course ? " (initial reference only; pending proposals are not fills)" : ""}`
          : "Account unavailable",
      );
      cell(
        tr,
        d.filters
          ? Object.entries(d.filters)
              .map(([k, v]) => k + ": " + (v ? "pass" : "fail"))
              .join(" · ")
          : "Not evaluated",
        (d.technical_status ? d.technical_status+". " : "") + (d.eligible ? "Final eligibility passed" : s.status === "blocked" ? "Final eligibility not established" : d.category === "Already proposed" ? "Existing proposal/weekly slot retained; not a new entry or a confirmed fill" : "Not eligible / not evaluated"),
      );
      cell(tr, s.status === "blocked" ? "Evaluation blocked" : d.category === "Proposed order" ? d.decision : d.category || d.decision || "Not evaluated", (d.reasons || []).join("; "));
      rows.append(tr);
    }
    text(
      "order-note",
      s.evaluation_kind === "retained_market_replay"
        ? "Order files were not changed by this retained-data replay. The displayed queue is retained, not newly published proposals; original session dates are preserved."
        : good
        ? orders.length
          ? (course ? "Proposed course orders under explicit hypothetical assumptions; not actual Sanji account orders or fills."
            : "Proposals based on the authoritative book; not verified fills.")
          : s.outcome === "awaiting_order_confirmation"
            ? "No active dated orders. Earlier proposals have unknown outcomes: affected tickers and collateral remain locked, not assumed filled or released. See the commitment record."
            : s.warnings?.length
              ? "No proposals from evaluable stocks. Other tickers have unavailable inputs; this is not evidence that the whole universe has no opportunities."
              : "Valid no-trade evaluation: no qualifying new or pending orders."
        : s.status === "not_run"
          ? "Initial empty queue; not yet a successful no-trade evaluation."
          : "Order files were not changed by this attempt. Any displayed orders are retained from an earlier run; their dated sessions govern eligibility.",
    );
    renderInitialAccount(s);
    const orderRows = $("order-rows");
    orderRows.replaceChildren();
    for (const o of orders) {
      const tr = document.createElement("tr");
      const t =
        Object.entries(s.conid_status || {}).find(
          ([, v]) => v === o.underlying,
        )?.[0] || "Unmapped";
      [
        o.for,
        t + " / " + o.underlying,
        o.action,
        o.contract,
        o.expiry,
        fmt(o.strike),
        String(o.qty),
        o.id,
      ].forEach((v) => cell(tr, v));
      orderRows.append(tr);
    }
    if (!orders.length)
      empty(
        orderRows,
        8,
        s.evaluation_kind === "retained_market_replay"
          ? "Empty retained production queue; replay does not publish orders."
          : good
          ? "No proposed orders for this valid evaluation."
          : "Empty queue; no successful order-generation run is asserted.",
      );
    if (!ordersAvailable) {
      text("order-note", "Production order file could not be loaded; queue contents are unknown, not an empty no-trade result. Market diagnostics are shown independently.");
      empty(orderRows, 8, "Order queue unavailable; no quantity or trade count inferred.");
    }
    const q = $("data-quality");
    q.replaceChildren();
    const stamp = document.createElement("p");
    stamp.textContent =
      "Last successful evaluation: " +
      (s.successful_at || "None verified") +
      ". Latest market response: " +
      (s.market_data_retrieved_at || "None verified") +
      ".";
    q.append(stamp);
    for (const [t, d] of Object.entries(s.data_quality || {})) {
      const p = document.createElement("p");
      p.textContent =
        t +
        ": " +
        (Number.isInteger(d.candidate_count) ? d.candidate_count+" accepted candidates; " : "candidate count unverified; ") +
        (d.options_status || "unavailable") +
        ". " +
        (d.delta_status || "Greeks unavailable") +
        ". " +
        (d.close_recheck_status ? d.close_recheck_status + '. ' : '') +
        (d.errors || []).join("; ");
      q.append(p);
    }
    $("snapshot-link").hidden = !s.market_snapshot_sha256;
    charts({ ...s, decisions: s.decisions || [] });
    renderDiscussion(s);
  }
  async function get(url) {
    const r = await fetch(url, { cache: "no-store" });
    if (!r.ok) throw Error("HTTP " + r.status);
    return r.json();
  }
  function renderDemo(demo) {
    if (demo.mode !== 'demonstration' || demo.production_orders_changed !== false)
      throw Error('Invalid demonstration label');
    text('demo-summary', 'DEMONSTRATION ONLY · Retained real LSEG response: ' + demo.market_retrieved_at +
      ' · Signal close: ' + demo.calendar.as_of + ' · Target: ' + demo.calendar.target_session +
      '. Production orders unchanged. Not a new market query.');
    const container = $('demo-results');
    container.replaceChildren();
    for (const s of demo.scenarios) {
      const block = document.createElement('article');
      const h = document.createElement('h3');
      h.textContent = s.id === 'cash_start' ? 'Example A — cash-only starting portfolio' : 'Example B — assumed covered inventory';
      const account = document.createElement('p');
      account.textContent = s.description + (s.account ? ' Cash: ' + fmt(s.account.cash) + '; equity: ' + fmt(s.account.equity) : ' No inventory or cash balance assumed') +
        '. Proposed orders: ' + (s.order_count ?? 'Blocked') + (s.status === 'success' ? '. Evaluation completed; individual tickers may still fail their entry rules.' : '. Blocked by missing or invalid inputs; no successful no-trade decision is claimed.');
      block.append(h, account);
      for (const d of s.decisions) {
        const p = document.createElement('p');
        const order = (s.proposed_orders || []).find(o => o.underlying === demo.conids[d.ticker]);
        p.textContent = d.ticker + ' — ' + d.decision + ': ' + (order ?
          '1 ' + order.contract + ', strike ' + fmt(order.strike) + ', expiry ' + order.expiry + '; ' : '') + d.reasons.join('; ');
        block.append(p);
      }
      if (s.capital) {
        const p = document.createElement('p');
        p.textContent = 'Hypothetical exposure ' + fmt(s.capital.exposure) + '; put collateral ' + fmt(s.capital.put_collateral) +
          '; uncommitted cash ' + fmt(s.capital.uncommitted_cash) + '; required reserve ' + fmt(s.capital.equity * .3) +
          '. Existing 30% per-name / 70% portfolio limits remain in force.';
        block.append(p);
      }
      container.append(block);
    }
    try {
      const c = window.FinalAnalysis.hypotheticalCapital(demo);
      const allocation = $("demo-capital-chart"); allocation.replaceChildren();
      allocation.classList.add("allocation-chart");
      for (const [label,value,fraction] of [["Stock",c.exposure,c.utilization],["Uncommitted cash",c.cash,c.cashFraction]]) {
        const row=document.createElement("div");row.className="allocation-row";
        const line=document.createElement("p");line.className="allocation-label";
        const name=document.createElement("span");name.textContent=label;
        const number=document.createElement("strong");number.textContent=fmt(value)+" · "+fmt(fraction,true);
        line.append(name,number);
        const track=document.createElement("div");track.className="allocation-track";
        track.setAttribute("role","img");track.setAttribute("aria-label",`Hypothetical ${label}: ${fmt(value)}, ${fmt(fraction,true)} of assumed equity; not a return.`);
        const fill=document.createElement("span");fill.setAttribute("style",`width:${fraction*100}%`);
        track.append(fill);row.append(line,track);allocation.append(row);
      }
      text("demo-capital-note", c.paragraph);
      const largest = Object.entries(c.byTicker).sort((a,b)=>b[1]-a[1])[0];
      text("demo-capital-interpretation", `In this assumed inventory, ${largest[0]} alone accounts for ${fmt(largest[1])}, or ${fmt(largest[1]/c.equity,true)} of equity. Equal contract counts do not mean equal dollar weights. Calls add no second stock exposure; no expected premium is credited. This dated example has no time series from which to calculate an average deployed amount, cash drag or profit.`);
    } catch (error) {
      text("demo-capital-chart", "Hypothetical allocation not shown: "+error.message);
      text("demo-capital-note", "No invalid or missing example amount is substituted with zero or treated as production capital.");
    }
  }
  get('data/demo_status.json').then(renderDemo).catch(() => {
    text('demo-summary', 'Demonstration unavailable. Production status and orders are shown independently above.');
  });
  Promise.allSettled([get("data/strategy_status.json"), get("../open_orders.json")])
    .then(([status, orders]) => {
      if (status.status !== "fulfilled") throw Error("Diagnostics unavailable");
      const loaded = orders.status === "fulfilled" && Array.isArray(orders.value);
      render(status.value, loaded ? orders.value : [], loaded);
    })
    .catch(() => {
      text("run-state", "Live data not yet available");
      text(
        "issues",
        "Published diagnostics or order files could not be loaded. Do not interpret this as a no-trade decision.",
      );
    });
})();
