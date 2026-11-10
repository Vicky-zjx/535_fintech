// Offline DOM harness: verifies the shipped frontend, never published market data.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const script = fs.readFileSync(path.join(__dirname, '../lseg-live/app.js'), 'utf8');
const html = fs.readFileSync(path.join(__dirname, '../lseg-live/index.html'), 'utf8');

async function render(instrument) {
  const elements = new Map([...html.matchAll(/id="([^"]+)"/g)].map(match => [match[1], {
    hidden: ['price-chart', 'downloads', 'run-link'].includes(match[1]),
    classList: {add() {}, toggle() {}}
  }]));
  const document = {title: '', getElementById: id => {
    assert.ok(elements.has(id), `Missing real HTML element: ${id}`);
    return elements.get(id);
  }};
  await vm.runInNewContext(script, {document, Intl, Date, fetch: async () => ({ok: true, json: async () => ({
    source: 'LSEG Data Platform', instrument, last_close_usd: 102, valid_prices: 2,
    observations_sha256: 'a'.repeat(64), retrieved_at_utc: '2026-11-10T17:40:17Z',
    first_price_date: '2026-11-02', last_price_date: '2026-11-04',
    requested_start: '2026-11-01', requested_end: '2026-11-09', returned_null_prices: 1
  })})});
  return {elements, document};
}

for (const ric of ['AAPL.O', 'TSLA.O', 'MSFT.O']) {
  test(`Page labels, numbers and iframe follow the ${ric} result`, async () => {
    const {elements, document} = await render(ric);
    assert.equal(document.title, `${ric} · LSEG Data Lab · FIN 535`);
    assert.equal(elements.get('chart-title').textContent, `${ric} closing price`);
    assert.equal(elements.get('close').textContent, '$102.00');
    assert.equal(elements.get('price-chart').hidden, false);
    assert.match(elements.get('price-chart').src, /^chart.html\?v=a{64}$/);
    assert.ok(elements.get('price-chart').title.includes(ric));
    assert.ok(elements.get('message').textContent.includes(`last successful query for ${ric}`));
  });
}
test('Invalid instrument fails closed without displaying a chart', async () => {
  const {elements} = await render('<script>');
  assert.equal(elements.get('status').textContent, 'Awaiting verified data');
  assert.equal(elements.get('price-chart').hidden, true);
});
