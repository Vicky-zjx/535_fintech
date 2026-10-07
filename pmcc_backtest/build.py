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
    """A short investment finding; algorithm details stay in the method drawer."""
    if book['status']=='blocked':
        return [('Backtest not published',
                 'The input audit has unresolved issues. No return is reported; blank values are not zero. See data limitations and reproduction details below.')]
    p=next(r for r in book['runs'] if r['strategy']=='pmcc' and r['fill_model']=='midpoint')['metrics']
    b=next(r for r in book['runs'] if r['strategy']=='buy_hold' and r['fill_model']=='midpoint')['metrics']
    side=next(r for r in book['runs'] if r['strategy']=='pmcc' and r['fill_model']=='quoted_side')['metrics']
    outlay=(f"The long call required {money(p['initial_capital_outlay'])} upfront versus "
            f"{money(p['stock_equivalent_at_entry'])} for 100 shares, before short-premium receipts. ")
    if p['net_pnl'] is None or b['net_pnl'] is None:
        return [('Finding',outlay+'Unresolved terminal exposure prevents a complete profit comparison. Lower entry outlay alone does not establish lower risk.')]
    difference=p['net_pnl']-b['net_pnl']
    comparison=('equal to buy and hold' if abs(difference)<.005 else
                f"{money(abs(difference))} {'below' if difference<0 else 'above'} buy and hold")
    return [('Finding',
        outlay+f"On the same $50,000 equity, midpoint PMCC earned {money(p['net_pnl'])} net—{comparison}; "
        f"quoted-side PMCC earned {money(side['net_pnl'])}. "
        'Lower upfront outlay is not lower risk: the long call adds time-value and volatility exposure. This short, single-stock sample does not establish a general advantage.')]

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
