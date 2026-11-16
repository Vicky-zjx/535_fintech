# Multi-Asset Risk-Managed Weekly Wheel

Simulation-only Final Project for FIN 535. Website: [Final Project](https://vicky-zjx.github.io/535_fintech/docs/).
Earlier assignments and their real caches are independent and unchanged.

## Run and reproduce

From the repository root, use Python 3.11+:

```sh
python -m pip install -r final_project/requirements.txt
python -W ignore::DeprecationWarning -m unittest final_project.test_strategy lseg_chart.test_update -v
python -m final_project.validate_publication
python -m http.server 8768 --bind 127.0.0.1
# Open http://127.0.0.1:8768/docs/
```

The test suite performs a dry run into a temporary directory before any network use.
Fixtures deliberately use TEST-prefixed contract IDs and artificial conids. They are
never production inputs or published results. No full historical backtest or equity
curve is asserted for this new strategy.

For a fresh live evaluation, set `LSEG_APP_KEY`, `LSEG_USERNAME` and `LSEG_PASSWORD`
securely in the process environment (or use the existing GitHub Actions Secrets), then:

```sh
python -m final_project.run
python -m final_project.validate_publication
```

Do not put credentials in source, shell history, public JSON, or a tracked `.env`.
The runner reuses `lseg_chart.update.query_lseg` and its guarded direct Platform
GrantPassword session, without force takeover, retries or desktop fallback. The
existing single-stock query remains the default operation and has regression tests.
No broker library is used. Exit 0 = validated evaluation, exit 2 = blocked; a blocked
run preserves both order files and updates diagnostics. API failures never become `[]`.

## Inputs and the unresolved Sanji account adapter

The public Sanji specification documents orders and the read-only role of
`mkt/positions.json`, **not its exact account object schema**. No positions file exists
in this checkout. The planner therefore cannot assert actual equity, cash or holdings.
It must not initialize a $40,000 account. That amount is illustrative only.

`portfolio.validate_account` defines the following **internal adapter contract**, not
an invented claim about Sanji's native format:

- `schema_version: 1`, `source: "Sanji"`, `currency: "USD"`, `as_of: "YYYY-MM-DD"`
- `cash`, `equity`: finite actual balances; cash cannot be negative.
- `positions`: complete list, aggregated per ticker and kind; no unsupported holdings
  may be omitted. Each entry has `ticker`, `kind` (`stock`, `put`, `call`), `quantity`.
- Stock quantity is positive; optional `cost_basis` is actual per-share basis. Missing
  basis blocks calls, not guessed from market value.
- Short option quantity is -1; require actual `strike`, `expiry`, `mark`, `multiplier:100`,
  `terms_status:"standard_verified"`. Unknown/adjusted obligations block the account.
- `resolved_order_ids`: optional list of IDs already resolved by Sanji.

The current strict loader accepts that envelope at `mkt/positions.json` only if the
course producer actually supplies it. When Sanji supplies its native sample, implement
and test a read-only format adapter here; **do not rewrite its file to make it match**.
Sanji must finish the preceding session's fills/assignment before this script runs.
Stale books and a NAV reconciliation error over $1 block new orders. Unknown outside-
universe positions are rejected rather than silently ignored in risk calculations.

Conids must come from numeric keys in the course `price_history.json`, with an explicit
`symbol`, `ticker`, or `ric` binding. The current file identifies Apple only, not the
four Final Project names. No conids are inferred from issuer names or copied from an
unrelated example. Have the course feed enroll BAC, KO, PFE and F and publish their
identifiers/book; this is the remaining external setup for actual order generation.

## Rules and conventions

- Universe BAC/KO/PFE/F. Lookup RICs are validated against `TR.TickerSymbol` before use.
  Closing prices use the NYSE listings (`.N`); US option discovery uses independently
  validated consolidated underlyings (`BAC`, `KO`, `PFE`, `F`). They are not interchangeable
  search filters: `.N` can return foreign derivatives rather than US OPRA contracts.
- XNYS calendar; latest completed close; next session must not already have opened.
  Puts only the first actual weekly session; calls any next session after confirmed
  assignment. No future close or missing-session compression in indicators.
- Close ≥ SMA50, SMA20 ≥ SMA50, sample-HV20 ≤45%, R5 ≥-8% for new puts. HV20 uses 20
  log returns (21 prices), ddof=1 and 252 annualization. Prices use LSEG's `TR.PriceClose`
  adjustment convention, retrieved afresh; this forward planner does not claim a
  point-in-time historical backtest. Null closes are retained and block validation.
- Current discovery candidates only, 3–10 calendar DTE from the **target session**,
  eligible expiry closest to7 (earlier tie). No synthetic RIC construction/strike grid.
- Ordinary zero-padded-day OPRA RICs are parsed and compared to discovery descriptions.
  LotSize100, USD, Standard, American and underlying identity must agree. Exclusions
  are saved. This is current reference verification, not proof of historical listing.
- Same-session `DELTA_EXCH`, if present for the full eligible slice, targets absolute
  .25. Missing/partial dated Greeks triggers nearest observed 3% OTM put fallback.
  Call fallback is exactly two observed strikes above ATM (lower ATM on tie), then both
  strike floors checked. No relative Sanji tokens are needed; no guessed Greeks.
- Earnings: `TR.EventStartDate/Type/Status`, RES, separate forward-looking window.
  `TR.EventStatus=False` means company-confirmed. Require a confirmed next reported
  event; empty/provisional calendar blocks puts. Any reported event entry..expiry
  blocks. Conservative coverage rule does not guarantee the vendor calendar is complete.
- Calls require 100 unencumbered shares, known cost, strike ≥1.01×cost AND ≥1.02×close.
- At most one short option per ticker; no borrowing, naked calls, rolls or stop-loss.
- Exposure = stock MV + existing/pending/new put strike×100. Calls do not double-count
  stock. Per-name≤30%, portfolio≤70%, cash less put obligations≥30% of current equity.
  Expected premium is excluded. Rank competing puts by ascending HV20 then ticker.
- Same-session pending orders are retained and reserved, not regenerated. Old dated
  orders cannot fill a later date; a current reconciled account is required before
  their obligations are released. IDs already resolved are never issued again.
- On required-input failure the batch is blocked. Preliminary per-name candidates
  are not published as orders. Successful no-trade runs may write valid empty arrays.

## Outputs and automation

`open_orders.json` and `mkt/open_orders.json` are byte-identical from one serializer.
Only the documented Sanji subset is used: stable `id`, dated `for`, `mkt`, `SHT`, qty1,
numeric underlying conid, `put`/`call`, explicit listed expiry/strike, `ref:prev_close`.
No `lmt_prc`. Sanji fills market orders at the contract open, not our signal close or
a claimed midpoint. Real fill/assignment support remains controlled by the professor;
the reviewed public spec still states that resolution is not enabled yet.

`docs/data/market_snapshot.json` retains API response tables, normalized observations,
timestamps and exclusions; `strategy_status.json` contains its SHA256, decisions,
capital checks and blocked reasons. Account identifiers and raw positions/fills are
not published. Missing outputs do not conceal the last attempt's failure.

`.github/workflows/nightly_orders.yaml` runs `0 22 * * *` with IANA timezone
`America/New_York` and supports `workflow_dispatch`. It tests offline first, fetches
live data, validates JSON, commits only four allowlisted outputs and calls the Pages
build API explicitly. A blocked evaluation publishes diagnostics but ends red rather
than claiming a successful strategy run. There is no push trigger/commit loop.
Both LSEG workflows share a concurrency group to avoid overlapping Platform sessions.
Existing main/root Pages publishing is retained, including previous navigation.

## Sources inspected

- [Sanji order specification](https://jakevestal.github.io/server-logic-533/order.html):
  orders, conids, supported fields, price tokens, idempotency and assignment.
- [Professor's nightly_refresh.py](https://github.com/JakeVestal/server-logic-533/blob/main/nightly_refresh.py):
  current LSEG discovery pattern; reused, not its broad price-guessing fallbacks.
- Actual example filenames are [`oi-plots.yml`](https://github.com/JakeVestal/server-logic-533/blob/main/.github/workflows/oi-plots.yml)
  and [`deploy.yml`](https://github.com/JakeVestal/server-logic-533/blob/main/.github/workflows/deploy.yml),
  not the underscored `.yaml` names. The latter deploys to a private course host;
  it is not copied and no Tailscale/SSH credentials are introduced.
- [OI reference page](https://jakevestal.github.io/server-logic-533/oi-clusters.html).
- [GitHub timezone-aware schedule](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#onschedule).
- [LSEG event fields and confirmed/estimated status](https://developers.lseg.com/en/article-catalog/article/workspace-corporate-actions-content-set-guide).
- [LSEG dated delta example](https://community.developers.lseg.com/discussion/68876/how-to-retrieve-historical-delta-of-one-specific-option).
- [LSEG consolidated versus exchange-specific option underlyings](https://community.developers.lseg.com/discussion/71956/how-to-retrieve-the-list-of-live-option-contracts-for-a-given-equity-or-equity-index).
- [OCC equity option terms](https://www.theocc.com/clearance-and-settlement/clearing/equity-options-product-specifications).

## Review

No promised performance, historical returns, premiums, fills or illustrative account
balances are displayed as actual. Evaluate a future baseline using identical data,
window, costs and fill assumptions. Track total return, MDD, Sharpe, receipts versus
P&L, assignment, exposure and costs only once real supporting history exists.
