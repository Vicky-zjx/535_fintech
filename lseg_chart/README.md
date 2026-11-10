# LSEG → Plotly → GitHub Pages

Independent API exercise. It does not rebuild or modify the older options backtests.

- Page: <https://vicky-zjx.github.io/535_fintech/lseg-live/>
- Change the single `RIC` setting in `lseg_chart/update.py` (currently `TSLA.O`)
  and push to **main**. The push triggers a fresh API query and publication. Or use
  **Actions → Update LSEG Plotly chart → Run workflow → main** to requery unchanged code.
- Inputs: the existing repository Secrets `LSEG_APP_KEY`, `LSEG_USERNAME`,
  `LSEG_PASSWORD`. Their values cannot be read back through GitHub; the runner
  injects them into the query step only. Do not add plaintext credentials to Git.
- Connection: explicit `lseg.data` Platform `GrantPassword`; no Workspace, no
  desktop fallback, no forced exclusive sign-on, no automatic authentication retry.
- Query: the configured RIC, `TR.PriceClose.date` and `TR.PriceClose`, daily, USD. The 90-calendar-day
  window ends yesterday in New York; dates are vendor-reported observation dates.
  Prices are not a real-time quote or total-return series. Response coverage is not
  assumed complete. Missing values remain null; unreturned dates are not fabricated.
- Outputs: `lseg-live/chart.html` (Plotly saved to disk), `prices.csv`, `data.json`,
  plus the compact `lseg-local/index.html` and identical `lseg-local/data.json`.
  JSON includes query parameters, UTC retrieval time, a data digest and workflow-run link.
  All outputs use the same validated response. Titles, hover labels and metrics
  follow its instrument, not a hardcoded Apple label. The page reads that JSON
  and embeds the saved HTML; it never accesses LSEG or Secrets from the browser.
- Failure: failed authentication/query/validation stops the job before publication;
  there is no synthetic fallback. Previously committed output remains available,
  with its original retrieval timestamp. Failed Pages builds are visible in Actions.
- Updates: query/render code and workflow changes on main, or a manual run; no
  scheduled automation. Generated output paths are excluded from push triggers.
  The workflow commits an exact five-file allowlist, then requests a Pages build because bot pushes
  with `GITHUB_TOKEN` do not automatically trigger legacy Pages. Existing `main /`
  publishing configuration and all earlier pages are preserved.

## Reproduce

```sh
python -m pip install -r lseg_chart/requirements.txt
python -m unittest lseg_chart.test_update -v
node --test lseg_chart/test_page.cjs
# Supply the three variables securely in this process's environment; never in arguments.
python -m lseg_chart.update
# Local alternative: prompts securely for missing credentials and updates BOTH pages.
.venv/bin/python -m lseg_chart.local_api
```

Locally, editing Python alone does not execute a query: rerun the local command,
then refresh `/lseg-local/` or `/lseg-live/`. On GitHub, wait for both Actions and
Pages to finish. An authentication failure (including session quota) cannot update
prices: both pages retain the old response's instrument and timestamp, rather than
relabeling old prices as the new stock. No cache is read by either query command.

The SDK can return duplicate `TR.PriceClose` headers for the requested date and
price fields. Only that exact known schema is mapped in request order; date/value
types and requested dates are checked. Ambiguous or swapped columns fail closed.

Tests use tiny offline fixtures in temporary directories only, never as published
market prices. A passing unit test is not an API-connection result. The actual
workflow is the end-to-end authentication/query/publication test. The shared
course navigation adds one Data Lab link; no previous strategy or data is changed.

## References

- [Instructor workflow](https://github.com/JakeVestal/server-logic-533/blob/main/.github/workflows/oi-plots.yml)
- [LSEG Data Library access layer](https://developers.lseg.com/en/article-catalog/article/the-data-library-for-python-quick-reference-guide-access-layer)
- [LSEG Platform vs desktop](https://developers.lseg.com/en/article-catalog/article/configuration-process)
- [GitHub Actions Secrets](https://docs.github.com/en/actions/security-for-github-actions/security-guides/using-secrets-in-github-actions)
- [Request a Pages build](https://docs.github.com/en/rest/pages/pages#request-a-github-pages-build)
