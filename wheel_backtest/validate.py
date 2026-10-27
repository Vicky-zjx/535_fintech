"""Independent event/state and CSV reconciliation plus exact accounting replay."""
import argparse,csv,json,math
from pathlib import Path
from .acquire import digest
from .config import Config
from .engine import run


def equal(a,b):assert math.isclose(a,b,abs_tol=1e-6),(a,b)


def validate(input_path,output):
    book=json.loads((output/'results.json').read_text());data=json.loads(input_path.read_text());cfg=Config(**book['config'])
    assert book['synthetic'] is False and data['metadata']['source']=='LSEG'
    assert digest(input_path)==book['input_sha256'];summaries=[]
    for r in book['runs']:
        replay=run(data,cfg,r['strategy'],r['fill_model'])
        compare=json.loads(json.dumps(r));compare['metrics'].pop('benchmark_excess_return',None)
        assert replay==compare,'Recomputed account differs'
        cash=cfg.initial_cash;shares=0
        for e in r['events']:
            equal(e['cash_before'],cash);assert e['shares_before']==shares
            cash+=e['net_cash_flow'];shares=e['shares_after'];equal(e['cash_after'],cash)
            equal(e['gross_cash_flow']-e['commission']-e['assignment_fee']-e['stock_execution_cost'],e['net_cash_flow'])
            if e['event_type']=='PUT_ASSIGNMENT':assert e['shares_after']-e['shares_before']==100;equal(e['gross_cash_flow'],-100*e['strike'])
            if e['event_type']=='CALL_ASSIGNMENT':assert e['shares_after']-e['shares_before']==-100;equal(e['gross_cash_flow'],100*e['strike'])
            if e['event_type'] in ('SELL_TO_OPEN','BUY_TO_CLOSE'):
                assert e['quote_date']==e['date'] and e['source_snapshot_sha256']
                equal(e['midpoint'],(e['bid']+e['ask'])/2)
                expected=e['midpoint'] if r['fill_model']=='midpoint' else e['bid'] if e['event_type']=='SELL_TO_OPEN' else e['ask']
                equal(e['fill_price'],expected);equal(e['commission'],cfg.option_commission*e['quantity'])
                if e['event_type']=='SELL_TO_OPEN':
                    assert e['before']['shares']==100 if e['cp']=='C' else e['before']['cash']>=100*e['strike']+cfg.option_commission+cfg.assignment_fee
            for side in ('before','after'):
                s=e[side];snapshot=next(x for x in r['snapshots'] if x['snapshot_id']==e['event_id']+'-'+side)
                for field in ('cash','shares','option','equity','reserved_cash'):assert s[field]==snapshot[field]
        for s in r['snapshots']:
            assert s['cash']>=-1e-7 and 0<=s['reserved_cash']<=s['cash']+1e-7 and s['shares']>=0
            equal(s['buying_power'],s['cash']-s['reserved_cash'])
            if s['option']:
                assert s['shares']==100 if s['option']['cp']=='C' else s['shares']==0
            else:equal(s['option_liability'],0)
            if s['equity'] is not None:
                equal(s['equity'],s['cash']+s['dividend_receivable']+s['stock_value']-s['option_liability'])
                equal(s['equity']-cfg.initial_cash,s['realized_pnl_net']+s['unrealized_option_pnl']+s['unrealized_stock_pnl'])
        for row in r['ledger']:
            equal(row['cash'],cfg.initial_cash+sum(e['net_cash_flow'] for e in r['events'] if e['date']<=row['date']))
            for event in r['events']:
                if event['date']==row['date']:assert row['timestamp']>event['timestamp'],'EOD must follow booked events'
        summaries.append(dict(strategy=r['strategy'],fill_model=r['fill_model'],status=r['status'],events=len(r['events']),snapshots=len(r['snapshots']),net_pnl=r['metrics']['net_pnl'],nav_gaps=r['metrics']['valuation_gap_dates']))
    for name,key in [('blotter.csv','events'),('ledger.csv','ledger'),('snapshots.csv','snapshots')]:
        with (output/name).open() as f:rows=list(csv.DictReader(f))
        expected=[e for r in book['runs'] for e in r[key]];assert len(rows)==len(expected)
        for row,original in zip(rows,expected):
            for k,value in row.items():
                v=original.get(k)
                if v is None:assert value==''
                elif isinstance(v,(dict,list)):assert json.loads(value)==v
                elif isinstance(v,bool):assert value==str(v)
                elif isinstance(v,(int,float)):equal(float(value),v)
                else:assert value==str(v)
    print(json.dumps({'validated':summaries,'csv_reconciled':True,'event_snapshots_reconciled':True},indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',required=True,type=Path);p.add_argument('--output',type=Path,default=Path(__file__).resolve().parents[1]/'wheel')
    a=p.parse_args();validate(a.input,a.output)
