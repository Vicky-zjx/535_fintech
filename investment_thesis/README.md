# FIN 535 — Independent Investment Thesis

[Standalone page](https://vicky-zjx.github.io/535_fintech/investment-thesis/)

This is a separate assignment from the [Wheel order-generation site](https://vicky-zjx.github.io/535_fintech/docs/).
It studies the Wheel's downside-risk premise, without modifying the strategy,
market-data acquisition, account assumptions or proposed orders. The original
research question concerns whether conditional put selling offers a better
premium-to-downside-risk trade-off than unconditional weekly selling. The price
tracker addresses the risk premise, not the still-unverified premium advantage.

## Fixed research design

`forward-stock-risk-v1.1`, 2026-11-23. V1 fixed the sampling design before the
first calculation; v1.1 corrects the review comparison to the stated unfiltered
baseline, with no changed market data or strategy parameters:

- Real LSEG data from the existing, validated `docs/data/historical_signals.json`.
  Its underlying market snapshot and indicators are independently reproduced.
- Signal at completed close t, reference at t+1, outcome at t+6 on XNYS.
  All six path closes must exist. No look-ahead in signals or rolling points,
  no filling, and no compressed multi-day gap. The latest six signals are pending.
- Subsequent stock price return, maximum closing loss from the reference,
  and frequency of a loss of at least 3%. These are **not** option returns,
  assignment probabilities or portfolio drawdown.
- Rolling 126 matured reference sessions; minimum 20 pass and 20 fail paths
  per stock. Aggregate lines equally weight within-stock cohort means; all four
  stocks must qualify, otherwise the point remains null. Unfiltered means are
  also shown. This controls ticker weights, not differences in market regimes.
- Review if pass mean loss >= unfiltered mean loss, or pass 3%-loss frequency >=
  unfiltered frequency; the fail cohort is diagnostic. Review flags do not change the trading algorithm. They are not
  significance tests. Pre-registration data are retrospective; prospective
  outcomes are counted separately, not manufactured from earlier history.

The four currently selected survivors and revised, as-retrieved price data
limit historical claims. Overlapping outcomes are not independent trades and
cannot be compounded or annualized into a Wheel Sharpe. The tracker tests only
the risk side of the insurance-pricing thesis; option mispricing and alpha
remain unestablished. Weak or contrary findings are explicitly displayed.

The cost note is a transparent planning sensitivity: 5, 10, 20, 30 and 50 bp gross surplus above
expected losses/cash benchmark, $0.65/contract/side and $0.02/share round-trip
slippage = $3.30 per contract. It is **not** an estimated premium/alpha, actual
broker fee, trade, buy-to-close instruction, or change to engine fee settings.
Illustrative collateral uses the preserved Nov 17 KO 96 / PFE 28 proposals,
checked against `course/proposal_history.json`.

## Reproduce and verify

```sh
python -m investment_thesis.refresh --verify-page
python -W ignore::DeprecationWarning -m unittest investment_thesis.test_research -q
node --test investment_thesis/test_page.cjs
python -m investment_thesis.validate
```

Only `investment-thesis/data/thesis_tracker.json`, `thesis_observations.csv`
and `refresh_status.json` are generated. They contain the source hashes, every signal and forward path,
exclusion reasons, sample counts, cohorts and rolling statistics. No API call
or order/state/price write takes place. The source history is not shortened or
rebuilt by this module.

`.github/workflows/investment-thesis.yaml` is an independent downstream job
triggered by completion of the existing nightly LSEG workflow (or
manual dispatch). It checks out trusted main, needs no LSEG credentials, tests,
recomputes, validates, commits only its three outputs and requests a Pages build.
If the upstream run fails, it retains both evidence files and publishes a failed
refresh record. A build/validation failure restores both old evidence files;
the failure is still returned as a failing job after the diagnostic publication.
Infrastructure failures before the status step cannot write a new record. The
browser additionally compares its clock with the next actual XNYS close (including
holidays/early closes), so an old snapshot is flagged even if no failure record
could be published. New build time is never treated as new market data.
Failure never means a fabricated new price. Recorded failed refreshes may display
their intact retained tracker even if the original source has since advanced;
that display is explicitly labeled stale, not a current source match.
The original nightly workflow and production `open_orders.json` are unchanged.

## Analysis and economic-data audit

`app.js` derives all chart interpretations from the same JSON cohorts as the
curves. ALL and each stock have full-sample comparisons, latest-window sample
checks, absolute/relative differences, counts of favorable/adverse rolling dates,
and the latest continuous adverse interval. Zero denominators have no relative
reduction; insufficient samples have no inferred advantage. Counts describe
overlapping dates, not independent trials. Four-stock paragraphs and the overall
interpretation disclose contrary results, not just favorable averages.

H1 is a stock-downside premise. H2 is the net economic compensation for forgone
premium/opportunities. The new third review condition concerns H2 and is explicitly
an extension, not an original preregistered condition. With the present sources,
it remains Not Yet Testable. No hypothetical option returns are published.

`option_audit.py` inventories the two retained four-stock discovery snapshots on
every build and includes their hashes in the tracker. Audit of the retained
Nov 13/20 market snapshots found 632 contract records (316 puts), no populated
bid/ask pairs and no populated dated deltas. These are two discovery observations,
not a historical weekly option universe. The normalized rows contain terms,
strike, expiry and discovery dates, not executable historical entry quotes.
The original `final_project/data_provider.py` retrieves three-year stock closes,
current discovery and same-session DELTA_EXCH. It does not collect a historical
four-stock bid/ask panel. Historical option entitlement remains untested; missing
local environment credentials do not establish that an account lacks entitlement.

A separate read-only local audit found the existing AAPL Wheel cache
(`wheel_backtest/local_data/input_v2.json`) has 28,805 option observations, including
9,249 put observations across 401 contracts (July 2–September 30, 2026; 224 missing
bids). The AAPL PMCC cache has 13,835 call observations; the UUUU pickle has 334
contracts and 8,587 observed contract-days, with mid/trade fields rather than
bid/ask or delta. These caches are not BAC/KO/PFE/F evidence and are not imported
into this research. Neither constructing a RIC nor observing it later proves it
was available at an earlier decision. The existing observed-strike fallback
cannot replace missing contemporaneous quotes.

The economic comparison still requires dated historical candidate availability,
entry quotes, unchanged contract selection, underlying/expiry outcomes, matched
capital and costs, and treatment of idle/no-trade weeks separately from missing
data. Until that exists, premium, net option return, benchmark excess return and
risk-adjusted alpha remain unestimated. The cost table is only an arithmetic
budget using recorded KO 96 and PFE 28 proposal strikes, not their executed prices.

## Assignment coverage

- One-sentence thesis and the separate H1/H2 questions: on the standalone page.
- Horizon: expected 6–12 months, monthly review, about 7 calendar days per option;
  no invented lifetime for an assigned-stock Wheel cycle.
- Daily tracker: genuine retained LSEG closes, two existing charts, dated status,
  independent downstream refresh, transparent insufficiency and exclusions.
- Wrong-if conditions: two unchanged quantitative checks; one clearly new
  economic extension, currently untestable.
- Alpha/cost note: quantitative break-even and five scenarios; a data-based
  option-alpha estimate is **not** yet possible.
- Macro: conditional scenarios and limitations, not an unsupported statement
  about current policy or proof of the mechanism.

Calendar construction includes context before the requested sample start, so a
three-year boundary on a holiday or weekend does not fail out-of-bounds. Only
actual sessions within the original requested window are analyzed; no holiday
rows or prices are added.
