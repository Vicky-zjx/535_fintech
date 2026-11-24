# FIN 535 Investment Thesis safe code snapshot

This branch preserves the frozen Investment Thesis source for code review. It is not a deployable website or a replacement for the trading repository.

The research modules and renderer files are copied unchanged from the local working tree. No research model, statistical result, trading rule, order or production workflow was changed to prepare this snapshot.

## Scope

Included: generic research calculations, fixed-study and forward-state handling, the permission gate, acquisition code, data-driven renderers, styles and reviewed test source. Constants describing research design, classroom examples, explicitly hypothetical cost budgets and artificial test fixtures are not observations or investment performance.

Excluded: market-price files, option quotes, observation paths, generated statistics, raw or encrypted datasets, private state, credentials, all workflows, order/account files, and production implementation directories. The existing HTML, detailed research README and payoff renderer remain local because they contain research findings. Tests with embedded empirical result counts are also withheld. These exclusions do not delete any local work.

The only included JSON file, `investment_thesis/publication_permission.json`, is configuration. Its status remains pending and all publication permissions remain false. Code availability does not grant permission to publish LSEG data or derived results.

## History isolation

This is a parentless source snapshot. It deliberately does not inherit `main` history, which already contains data-bearing files. It does not remove or remediate files already on other branches.

The local baseline was `a7da206bc9f7b9839656652918b792c6873ca569`; the copied source also includes the frozen uncommitted research changes. `SOURCE_SHA256SUMS` records checksums of the included source, not of private datasets.

Do not merge this branch wholesale over `main` or use it as a Pages source. Future integration must selectively review the relevant files in the existing repository.

## Validation and reproduction

Syntax and checksum checks require no market data:

```sh
LC_ALL=C shasum -a 256 -c SOURCE_SHA256SUMS
node --check investment-thesis/app.js
node --check investment-thesis/lecture.js
node --check investment-thesis/reliability.js
```

The complete local research workspace retains the full tests and reproduction instructions. Existing modules import `final_project` and `lseg_chart`, which are intentionally not bundled here. Integration tests also require local research inputs and the withheld website files. This snapshot therefore does not claim a standalone full-suite run.

Release checks passed: 81 Python and 35 JavaScript tests in the retained local workspace, plus the existing research validator. The exported code also passed syntax checks and 30 fixture-based tests using the existing local dependency modules. No live API call or research rebuild was needed. All included original files match the source checksum manifest.

In the existing authorized local workspace, the verification commands are:

```sh
.venv/bin/python -W ignore::DeprecationWarning -B -m unittest discover -s investment_thesis -t . -p 'test_*.py' -q
node --test investment_thesis/test_page.cjs investment_thesis/test_reliability.cjs investment_thesis/test_lecture.cjs investment_thesis/test_payoff.cjs
.venv/bin/python -W ignore::DeprecationWarning -B -m investment_thesis.validate
```

Supply the existing `THESIS_PRIVATE_HISTORY` environment setting privately when running tests that require the five-year evidence. Do not commit its value. These commands test retained research; they do not authorize new downloads, a rebuild, order generation or deployment.

## Before any website release

1. Obtain confirmation of the permitted audience and LSEG display rights, including aggregate statistics and charts. Keep permission gates closed until the scope is documented.
2. Confirm the professor's unified performance-monitoring requirements and provision authorized persistent private storage for forward observations. A rolling public snapshot must not silently reset that history.
3. Review a separate publication package, preserve the fixed research results, and verify the permitted tracker/state update path without changing production trading.
4. Obtain approval for selective integration, workflow changes if needed, and deployment.

There are no workflow definitions or site entry points on this branch. At review time, Pages used `main /`; the existing repository workflows did not have a push trigger matching this branch. This release does not request an Actions run or change Pages settings.
