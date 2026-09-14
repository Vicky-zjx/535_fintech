# FINTECH 535 — Covered Call Backtest

Published page: **https://vicky-zjx.github.io/535_fintech/covered-call/**

This assignment is separate from the Option Surface Lab at the repository root.
Its code does not import the prior assignment's synthetic fallback or write its
pickle, page, or builder. The new page is a static report of a working Python
backtest, with interactive account inspection and complete downloadable records.

## Run

From the repository root with the existing project environment:

```bash
.venv/bin/python -m unittest covered_call.test_engine -v
.venv/bin/python -m covered_call.build
.venv/bin/python -m covered_call.audit_real
```

Open `covered-call/index.html`, or serve the repository:

```bash
.venv/bin/python -m http.server 8876 --bind 127.0.0.1
```

Then visit `http://127.0.0.1:8876/covered-call/`. The page includes its own Plotly
bundle and baked `book.js`; the grader does not need Python or an LSEG session.

## Strategy and accounting

`config.py` is the single configuration source: AAPL.O, $30,000 initial cash,
Monday 11:00 America/New_York, July 6–September 11, 2026, hourly bars, 5% OTM.

Buy 100 shares if flat, subject to the prospective Reg T check. Choose the
lowest observed listed strike at or above 1.05 times the current stock print,
expiring the same Friday. If the selected contract has no valid same-bar
BID/ASK, skip the option leg, keeping any already-purchased stock. Do not
substitute a higher strike with a quote. Sell one call at the midpoint, hold
through expiry, and use Friday's 16:00 stock print: S <= K expires with shares
retained; S > K delivers 100 shares at strike and leaves both positions flat.
There are no rolls, buy-to-close orders, or early assignments.

Cash changes only through BUY, SELL, EXPIRE, and ASSIGN. The short-call value
is negative in NAV. Initial requirement is 50% of stock LMV; maintenance is
25%; available funds = NAV - initial; excess = NAV - maintenance. The covered
call adds zero initial requirement under the instructor's specification.
Stock purchases and call entries are checked before booking. Holdings are not
silently liquidated on subsequent margin breaches; those are flagged in the
ledger. A missing expiry stock print stops the run as incomplete rather than
inventing an expiry outcome. The publisher refuses to label that run complete.

Negative cash represents a margin debit, not a failed cash reconciliation.
Returns are gross and price-only: dividends, commissions, financing interest,
taxes, and slippage are excluded. No price is fabricated. The only carry-forward
is an explicitly timestamped stale mark for valuation, never for an entry fill.

## Data acquisition and audit trail

```bash
# LSEG Workspace must be logged in. Pick a new filename to preserve old pulls.
.venv/bin/python -m covered_call.fetch_lseg --output covered_call/data/aapl_hourly_new.json
.venv/bin/python -m covered_call.build --cache covered_call/data/aapl_hourly_new.json
```

Raw replies and errors are cached in `data/raw/` under request hashes. No login
or application credential is stored. The data page shows **Data connection
required** on GitHub Pages. This refers to a fresh data pull, not to reading the
already-published backtest.

The provider's hourly `startPeriod` timestamps are verified against `endPeriod`
and advanced exactly one hour before conversion from UTC to New York time. The
entry uses only the completed 10:00–11:00 bar. The 15:00–16:00 regular-session
bar supplies the expiry stock mark; the 16:00–17:00 bar is excluded. Source
timestamps remain in the normalized records. Exchange/manual corrections are
requested; split-adjustment factors are not applied by the client.

AAPL candidate RICs use a deterministic $0.50 grid from the first grid strike
at or above the 5% target up to $10 higher, plus ±$2.50 around the rounded
Monday stock price for near-ATM validation. Each is requested for the preceding
week through expiry. Eligibility requires an observed quote or print no later
than entry. Future rows cannot establish Monday listing eligibility. This is a
bounded observed universe, not an exhaustive historical chain master.

The assignment screenshot says the day is unpadded. Paired real tests found:

| Unpadded request | Padded request | Result |
|---|---|---|
| `AAPLH72632500.U^H26` | `AAPLH072632500.U^H26` | Unpadded failed 90001; padded returned BID 0.27 / ASK 0.29 / print 0.28 at source 2026-08-03 14:00 UTC |
| `AAPLI42633500.U^I26` | `AAPLI042633500.U^I26` | Unpadded failed 90001; padded returned BID 0.05 / ASK 0.07 / print 0.06 at source 2026-08-31 14:00 UTC |

`ric.option_ric()` defaults to the screenshot convention and takes an explicit
`pad_day=True` for the verified AAPL provider representation. Calls always use
A–L on both sides of the RIC; the already-verified A–L suffix for puts is retained.

## Module responsibilities

| Module | Responsibility |
|---|---|
| `config.py` | One source of order time, cash, dates and rule settings |
| `ric.py` | Tested reusable RIC constructor |
| `fetch_lseg.py` | Bounded real requests; raw reply caching and provenance |
| `ingest.py` | Validate source, timestamps, interval and duplicate rows |
| `accounting.py` | Position invariants, booked cash flows and Reg T formulas |
| `engine.py` | Chronological strategy loop, decisions, ledger and regression |
| `build.py` | Real-data-only bake into `book.js` |
| `audit_real.py` | Independently reconcile normalized rows, fills and regression to raw replies |
| `../covered-call/assets/app.js` | Plots, filters, account inspection and exports |
| `test_engine.py` | Explicit hand-checkable synthetic fixtures, never published as results |

The blotter contains only executed simulation events. The decisions log includes
skipped/rejected attempts. The ledger stores after-event states as well as bar
marks. Curves plot the last ledger state at each timestamp, not a separately
calculated NAV path. CSV exports include all rows, even when the visible table
is filtered or paginated. Regression X is observed BID/ASK mid, Y is TRDPRC_1;
points require a contemporaneous stock print and |K/S-1| <= 5%.
