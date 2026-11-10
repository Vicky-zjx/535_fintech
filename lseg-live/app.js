'use strict';
(async () => {
  const el = id => document.getElementById(id);
  try {
    const response = await fetch(`data.json?t=${Date.now()}`, {cache: 'no-store'});
    if (!response.ok) throw new Error('No successful query has been published yet.');
    const data = await response.json();
    if (data.source !== 'LSEG Data Platform' || typeof data.instrument !== 'string' ||
        !/^[A-Za-z0-9.^_:/=+-]{1,64}$/.test(data.instrument) ||
        !Number.isFinite(data.last_close_usd) || data.valid_prices < 2 ||
        !/^[a-f0-9]{64}$/.test(data.observations_sha256)) throw new Error('Published data failed validation.');
    const retrieved = new Date(data.retrieved_at_utc);
    if (!Number.isFinite(retrieved.getTime())) throw new Error('Published query timestamp is invalid.');
    document.title = `${data.instrument} · LSEG Data Lab · FIN 535`;
    el('instrument-lead').textContent = `${data.instrument} · daily closing prices`;
    el('instrument-label').textContent = `${data.instrument} · USD · historical, not live`;
    el('chart-title').textContent = `${data.instrument} closing price`;
    el('price-chart').title = `Interactive Plotly chart of real ${data.instrument} daily closing prices`;
    el('close').textContent = new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD'}).format(data.last_close_usd);
    el('close-date').textContent = `Price date: ${data.last_price_date}`;
    el('count').textContent = data.valid_prices;
    el('range').textContent = `${data.first_price_date} → ${data.last_price_date}`;
    el('updated').textContent = retrieved.toISOString().replace('T', ' ').slice(0, 19);
    el('nulls').textContent = `${data.returned_null_prices} returned null price(s) · kept missing`;
    const ageHours = (Date.now() - retrieved.getTime()) / 3600000;
    el('status').textContent = ageHours > 72 ? 'Saved result · older than 72 hours' : 'Real LSEG query · published';
    el('status').classList.toggle('warning', ageHours > 72);
    el('message').textContent = `Showing the last successful query for ${data.instrument}: ${data.requested_start} through ${data.requested_end}. Hover to inspect; drag to zoom. A code change updates this plot only after the API query and Pages build succeed.`;
    el('price-chart').src = `chart.html?v=${data.observations_sha256}`;
    el('price-chart').hidden = false;
    el('downloads').hidden = false;
    if (/^https:\/\/github\.com\/Vicky-zjx\/535_fintech\/actions\/runs\/\d+$/.test(data.workflow_run_url || '')) {
      el('run-link').href = data.workflow_run_url;
      el('run-link').hidden = false;
    }
  } catch (error) {
    el('status').textContent = 'Awaiting verified data';
    el('status').classList.add('warning');
    el('message').textContent = `${error.message} Run the GitHub workflow or inspect its latest result. No placeholder prices are displayed.`;
    el('message').classList.add('error');
  }
})();
