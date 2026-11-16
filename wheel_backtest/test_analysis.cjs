'use strict';
// Verify display-only interpretation against the saved real accounts, not a new backtest.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const book = require('../wheel/results.json');
const analysis = require('../wheel/assets/analysis.js');
const near = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-7, `${actual} != ${expected}`);
function freeze(value) {
  if (value && typeof value === 'object') {Object.freeze(value); Object.values(value).forEach(freeze);}
  return value;
}
freeze(book);

test('baseline attribution reconciles premiums, liabilities, stock, costs and dividends', () => {
  const e = analysis.evidence(book, 'quoted_side');
  assert.deepEqual(e.premiums.P, {count: 6, gross: 960, fees: 3.9, netCash: 956.1});
  near(e.premiums.C.gross, 261); near(e.premiums.C.netCash, 257.75);
  near(e.optionPnl, 838.85); near(e.stockPnl, 1000); near(e.end.dividend_income, 27);
  near(e.end.option_liability, 375); near(e.metrics.net_pnl, 1865.85);
  near(e.shortfall, 1409.348706);
  near(e.extraSharesGain, 1201.24); near(e.entryBasisDifference, 984); near(e.endpointExitDifference, 52);
  near(e.callCapAtAssignment, 363);
});
test('cash and EOD stock counts use all 62 rows, including the NAV-gap date', () => {
  const e = analysis.evidence(book, 'quoted_side');
  assert.equal(e.sessions, 62); assert.equal(e.heldSessions, 34);
  assert.equal(e.shares, 100); assert.equal(e.benchmarkShares, 159);
  near(e.averageCash, 33167.27258064517); near(e.averageFreeCash, 21304.36935483871);
});
test('partial-return volatility and Sharpe never bridge the missing NAV', () => {
  const e = analysis.evidence(book, 'quoted_side');
  assert.equal(e.wheelReturns.count, 60); assert.equal(e.benchmarkReturns.count, 62);
  assert.deepEqual(e.wheelReturns.excluded, ['2026-08-13', '2026-08-14']);
  near(e.wheelReturns.volatility, 0.10510182779473051);
  near(e.benchmarkReturns.volatility, 0.26660174478003595);
  assert.equal(e.metrics.max_drawdown, null); assert.equal(e.metrics.sharpe, null);
});
test('dividend eligibility, accrual and payment agree with before/after snapshots', () => {
  const e = analysis.evidence(book, 'quoted_side');
  assert.equal(e.put.date, '2026-07-31'); assert.equal(e.call.date, '2026-09-18');
  assert.equal(e.dividend.date, '2026-08-10'); assert.equal(e.payment.date, '2026-08-13');
  assert.equal(e.dividend.before.shares, 100); assert.equal(e.dividend.fill_price, 0.27);
  const run = book.runs.find(r => r.strategy === 'wheel' && r.fill_model === 'quoted_side');
  for (const event of [e.dividend, e.payment]) {
    for (const phase of ['before', 'after']) {
      const snap = run.snapshots.find(s => s.event_id === event.event_id && s.phase === phase + '_event');
      assert.ok(snap);
      for (const field of ['cash', 'shares', 'dividend_income', 'dividend_receivable']) near(snap[field], event[phase][field]);
    }
  }
});
test('five visible paragraphs track the selected fill model instead of hardcoded results', () => {
  const baseline = analysis.paragraphs(book, 'quoted_side');
  const midpoint = analysis.paragraphs(book, 'midpoint');
  assert.equal(baseline.length, 5); assert.equal(midpoint.length, 5);
  assert.match(baseline[0], /bid\/ask baseline returned 3\.73%/);
  assert.match(midpoint[0], /midpoint sensitivity returned 3\.83%/);
  assert.match(baseline[1], /\$1,221\.00/); assert.match(midpoint[1], /\$1,271\.50/);
  assert.match(midpoint[1], /\$889\.35 net option P&L/);
  assert.match(baseline[3], /-3\.63%/); assert.match(midpoint[3], /-3\.62%/);
  assert.match(baseline[4], /experiments have not been run/);
  assert.ok(baseline.join(' ').split(/\s+/).length < 560);
});
test('interpretation refuses inconsistent data rather than revising the saved numbers', () => {
  for (const corrupt of [
    b => {b.runs[0].metrics.gross_premiums += 1;},
    b => {b.runs[0].ledger.find(r => r.date === '2026-08-14').daily_return = 0;},
    b => {b.runs[0].events.find(e => e.event_type === 'DIVIDEND_PAYMENT').after.dividend_income += 27;},
    b => {b.runs[0].ledger.find(r => r.date === '2026-08-14').drawdown = 0;}
  ]) {
    const copy = structuredClone(book); corrupt(copy);
    assert.throws(() => analysis.evidence(copy, 'quoted_side'), /Analysis reconciliation:/);
  }
});
test('analysis is read-only and leaves every source result unchanged', () => {
  const before = JSON.stringify(book);
  analysis.paragraphs(book, 'quoted_side'); analysis.paragraphs(book, 'midpoint');
  assert.equal(JSON.stringify(book), before);
});
test('supplemental analysis preserves five paragraphs and updates both fill scenarios', () => {
  const research = freeze(require('../wheel/research.json'));
  const original = JSON.stringify(book), saved = JSON.stringify(research);
  for (const model of ['quoted_side', 'midpoint']) {
    const p = analysis.paragraphs(book, model, research);
    assert.equal(p.length, 5);
    assert.match(p[0], /4\.12% account return/);
    assert.match(p[2], model === 'quoted_side' ? /5\.81%/ : /5\.97%/);
    assert.match(p[2], /64\.22%/);
    assert.match(p[3], /28 sessions/);
    assert.match(p[3], /full-period MDD remains unavailable/);
    assert.equal(p[1], analysis.paragraphs(book, model)[1], 'Preserve premium/dividend paragraph');
    assert.equal(p[4], analysis.paragraphs(book, model)[4], 'Preserve thesis/research paragraph');
    assert.ok(p.join(' ').split(/\s+/).length < 550);
  }
  assert.equal(JSON.stringify(book), original); assert.equal(JSON.stringify(research), saved);
});
test('template and generated page expose Analysis below charts with scripts in dependency order', () => {
  const template = fs.readFileSync(path.join(root, 'wheel_backtest/page.html'), 'utf8');
  const page = fs.readFileSync(path.join(root, 'wheel/index.html'), 'utf8');
  assert.equal(page, template);
  assert.ok(page.indexOf('src="book.js"') < page.indexOf('src="assets/analysis.js"'));
  assert.ok(page.indexOf('src="assets/analysis.js"') < page.indexOf('src="assets/app.js"'));
  assert.match(page, /<div id="analysis"[^>]*><h3[^>]*>Analysis<\/h3><div id="analysis-content"/);
  assert.ok(page.indexOf('id="analysis"') > page.indexOf('id="drawdown-chart"'));
  assert.doesNotMatch(page, /<summary>Investment thesis and interpretation/);
  for (const id of ['blotter', 'ledger', 'date', 'snapshot', 'portfolio', 'equity-chart', 'drawdown-chart', 'model']) assert.ok(page.includes(`id="${id}"`));
});
