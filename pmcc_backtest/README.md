# AAPL PMCC — reproducible account engine

Published route: `/535_fintech/pmcc/`. This is independent of the earlier
`covered_call` assignment and its $30,000 Reg T result. Every new comparison
account starts at $50,000; old caches, calculations and plots are preserved.

## Current evidence and status

Six real-input simulated accounts now run over **2026-07-06–2026-09-30**:
PMCC, fully funded covered call and 100-share buy/hold, each under midpoint and
actual quoted-side fills. The window was locked from available expired-short
coverage before P&L; a year-long chain was unavailable. The requested September
endpoint remains. Four previously uncovered short-expiry series are now queried
and historically validated, including October 2 for September 28 entry and
September 30 terminal close. There are 62 trading sessions.

The repaired local input contains 306 contracts and 13,835 daily option rows,
plus 66 stock rows including warm-up and four real dividend records. The
universe starts with 56 exact RICs observed in the old cache and actual long-call
identifiers returned by LSEG discovery, never an invented strike grid. Current
discovery is not historical membership: a contract must have an observation
available by its signal. Long discovery is survivor-biased, and the candidate
chain is incomplete. The long-request strike cap is 255; every sample signal's
75%-spot threshold is below it. Strikes are actual returned values.

`repair_coverage` locks its acquisition plan before requests. Actual AAPL strike
values from retained history/current discovery supply leads within 95%–120% of
each prior-session spot. Expiry-specific zero-padded RICs are **unverified probes**,
not listings. Of 113 probes, 102 have actual historical price evidence; 11 fail
to establish membership (not proof they never listed). Signal-time counts for
September 11/18/25 and October 2 are 24/23/26/27. Two September 25 contracts first
appear after the signal and cannot enter that signal's candidate set. Bounds and
historical discovery limitations remain disclosed; no complete chain is claimed.

The selected long is `AAPLI172723000.U`, bought July 6 and closed September 30.
The long mode was fixed to the 75%-spot proxy before P&L. Later historical DELTA
responses are used only for exposure, not to switch the selection method.

| Account | Midpoint net P&L | Quoted-side net P&L |
|---|---:|---:|
| PMCC | $1,841.60 | $1,437.60 |
| Cash-funded covered call | $2,316.94 | $2,290.44 |
| 100-share buy/hold | $2,056.54 | $2,056.54 |

These are independently reconciled **terminal** outcomes, not complete PMCC/CC
daily paths. Original daily replies have null BID/MID_PRICE on July 23, August
13 and August 27; the parser preserves them. Genuine zero bids are already valid.
The latter two dates are recovered from real same-event BBOs with source times
15:59:31.022 and 15:59:49.231 ET respectively. July 23 has no eligible final-minute
event: the 15:50 minute bar is not a close and is not carried forward. NAV stays
null on July 23, adjacent daily returns are unavailable and full-sample MDD is
withheld. Positions remain in the ledger. All terminal positions
close at observed prices; their cash and attribution reconcile. PMCC/CC each
write 13 shorts, skip zero weeks, and have no modeled assignments. Buy/hold
has a complete valuation path. No annualized headline return is reported.

The strict `drawdown` stops at the first missing NAV and remains blank afterward,
because the true running peak may have been missed. `observed_drawdown` resumes
from observed peaks but retains missing points; its maximum magnitude is only a
**lower bound** on full-sample MDD. Midpoint observed maxima are −6.8678% PMCC and
−6.8563% CC; quoted-side are −6.8915% and −6.8613%. Buy/hold full MDD is −7.1219%.
The page never substitutes the observed statistic for a null full-sample MDD.

### Uniform closing-quote repair

Daily BBO is preferred. For a missing daily leg only, use the **last quote event**
in the final 60 seconds of the actual regular session if it has a complete valid
BBO and both source/event timestamps are same-day, pre-close and within 60s.
A later invalid update rejects the event fallback; no earlier valid quote is
carried through it. Original null fields stay null in the immutable input.
[LSEG event-field guidance](https://community.developers.lseg.com/discussion/72431/historical-pricing-api-rdp)
describes the same-event BID/ASK record; no trade or theoretical field is used.

The same accepted quote supports daily marks and unchanged midpoint/quoted-side
closing-fill formulas. This fixes a daily-only terminal-price rejection: the
October 2 $360 call has a real September 30 quote sourced at 15:59:48.070 ET
(event 15:59:53.116), supporting the preplanned closing buyback. Its actual quote
time is recorded; the closing execution remains simulated, not an observed fill
or an asserted exact-16:00 quote. Signal inputs/long selection are unchanged.
The acquisition began with events isolated for valuation; this plumbing correction
is recorded as `quote_policy_revision`, not hidden as a vendor correction.

The identical time/validity rule rechecks **all 381 missing candidate-panel BBOs**,
recovering 189 and leaving 192 unresolved, not just selected winning trades.
Those counts are not account NAV gaps: only July 23 remains missing for held
PMCC/CC positions. New raw responses, old snapshots and their hashes are retained.

## Contract evidence, assumptions and exclusions

`contracts.py` parses ordinary AAPL OPRA identities using
[LSEG's RIC rules](https://developers.lseg.com/en/article-catalog/article/functions-to-find-option-rics-traded-on-different-exchanges).
Day values are zero-padded per instructor correction and retained real tests.
Calls/puts use A–L/M–X before the day; expired suffixes use A–L for both.
Identity/strike/expiry are rule-derived and compared with available descriptions
or old records. First/last observed quote dates come from real history. Scheduled
last trading dates use the contract rule and exchange calendar, **not the last
quote**. Signal membership is tested against historical availability separately.

Multiplier 100, 100-AAPL-share delivery, USD and American exercise are explicitly
supported **research assumptions**, not individually supplier-verified historical
terms. [OCC standard specifications](https://www.theocc.com/clearance-and-settlement/clearing/equity-options-product-specifications),
available current Standard/American/100-lot descriptions,
[Apple split history](https://investor.apple.com/faq./default.aspx),
[OCC's 2020 AAPL split memo](https://infomemo.theocc.com/infomemos?number=47369)
and the authorized LSEG capital-action query support this screen. No relevant
nonblank capital-action event was returned; that is not a guarantee of every
deliverable or a complete OCC notice search. The
[OIC adjustment guidance](https://www.optionseducation.org/referencelibrary/faq/splits-mergers-spinoffs-bankruptcies)
explains why conflicting/adjusted/mini terms cannot silently be treated as standard.

All 306 records keep `standard_verified=false`, `terms_status="research assumption"`
and field-level sources. Of 50 exclusions, five non-OPRA/unsupported identities
fail the strategy's contract screen; 45 June-2027 candidates are outside the
predeclared long-DTE acquisition window, not allegedly unlisted. The public
contract table and exclusions CSV show the distinction. No supplied historical
contract-master file is a prerequisite. `audit_snapshot.json` is the **archived
initial capability probe**, whose stricter policy was superseded by the explicit
source-supported-assumptions policy; it is not the current run's audit.

## Reproduce the committed publication (offline)

From the repository root, Python 3.13 was tested:

```sh
python -m pip install -r pmcc_backtest/requirements.txt
python -m unittest pmcc_backtest.test_engine pmcc_backtest.test_pipeline pmcc_backtest.test_contracts pmcc_backtest.test_repair covered_call.test_engine -v
python -m pmcc_backtest.build
```

With no input, `build` re-renders committed derived accounts; it does **not**
claim to recalculate P&L without licensed data. It writes only `pmcc/index.html`,
`book.js`, `results.json`, `config.json`, `data_audit.json`, `daily_nav.csv`,
`trades.csv`, `weekly_coverage.csv`, `candidate_coverage.csv`, `quote_rechecks.csv`,
`contracts.csv` and `exclusions.csv`.
The page uses the existing bundled Plotly library, not a CDN or backend.
It records dependency versions and source hashes. Identical inputs and runtime
produce byte-identical results. No current timestamp is inserted by the build.

## Re-audit / obtain real inputs

Use an already authorized LSEG Workspace session. No token or password belongs
in the repository. Use a new directory on each pull; scripts refuse overwrites.

```sh
# Only on a fresh checkout, if the retained probe directory does not exist:
python -m pmcc_backtest.probe_lseg --output-dir pmcc_backtest/local_data/probe
# Exact IDs from that discovery and the retained historical cache:
python -m pmcc_backtest.acquire_observed --output pmcc_backtest/local_data/observed_input_new.json
# This repair's live acquisition (already executed; do not overwrite it):
python -m pmcc_backtest.repair_coverage --input pmcc_backtest/local_data/observed_input_v2.json --output pmcc_backtest/local_data/observed_input_v3.json --cache-dir pmcc_backtest/local_data/repair_v3
# Final policy reconstruction from those immutable raw replies (executed offline):
python -m pmcc_backtest.repair_coverage --input pmcc_backtest/local_data/observed_input_v2.json --output pmcc_backtest/local_data/observed_input_repaired.json --cache-dir pmcc_backtest/local_data/repair_v3 --offline
# Full accounting rerun + independent cash/positions/NAV/fees/CSV reconciliation:
python -m pmcc_backtest.build --input pmcc_backtest/local_data/observed_input_repaired.json
python -m pmcc_backtest.validate_publication --input pmcc_backtest/local_data/observed_input_repaired.json --base pmcc_backtest/local_data/observed_input_v2.json
```

For reconstruction choose a NEW output filename. `acquire_observed` now includes
the missing-series repair stage automatically; `--base-input` reuses an existing
licensed base and `--cache-dir` selects retained replies. Current
search and reconstructed RICs are only leads, never proof of historical membership. The audit source
snapshot used in this publication is retained privately under `local_data/probe`.

`acquire_observed` assembles the source-labeled table automatically and refuses
to overwrite snapshots. It reuses retained immutable raw responses. Changing
provider history later is not guaranteed to reproduce the original pull; use
the recorded input hash and retained `observed_input_repaired.json` for accounting reproduction.
The earlier real June 29 long quote, missing from a later reply, is preserved
from its original response; overlapping BBO values must agree or acquisition
stops for review. This is a documented real-snapshot merge, not interpolation.

The optional `fetch_lseg --manifest ... --output ...` path accepts an external
manifest with either verified or explicitly supported assumed terms, but is not
required. Both extractors request exact evidenced identifiers with daily normal-session
historical pricing, excluding stock split/dividend adjustments. It preserves
missing fields and individual request errors. It does not silently switch to
synthetic values, rerank contracts on future fills, or change the long-selection
mode. Both fill models and all three strategies are rebuilt together after the
input audit passes. Missing held-position marks/mandatory exits still mark the
valuation path incomplete, even when initial input validation passed. A missing
mandatory exit also prevents a resolved endpoint; a temporary mark gap alone
does not invalidate separately reconciled terminal cash.

New licensed raw data and manifests stay in ignored `pmcc_backtest/local_data/`.
The public repository contains only code, audit counts/hashes, and authorized
derived account outputs. Do not stage the private directory or force-add it.

## Event and accounting conventions

- First actual weekly session, including Tuesday after a Monday holiday. Signal
  uses previous-session data; normal close is 16:00 America/New_York, early close
  13:00, with calendar DST. Exchange calendar is XNYS for the shared US equity
  holiday schedule, checked against regular AAPL option/OCC and Cboe hours. It is
  not an index-option 16:15 close or an extended-hours option session.
- Prior EOD publication by the following 09:00 checkpoint is an explicit
  availability assumption unless actual `available_at` is supplied. Daily
  responses have unknown intraday quote time. Exact synchronization cannot be
  established from DATE alone; a BBO-mid disagreement is rejected. Close is a
  modeled reference, not a claim that an order was sent or filled after closing.
- One fully paid long, expiry closest to 450 within 365–550 signal DTE, then
  proxy largest observed strike ≤75% signal spot. The alternative historical
  delta mode is implemented but must be locked for the entire run before P&L.
- Short: minimum observed Friday-series K≥1.05 signal spot and ≥long K; shorter
  expiry, matching standard 100-share terms. Buy long before writing its
  preselected short. No atomic spread fill, future reranking, or midweek retry.
- At expiry ≥$0.01 ITM: remove short, receive 100K, create −100 stock, keep long.
  Otherwise remove the short at zero and retain long. The short premium becomes
  realized option P&L; subsequent signed stock P&L captures assignment economics.
  Intrinsic is not separately subtracted again.
- Cover assigned stock next actual close. Borrow accrues 3% on the preceding
  stock reference over actual calendar days. If cash after reserving costs and
  dividend payables is insufficient, check both prices/costs and sell long plus
  cover stock. Missing/unfunded mandatory cover leaves unresolved exposure.
  Never re-enter a discretionary weekly short at the same close as the cover.
- Ex-date entitlement applies to carried shares, not stock bought at that day's
  close. Pay date moves a receivable/payable to cash without adding P&L again.
  Long calls receive no dividend. Date-only announcements become known the
  next local day; pre-ex assignment needs announcement availability, ITM and
  `max(mid-intrinsic,0)<dividend`. Unavailable announcements require a conspicuous
  expiry-only limitation; missing dividend coverage blocks the input audit.
- Cash is trade-date economic cash, including unsettled proceeds exactly once.
  Dividend balances and accrued borrow are separate NAV items. No settled-cash,
  stock-loan locate, broker buying-power or portfolio-margin feasibility claim
  is made; no prior stock Reg T formula is imported.
- $0.65 per option per side, stock 1 bp per side, no stock commission or
  exercise fees. Mark using the uniform same-date closing-quote rule above; held gaps remain
  null. Quoted-side sensitivity buys at ask/sells at bid. Idle cash earns zero.
- Terminal discretionary entries are suppressed. Close the short first, then
  stock obligations and long; only residual positions face after-close
  assignment. No same-date retroactive cover of a new after-close assignment.
- NAV and attribution reconcile to cash/events, long, short, signed stock,
  dividends and costs. A missing mark invalidates full-sample path statistics,
  not the historical position. Strict drawdown is never bridged across a gap;
  the separate observed-NAV lower-bound statistic is explicitly labeled. Returns
  share the $50,000 denominator, and annualized headline metrics are omitted.

## Validation and site routes

Synthetic fixtures in `test_*.py` are strictly for accounting/calendar tests;
normal publication rejects synthetic inputs. Tests cover holiday adjustment,
early closes/DST, long/short selection, prior availability, costs, assignment
NAV conservation, dividends, cover, funding, gaps, terminal sequencing,
replacement, cutoff invariance, supported-assumption gates, zero-padded RICs,
holiday expiry versus last observed quote, and deterministic publication.

All discovered routes share `course-nav.js`: `/`, the legacy
`options_surface_preview.html` alias, `/covered-call/`, `/covered-call/data.html`,
and `/pmcc/`. Relative URLs resolve under `/535_fintech/`; direct refresh and
static CSV/JSON downloads do not need Python. Deployment continues through the
repository's existing main-branch GitHub Pages build.

Primary references are cited on the page. The code does not treat documentation
or tests as proof that a missing historical observation existed.
