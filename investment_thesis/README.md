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

The cost note is a transparent planning scenario: 20 bp gross surplus above
expected losses/cash benchmark, $0.65/contract/side and $0.02/share round-trip
slippage = $3.30 per contract. It is **not** an estimated premium/alpha, actual
broker fee, trade, buy-to-close instruction, or change to engine fee settings.
Illustrative collateral uses the preserved Nov 17 KO 96 / PFE 28 proposals,
checked against `course/proposal_history.json`.

## Reproduce and verify

```sh
python -m investment_thesis.research
python -W ignore::DeprecationWarning -m unittest investment_thesis.test_research -q
node --test investment_thesis/test_page.cjs
python -m investment_thesis.validate
```

Only `investment-thesis/data/thesis_tracker.json` and `thesis_observations.csv`
are generated. They contain the source hashes, every signal and forward path,
exclusion reasons, sample counts, cohorts and rolling statistics. No API call
or order/state/price write takes place. The source history is not shortened or
rebuilt by this module.

`.github/workflows/investment-thesis.yaml` is an independent downstream job
triggered by completion of the existing successful nightly LSEG workflow (or
manual dispatch). It checks out trusted main, needs no LSEG credentials, tests,
recomputes, validates, commits only its two outputs and requests a Pages build.
If the original market refresh fails, the tracker is not refreshed; the page
retains its actual source timestamp. Failure never means a fabricated new price.
The original nightly workflow and production `open_orders.json` are unchanged.
