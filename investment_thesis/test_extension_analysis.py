"""Five-year local evidence and date/price-protection regression tests."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timezone
from . import reference, ablation
from .research import analyze, outcomes
from .lecture import risk_candidates
from .extension_plan import PLAN
from .import_history import private_history_path
from .economic_probe import analyze as economics

ROOT=Path(__file__).resolve().parents[1]


class ExtensionAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frozen=reference.load(ROOT)
        cls.h=reference.history(cls.frozen['evidence'],PLAN['original_start'],PLAN['reference_end'])
        cls.d=analyze(cls.h)

    def test_baseline_maturity_and_common_prospective_cutoff(self):
        self.assertEqual(self.d['full_sample'],self.frozen['evidence']['original_full_sample'])
        for rows in self.d['rows'].values():
            self.assertTrue(all(r['outcome_date']<=PLAN['reference_end'] for r in rows if r['status']=='observed'))
            self.assertTrue(all(not r['prospective'] for r in rows))
            self.assertEqual(rows[-1]['signal_date'],PLAN['reference_end'])
            self.assertEqual(rows[-1]['status'],'unmatured')

    def test_overlap_counts_and_calendar_partitions_are_not_regime_selection(self):
        z=ablation.diagnostics(self.h,self.d)
        for t in self.d['rows']:
            flag={r['signal_date']:r for r in self.h['tickers'][t]['daily_rows']}
            mature=[flag[r['signal_date']] for r in self.d['rows'][t] if r['status']=='observed']
            self.assertEqual(z['filter_overlap'][t]['additional_exclusions_after_trend'],
                             sum(r['trend'] and not r['eligible'] for r in mature))
            self.assertEqual([r['year'] for r in z['calendar_partitions'][t]],['2023','2024','2025','2026'])
            self.assertEqual(sum(r['mature_paths'] for r in z['calendar_partitions'][t]),len(mature))

    def test_risk_budget_candidates_do_not_activate_thresholds(self):
        z=risk_candidates(self.d)
        self.assertIn('Pending',z['status'])
        self.assertTrue(all(v is None for v in PLAN['maximum_acceptable_decline_probability'].values()))
        for t,item in z['tickers'].items():
            self.assertGreaterEqual(item['conditional_mean_closing_decline'],.03)
            for s in item['scenarios']:
                self.assertAlmostEqual(s['probability_candidate'],s['expected_tail_loss_budget']/item['conditional_mean_closing_decline'])

    def test_refresh_cannot_silently_remove_private_five_year_results(self):
        from .refresh import refresh
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data=root/'investment-thesis/data';data.mkdir(parents=True)
            retained=json.dumps({'lecture_extension':{'historical':{'expanded':{'window':'fixed'}}}}).encode()
            (data/'thesis_tracker.json').write_bytes(retained)
            (data/'thesis_observations.csv').write_bytes(b'preserved observations\n')
            with patch.dict(os.environ,{},clear=True),patch('investment_thesis.refresh.build') as build:
                status=refresh(root,datetime.now(timezone.utc))
            build.assert_not_called()
            self.assertEqual(status['status'],'failed')
            self.assertIn('Fixed research summary is missing',status['reason'])
            self.assertEqual((data/'thesis_tracker.json').read_bytes(),retained)
            self.assertEqual((data/'thesis_observations.csv').read_bytes(),b'preserved observations\n')

    def test_private_real_option_evidence_is_not_alpha_or_execution(self):
        path=private_history_path(ROOT)
        if path is None:self.skipTest('Private evidence not configured')
        e=json.loads(path.read_text())['evidence'];before=deepcopy(e)
        z=economics(e)
        self.assertIsNone(z['expected_alpha']);self.assertEqual(e,before)
        self.assertEqual(z['probed_contracts'],len(e['option_probes']['results']))
        self.assertNotIn('dated_records',json.dumps(z))
        r=e['option_probes']['results'][0]
        q=next(v for v in r['dated_records'] if v['date']==r['observed_on'])
        q['BID']=None
        after=economics(e)
        self.assertEqual(after['available_metrics']['illustrations'][0]['usable_contracts'],z['available_metrics']['illustrations'][0]['usable_contracts']-1)

    def test_raw_prices_never_enter_public_download_audit(self):
        d=json.loads((ROOT/'investment-thesis/data/thesis_tracker.json').read_text())
        audit=d['lecture_extension']['historical'].get('download_audit')
        if audit is None:self.skipTest('Local output has not yet been rebuilt')
        def keys(obj):
            if isinstance(obj,dict):
                return set(obj).union(*(keys(v) for v in obj.values()))
            if isinstance(obj,list):return set().union(*(keys(v) for v in obj))
            return set()
        for key in ('dated_records','raw_records','underlying_close','selection_spot'):
            self.assertNotIn(key,keys(audit))

    def test_adjustment_audit_reconciles_exact_dated_records_without_rewriting(self):
        path=private_history_path(ROOT)
        if path is None:self.skipTest('Private evidence not configured')
        from .price_audit import analyze as price_audit
        e=json.loads(path.read_text())['evidence'];before=deepcopy(e)
        a=price_audit(e)
        self.assertEqual(e,before)
        for item in a['tickers'].values():
            for c in item['price_comparisons']:
                self.assertEqual(c['compared'],1309)
                self.assertEqual(c['differences'],0)
        q=e['probes']['adjustments']['BAC']['price_comparisons'][0]['query_id']
        e['raw_records'][q]['data'][0][2]+=1
        self.assertEqual(price_audit(e)['tickers']['BAC']['price_comparisons'][0]['differences'],1)


if __name__=='__main__':unittest.main()
