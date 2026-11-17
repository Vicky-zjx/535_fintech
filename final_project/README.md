# FIN 535 — Multi-Asset Risk-Managed Weekly Wheel

[English website](https://vicky-zjx.github.io/535_fintech/docs/) ·
[Nightly workflow](https://github.com/Vicky-zjx/535_fintech/actions/workflows/nightly_orders.yaml)

## Assignment output: proposed orders, not an executed account

The nightly job runs the model and manages root `open_orders.json`, with an
identical `mkt/open_orders.json` compatibility copy. The professor's clarification
does not require an active Sanji resolver or completed fills to generate proposals.
Nothing is submitted to Canvas by this code.

### Current policy — gap-aware flexible weekly entry

Revision `gap-aware-flexible-weekly-v2` intentionally changes the observation window
and put-entry schedule. It does not relax technical thresholds, option selection,
cash security, position protection or exposure limits. Current real outcomes are
in `docs/data/strategy_status.json`; the older run below describes superseded rules.

### Verified fresh run — November 16, 2026, 23:42 UTC

[Actions run 43981421173](https://github.com/Vicky-zjx/535_fintech/actions/runs/43981421173)
completed successfully, queried real LSEG data and wrote both matching order files
plus the durable proposal history. Target: Tuesday November 17; no Monday gate.
Mode: explicitly hypothetical $40,000 course proposal, NOT an official Sanji account.

| Stock | Close / SMA20 / SMA50 | HV20 / R5 | Result |
| --- | --- | --- | --- |
| BAC | 50.08 / 50.4905 / 53.8188 | 24.97% / -0.93% | Trend failed |
| KO | 99.48 / 95.0620 / 91.0482 | 20.44% / +3.59% | Propose 1 put, strike 96, expiry 2026-11-27 |
| PFE | 28.86 / 29.7635 / 28.8100 | 25.25% / -1.27% | Propose 1 put, strike 28, expiry 2026-11-27 |
| F | 11.57 / 12.1210 / 12.4984 | 31.23% / -7.59% | Trend failed |

All four now have 55/55 valid recent closes and the actual November 16 price date.
BAC/F's earlier reply and exact-day retry stopped at November 13; the newly queried
original-RIC history itself now contains November 16. This is an observed provider
availability change, not a confirmed explanation of LSEG's update timing. No
additional recovery/alternate-RIC queries were needed this time, and no price
field, date or observation was fabricated. Earlier raw replies remain in Git history
(commit `79dff0e`); current raw replies are in `docs/data/market_snapshot.json`.

The two proposals reserve $12,400 (31%); uncommitted cash is $27,600 (69%), above the
$12,000 floor. KO/PFE commitments are 24%/7% of starting equity. Cash remains $40,000:
no premium or fill is credited. Both expiries are 10 calendar DTE, the observed
expiry nearest the unchanged seven-day target. Dated Greeks remain incomplete;
the existing observed-strike-nearest-3%-OTM fallback was used, NOT verified 25-delta.

Validation: 119 Python tests, 4 layout tests, 35 JavaScript tests and independent
publication reproduction. Official account/fill history and course execution
coverage remain unresolved; these do not prevent labeled course proposals.

### Archived run — November 16, 2026, 23:16 UTC (superseded policy)

[Live Actions run](https://github.com/Vicky-zjx/535_fintech/actions/runs/43977705993)
used the new course mode and successfully retrieved LSEG responses. The missing
official book was **not** a blocking condition. BAC/F still returned November 13
closes in both the main history and exact-November-16 recheck; neither was relabeled.
Planning for November 17 therefore remained blocked by missing market inputs.
KO/PFE were independently rejected for new puts because Tuesday is not this week's
first trading session. No filters were relaxed to manufacture an order.

This real run did **not** replace either order array: `orders_updated:false`,
`evaluated_orders:null`; the retained [] is NOT a successful no-trade claim.
It automatically committed the new real snapshot/diagnostics and rebuilt Pages;
the job's final failure correctly exposes missing prices. Official account access,
conids or authentication were not the failure. Next valid scheduled/manual runs
use the same writer and persistent commitment checks.

Validation: 146 checks (109 Python engine/provider/history/mode tests, 4 layout,
33 JavaScript), plus publication reproduction. The retained real week-start
integration exercises both JSON writes and commitment persistence in a temporary
directory; those historical proposals are not published as today's orders.

### Account modes

- **Clarified initial state:** the professor confirmed: "You start with no positions.
  Yes, cash only initially." Zero shares, zero open puts and zero open calls are
  therefore established without creating or waiting for `positions.json`.
  The student separately selected and explicitly authorized **$40,000 of simulated
  starting cash**. This is a student-selected course assumption, not a
  professor-confirmed amount or an official Sanji balance. `course.initial_policy()`
  records these two authorities separately in each new diagnostic report.
- **Course mode (default, `--mode course`):** if no official account file exists,
  use the student-authorized simulated USD 40,000 and professor-confirmed initial
  zero inventory, with no leverage. These are not actual account balances.
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

`initial_cycle_review` reselects initial puts with the same real, dated snapshot
and reconciles each proposed strike × 100 against all unchanged capital checks.
It is a read-only check, not another order writer. It is withheld once earlier
proposal dates or an authoritative book exist. The actual evaluation always
includes durable pending commitments and weekly locks. A zero initial reference
must not be mistaken for verified zero holdings after proposals could have filled.
Reproduce without querying LSEG or changing either order file:
`python -m final_project.run --mode course --replay`, followed by
`python -m final_project.validate_publication`. Replay updates diagnostics only;
fresh nightly course runs remain the sole API-driven proposal workflow.

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

## Trading rules

Universe: BAC, KO, PFE and F. Each ticker is evaluated independently, with at most
one Wheel option per ticker and multiple simultaneous names when capital permits.

New puts can target any next XNYS trading session, at most once per ticker per
trading week (Monday-based exchange week, including holiday-shortened weeks).
`course/proposal_state.json` retains `put_proposal_history` for both account modes:
an issued put consumes its week even when later resolved. Unconfirmed course
orders also reserve collateral and lock the ticker beyond that week/expiry;
only authoritative reconciliation releases those obligations. Never infer fills.
Use the preceding
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

Retrieve three years plus 55 warm-up exchange sessions. Each ticker needs at least
50 valid closes within the latest 55 completed XNYS sessions, including the latest
completed close. SMA20/50 use the most recent 20/50 valid observations; diagnostics
list their dates and missing sessions. HV20 uses the latest 20 valid adjacent-session
log returns within those 55 sessions (sample standard deviation, annualized by sqrt(252));
its actual span can exceed 20 sessions. R5 still compares the current close with
the close exactly five exchange sessions earlier, which must exist.

Recovery first queries the original RIC over the recent 55 sessions and individually
missing dates. If still missing, the independently identity-verified consolidated
RIC is queried using the SAME `TR.PriceClose.date` / `TR.PriceClose`, USD fields.
It must have at least five overlapping closes, and all overlaps must match within
1e-8 USD. Only genuinely returned missing dates are added; existing valid prices
are never overwritten. Raw replies, requests and per-date source RICs are retained
under `price_recovery`. Previous dates returned for an exact-day query are not redated.
No forward fill, interpolation, zero fill or substitution of last trade for close.

An unavailable flat ticker is isolated: other validated stocks may proceed. A
missing mark needed to reconcile held positions, an invalid account, unknown pending
obligations, or an API-wide failure still blocks publication. If all stock indicators
are unavailable, preserve prior orders. Partial coverage is not reported as proof
that the entire market has no opportunities. Diagnostics distinguish technical
pass/fail, data unavailable, option unavailable, capital limits and already proposed.

Alternative-source investigation: [Alpha Vantage's official documentation](https://www.alphavantage.co/documentation/)
offers raw and adjusted daily series but requires its own API key; no such authorized
key is configured here. No alternative prices are mixed into the LSEG series.
Adjustment definitions must be reconciled before any future alternative is used;
[LSEG's content guidance](https://community.developers.lseg.com/discussion/133456/tr-priceclose-field-always-returns-adjusted-stock-prices)
also directs field-definition questions to its content helpdesk. An unverified
alternative does not satisfy the latest-close requirement.
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
python -m unittest final_project.test_strategy final_project.test_course final_project.test_demo final_project.test_historical final_project.test_flexible_entry lseg_chart.test_update -b
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

`historical.py` studies three years of real daily closes plus 55 warm-up sessions,
with previous-close signals for every next-session opportunity, explicit missing
dates and valid denominators. It shares the exact nightly indicator implementation.
Legacy JSON keys `weekly`, `weekly_rows`, `joint_weekly` now contain daily next-session
opportunities, explicitly declared in `entry_sampling`, not independent weekly trades.
Weekly proposal locks are enforced in the planner, not inferred in technical counts.
It generates JSON/CSV and the existing charts. This is technical eligibility
analysis, NOT a historical option backtest or verified investment performance.

The English page's five historical charts read only `docs/data/historical_signals.json`
through `docs/assets/history.js`. Stock and 1M/3M/1Y/3Y controls slice the saved closing-date
rows for Close/SMA20/SMA50, HV20 and five-session returns; they never recalculate
indicators, fill gaps or trim the stored sample. Both comparison charts and their tables
retain the full next-session-opportunity sample, which uses the preceding close and
therefore has different signal-date endpoints. Standalone/exclusive rejection counts
are checked against individual saved rows. The source disclosure reconciles the
snapshot hash, retrieval timestamp, strategy revision and latest four-stock indicators
with `strategy_status.json`; disagreement is displayed rather than silently accepted.
The chart-only update preserves the November 16, 2023–November 16, 2026 data and
the existing KO/PFE proposals. No data fetch or historical rebuild is needed to preview it.

The retained November 13 signal / November 16 target real-market integration
produces KO 96 and PFE 28 puts, November 20 expiry, under $40,000 course assumptions:
$12,400 collateral and $27,600 uncommitted cash. This is a **dated historical
integration check**, not today's active queue or actual fills. Current outcomes
come only from the latest workflow's diagnostics. A midweek date by itself no
longer rejects an eligible put.

The archived [pre-course-mode run](https://github.com/Vicky-zjx/535_fintech/actions/runs/43969760293)
demonstrated working LSEG retrieval but was blocked by the former official-book
requirement and two latest-close gaps. Its status is historical, not the current
course policy. Current website design, editable workflow SVG geometry, prior
assignment navigation and earlier backtest caches are preserved.

## What still needs the professor

Initial course proposal generation no longer depends on official account access.
Initial empty inventory is professor-confirmed; the student-authorized $40,000
simulation budget also resolves the classroom cash-setting dependency. The professor
has **not** confirmed that specific amount. Subsequent authoritative operation and
performance measurement still need:

- Native Sanji account schema/sample, dated balances/complete subsequent positions,
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
