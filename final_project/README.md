# Multi-Asset Risk-Managed Weekly Wheel

Simulation-only Final Project for FIN 535. Website: [Final Project](https://vicky-zjx.github.io/535_fintech/docs/).
Earlier assignments and their real caches are independent and unchanged.

## Intentional strategy revision — no earnings filter

Revision `no-earnings-filter-v1` removes earnings screening as a strategy design
decision, not an unavailable-data workaround. The provider no longer requests any
earnings/event fields or alternate calendars. Missing, upcoming or unknown earnings
do not gate entries. The strategy may be exposed to earnings-related price gaps;
remaining technical, capital and position checks do not eliminate that risk.
All other rules, Sanji schema, production account validation and nightly schedule
remain unchanged. Legacy event responses in the retained raw snapshot are unused
historical evidence, not current diagnostics or inputs. The obsolete standalone
calendar investigation is removed; its history remains in Git.

Use `python -m final_project.run --replay` to audit the saved real snapshot under
the new rule without any API requests or production-order publication, even if
an account later becomes available. The report records `retained_market_replay`,
its evaluation time, the original market retrieval time and original session dates.
This mode is explicit, never a fallback after a failed live query. Run
`python -m final_project.demo` separately to rebuild the hypothetical examples.

Verification for this revision: 74 Python engine/provider/demo tests, four site
layout tests and 24 JavaScript tests pass (102 total), plus publication validation.
Browser verification confirms two cash-start put proposals, three unchanged
covered-inventory call proposals, all seven course-navigation links and no console
errors or horizontal page overflow. Production queues, the original raw snapshot,
portfolio validation, Sanji serialization and nightly schedule remain byte-identical.
No fresh LSEG request was made for this replay; the close is 2026-11-13 and the
original target remains 2026-11-16, not a new order for the current clock time.

## Financial discussion and evidence boundaries

The English page separates **currently supported market analysis**, **explicitly
hypothetical accounts**, and **performance evaluation pending Sanji history**.
`docs/assets/analysis.js` interprets the latest engine-validated published status;
dates, filter outcomes and 100-share reference values are not fixed narrative
numbers. It cross-checks indicator flags and dates and withholds interpretation
when inputs do not reconcile. This is presentation code, not another strategy
engine. An unavailable order download no longer hides available market diagnostics.

The capital illustration reads and reconciles the isolated covered-inventory
example: stock market value plus cash equals its hypothetical equity. It is a
single dated stock allocation, not actual Sanji holdings, average deployed capital
or investment performance. Production allocation remains unmeasured without the
account. The real saved 2026-11-13 close (retrieved 2026-11-16) has BAC/F failing
trend and KO/PFE passing all three technical gates; all four pass HV20/R5. Missing
account data and course mappings are separate dependencies.

The proposed future measurement convention uses EOD stock market value plus
filled-put strike collateral, without double-counting covered calls. Average all
sessions, including cash days; report pending-order reservations separately.
Account return = net portfolio P&L / starting equity (no external flows); capital
return = net strategy P&L / average deployed capital; utilization = deployed /
equity. Net P&L includes realized/unrealized positions, dividends and credited
interest after actual costs. Flow adjustment is required if external flows occur.
Capital return is descriptive and non-annualized. Daily Sharpe would use sample
SD, sqrt(252) and a disclosed 0% RF comparison; complete drawdown needs a complete
flow-adjusted wealth path. No performance values are calculated from signals.

The evaluation discussion proposes a future comparison with the same four-name
Wheel without the three technical entry filters, keeping account validation,
capital, periods, contract access and costs consistent. It is **not an executed
backtest**. Actual strategy fills cannot supply counterfactual baseline fills.

Offline checks (no API pull, no production or demo output writes):

```sh
node --test final_project/test_page.cjs
python -m final_project.validate_publication
python -W ignore::DeprecationWarning -m unittest final_project.test_strategy final_project.test_demo lseg_chart.test_update -q
```

Only the declared earnings policy and associated queries/diagnostics were removed;
the order schema and nightly schedule are unchanged. The existing SVG layout is
preserved with updated labels. OIC references on the page support general option
risk mechanics; saved LSEG diagnostics and example JSON support the dated findings.

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
Production must not initialize a $40,000 account. That amount is used only by the
separate, explicitly hypothetical demonstration described below.

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

### Production versus isolated demonstration (2026-11-16 audit)

The actual control flow is `run.run -> read_orders -> fetch_market ->
conids_from_course -> strategy.evaluate -> validate_account -> pending obligations
-> per-name filters/contract selection -> capital_check -> publish_orders`.
Account validation is the **first current failure**, so subsequent gates have not
passed merely because they did not appear in the top-level error. The retained
four-ticker LSEG price and option responses are real; the missing book is not an
authentication failure. `run.py` now records these independent dependencies in
`pipeline_audit` even when the account blocks the batch.

- `portfolio.validate_account`: missing schema/account, stale date, non-USD book,
  unrecognized source, negative cash, invalid quantities, unsupported/unverified
  obligations, expired unresolved positions, NAV mismatch over $1, uncovered calls
  or conflicting Wheel phases block the account. Cost basis is essential for a call.
- `strategy.evaluate`: source must match the mode; pending orders must be valid,
  identified, nonconflicting and covered. A held short option prevents a new order.
  Partial stock holdings cannot back a call or start another put.
- For puts: first weekly session, close >= SMA50, SMA20 >= SMA50, HV20 <=45%,
  R5 >=-8%. There is no earnings screen or blackout window.
- Both branches need verified conids, actual observed standard contracts and the
  unchanged expiry/strike rules. Expiry is selected first: 3–10 calendar DTE,
  nearest seven days, earlier tie. Same-session delta missing => existing fallback,
  **not** an additional hard block. Calls' two-observed-strikes fallback must still
  satisfy both price floors. Trend/volatility/sudden-drop gates remain new-put
  gates; they are not newly waived to obtain covered-call examples.
- Every new order must satisfy per-name exposure <=30%, total exposure <=70%,
  free cash >=30% of equity. Existing obligations and pending puts consume capacity;
  expected premiums do not fund collateral. No margin or fabricated positions.
- Missing required identity/account/chain inputs block the batch and preserve the
  production queue. Individual strategy rejections can finish evaluation
  with zero orders. This is not the same as passing every input gate.

IBKR's public search and security definitions were independently queried on
2026-11-16: BAC **10098**, KO **8894**, PFE **11031**, F **9599491**; all NYSE, USD,
US common stock. `docs/data/conid_verification.json` retains request URLs, selected
search responses and complete security definitions. `verify_conids.py` checks
ticker, issuer, conid, exchange, currency and asset class. It does not log into IBKR
or place orders. These identifiers are used in demonstrations; production retains
the professor's explicit course `price_history.json` mapping requirement. The
remaining issue is course-feed enrollment/coverage, **not unknown stock identity**.

`python -m final_project.demo` reads the real retained LSEG response, not new prices,
and calls the identical engine with `mode:demonstration` and
`source:HYPOTHETICAL_DEMONSTRATION`. It creates two independent example books:

1. $40,000 cash, no stock/options/pending orders. For the 2026-11-13 signals targeting
   2026-11-16, BAC/F fail trend. Under the revised policy, KO and PFE generate
   one put proposal each: strikes $96 and $28, expiry 2026-11-20 (four DTE).
   They use the unchanged observed-strike fallback, not verified 25-delta Greeks.
   Total collateral/exposure is $12,400 (31%), with $27,600 uncommitted cash
   above the $12,000 reserve; each name is below the $12,000 per-name limit.
2. $40,000 marked equity, 100 shares of each name with explicitly assumed basis
   equal to the real close, $20,893 residual cash, no short options/pending orders.
   This is **not** a claimed assignment or purchase history. Exposure $19,107
   (47.7675%), each name below $12,000, free cash $20,893 above the $12,000 reserve.
   The original rules generate one call each: BAC $52.50, PFE $30, F $13, all
   expiring 2026-11-20 (four calendar DTE). KO's two-strike fallback fails the 2%
   above-close floor, so no KO call. Numeric strikes reference actually discovered
   contracts, not fabricated strike grids. No option premium or fill is invented.

The downloadable example arrays are `docs/data/demo_cash_start_orders.json` and
`docs/data/demo_covered_inventory_orders.json`. Full example books, rejection reasons
and capital checks are in `docs/data/demo_status.json`. Their `fin535-demo-*` IDs
cannot be published by the production writer. Demonstration records never change
the production status, either `open_orders.json`, or `mkt/positions.json`. A failed
demo has a null proposal, not a stale example array. Unit-test fixtures remain
separate synthetic TEST data and are not presented as real-market examples.

The professor-specific dependencies are:

1. Authoritative end-of-session book and its **native schema/sample** (actual balances,
   complete positions, stock bases, option terms/marks, resolution IDs/fills), plus
   the upstream completion signal/timing. We must adapt read-only, not write his book.
2. Enrollment of BAC/KO/PFE/F in the course price/option feed and explicit conid bindings,
   consistent with the independently verified IDs. Provider identity does not prove
   Robin contains the contract-open bars needed for resolution.
3. Resolver activation and outputs only for **actual course execution**, not for
   producing schema-valid example JSON: his current spec explicitly says Sanji does
   not resolve orders yet. These proposals are therefore not claimed fills.

No earnings-calendar dependency remains. Greek entitlement is optional because
the original fallback exists. Neither a broker connection nor
a fabricated starting production account is needed or permitted.

Reproduction (from repository root):

```bash
python -m final_project.verify_conids   # public IBKR read-only lookup; no credentials
python -m final_project.run --replay    # audit saved real inputs; never publishes orders; exit 2 if blocked
python -m final_project.demo            # isolated real-response replay
python -W ignore::DeprecationWarning -m unittest final_project.test_strategy final_project.test_demo lseg_chart.test_update -q
python -m unittest discover -s tests -p test_site_layout.py -q
node --test final_project/test_page.cjs lseg_chart/test_page.cjs
python -m final_project.validate_publication
python -m final_project.run             # fresh LSEG; env secrets; exit 2 if production blocked
python -m final_project.demo            # refresh isolated examples after fresh response
```

The nightly workflow runs production and demonstration separately; its final blocked
production status can remain red while the LSEG requests and isolated examples pass.
That status must not be misreported as an API authentication failure.

Historical, pre-revision run: https://github.com/Vicky-zjx/535_fintech/actions/runs/43822857009 .
All **90** regression checks passed (73 Python engine/provider tests, four site-layout
tests and 13 JavaScript DOM tests). Fresh real inputs reproduced the same 0/3 example
orders under the previous policy, not the revised 2/3 proposals. Both production files retain their original byte hash
`37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570`.
GitHub Pages deployed the generated evidence at commit `6b5a3b7`; the red final
workflow step is the intentionally reported missing production-account dependency.

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
  observed expiry closest to7 (earlier tie), chosen before the strike test. If that
  expiry has no qualifying strike, skip rather than silently changing the tenor.
  No synthetic RIC construction/strike grid.
- Ordinary zero-padded-day OPRA RICs are parsed and compared to discovery descriptions.
  LotSize100, USD, Standard, American and underlying identity must agree. Exclusions
  are saved. This is current reference verification, not proof of historical listing.
- Same-session `DELTA_EXCH`, if present for the full eligible slice, targets absolute
  .25. Missing/partial dated Greeks triggers nearest observed 3% OTM put fallback.
  Call fallback is exactly two observed strikes above ATM (lower ATM on tie), then both
  strike floors checked. No relative Sanji tokens are needed; no guessed Greeks.
- No earnings-announcement screen. No event queries or blackout restrictions.
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
live data, validates JSON, commits only allowlisted outputs and calls the Pages
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
- [LSEG dated delta example](https://community.developers.lseg.com/discussion/68876/how-to-retrieve-historical-delta-of-one-specific-option).
- [LSEG consolidated versus exchange-specific option underlyings](https://community.developers.lseg.com/discussion/71956/how-to-retrieve-the-list-of-live-option-contracts-for-a-given-equity-or-equity-index).
- [OCC equity option terms](https://www.theocc.com/clearance-and-settlement/clearing/equity-options-product-specifications).

## Review

No promised performance, historical returns, premiums, fills or illustrative account
balances are displayed as actual. Evaluate a future baseline using identical data,
window, costs and fill assumptions. Track total return, MDD, Sharpe, receipts versus
P&L, assignment, exposure and costs only once real supporting history exists.

## Historical implementation run — before the no-earnings revision

The [third live verification](https://github.com/Vicky-zjx/535_fintech/actions/runs/43815983908)
opened the direct Platform session without Workspace, retrieved 86 actual close
observations per ticker through 2026-11-13, and verified 84 BAC, 92 KO, 80 PFE and
80 F standard OPRA candidates (336 total). The raw discovery also contained 54
nonstandard/foreign identifiers, all excluded with reasons. NYSE listing versus
consolidated-underlying search and display-name header differences were found in
real responses and fixed, with regression tests.

The proposed target session was 2026-11-16. BAC and F failed the trend screen;
KO and PFE passed the three price-based filters. This is **not** an order approval:
the account file and all four course conids were missing, and dated DELTA_EXCH
retrieval was unavailable. The former event-field queries also failed; the revised
strategy removes those queries and their dependency entirely. The documented
listed-strike fallback for missing Greeks remains unchanged. Orders were not changed; both initial arrays remain
empty. The workflow tested and published diagnostics successfully but deliberately
ended with a failed/blocked evaluation, not a claimed successful trading run.

Local verification: 45 Final Project Python tests, 20 existing LSEG Python tests,
4 site-layout tests, 7 Final Project DOM tests and 4 existing chart DOM tests passed
(80 total). Publication JSON/SVG/link checks and YAML parsing passed separately.
Browser checks at 390px and desktop width confirmed the SVG, four ticker rows,
seven navigation links, no horizontal page overflow and no console errors.
