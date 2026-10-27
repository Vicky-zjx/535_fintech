"""Build /wheel from real licensed input, or rerender committed derived results."""
import argparse,csv,io,json,platform,statistics
from importlib.metadata import version
from datetime import date,timedelta
from pathlib import Path
from .acquire import read_config,digest
from .config import Config
from .data import Market,finite,mid
from .engine import run

THESIS=('A systematic cash-secured put and covered-call wheel may generate income and potentially improve risk-adjusted returns relative to buy-and-hold in sideways or moderately bullish markets, particularly when implied volatility exceeds subsequent realized volatility. However, the strategy gives up some upside in strong rallies and retains substantial downside exposure during market declines.')


def coverage(data,cfg):
    m=Market(data,cfg);weeks=[];quote_issues=[]
    for w in m.calendar.weekly():
        for cp in ('P','C'):
            cs,row=m.candidates(w['date'],cp);row['contract_cost_floor']='Not applied in generic coverage; applied to actual carried stock basis in decisions'
            weeks.append(row)
    eligible=[c for c in data['contracts'] if c['last_trade_date']>=cfg.start and c['expiry']<=str(date.fromisoformat(cfg.end)+timedelta(days=cfg.dte_max))]
    ids={c['id'] for c in eligible};widths=[];relative=[];delta_count=0
    for q in data['options']:
        if q['id'] not in ids or not cfg.start<=q['date']<=cfg.end:continue
        value=mid(q)
        if value is not None and finite(q.get('bid')) and finite(q.get('ask')):
            widths.append(q['ask']-q['bid']);relative.append((q['ask']-q['bid'])/value)
        else:
            quote_issues.append(dict(date=q['date'],contract=q['id'],missing_fields=[k for k in ('bid','ask') if q.get(k) is None],
                reason='MISSING_OR_INVALID_DAILY_BBO',closing_fallback_available=m.closing_quote(q['id'],q['date']) is not None))
        if finite(q.get('delta')) and q.get('delta_source')=='historical':delta_count+=1
    missing=[dict(date=w['date'],cp=w['cp'],reason=w['reason'],required_fields=['historical membership','previous-session BID','ASK','historical DELTA' if cfg.selection=='historical_delta' else 'prior stock print']) for w in weeks if not w['known_contracts']]
    return dict(weeks=weeks,missing_candidate_weeks=missing,quote_issues=quote_issues,
        contract_counts={cp:sum(c['cp']==cp for c in eligible) for cp in ('P','C')},stock_rows=len(data['stock']),
        option_rows=len(data['options']),historical_delta_rows=delta_count,
        quoted_observations=len(widths),median_spread=statistics.median(widths) if widths else None,
        median_relative_spread=statistics.median(relative) if relative else None,
        spread_population='All observed short-dated candidate BBOs in the study window; not restricted to executed trades.',
        source_precision='Daily endPeriod BBO; no verified exact simultaneous intraday timestamps except retained final-minute event repairs.',
        candidate_universe=data['metadata'].get('candidate_universe'),corporate_action_review=data['metadata'].get('corporate_action_review'),
        acquisition=data['metadata'].get('wheel_acquisition'),mark_repair=data['metadata'].get('wheel_mark_repair'),exclusions=m.exclusions,
        contracts=eligible,complete_chain_proven=False)


def conclusion(runs):
    b=next(r for r in runs if r['strategy']=='buy_hold')['metrics']
    w=next(r for r in runs if r['strategy']=='wheel' and r['fill_model']=='quoted_side')['metrics']
    if not w['empirical_strategy_supported']:
        return 'Not tested: no supported Wheel option fills. The retained sample has insufficient historical put coverage; cash-only diagnostic balances are not a successful Wheel backtest. Buy-and-hold is measured separately. The income, excess-return and risk-adjusted-return thesis is not established; IV versus realized volatility is not tested.'
    excess=w['total_return']-b['total_return'] if w['total_return'] is not None and b['total_return'] is not None else None
    result=f"Bid/ask baseline: observed-subset Wheel return {w['total_return']:.2%} versus buy-and-hold {b['total_return']:.2%}; excess {excess:.2%}. " if excess is not None else 'Endpoint comparison unavailable because a required valuation is missing. '
    if w['sharpe'] is None or b['sharpe'] is None:result+='Risk-adjusted-return thesis not established: complete-path Sharpe comparison unavailable. '
    else:result+=f"Wheel Sharpe {w['sharpe']:.2f} versus {b['sharpe']:.2f}: {'supports' if w['sharpe']>b['sharpe'] else 'does not support'} the risk-adjusted-return thesis in this sample only. "
    return result+'Incomplete historical candidate coverage and the short single-stock sample limit inference. IV versus subsequent realized volatility is not tested.'


def make_book(path,cfg):
    data=json.loads(path.read_text());audit=coverage(data,cfg)
    runs=[run(data,cfg,'wheel',model) for model in ('quoted_side','midpoint')]+[run(data,cfg,'buy_hold','quoted_side')]
    benchmark=runs[-1]['metrics']
    for r in runs:
        total=r['metrics']['total_return'];bt=benchmark['total_return']
        r['metrics']['benchmark_excess_return']=total-bt if total is not None and bt is not None else None
    root=Path(__file__).resolve().parents[1]
    sources=list((root/'wheel_backtest').glob('*.py'))+[root/'pmcc_backtest'/n for n in ('calendar.py','data.py','fetch_lseg.py','contracts.py','repair_coverage.py')]
    return dict(schema_version=1,config=cfg.to_dict(),source='LSEG',synthetic=False,input_sha256=digest(path),
        python=platform.python_version(),dependencies={p:version(p) for p in ('pandas','numpy','exchange-calendars','lseg-data')},
        code_hashes={str(p.relative_to(root)):digest(p) for p in sources if p.exists()},
        audit=audit,runs=runs,thesis=THESIS,conclusion=conclusion(runs),
        status='unsupported_missing_wheel_fills' if not runs[0]['metrics']['empirical_strategy_supported'] else 'observed_universe_research',
        capital_note=f'Configured starting cash: ${cfg.initial_cash:,.2f}. The suggested $10,000 cannot secure an approximately $300 AAPL put; the default example therefore uses $50,000, fixed before Wheel returns. Every entry must pass strike × 100 plus fee/reserve checks using existing cash, not the new premium.',
        timing='Prior-session observations assumed available by next 09:00 ET. Select on the first actual trading session of each week; lock the contract before modeled closing fills. Daily BBOs do not prove synchronized quotes or an executed trade.',
        accounting='Cash is trade-date economic cash (not broker settled cash); available buying power excludes dividend receivables and reserved strike cash. Equity = cash + dividend receivable + stock value − short-option liability. Assignment transfers at strike are atomic option/stock events; premiums are realized on expiry/assignment separately from stock basis. No naked positions or borrow.',
        assignment='American exercise is modeled, not observed: ≥$0.01 expiry ITM assigns. Default pre-ex-dividend call model assigns an ITM call when same-date time value is less than an already announced next-session dividend. Other early call exercise and early put exercise are not modeled; daily bars cannot establish actual assignments. T+1 legal settlement is not a brokerage settled-cash simulation.',
        limitations=['Observed historical candidate subset, not a complete chain; probe/discovery and source-cache survivorship bias remain.',
            'Standard 100-share American deliverables are explicitly assumed from OCC rules and the retained corporate-action screen, not individually vendor-verified.',
            'Adjusted/mini contracts are excluded; unresolved split, merger, delisting or adjustment blocks the run. No silent standard-contract continuation.',
            'No forward fill, interpolation, theoretical premiums, future membership, assumed intermediate strikes, or missing-option zero marks.',
            'Endpoint positions are marked, not forcibly sold; unrealized P&L is included. Zero rolls is intentional.',
            'Full-path statistics are withheld across NAV gaps. Observed drawdown magnitude is only a lower bound; strict drawdown stops at the first gap.'])


def csv_text(rows,keys):
    out=io.StringIO();w=csv.DictWriter(out,fieldnames=keys,lineterminator='\n');w.writeheader()
    for r in rows:w.writerow({k:json.dumps(r.get(k),sort_keys=True) if isinstance(r.get(k),(dict,list)) else r.get(k) for k in keys})
    return out.getvalue()


def publish(book,output,template=None):
    if book.get('source')!='LSEG' or book.get('synthetic') is not False:
        raise ValueError('Only explicitly real LSEG results may be published')
    output.mkdir(parents=True,exist_ok=True)
    events=[e for r in book['runs'] for e in r['events']];ledger=[e for r in book['runs'] for e in r['ledger']];snapshots=[e for r in book['runs'] for e in r['snapshots']]
    export={
        'blotter.csv':(events,['event_id','timestamp','strategy','fill_model','event_type','underlying','contract','cp','expiry','strike','quantity','multiplier','fill_price','bid','ask','midpoint','spread','quote_date','quote_timestamp','quote_precision','gross_cash_flow','commission','assignment_fee','stock_execution_cost','net_cash_flow','realized_pnl_gross','stock_action','cash_before','cash_after','shares_before','shares_after','reason','source','source_snapshot_sha256','assumption_flags']),
        'ledger.csv':(ledger,['date','strategy','fill_model','cash','dividend_receivable','economic_cash','reserved_cash','buying_power','shares','share_acquisition_cost','stock_mark','stock_value','short_put','covered_call','option','option_mark','option_liability','equity','realized_pnl_net','unrealized_stock_pnl','unrealized_option_pnl','commissions','stock_execution_costs','assignment_fees','daily_return','drawdown','observed_drawdown','unresolved']),
        'snapshots.csv':(snapshots,['snapshot_id','event_id','timestamp','phase','date','mark_date','strategy','fill_model','cash','dividend_receivable','reserved_cash','buying_power','shares','share_acquisition_cost','stock_value','option','option_mark','option_liability','equity']),
        'coverage.csv':(book['audit']['weeks'],['date','signal_date','cp','known_contracts','valid_signal_quotes','eligible_contracts','selected','reason','universe_complete']),
        'decisions.csv':([e|{'fill_model':r['fill_model']} for r in book['runs'] for e in r['decisions']],['date','fill_model','signal_date','signal_at','cp','signal_spot','known_contracts','valid_signal_quotes','eligible_contracts','selected','reason','outcome']),
        'quote_issues.csv':(book['audit']['quote_issues'],['date','contract','missing_fields','reason','closing_fallback_available'])}
    for file,(rows,keys) in export.items():(output/file).write_text(csv_text(rows,keys))
    for file,value in [('results.json',book),('config.json',book['config']),('data_audit.json',book['audit'])]:
        (output/file).write_text(json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n')
    (output/'book.js').write_text('window.WHEEL_BOOK = '+json.dumps(book,sort_keys=True,allow_nan=False).replace('<','\\u003c')+';\n')
    page=template or Path(__file__).with_name('page.html')
    (output/'index.html').write_text(page.read_text())
    print(json.dumps(dict(status=book['status'],accounts=len(book['runs']),events=len(events),daily_rows=len(ledger),snapshots=len(snapshots),contract_counts=book['audit']['contract_counts']),indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',type=Path);p.add_argument('--config',type=Path);p.add_argument('--output',type=Path,default=Path(__file__).resolve().parents[1]/'wheel')
    a=p.parse_args()
    if a.input:book=make_book(a.input,read_config(a.config))
    else:
        if a.config:raise ValueError('Config changes require --input and a full rerun')
        book=json.loads((a.output/'results.json').read_text())
    publish(book,a.output)
