'use strict';
// Presentation-only analysis of saved results. No new prices, fills or NAVs.
(() => {
  const sum = xs => xs.reduce((a, b) => a + b, 0);
  const mean = xs => sum(xs) / xs.length;
  const money = x => new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD'}).format(x);
  const dollars = x => new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD', maximumFractionDigits: 0}).format(x);
  const pct = x => (100 * x).toFixed(2) + '%';
  const day = x => new Intl.DateTimeFormat('en-US', {month: 'short', day: 'numeric', timeZone: 'UTC'}).format(new Date(x + 'T00:00:00Z'));
  function check(ok, message) { if (!ok) throw new Error('Analysis reconciliation: ' + message); }
  function equal(actual, expected, label) {
    check(Number.isFinite(actual) && Number.isFinite(expected) && Math.abs(actual - expected) < 1e-7, label);
  }
  function returnsStats(run, initialCash, annualRF) {
    // Never filter NAV before calculating returns: that would bridge the gap.
    let previous = initialCash;
    const returns = [], excluded = [];
    for (const row of run.ledger) {
      const value = row.equity === null || previous === null ? null : row.equity / previous - 1;
      if (value === null) {
        check(row.daily_return === null, 'missing adjacent return must stay null');
        excluded.push(row.date);
      } else {
        equal(row.daily_return, value, 'one-session return');
        returns.push(value);
      }
      previous = row.equity;
    }
    check(returns.length > 1, 'insufficient returns');
    const average = mean(returns);
    const sd = Math.sqrt(sum(returns.map(x => (x - average) ** 2)) / (returns.length - 1));
    check(sd > 0, 'undefined return dispersion');
    const sharpe = (average - ((1 + annualRF) ** (1 / 252) - 1)) / sd * Math.sqrt(252);
    equal(sharpe, run.metrics.available_daily_return_sharpe, 'saved available-return Sharpe');
    check(returns.length === run.metrics.valid_daily_returns, 'return sample count');
    check(JSON.stringify(excluded) === JSON.stringify(run.metrics.excluded_daily_return_dates), 'excluded return dates');
    return {count: returns.length, excluded, volatility: sd * Math.sqrt(252), sharpe};
  }
  function evidence(book, model) {
    const wheel = book.runs.find(r => r.strategy === 'wheel' && r.fill_model === model);
    const benchmark = book.runs.find(r => r.strategy === 'buy_hold');
    check(wheel && benchmark && wheel.metrics.empirical_strategy_supported, 'supported saved accounts required');
    const m = wheel.metrics, bm = benchmark.metrics, rows = wheel.ledger;
    const end = rows.at(-1), bEnd = benchmark.ledger.at(-1);
    const sales = wheel.events.filter(e => e.event_type === 'SELL_TO_OPEN');
    const premiums = Object.fromEntries(['P', 'C'].map(cp => {
      const events = sales.filter(e => e.cp === cp);
      const gross = sum(events.map(e => e.gross_cash_flow));
      const fees = sum(events.map(e => e.commission));
      return [cp, {count: events.length, gross, fees, netCash: gross - fees}];
    }));
    equal(premiums.P.gross + premiums.C.gross, m.gross_premiums, 'gross premium receipts');
    equal(premiums.P.netCash + premiums.C.netCash, m.net_premiums_after_option_costs, 'net premium cash');
    const stockPnl = end.realized_stock_pnl + end.unrealized_stock_pnl;
    const optionPnl = end.realized_option_pnl + end.unrealized_option_pnl - end.commissions;
    const otherCosts = end.stock_execution_costs + end.assignment_fees;
    equal(stockPnl + optionPnl + end.dividend_income - otherCosts, m.net_pnl, 'net P&L components');
    equal(end.cash + end.stock_value + end.dividend_receivable - end.option_liability, end.equity, 'endpoint equity');
    // The narrative describes the saved one-cycle experiment, not arbitrary future runs.
    const puts = wheel.events.filter(e => e.event_type === 'PUT_ASSIGNMENT');
    const calls = wheel.events.filter(e => e.event_type === 'CALL_ASSIGNMENT');
    const dividends = wheel.events.filter(e => e.event_type === 'DIVIDEND_ENTITLEMENT');
    const payments = wheel.events.filter(e => e.event_type === 'DIVIDEND_PAYMENT');
    const buys = benchmark.events.filter(e => e.event_type === 'STOCK_BUY');
    check(puts.length === 1 && calls.length === 1 && dividends.length === 1 && payments.length === 1 && buys.length === 1,
      'one stock cycle and one dividend required; revise interpretation for a different experiment');
    const put = puts[0], call = calls[0], dividend = dividends[0], payment = payments[0], buy = buys[0];
    const shares = put.shares_after - put.shares_before;
    const heldSessions = rows.filter(r => r.shares > 0).length;
    check(rows.every(r => r.shares === 0 || r.shares === shares), 'consistent Wheel share size');
    check(benchmark.ledger.every(r => r.shares === buy.shares_after), 'constant benchmark shares');
    equal(heldSessions, m.days_with_shares, 'EOD sessions with shares');
    check(put.date < dividend.date && dividend.date < call.date && dividend.date <= payment.date, 'dividend eligibility');
    equal(dividend.before.shares, dividend.quantity, 'eligible dividend shares');
    equal(dividend.quantity * dividend.fill_price, end.dividend_income, 'dividend income');
    equal(dividend.after.dividend_receivable - dividend.before.dividend_receivable, end.dividend_income, 'ex-date receivable');
    equal(dividend.cash_after, dividend.cash_before, 'no ex-date cash movement');
    equal(payment.cash_after - payment.cash_before, end.dividend_income, 'dividend payment cash');
    equal(payment.before.dividend_receivable - payment.after.dividend_receivable, end.dividend_income, 'receivable released');
    equal(payment.after.dividend_income, payment.before.dividend_income, 'no double-counted dividend income');
    check(sales.length === m.option_entries && wheel.events.every(e => e.event_type !== 'BUY_TO_CLOSE'), 'no unreported buyback');
    equal(m.net_premiums_after_option_costs - end.option_liability, optionPnl, 'premium cash less open liability');
    check(end.option?.cp === 'P' && end.option.expiry > book.config.end, 'open endpoint put');
    equal(otherCosts, 0, 'baseline has no stock execution or assignment charges');
    equal(m.total_costs, end.commissions, 'costs are option commissions in this experiment');
    const gaps = rows.filter(r => r.equity === null).map(r => r.date);
    check(JSON.stringify(gaps) === JSON.stringify(m.valuation_gap_dates), 'NAV gap dates');
    check(gaps.length > 0 && m.max_drawdown === null && m.sharpe === null, 'incomplete full-path statistics');
    check(rows.filter(r => r.date >= gaps[0]).every(r => r.drawdown === null), 'strict drawdown stops at first gap');
    check(rows.filter(r => r.equity === null).every(r => r.observed_drawdown === null), 'observed drawdown retains gaps');
    check(bm.full_path_complete, 'complete benchmark required for this comparison');
    const stockGap = bEnd.realized_stock_pnl + bEnd.unrealized_stock_pnl - stockPnl;
    const extraSharesGain = (buy.shares_after - shares) * (bEnd.stock_mark - buy.fill_price);
    const entryBasisDifference = shares * (put.fill_price - buy.fill_price);
    const endpointExitDifference = shares * (bEnd.stock_mark - call.fill_price);
    equal(extraSharesGain + entryBasisDifference + endpointExitDifference, stockGap, 'stock P&L difference decomposition');
    const shortfall = bm.net_pnl - m.net_pnl;
    equal(stockGap - optionPnl + bEnd.dividend_income - end.dividend_income - bm.total_costs, shortfall, 'benchmark shortfall');
    check(shortfall > 0, 'rewrite thesis interpretation if the Wheel no longer underperforms');
    const result = {model, metrics: m, benchmarkMetrics: bm, sessions: rows.length, heldSessions, shares,
      benchmarkShares: buy.shares_after, averageCash: mean(rows.map(r => r.cash)),
      averageFreeCash: mean(rows.map(r => r.buying_power)), premiums, stockPnl, optionPnl, shortfall,
      extraSharesGain, entryBasisDifference, endpointExitDifference, stockGap, put, call, buy, dividend, payment, end,
      callCapAtAssignment: shares * (call.before.stock_mark - call.fill_price),
      wheelReturns: returnsStats(wheel, book.config.initial_cash, book.config.risk_free_rate),
      benchmarkReturns: returnsStats(benchmark, book.config.initial_cash, book.config.risk_free_rate)};
    check(result.wheelReturns.sharpe > result.benchmarkReturns.sharpe && result.wheelReturns.volatility < result.benchmarkReturns.volatility,
      'rewrite risk interpretation if the observed relationship changes');
    return result;
  }
  function paragraphs(book, model, research) {
    const e = evidence(book, model), m = e.metrics, bm = e.benchmarkMetrics;
    const label = model === 'quoted_side' ? 'bid/ask baseline' : 'midpoint sensitivity';
    const text = [
      `The ${label} returned ${pct(m.total_return)}, behind buy-and-hold’s ${pct(bm.total_return)}. Position sizing and entry timing mattered: the Wheel held ${e.shares} shares at ${e.heldSessions} of ${e.sessions} daily closes; the benchmark held ${e.benchmarkShares} throughout. Cash averaged ${dollars(e.averageCash)}, including put collateral; ${dollars(e.averageFreeCash)} was unreserved, earning no interest. The ${day(e.put.date)} put assignment acquired shares at ${money(e.put.fill_price)}, versus the benchmark’s ${money(e.buy.fill_price)} entry. The ${day(e.call.date)} call assignment sold at ${money(e.call.fill_price)} against a ${money(e.call.before.stock_mark)} close, capping ${dollars(e.callCapAtAssignment)} of stock upside that day—not the entire ${money(e.shortfall)} performance shortfall.`,
      `The ${m.option_entries} option sales collected ${money(m.gross_premiums)}: ${money(e.premiums.P.gross)} from puts and ${money(e.premiums.C.gross)} from calls. After ${money(m.option_commissions)} in commissions, net premium cash was ${money(m.net_premiums_after_option_costs)} (${money(e.premiums.P.netCash)} puts; ${money(e.premiums.C.netCash)} calls). Subtracting the remaining ${money(e.end.option_liability)} short-put liability leaves ${money(e.optionPnl)} net option P&L; adding ${money(e.stockPnl)} stock gains and ${money(e.end.dividend_income)} dividends reconciles to ${money(m.net_pnl)} total profit. Costs were small, not the main explanation for the gap; bid/ask effects are already in fills. The ${e.dividend.quantity} shares held before the ${day(e.dividend.date)} ex-date earned ${money(e.dividend.fill_price)} each: a receivable on that date, converted to cash on ${day(e.payment.date)}, not income counted twice.`,
      `Lower stock ownership and large cash balances are consistent with the Wheel’s lower observed return volatility (${pct(e.wheelReturns.volatility)} annualized versus ${pct(e.benchmarkReturns.volatility)}). This helps explain its slightly higher observed Sharpe, ${e.wheelReturns.sharpe.toFixed(2)} versus ${e.benchmarkReturns.sharpe.toFixed(2)}, despite lower total return. However, it uses ${e.wheelReturns.count} of ${e.sessions} one-session returns: ${e.wheelReturns.excluded.map(day).join(' and ')} are excluded because NAV is missing on ${day(m.valuation_gap_dates[0])}. The benchmark uses all ${e.benchmarkReturns.count}; missing-return selection can bias the comparison either way. No return bridges the gap.`,
      `Strict Wheel drawdown stops at the first missing NAV, ${day(m.valuation_gap_dates[0])}, and remains unavailable thereafter because the running peak is uncertain; full-sample MDD stays unreported. Observed-NAV drawdown resumes using only available marks and retains the missing point. The observed drawdown of ${pct(m.observed_max_drawdown)} is only a lower bound in magnitude, so comparing it with the benchmark’s complete ${pct(bm.max_drawdown)} drawdown does not prove better downside protection. No prices or NAVs have been filled or interpolated.`,
      `The sideways/moderately bullish-market thesis receives limited support from positive net option P&L and a higher observed Sharpe, but the Wheel did not beat buy-and-hold in total return. Cash collateral does not remove the puts’ downside risk, and the incomplete NAV path prevents a firm risk-adjusted conclusion. The short, single-stock sample and incomplete historical candidate universe limit generalization; implied versus subsequent realized volatility was not tested. Testing other delta targets and expirations over longer rising, sideways and falling markets would help assess robustness; those experiments have not been run.`
    ];
    if (!research) return text;
    const c = research.accounts['wheel:'+model].capital;
    const fixed = research.fixed_benchmark.metrics;
    const common = research.common_observations[model];
    const prefix = research.accounts['wheel:'+model].prefix;
    equal(c.net_pnl, m.net_pnl, 'supplemental capital numerator');
    equal(c.account_return, m.total_return, 'supplemental account return');
    equal(c.return_on_average_committed, m.net_pnl/c.average_committed, 'capital-return denominator');
    equal(common.accounts['wheel:'+model].sharpe, m.available_daily_return_sharpe, 'common Wheel returns');
    text[0] = `The ${label} returned ${pct(m.total_return)}, behind full-capital buy-and-hold’s ${pct(bm.total_return)}. Position sizing and entry timing mattered: the Wheel held ${e.shares} shares at ${e.heldSessions} of ${e.sessions} daily closes; the benchmark held ${e.benchmarkShares} throughout. Reducing only the benchmark to 100 shares lowers its profit by ${money(bm.net_pnl-fixed.net_pnl)}; its ${pct(fixed.total_return)} account return still exceeds the Wheel by ${money(fixed.net_pnl-m.net_pnl)}. This is not matched exposure. The put assignment acquired shares at ${money(e.put.fill_price)}, versus ${money(e.buy.fill_price)} for buy-and-hold. The ${day(e.call.date)} call assignment capped ${dollars(e.callCapAtAssignment)} of stock upside against that day’s close—not the entire ${money(e.shortfall)} shortfall.`;
    text[2] = `Average session-peak committed capital was ${money(c.average_committed)} (${pct(c.utilization)} of starting cash), making return on average committed capital ${pct(c.return_on_average_committed)}: a descriptive, non-annualized ratio, not an alternative account return. Average EOD unreserved cash was ${money(c.average_unreserved_cash)}; reserved put cash is not idle. Lower stock ownership and cash holdings are consistent with observed volatility of ${pct(e.wheelReturns.volatility)} versus ${pct(e.benchmarkReturns.volatility)} and observed Sharpe of ${e.wheelReturns.sharpe.toFixed(2)} versus ${e.benchmarkReturns.sharpe.toFixed(2)}. Those use ${e.wheelReturns.count}/${e.sessions} versus ${e.benchmarkReturns.count}/${e.sessions} returns. On exactly ${common.dates.length} common dates, Sharpe is ${common.accounts['wheel:'+model].sharpe.toFixed(2)} versus ${common.accounts['buy_hold:quoted_side'].sharpe.toFixed(2)}; ${common.excluded_dates.map(day).join(' and ')} remain excluded. Neither comparison proves superior risk-adjusted performance.`;
    text[3] = `Strict Wheel drawdown stops at the first missing NAV, ${day(m.valuation_gap_dates[0])}, because the running peak becomes uncertain; full-period MDD remains unavailable. The uninterrupted ${day(prefix.start)}–${day(prefix.end)} prefix has ${prefix.sessions} sessions and MDD ${pct(prefix.max_drawdown)}, but covers only that shorter period. Observed-NAV drawdown resumes from available marks, retaining the missing point; ${pct(m.observed_max_drawdown)} is only a lower bound in magnitude. Comparing it with buy-and-hold’s complete ${pct(bm.max_drawdown)} drawdown does not establish better downside protection. Existing data did not verify a qualifying closing quote; no prices or NAVs were filled or interpolated.`;
    return text;
  }
  const api = {evidence, paragraphs};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof window !== 'undefined') window.WheelAnalysis = api;
})();
