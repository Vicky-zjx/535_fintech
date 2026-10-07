"""Deterministic static publisher. Missing verified inputs never become a flat NAV."""
import argparse
import csv
import hashlib
from html import escape
import importlib.metadata
import io
import json
from pathlib import Path
import platform

from .audit import audit_dataset
from .calendar import Calendar
from .config import Config
from .engine import run

STRATEGIES=('pmcc','covered_call','buy_hold')
MODELS=('midpoint','quoted_side')
LABELS=dict(pmcc='PMCC',covered_call='Cash-funded covered call',buy_hold='100-share buy and hold')


def public_provenance(c):
    """Publish evidence labels/citations, not the licensed reference response."""
    result={k:v for k,v in c.get('provenance',{}).items() if k!='current_description'}
    description=c.get('provenance',{}).get('current_description',{})
    result['current_description']={k:v for k,v in description.items() if k!='values'}
    return result


def csv_text(rows,columns):
    buf=io.StringIO(newline='');writer=csv.DictWriter(buf,fieldnames=columns,extrasaction='ignore',lineterminator='\n')
    writer.writeheader()
    for row in rows:
        safe={k:json.dumps(v,separators=(',',':'),sort_keys=True,allow_nan=False) if isinstance(v,(list,dict)) else v for k,v in row.items()}
        writer.writerow(safe)
    return buf.getvalue()


def money(x): return 'unavailable' if x is None else f'${x:,.2f}'


def narrative(book):
    common=[
      ('Why AAPL, why these rules',
       'I use AAPL to connect this study to my earlier covered-call assignment, not because it was a prospectively selected winner. Each new account starts with $50,000 and can hold only one strategy unit. The comparison covered call is fully funded; its results must be rebuilt under the new timing rules rather than borrowed from the old $30,000 Reg T account. The 5% OTM threshold stays fixed. A missing listed strike is not an invitation to invent an intermediate one.'),
      ('First session is the schedule; close is the reference',
       'The first trading session gives the short call most of its remaining weekly cycle; a Monday holiday moves the opportunity to Tuesday. I use the closing reference because the inputs are daily and the three accounts need a consistent valuation schedule, not because the close is optimal. Choices use the prior session, at a 09:00 ET checkpoint after overnight availability. Where publication timestamps are absent, that availability is an explicit assumption. Daily dates are not verified intraday quote or fill times. Waiting until the close leaves less time to expiry and can move the strike away from 5% OTM.'),
      ('Capital is not profit',
       'The declared long-selection mode is the 75%-of-spot strike proxy, not a claim of 0.80 delta. The long call is paid in full and retained between weekly cycles. Lower entry cash would leave more unused cash, but one long call is not 100 shares and its remaining time value can change substantially. Premium receipts create a short-option liability; they are not immediate profit. Account returns use the same $50,000 denominator. Idle cash earns zero, and discretionary entries cannot borrow. Economic cash includes trade-date proceeds; it is not settled cash or broker buying power.'),
      ('What assignment changes',
       'An assigned PMCC short call removes the option, credits the strike proceeds and leaves the long call alongside minus 100 shares. The model covers those shares at the next actual session’s close, including weekend borrow accrual. It sells the long only if a mandatory paired liquidation is needed to fund that cover. There is no automatic exercise and no new short at the same close as the cover. Dividend-related assignment is a disclosed time-value convention, not an observation of what a historical holder did.'),
      ('Terms and coverage are part of the result',
       'Identity and expiry are decoded from real RICs; historical observations establish signal-time membership. Multiplier 100 and delivery of 100 AAPL shares are source-supported research assumptions, not supplier-confirmed historical terms for every contract. The screen excludes conflicting or nonstandard identities, using OCC specifications, available descriptions and corporate-action evidence. Scheduled last trading date comes from contract rules and the exchange calendar, never the final quote date. The strike is the minimum among historically evidenced candidates, not necessarily every listed strike. Current long-contract discovery also leaves survivor bias. This retrospective single-stock study does not establish a universal edge.')]
    if book['status']=='blocked':
        audit=book['audit']
        stock_count=audit.get('stock',{}).get('rows',audit.get('stock_observations','unavailable'))
        dividend_count=audit.get('dividends',{})
        dividend_count=dividend_count.get('records','unavailable') if isinstance(dividend_count,dict) else dividend_count
        long_count=audit.get('long_probe',{}).get('rows')
        long_evidence=(f' and {long_count} daily observations for one real long-dated call' if long_count is not None else '')
        lead=('Finding: prices exist, but the historical universe is not verified',
          f'The LSEG input audit records {stock_count} AAPL daily stock observations and {dividend_count} dividend records{long_evidence}. '
          'It did not establish all required historical inputs and contract terms; inspect the exact blocking issues below. '
          'An observed candidate subset is not a complete historical chain. Therefore no empirical PMCC or comparison return is published. '
          'Blank charts and unavailable metrics mean the audit stopped the run; they do not mean zero return. '
          f"The requested window is {book['config']['start']}–{book['config']['end']}, with no validated common empirical backtest published. "
          'The period has not been shortened to select favorable returns.')
    else:
        runs={r['strategy']:r for r in book['runs'] if r['fill_model']=='midpoint'}
        p,c,b=[runs[s] for s in STRATEGIES]
        side=next(r for r in book['runs'] if r['strategy']=='pmcc' and r['fill_model']=='quoted_side')
        lead=('Finding from the generated ledger',
          f"Over {book['config']['start']}–{book['config']['end']}, midpoint PMCC net P&L is {money(p['metrics']['net_pnl'])}; "
          f"the cash-funded covered call reports {money(c['metrics']['net_pnl'])} and buy and hold {money(b['metrics']['net_pnl'])}. "
          f"PMCC collected {money(p['metrics']['gross_premiums'])} in gross premiums from {p['metrics']['short_calls']} shorts, with "
          f"{p['metrics']['skipped_weeks']} skipped weeks and {p['metrics']['long_only_sessions']} end-of-session long-only states. "
          f"Quoted-side PMCC P&L is {money(side['metrics']['net_pnl'])}. "+
          (f"There are {p['metrics']['valuation_gap_sessions']} PMCC NAV gaps ({', '.join(p['metrics']['valuation_gap_dates'])}); full-sample MDD is unavailable. The separately labeled observed-NAV drawdown is only a lower bound on its magnitude. " if p['metrics']['valuation_gap_sessions'] else
           'The complete daily NAV path supports a full-sample maximum drawdown. ')+
          ('Terminal positions are fully liquidated and cash reconciles independently. ' if p['metrics']['terminal_resolved'] else 'Terminal exposure remains unresolved. ')+
          'No missing observation is interpolated.')
        if p['metrics']['net_pnl'] is not None and b['metrics']['net_pnl'] is not None:
            direction='underperformed' if p['metrics']['net_pnl']<b['metrics']['net_pnl'] else 'outperformed'
            common[2]=(common[2][0],common[2][1]+f" Here PMCC {direction} buy and hold by {money(abs(p['metrics']['net_pnl']-b['metrics']['net_pnl']))} under the midpoint model; lower cash outlay did not determine the better return.")
    if book['config']['long_mode']!='75%-of-spot strike proxy':
        common[2]=(common[2][0],common[2][1].replace('The declared long-selection mode is the 75%-of-spot strike proxy, not a claim of 0.80 delta.','The declared long-selection mode targets 0.80 historical delta, using eligible signal-time deltas from 0.70 to 0.90.'))
    return [lead,*common]


def build(root,input_path=None):
    root=Path(root);out=root/'pmcc';out.mkdir(exist_ok=True)
    cfg=Config();audit=json.loads((root/'pmcc_backtest/audit_snapshot.json').read_text())
    runs=[];source_hash=None;catalogue=[]
    if input_path:
        data=json.loads(Path(input_path).read_text())
        cfg=Config(**data['metadata']['config'])
        source_hash=hashlib.sha256(Path(input_path).read_bytes()).hexdigest()
        audit=audit_dataset(data,cfg)
        for c in data.get('contracts',[]):
            catalogue.append({k:c.get(k) for k in ('id','underlying','cp','strike','expiry','scheduled_last_trading_date','last_trade_date','first_observed_quote_date','last_observed_quote_date','series_friday','multiplier','deliverable','standard_verified','terms_status','terms_assumption','terms_source','risk_flags')}
                | {'identity_status':'official RIC-rule derivation, checked against available description/cache',
                   'membership_status':'direct historical quotation evidence, gated at each signal',
                   'last_trade_status':'rule/calendar derivation, distinct from final quote',
                   'multiplier_status':'directly verified' if c.get('standard_verified') else 'research assumption',
                   'deliverable_status':'directly verified' if c.get('standard_verified') else 'research assumption',
                   'field_provenance':public_provenance(c)})
        if audit['ready']:
            runs=[run(data,cfg,strategy,model) for model in MODELS for strategy in STRATEGIES]
    status='blocked' if not runs else ('complete' if all(r['status']=='complete' for r in runs) else 'incomplete')
    versions={name:importlib.metadata.version(name) for name in ('pandas','numpy','exchange-calendars','lseg-data')}
    code_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((root/'pmcc_backtest').glob('*.py'))}
    book=dict(schema_version=1,status=status,config=cfg.to_dict(),audit=audit,runs=runs,
              input_sha256=source_hash,versions=versions,python=platform.python_version(),code_hashes=code_hashes,
              annualized_headlines=False,raw_data_redistributed=False,contract_catalogue=catalogue)
    return publish(root,book)


def publish(root,book):
    root=Path(root);out=root/'pmcc';out.mkdir(exist_ok=True)
    cfg=Config(**book['config']);audit=book['audit'];runs=book['runs'];status=book['status']
    book['narrative']=narrative(book)
    all_ledger=[row for r in runs for row in r['ledger']]
    trades=[row for r in runs for row in r['blotter']]
    weeks=[row for r in runs for row in r['weekly_coverage']]
    if not runs:
        weeks=[dict(date=w['date'],signal_date=w['previous_session'],signal_at=w['signal_at'],
                    closing_reference=w['closing_reference'],friday_series=w['friday'],last_session=w['friday_last_session'],
                    holiday_shifted=w['date']!=w['monday'],strategy='NOT_RUN',fill_model='NOT_RUN',
                    outcome='not_run',reason='DATA_AUDIT_BLOCKED_NOT_A_TRADE_DECISION') for w in Calendar(cfg.start,cfg.end).weekly()]
    book['weekly_coverage']=weeks
    exports={
      'daily_nav.csv':(all_ledger,['date','closing_reference','strategy','fill_model','economic_cash','long_contract','n_long','short_contract','n_short','stock_shares','long_mark','short_mark','stock_mark','long_mv','short_mv','stock_mv','dividend_receivables','dividend_payables','accrued_cost_liabilities','nav','drawdown','observed_drawdown','daily_return','capital_deployed_cost','delta_dollar','delta_to_nav','long_only','valuation_gaps','mark_sources','unresolved','settled_cash','broker_buying_power']),
      'trades.csv':(trades,['id','strategy','fill_model','date','signal_date','signal_at','execution_reference','execution_time_is_modeled','event_phase','leg','contract','strike','expiry','action','quantity','multiplier','price','cash_delta','commission','stock_slippage_cost','cash_after','shares_after','long_after','short_after','signal_spot','execution_spot','source_date','source_precision','source_timestamp','source_event_timestamp','source_quote_method','source_snapshot_sha256','actual_fill_timestamp','reason']),
      'weekly_coverage.csv':(weeks,['strategy','fill_model','date','signal_date','signal_at','closing_reference','friday_series','last_session','holiday_shifted','signal_spot','execution_spot','signal_target','selected_long','selected_short','selected_strike','actual_entry_moneyness','time_to_last_trade_days','positive_bid_verified','candidate_coverage','candidate_coverage_complete','candidate_requests','signal_observed_contracts','outcome','reason']),
      'candidate_coverage.csv':(audit.get('short_universe_coverage',[]),['expiry','execution_day','signal_day','scope','complete','queried_candidates','historical_contracts','signal_observed_contracts','signal_observed_strikes','provider_errors']),
      'quote_rechecks.csv':(audit.get('coverage_repair',{}).get('quote_checks',[]),['id','date','daily_bid_missing','status','source_timestamp','raw_sha256','error'])}
    for name,(rows,fields) in exports.items(): (out/name).write_text(csv_text(rows,fields))
    catalogue=book.get('contract_catalogue',[])
    (out/'contracts.csv').write_text(csv_text(catalogue,['id','underlying','cp','strike','expiry','scheduled_last_trading_date','first_observed_quote_date','last_observed_quote_date','series_friday','multiplier','deliverable','standard_verified','terms_status','identity_status','membership_status','last_trade_status','multiplier_status','deliverable_status','terms_assumption','terms_source','risk_flags','field_provenance']))
    (out/'exclusions.csv').write_text(csv_text(audit.get('excluded_contracts',[]),['id','reason','scope']))
    text=json.dumps(book,sort_keys=True,indent=2,allow_nan=False)+'\n'
    (out/'results.json').write_text(text)
    (out/'book.js').write_text('window.PMCC_BOOK = '+json.dumps(book,sort_keys=True,allow_nan=False).replace('<','\\u003c')+';\n')
    (out/'config.json').write_text(json.dumps(cfg.to_dict(),sort_keys=True,indent=2)+'\n')
    (out/'data_audit.json').write_text(json.dumps(audit,sort_keys=True,indent=2,allow_nan=False)+'\n')
    template=(root/'pmcc_backtest/page.html').read_text()
    paragraphs='\n'.join(f'<article class="narrative"><h3>{escape(title)}</h3><p>{escape(body)}</p></article>' for title,body in book['narrative'])
    (out/'index.html').write_text(template.replace('<!-- GENERATED_NARRATIVE -->',paragraphs))
    words=sum(len(body.split()) for _,body in book['narrative'])
    print(json.dumps(dict(status=status,runs=len(runs),trades=len(trades),ledger_rows=len(all_ledger),weekly_rows=len(weeks),main_narrative_words=words),indent=2))
    return book


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,help='Private real input: recalculate all accounts under disclosed assumptions.')
    p.add_argument('--audit-only',action='store_true',help='Explicitly reproduce the initial capability-audit blocked state.')
    args=p.parse_args();root=Path(__file__).resolve().parents[1]
    existing=root/'pmcc/results.json'
    if args.input or args.audit_only or not existing.exists():
        build(root,args.input)
    else:
        print('Re-rendering committed derived account outputs; market data and P&L are NOT recalculated. Use --input for a full licensed-input rerun.')
        publish(root,json.loads(existing.read_text()))
