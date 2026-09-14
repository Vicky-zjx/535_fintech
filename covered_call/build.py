"""Bake the real Python backtest into an offline-capable GitHub Pages page."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

import plotly

from .config import Config
from .engine import run_backtest
from .ingest import load_real


def build(cache: Path, output: Path, config=Config()):
    data=load_real(cache,config)
    if not data['stock'] or not data['options']:
        raise ValueError('Cannot publish results without real stock and option observations')
    result=run_backtest(data['stock'],data['options'],config)
    if result['status'] != 'complete':
        raise ValueError(f"Cannot publish a completed backtest: {result['status']}. Inspect missing expiry data first.")
    m=result['metrics']; v=result['validation']
    md=data['metadata']
    result['metadata']=dict(source='LSEG',synthetic=False,fetched_at=md['fetched_at'],
                            built_at=datetime.now(timezone.utc).isoformat(),
                            cache_sha256=hashlib.sha256(cache.read_bytes()).hexdigest(),
                            stock_bars=len(data['stock']),option_bars=len(data['options']),
                            option_contracts=len({r['ric'] for r in data['options']}),
                            timestamp_normalization=md['timestamp_normalization'],
                            ric_day_convention=md['ric_day_convention'],
                            candidate_grid=md['candidate_grid'])
    first_buy=next((r for r in result['blotter'] if r['action']=='BUY'),None)
    debit=max(0,-min(r['cash'] for r in result['ledger']))
    result['analysis']=[
        dict(title='What happened',text=(
            f"NAV moved from ${m['starting_nav']:,.2f} to ${m['ending_nav']:,.2f} ({m['total_return']:.2%}), "
            f"including ${m['premium_collected']:,.2f} from {m['calls_sold']} calls. "
            f"{m['expired']} expired OTM/ATM and {m['assigned']} were assigned. "
            f"The account finished with {m['ending_shares']} shares; the return includes their unrealized price change. "
            f"Maximum drawdown was {m['max_drawdown']:.2%}.")),
        dict(title='Where theory met the tape',text=(
            f"The 5% rule produced modest premiums and a {m['assignment_rate'] or 0:.1%} assignment rate in this sample; "
            f"it left stock exposure in place during the drawdown. {m['skipped_weeks']} week(s) were skipped at the exact entry timestamp. "
            f"{v['count']:,} genuine midpoint/print pairs support measuring the fill assumption, but a high R² does not prove an executable midpoint. "
            f"{m['stale_option_marks']} ledger states used a disclosed earlier option mark.")),
        dict(title='What I would change',text=(
            "Next I would compare the same 5% rule with bid-side fills and explicit commissions and financing, "
            "then repeat over more market regimes. I would compare alternative OTM targets in a separate run, "
            "without tuning this result after seeing the outcome. Farther OTM preserves upside before the cap, "
            "but the smaller premium also provides less protection against a stock decline.")),
    ]
    result['methodology']=[
        dict(title='Trading clock and horizon',text=(
            f"{config.start} through {config.end}; stock and options both use {config.bar_minutes}-minute bars. "
            f"ENTRY_TIME = {config.entry_time} America/New_York. A source bar labeled 10:00 becomes available at 11:00. "
            "A missed Monday is not rescheduled to Tuesday. Expiry uses the stock print in the hourly bar ending Friday 16:00.")),
        dict(title='Candidate universe and no look-ahead',text=(
            "For each week, test a $0.50 strike grid from the rounded-up 5% target through $10 above it, "
            "plus an ATM band of ±$2.50 for validation. A candidate is eligible only after LSEG has returned "
            "a quote or print timestamped at or before entry. Choose the lowest eligible strike ≥ target; "
            "if its current bid/ask is missing, skip instead of reaching for another strike. This is a documented observed universe, not a claim to recover an entire historical listing master.")),
        dict(title='Simulated fills and sparse marks',text=(
            "The fill is the observed bar’s closing BID/ASK midpoint; the stock fill is that bar’s TRDPRC_1. "
            "These are simulated executions from real historical bars, not claims of actual orders. "
            "No quote is filled forward for entry. Valuation alone carries an earlier valid midpoint when necessary, "
            "and records its timestamp. Bar endpoints cannot prove quote and trade simultaneity within the hour.")),
        dict(title='Funding and the simplified account',text=(
            f"INITIAL_CASH = ${config.initial_cash:,.2f}. "
            +(f"The initial stock purchase cost ${-first_buy['cash_delta']:,.2f}. " if first_buy else '')+
            f"Maximum cash borrowing was ${debit:,.2f}. Negative cash is allowed only under the specified Reg T checks. "
            "Short-call MV is negative. Initial = 50% of stock LMV; maintenance = 25%; the covered call adds zero. "
            "Cash changes only through the four required blotter actions.")),
        dict(title='Scope of the return',text=(
            "Gross price-only result: dividends, commissions, taxes, slippage, borrowing interest, and interest on cash are excluded. "
            "The model follows the assignment’s expiry-only assignment rule for American calls; it does not model early exercise or broker-specific house margins. "
            "Remaining stock is marked, not forcibly liquidated at the end.")),
        dict(title='Identifiers, source, and reproducibility',text=(
            "The separate AAPL cache preserves raw LSEG replies and missing values. Single-digit expiry days required zero padding in paired real API tests, "
            "so the provider adapter uses that verified format while the default constructor retains the screenshot examples. "
            "The source, cache hash, Python engine, tests, full blotter, and ledger are available from the Data page. Assignment 1.1’s cache and page remain separate.")),
    ]
    output.mkdir(parents=True,exist_ok=True)
    (output/'assets').mkdir(exist_ok=True)
    # Bundled Plotly keeps the published result usable without a CDN or backend.
    js=Path(plotly.__file__).parent/'package_data'/'plotly.min.js'
    shutil.copyfile(js,output/'assets'/'plotly.min.js')
    serialized=json.dumps(result,allow_nan=False,separators=(',',':'))
    (output/'book.js').write_text('window.COVERED_CALL_BOOK = '+serialized+';\n',encoding='utf-8')
    print(json.dumps(dict(status=result['status'],metrics=m,paired_points=v['count'],fit=v['fit'],audit=result['audit']),indent=2))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache',type=Path,default=Path('covered_call/data/aapl_hourly_verified.json'))
    parser.add_argument('--output',type=Path,default=Path('covered-call'))
    args=parser.parse_args()
    build(args.cache,args.output)
