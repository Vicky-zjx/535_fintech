# FIN 535 — Multi-Asset Risk-Managed Weekly Wheel

[English website](https://vicky-zjx.github.io/535_fintech/docs/) ·
[Nightly workflow](https://github.com/Vicky-zjx/535_fintech/actions/workflows/nightly_orders.yaml)

## Assignment output: proposed orders, not an executed account

The nightly job runs the model and manages root `open_orders.json`, with an
identical `mkt/open_orders.json` compatibility copy. The professor's clarification
does not require an active Sanji resolver or completed fills to generate proposals.
Nothing is submitted to Canvas by this code.

### Account modes

- **Course mode (default, `--mode course`):** if no official account file exists,
  use explicitly hypothetical USD 40,000 starting cash, zero shares, zero short
  options and no leverage. These are course assumptions, not actual balances.
  All normal filters, contract selection, capital limits and position checks apply.
- If `mkt/positions.json` exists, course mode automatically uses the strict
  authoritative adapter instead. Invalid, stale, null or unfamiliar official
  records BLOCK; they never trigger a silent hypothetical fallback.
- **Authoritative-only (`--mode authoritative`):** requires the official book.
  No starting cash is assumed. A previously used official account cannot disappear
  and reset the planner to hypothetical cash.
- **Isolated demonstrations:** `demo.py` replays retained real market observations
  with separate hypothetical books. Their `fin535-demo-` IDs are forbidden in
  the managed queue. The assumed-inventory example is NOT a way to invent covered
  holdings in course mode.

No code creates an official positions file, fills, assignments, premiums, profits
or NAV history. Course proposals have `fin535-course-` IDs; proposals from an
authoritative book use `fin535-wheel-` IDs. Neither is a claim of execution.

### Unconfirmed proposal lifecycle

`course/proposal_state.json` is a durable **commitment record**, not an account.
It stores assumptions and unconfirmed course proposals, never hypothetical fills.

1. Reserve strike × 100 for each proposed put; lock its ticker.
2. Repeat runs for the same session retain the same ID and terms without reserving twice.
3. Once an order's target session has passed, remove it from the active dated queue,
   but KEEP the ticker lock and collateral in the commitment record.
4. Do not infer non-fill, expiry or assignment from elapsed time. Even a proposal
   whose option expiry passed remains uncertain until reconciled.
5. An authoritative, reconciled book with the corresponding `resolved_order_ids`
   can retire those commitments. Stock holdings and cost bases must then support
   any covered call. Merely receiving a book without resolving conflicting
   proposals does not establish that they were unfilled.
6. No manual reset button or automatic nightly reinitialization releases capital.
   Unknown existing queue entries or changed terms under an existing ID block.

Other tickers can still qualify if their data and remaining capital allow it.
If every ticker is locked, the report says `awaiting_order_confirmation`, not
“the market had no opportunities.” This necessarily limits repeated operation
without execution feedback, but does not block initial course proposals.

## Unchanged trading rules

Universe: BAC, KO, PFE and F. Each ticker is evaluated independently, with at most
one Wheel option per ticker and multiple simultaneous names when capital permits.

New puts only target the first actual XNYS session of the week. Use the preceding
completed session's close, SMA20, SMA50, HV20 and five-day return:

- Close >= SMA50 and SMA20 >= SMA50.
- HV20 <= 45%; five-day return >= -8%.
- Target put delta approximately -0.25; call delta approximately +0.25.
- Observed standard-contract expiry 3–10 calendar DTE, nearest 7; earlier expiry
  breaks a tie. Not necessarily Friday of the entry week.
- Missing/incomplete same-session Greeks: observed put strike nearest 3% OTM;
  calls exactly two observed strikes above ATM, subject to both call floors.
  This fallback is NOT a 25-delta estimate. No invented strike grid or Greek.
- Covered calls require confirmed 100 unencumbered shares, strike >=1.01× verified
  stock basis and >=1.02× latest close. They can target any next trading session.
- Exposure <=30% per name, <=70% total; uncommitted cash >=30% of equity.
  No leverage or naked calls. Pending puts count in collateral/exposure. Calls
  add no second stock exposure. Premiums not received cannot finance orders.
- Competing puts are allocated by ascending HV20, then ticker. Calls require no
  additional put collateral. All limits remain enforced.
- **No earnings filter or earnings API requests.** Earnings-related price gaps
  remain a disclosed risk.

## Market inputs and identity

The existing licensed LSEG Data Platform connection uses repository Secrets:
`LSEG_APP_KEY`, `LSEG_USERNAME`, `LSEG_PASSWORD`. No secret is in source or public
outputs; no Workspace dependency is added; no session takeover is forced.

Official IBKR evidence independently verifies BAC **10098**, KO **8894**,
PFE **11031**, F **9599491**, NYSE / USD common stocks. Static mappings must match
`docs/data/conid_verification.json`; conflicting course mappings block.
Identity validity is separate from course database enrollment or option-open
coverage. Apple-only sample history does NOT narrow the strategy universe.

Each ticker needs 50 consecutive completed XNYS closes with actual returned dates.
No stale-date relabeling, interpolation or forward fill. The exact-day close
recheck uses the same `TR.PriceClose.date` / `TR.PriceClose` definition. A successful
API login does not guarantee all requested fields are present. Required missing
market inputs block the batch and preserve prior orders, rather than writing [].
Contract discovery is an observed candidate set, not a complete historical chain.
Current survivors and revised historical closes imply survivorship/revision risks.

## Output contract and failure behavior

The Sanji subset is: stable `id`, dated `for`, `order_type:mkt`, `action:SHT`,
`qty:1`, numeric verified `underlying`, `contract:put|call`, explicit observed
`expiry` and `strike`, `ref:prev_close`. No limit field on a market order.
Sanji's documented market execution reference is the resolved contract's open,
not the signal close or a guaranteed midpoint.

Per-file writes use a flushed/fsynced temporary file and atomic replace. The
commitment record is written before the two queues; in-process failure restores
exact prior bytes. A process crash can leave a conservative lock or disagreeing
mirrors, which the next run rejects; it cannot silently spend unrecorded collateral.
One Git commit publishes the files together. No claim of a multi-file filesystem
atomic transaction is made.

`strategy_status.json` records account mode/assumptions, source hash, input
commitments, per-stock decisions, capital checks, evaluated order array, queue
hash, whether the writer ran and whether content changed. The publication
validator independently reruns successful course decisions from the real snapshot
and requires exact order/decision agreement (1e-12 tolerance only for floating
roundoff), correct target dates and durable commitments.

Distinct outcomes: proposals available, valid no-eligible-trade [], prior proposals
awaiting confirmation, and required-input failure. An unchanged empty array is
not by itself proof of a successful model run.

## Nightly Actions and reproducibility

Schedule: `0 22 * * *`, timezone `America/New_York`; manual dispatch supported.
The shared Platform concurrency group avoids overlapping logins. Each run tests,
queries LSEG, plans all four stocks, validates outputs, commits changed public
artifacts and explicitly requests a Pages rebuild. GitHub may delay cron jobs.
Blocked evaluations publish diagnostics and end nonzero; they do not clear orders.

From the repository root, using the project environment:

```sh
python -m pip install -r final_project/requirements.txt
python -m unittest final_project.test_strategy final_project.test_course final_project.test_demo final_project.test_historical lseg_chart.test_update -b
python -m unittest discover -s tests -p 'test_site_layout.py'
node --test lseg_chart/test_page.cjs final_project/test_page.cjs final_project/test_history_page.cjs
python -m final_project.run --mode course
python -m final_project.demo
python -m final_project.demo --weekly-entry-example
python -m final_project.historical
python -m final_project.validate_publication
```

`python -m final_project.run --mode course --replay` is a clearly labeled retained
snapshot audit: no API request and NO order/commitment writes, even if successful.
Do not substitute an archived week-start snapshot for the current target session.
Unit fixture accounts/prices exist only in tests/temp directories; retained real
LSEG data is used separately for integration checks. Tests never publish fixture
orders as market results.

## Evidence and performance boundaries

`historical.py` studies three years of real daily closes plus 50 warm-up sessions,
with previous-close weekly signals, explicit missing dates and valid denominators.
It generates JSON/CSV and the existing charts. This is technical eligibility
analysis, NOT a historical option backtest or verified investment performance.

The retained November 13 signal / November 16 target real-market integration
produces KO 96 and PFE 28 puts, November 20 expiry, under $40,000 course assumptions:
$12,400 collateral and $27,600 uncommitted cash. This is a **dated historical
integration check**, not today's active queue or actual fills. Current outcomes
come only from the latest workflow's diagnostics; a midweek flat book can rightly
produce zero puts.

The archived [pre-course-mode run](https://github.com/Vicky-zjx/535_fintech/actions/runs/43969760293)
demonstrated working LSEG retrieval but was blocked by the former official-book
requirement and two latest-close gaps. Its status is historical, not the current
course policy. Current website design, editable workflow SVG geometry, prior
assignment navigation and earlier backtest caches are preserved.

## What still needs the professor

Initial course proposal generation no longer depends on official account access.
Authoritative operation and performance measurement still need:

- Native Sanji account schema/sample, confirmed initial balances/complete positions,
  and update-complete timing; a verified read-only adapter to the internal schema.
- Resolution/fill IDs for outstanding proposals; confirmed holdings and bases for
  covered calls; terms and marks for existing option positions.
- Course contract-opening-price coverage and active resolver outputs before claiming
  execution. Public documentation currently says Sanji does not resolve orders yet.

The internal account adapter expects schema_version 1, source Sanji, dated USD cash,
equity, complete positions and optional resolved_order_ids. Stocks require integer
quantity and a verified basis for calls; short options require quantity -1,
multiplier 100, standard_verified terms, strike, expiry and actual mark. NAV must
reconcile within $1. This is NOT asserted to be Sanji's unprovided native schema.

No returns, realized premium income, Sharpe or drawdown are claimed without
verified fills and complete account NAV. [Sanji specification](https://jakevestal.github.io/server-logic-533/order.html).
