# Private historical input schema, version 1

The engine consumes JSON with `metadata`, `contracts`, `stock`, `options`, and
`dividends`. An empty/missing field is not zero. ISO date strings are YYYY-MM-DD;
actual timestamps must be timezone-aware. All monetary prices are USD/share;
the standard contract multiplier is 100. Do not supply adjusted stock prices.

## Optional manifest consumed by `fetch_lseg`

The primary `acquire_observed` workflow builds contract evidence automatically
from retained real RICs, historical LSEG observations and official rule sources.
It does not require a user-supplied historical master. The optional manifest is
for importing independently sourced evidence, not a prerequisite to this study.

- `config`: the exact fields from `pmcc/config.json`, with any shorter window
  justified from data availability **before** P&L; no performance optimization.
- `window_selection_reason`: coverage-based rationale and old-assignment overlap.
- `candidate_universe`: source, scope, point-in-time/observed limitations and any
  missing expiries/strikes. A current chain is not historical membership.
- `dividend_coverage_verified`: boolean; verify complete cash-dividend coverage,
  including no-dividend periods. Empty API output alone does not establish this.
- `contracts`: records described below, with verified or explicitly assumed
  source-supported terms. Flags alone do not establish authenticity.

## Contract records

| Field | Meaning |
|---|---|
| `id` | Exact provider RIC, not a synthetically invented listing |
| `underlying`, `cp`, `currency` | AAPL.O, C, USD |
| `strike` | Actual observed positive strike, not grid arithmetic |
| `expiry` | RIC-rule-derived expiry, checked against available source descriptions |
| `scheduled_last_trading_date`, `last_trade_date` | Scheduled session derived from applicable rules/calendar, including holidays; `last_trade_date` is the engine alias |
| `first_observed_quote_date`, `last_observed_quote_date` | Actual historical observation bounds, not contractual dates |
| `series_friday` | Friday-series identity for short candidates; can differ from holiday-adjusted last trade; null for other series |
| `known_from` | First known historical listing/evidence date, not today's discovery date retroactively applied |
| `metadata_known_at` | Optional actual availability timestamp for terms; cannot be after signal |
| `multiplier` | 100; other sizes are excluded |
| `deliverable` | Exactly `100 AAPL shares`; adjusted/nonstandard contracts excluded |
| `standard_verified` | true only for actual individual historical verification; false for every contract in this publication |
| `standard_assumption_allowed`, `terms_status` | true and `research assumption` for explicitly supported standard terms |
| `terms_source`, `terms_assumption` | Official sources and exact scope/limitations of the assumption |
| `terms_verified_at` | null when not individually verified; never replace it with the time the assumption was made |
| `risk_flags` | Must be empty to use assumed terms; unresolved adjustment/mini/conflicting identity is excluded |
| `provenance` | Per-field direct evidence, rule derivation, research assumption and unresolved status; no blanket verified flag |

Even with metadata, selection requires a real quote or trade observation known
by signal time. Long entries additionally require a valid **previous-session**
signal quote. Later price observations cannot establish earlier membership.
No requirement for an entire future price path may be used to select a winner.

## Stock and option records

Stock fields: `date`, `ric`, `price` (unadjusted `TRDPRC_1` daily reference),
`precision`, `source_timestamp`, `available_at`.

Option fields: `date`, `id`, `bid`, `ask`, `vendor_mid`, `trade` (`TRDPRC_1`),
optional `delta`/`delta_source`, `precision`, `source_timestamp`, `available_at`.
`delta_source` is `historical` or `estimated contemporaneous`; any estimate must
carry a documented contemporaneous-input method/source, never future realized
volatility. Call delta outside [0,1] is unavailable for exposure.

Keep `source_timestamp=null` when the provider supplies DATE only. Execution
reference belongs to the engine, not the quote. Explicit unequal `bid_timestamp`
and `ask_timestamp`, `quote_inconsistent=true`, crossed/negative quotes and missing
BBO legs reject the quote. A supplied vendor MID_PRICE inconsistent with the
real BID/ASK pair is flagged. Vendor-mid-only use requires explicit
`vendor_mid_definition_verified=true`; the extractor never sets that flag simply
because the column exists. It cannot generate a quoted-side result without BBO.

`available_at` represents actual availability, not merely a bar's date. When
unknown, the declared `previous_session_by_next_09_assumed` metadata policy lets
the engine test a clearly labeled overnight-availability assumption; it does
not establish when the provider really published the close. Signals never use
an explicit later availability timestamp. The page must retain that limitation.

## Dividends

`ex_date`, `pay_date`, `amount` per share, `announced_at`, plus announcement
source and precision. Date-only announcements are available conservatively
from the following local day. Do not backdate unknown intraday announcements.
If announcements are unavailable, disable early-assignment modeling explicitly;
cash dividends still require complete ex/pay/amount coverage for comparisons.
The engine includes dividend payables on assigned short stock.

## Metadata / publication gate

Require `source="LSEG"`, `synthetic=false`, `stock_unadjusted=true`,
`research_window_locked=true`, exact `config`, `window_selection_reason`,
`candidate_universe`, `dividend_coverage_verified=true`. `terms_verified=false`
is permitted with explicit supported standard-contract assumptions; it must not
be silently promoted to true. The published sample uses that assumption pathway.
Record `dividend_assignment_enabled`, `source_precision`, `availability_policy`,
`quote_basis`, `field_definitions_source`, `adjustments`, `sessions`, input
manifest hash and individual response hashes/errors. Also retain window lock,
corporate-action screening evidence, exclusion reasons and acquisition bounds.
Unsupported or conflicting terms are blockers for the affected contract; a
well-supported disclosed derivation/assumption is not automatically a blocker.

The audit must find eligible historical long candidates and a verified
Friday-series observed subset (not proof of chain completeness). Entry quote holes are allowed and logged; absent long
data must not produce a misleading all-cash 'PMCC result'. Held-position gaps or
unresolved exits mark the path incomplete. A fully liquidated reconciled endpoint
can still support terminal P&L despite intermediate NAV gaps; full-sample drawdown
cannot. Only after the audit passes are six strategy/fill-model results generated.
The committed publication passes this input gate under explicit research terms.

## Public outputs

- `results.json` / `book.js`: config, public audit, versions/source hashes,
  result status, per-model/account metrics, ledger, events, decisions and prose.
- `daily_nav.csv`: one account/fill-model/session state; gaps are blank NAV.
- `trades.csv`: booked trades plus separately typed assignment/accrual/payment
  events. Cash delta, fees, positions and modeled/source timestamps remain distinct.
- `weekly_coverage.csv`: every scheduled opportunity; `not_run` is distinct from
  a backtest's reason-coded `skipped` or `filled` decision.
- `config.json` and `data_audit.json`: reproducible rules and evidence.
- `contracts.csv`: source-labeled identity, derived expiry/scheduled last trade,
  separate actual quote bounds and assumed multiplier/deliverable.
- `exclusions.csv`: exact identifier, reason and whether a contract-risk or
  acquisition-scope exclusion; outside scope does not mean unlisted.

No full raw vendor market panel, current-chain response, credentials or private
manifest is published. Licensed inputs remain in the Git-ignored `local_data/`
directory. Synthetic test fixtures are visibly labeled and not input snapshots.
