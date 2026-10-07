"""Independently reconcile all six published real-input accounts and exports."""
import argparse,csv,hashlib,json,math
from pathlib import Path
from .calendar import Calendar
from .config import Config
from .data import Market,fill
from .engine import run


def equal(a,b):assert math.isclose(a,b,abs_tol=1e-6),(a,b)


def validate(input_path,base_path=None):
    root=Path(__file__).resolve().parents[1];data=json.loads(input_path.read_text())
    book=json.loads((root/'pmcc/results.json').read_text());cfg=Config(**book['config'])
    assert book['input_sha256']==hashlib.sha256(input_path.read_bytes()).hexdigest()
    assert data['metadata']['config']==cfg.to_dict()
    if base_path:
        base=json.loads(base_path.read_text());assert base['metadata']['config']==cfg.to_dict()
        new={(q['id'],q['date']):q for q in data['options']}
        for old in base['options']:
            assert all(new[(old['id'],old['date'])].get(k)==v for k,v in old.items()),'Original observation changed'
        assert base['stock']==data['stock'] and base['dividends']==data['dividends']
    m=Market(data,cfg,Calendar(cfg.start,cfg.end));summary=[]
    for r in book['runs']:
        assert r==run(data,cfg,r['strategy'],r['fill_model']),'Full recomputation differs'
        cash=cfg.initial_equity;events=r['blotter']
        for e in events:
            cash+=e['cash_delta'];equal(cash,e['cash_after'])
            assert e['actual_fill_timestamp'] is None
            if e['leg'] in ('LONG_CALL','SHORT_CALL') and e['action'] in ('BUY','SELL'):
                q=m.execution_quote(e['contract'],e['date']);assert q and q['date']==e['date']
                equal(e['price'],fill(q,e['action'],r['fill_model']))
                equal(e['commission'],cfg.option_commission*e['quantity'])
                equal(e['cash_delta'],(-1 if e['action']=='BUY' else 1)*100*e['quantity']*e['price']-e['commission'])
        for row in r['ledger']:
            equal(row['economic_cash'],cfg.initial_equity+sum(e['cash_delta'] for e in events if e['date']<=row['date']))
            prior=[e for e in events if e['date']<=row['date']]
            if prior:
                assert row['long_contract']==prior[-1]['long_after']
                assert row['short_contract']==prior[-1]['short_after']
                assert row['stock_shares']==prior[-1]['shares_after']
            if row['nav'] is not None:
                equal(row['nav'],row['economic_cash']+row['long_mv']+row['short_mv']+row['stock_mv']+row['dividend_receivables']-row['dividend_payables']-row['accrued_cost_liabilities'])
            else:assert row['observed_drawdown'] is None
        gaps=[x['date'] for x in r['ledger'] if x['nav'] is None]
        if gaps:assert r['metrics']['max_drawdown'] is None
        else:equal(r['metrics']['max_drawdown'],min(x['drawdown'] for x in r['ledger']))
        if r['metrics']['terminal_resolved']:
            last=r['ledger'][-1];assert not last['n_long'] and not last['n_short'] and last['stock_shares']==0
            equal(cash,last['nav']);equal(last['nav']-cfg.initial_equity,r['metrics']['net_pnl'])
            a=r['attribution'];equal(sum(a[k] for k in ('long_realized','short_realized','stock_realized','dividends'))-sum(a[k] for k in ('option_commissions','stock_slippage','borrow_cost')),r['metrics']['net_pnl'])
        equal(sum(e['commission'] for e in events),r['attribution']['option_commissions'])
        equal(sum(e['stock_slippage_cost'] for e in events),r['attribution']['stock_slippage'])
        summary.append(dict(strategy=r['strategy'],fill_model=r['fill_model'],net_pnl=r['metrics']['net_pnl'],full_mdd=r['metrics']['max_drawdown'],observed_mdd=r['metrics']['max_observed_drawdown'],gap_dates=gaps,shorts=r['metrics']['short_calls'],terminal_resolved=r['metrics']['terminal_resolved']))
    for file,key in [('daily_nav.csv','ledger'),('trades.csv','blotter'),('weekly_coverage.csv','weekly_coverage')]:
        with (root/'pmcc'/file).open() as f:rows=list(csv.DictReader(f))
        expected=[x for r in book['runs'] for x in r[key]];assert len(rows)==len(expected)
        for row,source in zip(rows,expected):
            for k,v in row.items():
                original=source.get(k)
                if original is None:assert v==''
                elif isinstance(original,(dict,list)):assert json.loads(v)==original
                elif isinstance(original,bool):assert v==str(original)
                elif isinstance(original,(int,float)):equal(float(v),original)
                else:assert v==str(original)
    print(json.dumps(dict(validated_accounts=len(summary),results=summary),indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',type=Path,required=True);p.add_argument('--base',type=Path)
    a=p.parse_args();validate(a.input,a.base)
