# FIN 535 Investment Thesis — course research edition

The independent [research page](https://vicky-zjx.github.io/535_fintech/investment-thesis/)
preserves the completed three-year and fixed five-year studies, filter ablation,
joint date-based block bootstrap, non-overlapping samples, hypothetical put payoff
analysis, and the professor's Hoeffding framework and monitoring examples.
No investment strategy, order, account or Sanji behavior is changed by this release.

## Findings and scope

The evidence does not consistently support lower downside risk across BAC, KO,
PFE and F. Trend screening removes most opportunities; additional filters matter
for PFE and F in the extended sample. BAC's favorable point estimates are sensitive
to sampling. Hypothetical option payoffs do not improve consistently. Break-even
premiums are not alpha estimates, and complete point-in-time option data remain
unavailable for an actual option-strategy return study. See the page for the
unchanged estimates, uncertainty intervals and adverse findings.

## Release and data boundary

The owner authorized this limited course publication on November 24, 2026,
reporting the professor's requirement to use LSEG and GitHub Pages. Separate
confirmation of the exact display scope remains pending. This authorization is
not represented as vendor confirmation. `publication_permission.json` records both
facts separately. [Duke/Ford Library terms](https://library.fuqua.duke.edu/databases/dbterms.htm)
permit academic work product with appropriately cited insubstantial excerpts,
not wholesale redistribution. [LSEG guidance](https://www.lseg.com/en/data-analytics/market-data/data-redistribution)
also requires reviewing derived-data use; broader reuse needs separate approval.

Only existing summarized findings and aggregate chart inputs are newly published:

- `public_tracker.json`: row-free browser projection and source checksums.
- `fixed_research_public.json`: integrity-checked immutable aggregate study package.
- `refresh_status.json`: successful/failed attempt and retained-evidence timestamps.

Raw runtime JSON/CSV, frozen individual paths, original private history, keys and
forward state are excluded. The current public copies of the old Thesis raw JSON
and CSV are removed; the owner's local originals are retained. Git history and
other branches are not rewritten. Removing a download link alone is not access
control; aggregate chart inputs remain accessible to browsers. Existing production
data are outside this release and are neither changed nor newly authorized by it.

## Independent refresh

`.github/workflows/investment-thesis.yaml` is manually runnable and runs downstream
of the existing nightly Wheel job. It uses validated existing LSEG-derived inputs;
it has no credentials, order writes, dispatch back to production or shared
concurrency group. Production retains its 10 PM America/New_York schedule unchanged.

The padded exchange calendar handles holiday/weekend boundaries. Fixed five-year
results are loaded from the checked aggregate package and never rebuilt by the
daily refresh. No `THESIS_PRIVATE_HISTORY` setting is required for that refresh.
Private runtime outputs may be recreated during validation but are ignored by git;
the workflow explicitly stages only the public tracker and refresh status.

Forward Monitoring remains experimental. It is withheld if complete post-freeze
history cannot be reconstructed. No persistent hosted store is configured, and
missing state does not block the Daily Tracker or reset its frozen reference.
The retrospective cutoff is November 23, 2026; only outcomes matured by that date
enter the frozen baseline. Prospective signals are strictly later.

Upstream or validation failure retains the last valid study/chart data, publishes
an explicit failure status and fails the research job honestly. This does not
stop or alter production. Data access ending does not authorize indefinite
retention beyond institutional licensing terms.

## Reproduce the release checks

From the repository root, using Python 3.11 or later and Node:

```sh
python -m pip install -r final_project/requirements.txt
python -m unittest investment_thesis.test_research investment_thesis.test_reliability investment_thesis.test_workflow_isolation -q
python -m investment_thesis.refresh --upstream manual --verify-page
python -m unittest investment_thesis.test_release investment_thesis.test_architecture -q
python -m investment_thesis.publication --require-approval
python -m final_project.validate_publication
```

These checks do not fetch new market data or generate orders. Some full historical
replay/download tests need the retained private local reference and are not hosted
prerequisites. The release tests cover fixed-summary integrity, holiday boundaries,
new real sessions, unavailable/corrupt forward storage, upstream failure and scoped
publication without claiming confirmed licensing. The four Node test files check
the existing calculations, charts, states and page content. No statistical result
is changed to make a test pass.
