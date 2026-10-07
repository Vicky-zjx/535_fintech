"""Input, audit and publisher regressions; fixtures stay outside real builds."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from .audit import audit_dataset
from .build import build, csv_text
from .data import Market, mid
from .fetch_lseg import parse_daily, parse_dividends
from .selection import long_call, short_call
from .test_engine import fixture, market, row


class PipelineTests(unittest.TestCase):
    def test_daily_date_not_invented_time(self):
        raw=dict(interval='P1D',summaryTimestampLabel='endPeriod',headers=[{'name':x} for x in ['DATE','BID','ASK','MID_PRICE','TRDPRC_1']],data=[['2026-09-04',1.,2.,1.5,None]])
        q=parse_daily(raw,'KNOWN_RIC')[0]
        self.assertEqual(q['precision'],'daily');self.assertIsNone(q['source_timestamp']);self.assertIsNone(q['available_at'])
        self.assertEqual(mid(q),1.5);self.assertIsNone(q['trade'])

    def test_inconsistent_vendor_mid_rejected(self):
        raw=dict(interval='P1D',summaryTimestampLabel='endPeriod',headers=[{'name':x} for x in ['DATE','BID','ASK','MID_PRICE']],data=[['2026-09-04',1.,2.,3.]])
        self.assertIsNone(mid(parse_daily(raw,'KNOWN_RIC')[0]))

    def test_wrong_bar_interval_or_label_rejected(self):
        with self.assertRaises(ValueError): parse_daily({'interval':'PT1H','summaryTimestampLabel':'startPeriod'},'ID')

    def test_date_only_dividend_not_backdated(self):
        d=parse_dividends([{'Dividend Ex Date':'2026-08-10','Dividend Pay Date':'2026-08-13','Dividend Announcement Date':'2026-07-30','Gross Dividend Amount':.27}])[0]
        self.assertEqual(d['announced_at'],'2026-07-31T00:00:00-04:00')

    def test_first_observation_cannot_be_used_before_publication(self):
        cfg,data=fixture()
        row(data,'SHORT1','2026-08-28')['available_at']='2026-09-01T00:00:00-04:00'
        self.assertIsNone(short_call(market(cfg,data),'2026-08-31')[0])

    def test_duplicate_observations_rejected(self):
        cfg,data=fixture();data['options'].append(deepcopy(data['options'][0]))
        with self.assertRaises(ValueError): market(cfg,data)

    def test_no_real_label_no_public_audit(self):
        cfg,data=fixture()
        with self.assertRaises(ValueError): audit_dataset(data,cfg)

    def test_audit_does_not_accept_missing_terms_or_dividends(self):
        # Artificial test ONLY: explicit caller test of provenance validation.
        cfg,data=fixture();data['metadata'].update(source='LSEG',synthetic=False)
        audit=audit_dataset(data,cfg)
        self.assertFalse(audit['ready'])
        self.assertTrue(any('contract terms' in s for s in audit['blocking_issues']))
        self.assertTrue(any('dividend' in s for s in audit['blocking_issues']))

    def test_delta_expiry_and_tie_break_rules(self):
        cfg,data=fixture();cfg=replace(cfg,long_mode='historical delta')
        row(data,'LONG','2026-08-28').update(delta=.8,delta_source='historical')
        c=deepcopy(data['contracts'][0]);c.update(id='LONG2',strike=70)
        data['contracts'].append(c)
        q=deepcopy(row(data,'LONG','2026-08-28'));q['id']='LONG2';data['options'].append(q)
        self.assertEqual(long_call(market(cfg,data),'2026-08-31')[0]['id'],'LONG2')

    def test_invalid_delta_unavailable_exposure(self):
        from .engine import run
        cfg,data=fixture()
        for q in data['options']: q.update(delta=2,delta_source='historical')
        result=run(data,cfg,allow_test=True)
        self.assertIsNone(result['ledger'][0]['delta_dollar'])

    def test_nearer_eligible_expiry_wins_before_strike(self):
        cfg,data=fixture()
        c=deepcopy(data['contracts'][0]);c.update(id='NEARER',strike=70,expiry='2027-11-19',last_trade_date='2027-11-19')
        data['contracts'].append(c)
        q=deepcopy(row(data,'LONG','2026-08-28'));q['id']='NEARER';data['options'].append(q)
        self.assertEqual(long_call(market(cfg,data),'2026-08-31')[0]['id'],'NEARER')

    def test_blank_csv_is_header_only_not_fake_trade(self):
        self.assertEqual(csv_text([],['date','nav']),'date,nav\n')

    def test_deterministic_blocked_build(self):
        import shutil
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix='pmcc-test-') as tmp:
            dest=Path(tmp);(dest/'pmcc_backtest').mkdir()
            for name in ('page.html','audit_snapshot.json'):
                shutil.copy2(root/'pmcc_backtest'/name,dest/'pmcc_backtest'/name)
            first=build(dest);before=(dest/'pmcc/results.json').read_bytes()
            second=build(dest);after=(dest/'pmcc/results.json').read_bytes()
            self.assertEqual(before,after);self.assertEqual(first,second)
            self.assertEqual(first['runs'],[]);self.assertEqual(first['status'],'blocked')
            self.assertTrue(all(w['outcome']=='not_run' for w in first['weekly_coverage']))
            self.assertEqual(len((dest/'pmcc/trades.csv').read_text().splitlines()),1)
            self.assertEqual(len((dest/'pmcc/daily_nav.csv').read_text().splitlines()),1)


if __name__=='__main__': unittest.main()
