"""Labeled synthetic fixtures test the pipeline; never publish these results."""
import csv,io,json,tempfile,unittest
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from .config import Config
from .build import csv_text,publish,make_book,conclusion
from .data import Market,parse_ric,candidate_ric
from .engine import run
from .test_engine import fixture,simulate


class PipelineTests(unittest.TestCase):
    def test_publisher_rejects_synthetic_even_on_rerender(self):
        with tempfile.TemporaryDirectory() as d:
            output=Path(d)/'publication'
            with self.assertRaisesRegex(ValueError,'real LSEG'):
                publish({'source':'UNIT_TEST_ONLY','synthetic':True},output)
            self.assertFalse(output.exists())
    def test_eod_is_after_all_same_day_events(self):
        cfg,data=fixture();r=simulate(data,cfg)
        for row in r['ledger']:
            for event in r['events']:
                if event['date']==row['date']:self.assertGreater(row['timestamp'],event['timestamp'])
    def test_csv_roundtrips_null_and_nested_option(self):
        rows=[{'cash':50,'option':{'id':'REAL,comma','cp':'P'},'equity':None}]
        self.assertNotIn('\r',csv_text(rows,['cash','option','equity']))
        parsed=list(csv.DictReader(io.StringIO(csv_text(rows,['cash','option','equity']))))[0]
        self.assertEqual(parsed['equity'],'');self.assertEqual(json.loads(parsed['option']),rows[0]['option'])
    def test_no_fake_wheel_performance_when_puts_absent(self):
        cfg,data=fixture();data['contracts']=[c for c in data['contracts'] if c['cp']=='C'];ids={c['id'] for c in data['contracts']};data['options']=[q for q in data['options'] if q['id'] in ids]
        r=simulate(data,cfg);self.assertIsNone(r['metrics']['net_pnl']);self.assertEqual(r['events'],[])
        self.assertTrue(all(d['outcome']=='CANDIDATE_DATA_NOT_COVERED' for d in r['decisions']))
        bm=simulate(data,cfg,strategy='buy_hold');self.assertIn('Not tested',conclusion([r,bm]))
    def test_missing_final_quote_does_not_erase_liability(self):
        cfg,data=fixture();cfg=replace(cfg,end='2026-08-05')
        for q in data['options']:
            if q['date']==cfg.end:q['ask']=None
        r=simulate(data,cfg);s=r['ledger'][-1]
        self.assertIsNotNone(s['option']);self.assertIsNone(s['option_liability']);self.assertIsNone(r['metrics']['total_return'])
    def test_corrupted_ric_metadata_rejected(self):
        cfg,data=fixture();data['metadata'].update(source='LSEG',synthetic=False)
        data['contracts'][0]['strike']=999.
        with self.assertRaisesRegex(ValueError,'conflict'):Market(data,cfg)
    def test_dates_not_from_last_observation(self):
        parsed=parse_ric(candidate_ric('AAPL.O','2026-09-04',300,'P'),'AAPL.O')
        self.assertEqual(parsed['expiry'],'2026-09-04')
    def test_config_invalid_or_leverage_rejected(self):
        for kw in [{'initial_cash':-1},{'contracts':2},{'dte_min':20},{'put_delta':.25},{'selection':'best_backtest'}]:
            with self.assertRaises(ValueError):Config(**kw)
    def test_missing_dividend_coverage_blocks_real_run(self):
        cfg,data=fixture();data['metadata'].update(source='LSEG',synthetic=False,dividend_coverage_verified=False)
        with self.assertRaisesRegex(ValueError,'Dividend coverage'):run(data,cfg)
    def test_price_source_has_no_time_travel(self):
        cfg,data=fixture();data['stock'][1]['source_timestamp']='2026-08-04T16:00:00-04:00'
        r=simulate(data,cfg);self.assertEqual(r['decisions'][0]['outcome'],'EXECUTION_QUOTE_MISSING_INVALID_OR_ZERO_BID')


if __name__=='__main__':unittest.main()
