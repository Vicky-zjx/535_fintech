# AAPL cash-secured Wheel

Published route: [/535_fintech/wheel/](https://vicky-zjx.github.io/535_fintech/wheel/).
This new account engine does not rerun or replace Covered Call, PMCC or Surface
Lab. It reuses their calendar, source-aware price validation, LSEG daily parser
and final-minute quote validator, not their position or leverage rules.

## Measured result

Real LSEG inputs, **2026-07-06–2026-09-30**, 62 trading sessions, $50,000 per
account. Rules were fixed before inspecting Wheel P&L. The suggested $10,000
cannot secure a put on approximately $300 AAPL. One contract is permitted;
the rest of the cash remains idle and earns zero interest. No financing.

| Measure | Wheel: bid sell / ask buy | Wheel: midpoint sensitivity | Buy and hold |
|---|---:|---:|---:|
| Ending equity | $51,865.85 | $51,916.35 | $53,275.20 |
| Net P&L | $1,865.85 | $1,916.35 | $3,275.20 |
| Total return | 3.73% | 3.83% | 6.55% |
| Excess return vs benchmark | −2.82 pp | −2.72 pp | — |
| Full-sample MDD | N/A | N/A | −10.99% |
| Full-sample Sharpe | N/A | N/A | 1.1005 |
| Available daily-return Sharpe | 1.2130 | 1.2543 | 1.1005 |
| Valid daily returns / sessions | 60 / 62 | 60 / 62 | 62 / 62 |
| Observed-NAV drawdown lower bound | −3.63% | −3.62% | −10.99% (complete) |
| Gross premium cash receipts | $1,221.00 | $1,271.50 | $0 |
| Option / stock execution costs | $7.15 / $0 | $7.15 / $0 | $0 / $4.97 |
| Options opened; put / call assignments | 11; 1 / 1 | 11; 1 / 1 | 0 |
| Worthless expiries; rolls | 8; 0 | 8; 0 | 0 |
| EOD sessions with / without shares | 34 / 28 | 34 / 28 | 62 / 0 |

The income thesis produced premium receipts, **not benchmark outperformance**.
Wheel underperformed by 2.82 percentage points in the bid/ask baseline.
A missing daily NAV prevents a complete Sharpe/MDD comparison, so improved
risk-adjusted performance is **not established**. IV versus subsequent realized
volatility is not tested. A short, single-stock, incomplete-universe sample
does not establish an expected-return advantage.

One full Wheel cycle completes. July 31's modeled put assignment acquires 100
shares at $322.50; September 18's modeled call assignment delivers them at $332.50.
August 17 has no eligible call in the observed subset under the cost-floor and
delta rules; it is a documented skip, not proof that no market contract existed.
September 8 (Tuesday after the holiday) selects a September 18 expiry: 10 DTE
is closer to the 7-DTE target than 3 DTE. September 14 therefore keeps that
existing option instead of opening another.

The terminal account is **not forcibly liquidated**. On September 30 it still
holds one short October 2 $335 put, `AAPLV022633500.U^J26`, with an actual
$3.75 midpoint / $375 liability. Baseline cash is $52,240.85, reserved cash
$33,500, shares zero, and equity $51,865.85. Benchmark holds 159 shares plus
$325.02 idle cash. Net equity includes unrealized P&L; premium receipts alone
are never reported as return.

## One genuine unresolved valuation

**2026-08-13, `AAPLH142632250.U^H26`: missing valid closing BBO.**
The original daily null is preserved. A new authorized LSEG quote-event request
for the final 60 seconds returned no eligible same-event BBO. No prior bar,
next-day price, theoretical value, interpolation, forward fill or zero liability
was substituted. A genuine zero bid with a valid positive ask is a valid mark,
but not a positive-premium sell entry.

Both Wheel NAV paths retain this one gap. Full MDD, Sharpe, annualized volatility
and CAGR stay null. Strict drawdown stops at the first gap because an unknown
peak could have occurred. Independently named `observed_drawdown` resumes from
observed peaks, retains the missing point and is only a **lower bound on the
magnitude** of full-sample drawdown. Endpoint P&L remains measurable.

## Strategy and timing

### Available-return statistic (separate from full-sample Sharpe)

`available_daily_return_sharpe` uses only already-computed one-session returns
on the unfiltered daily ledger. Missing August 13 NAV excludes returns dated
**August 13 and August 14**; it never turns the August 12–14 move into a daily
return. The first-session return uses starting cash. Both Wheel scenarios use
60 of 62 returns; buy-and-hold uses 62 of 62. Source prices, NAV gaps, strategy,
fills and all pre-existing statistics remain unchanged.

The formula is `(mean(valid returns) - daily RF) / sample_std(valid returns)
* sqrt(252)`, with `ddof=1` and `daily RF=(1+annual RF)^(1/252)-1` (configured
annual RF is 0%). Fewer than two observations or zero sample variance leaves the
estimate undefined. This is a **partial-sample estimate**, not a repaired NAV
path or full-sample Sharpe; missing-return selection may bias it either way.
Do not infer risk-adjusted outperformance from unequal samples. The page,
`results.json` and `metrics.csv` report its sample counts and excluded dates.

### Trading rules

- First actual trading session of each week, 09:00 ET: use only previous-session
  stock/BBO/historical DELTA and historically evidenced membership. Overnight
  availability is a disclosed assumption where LSEG supplies no publication time.
- Flat: select an observed OTM put targeting −0.25 delta. Holding 100 shares:
  select an observed OTM call targeting +0.25 delta, strike at/above gross share
  acquisition basis. Delta tolerance ±0.15; positive bid and relative spread ≤100%.
- Expiries: 3–10 calendar DTE, closest to 7 first; ties prefer earlier expiry,
  then delta distance, deterministic strike and identifier. No future re-ranking
  when the preselected option lacks a valid execution quote. Missing delta skips;
  explicitly configurable `otm_moneyness` is a different rule, never a fallback.
- Lock the contract before using the same day's closing BBO for simulated fills;
  daily closing marks are consistent with the available bar frequency. No claim
  of exact quote synchrony, available size or actual executed fills.
- Sell at observed bid; necessary buyback hook uses ask. Baseline holds to expiry,
  performs no discretionary buybacks/rolls, and does not force a terminal sale.
  Midpoint is an optimistic spread sensitivity, not execution evidence.
- Daily BBO is preferred. Retained source-validated final-minute quotes follow the
  earlier source policy. New Wheel missing-mark repairs are **valuation-only**,
  so they cannot change selections or execution. Original daily fields stay intact.
- Expiration ≥$0.01 ITM models assignment. American assignment is not observed:
  the default call model also assigns before an already-announced next-session
  dividend when ITM time value is less than that dividend. Other early calls and
  early put assignments are not modeled. After-hours exercise decisions are not
  available from daily bars. No claim of reconstructing actual holder decisions.

All parameters are in `wheel/config.json`; changing it requires a new Python run
with matching real data. UI configuration editing only downloads a JSON file.
There is no browser-side fake rerun and no optimization against this sample.

## Accounting and cost convention

`equity = cash + dividend_receivable + shares × stock_mark − short_option_liability`.
Dividend receivables are economic assets, not spendable cash: accrue once on the
ex-date for shares carried into the open, pay once on the recorded payment date.
This avoids double-counting dividend income and using a future closing mark for
a session-open snapshot. `economic_cash` includes receivables; actual `cash` does
not. Cash is trade-date accounting, **not a T+1 broker settled-cash simulation**.

Before a put opens, existing cash must cover strike × 100 plus option commission
and assignment fee, without funding the check from the incoming premium. Reserve
strike × 100 while the put is open. Calls require exactly 100 shares. No borrow,
leverage, naked calls, short stock, LEAPs or incompatible overlapping positions.

Premium increases cash and creates a short liability. On expiry/assignment it is
realized separately from stock basis. Assignment is one atomic auditable event:
remove the option and transfer exactly 100 shares at strike. Its `stock_action`
records acquisition/delivery; no duplicate stock purchase/sale or intrinsic-value
cash flow is booked. Event before/after snapshots and EOD state reconcile.
EOD timestamps are explicitly after any modeled post-close expiry/assignment.

Option fee: $0.65 per executed contract-side. Stock cost: 1 bp per market-executed
share-side. Assignment fee: $0 default, configurable. Contractual strike delivery
does not incur a second stock-market spread. No expiry commission; bid/ask spread
is already reflected in fill prices, never separately deducted again. Cash earns
0%; Sharpe uses 0% annual RF and daily returns annualized at 252 periods. CAGR uses
calendar days and is withheld with NAV gaps; Calmar is withheld below one year.

The benchmark invests the maximum affordable **whole shares** at the initial
stock print plus the same 1 bp cost; it uses identical dates, dividends and stock
marks. This is a fully invested account comparator, not exposure-matched to a
single option contract. Idle cash differences are intentional and disclosed.

## Actual data, provenance and limitations

The new independent input retains all 306 existing PMCC contracts, 13,835 option
rows, 66 stock rows including warm-up, and four dividend records unchanged.
It requests **702** additional candidate RICs, validates **656** through historical
observations, and adds **14,970** actual daily option rows. The combined input has
962 contracts and 28,805 option rows. Its short-dated study subset has **401 puts
and 413 calls**, with observed put candidates for all 13 weekly signals.
46 probes fail to establish historical membership; they are not declared unlisted.

Strike leads come from retained real RICs and retained LSEG discovery, bounded to
85%–115% of prior spot. There is **no invented strike grid**. Expiry-specific RICs
are unverified probes until real historical responses support them; a later quote
cannot establish earlier availability. Current discovery is not a complete
historical chain. Bounded probing, retained seed selection and survivorship bias
remain explicit limitations. `CANDIDATE_DATA_NOT_COVERED` is distinct from
`NO_ELIGIBLE_IN_OBSERVED_SUBSET`.

RIC day values are zero-padded, call/put letters A–L/M–X, expired suffix A–L for
both. Identity, strike, expiry and scheduled last trading date are rule-derived
and separately validated; last observed quote date is not expiry/last trading day.
100-share USD American terms are **research assumptions**, not per-contract vendor
verification. The retained corporate-action screen and OCC standard specifications
support them, but are not proof of a complete adjustment-history search. Adjusted,
mini or conflicting terms are excluded; unresolved split/delisting/adjustment
blocks a standard-contract run rather than silently continuing.

Candidate-panel fill diagnostics: 17,744 valid daily BBOs, median absolute spread
$0.50/share and median relative spread 8.5722%. This is the candidate population,
not just the 11 fills. Each executed option includes exact RIC, quote date,
bid/ask/midpoint, raw snapshot hash, source and assumptions in JSON/CSV. A missing
exact source timestamp is explicitly null; modeled event times are not presented
as observed trade times. Metadata, exclusions and raw-response hashes are in
`wheel/data_audit.json`; raw licensed snapshots remain local and git-ignored.

Source rules: [LSEG option RICs](https://developers.lseg.com/en/article-catalog/article/functions-to-find-option-rics-traded-on-different-exchanges),
[OCC standard equity options](https://www.theocc.com/clearance-and-settlement/clearing/equity-options-product-specifications),
[OIC adjustment guidance](https://www.optionseducation.org/referencelibrary/faq/splits-mergers-spinoffs-bankruptcies).
The [Schwab Wheel overview](https://www.schwab.com/learn/story/three-things-to-know-about-wheel-strategy)
is a mechanics/risk reference, not a price source or evidence of outperformance.

## Reproduce

From the repository root, using the existing Python 3.13 virtual environment:

```sh
# New environment only; Wheel uses the same dependencies as PMCC.
python -m pip install -r pmcc_backtest/requirements.txt

# Actual acquisition already executed; these files are immutable. For another
# pull, choose NEW output filenames and cache directories. Requires authorized
# LSEG Workspace, the retained real PMCC base and discovery, not a paid-data fake.
.venv/bin/python -m wheel_backtest.acquire --base pmcc_backtest/local_data/observed_input_repaired.json --config wheel/config.json --discovery pmcc_backtest/local_data/probe/search_long.json --output wheel_backtest/local_data/input_v1.json --cache-dir wheel_backtest/local_data/pull_v1
.venv/bin/python -m wheel_backtest.repair_marks --input wheel_backtest/local_data/input_v1.json --output wheel_backtest/local_data/input_v2.json --cache-dir wheel_backtest/local_data/mark_repair_v1 --config wheel/config.json

# Actual full replay, exports and independent account/CSV reconciliation:
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m wheel_backtest.build --input wheel_backtest/local_data/input_v2.json --config wheel/config.json
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m wheel_backtest.validate --input wheel_backtest/local_data/input_v2.json
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest wheel_backtest.test_engine wheel_backtest.test_pipeline wheel_backtest.test_metrics pmcc_backtest.test_engine pmcc_backtest.test_pipeline pmcc_backtest.test_contracts pmcc_backtest.test_repair covered_call.test_engine -q

# Public checkout without licensed inputs: deterministic rendering of committed
# derived results, NOT a claim of recalculating prices or a new empirical run.
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m wheel_backtest.build
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pmcc_backtest.serve_preview --port 8769
# Open http://127.0.0.1:8769/535_fintech/wheel/
```

Optional browser regression (Playwright and local Chrome; not site dependencies):

```sh
WHEEL_PLAYWRIGHT_MODULE=/absolute/path/to/playwright node wheel_backtest/browser_check.cjs http://127.0.0.1:8769/535_fintech/
PMCC_PLAYWRIGHT_MODULE=/absolute/path/to/playwright node pmcc_backtest/browser_check.cjs http://127.0.0.1:8769/535_fintech/
```

For offline raw-response replay use `--offline` and a NEW output with the retained
cache directory/identical request plan. Acquisition records offline replay status,
so that copy's input hash differs; historical rows are unchanged. The mark repair
can be replayed from retained `input_v1.json` and its original cache to reproduce
`input_v2.json` exactly. The public input hash is
`062df6a818222958ff18577eedc825a662bcf362f90227c90d729cdb1bbfeb0d`.

Tests use explicitly synthetic fixtures **only in memory**. Production loading
and publication reject them. Tests cover Wheel cycles, loss despite premiums,
fees, collateral, assignments, dividends, holidays, adjusted terms, zero bids,
missing/stale/future quotes, terminal liabilities and source-time constraints.
`validate` independently replays all three accounts, reconciles cash and P&L,
checks before/after snapshots and compares every exported transaction/state cell.
The browser test checks navigation, downloads, charts, filters, sorting, config
download, desktop/mobile layout and every selectable event/EOD state.

Executed validation: **151 tests passed** across Wheel and existing engines;
49 events, 186 daily ledger rows and 284 snapshots reconcile. Browser checks
passed 352 state selections, 5 routes / 25 navigation links and 10 downloads with
zero JavaScript exceptions. Existing PMCC charts/results also passed regression.
Offline replay of retained raw mark responses reproduced `input_v2.json`
byte-for-byte; a full replay and a saved-result render reproduced result JSON.

Outputs are `wheel/{index.html,book.js,results.json,config.json,data_audit.json,
metrics.csv,blotter.csv,ledger.csv,snapshots.csv,decisions.csv,coverage.csv,quote_issues.csv}`.
The static page uses bundled Plotly; it needs no live LSEG connection or backend.
Existing Pages deployment is `main:/`; private `local_data` and credentials are
excluded. Only the shared route registry and its navigation test change outside
the new Wheel source/publication directories.
