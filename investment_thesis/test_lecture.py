"""Local research tests. Artificial prospective fixtures are never published."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import statistics
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from final_project.data_provider import digest
from final_project.validate_publication import equivalent_observations
from . import reference, monitoring, ablation
from .lecture import overlap_audit
from .extension_plan import PLAN, REFERENCE_NAME
from .reliability import TICKERS, nonoverlap_dates, log_bound
from .research import analyze, outcomes
from .import_history import import_download, private_history_path

ROOT=Path(__file__).resolve().parents[1]


class LectureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d=json.loads((ROOT/'investment-thesis/data/thesis_tracker.json').read_text())
        cls.ref=reference.load(ROOT)
        cls.h=reference.history(cls.ref['evidence'],PLAN['original_start'],PLAN['reference_end'])

    def test_classroom_example_matches_lower_tail_not_own_trades(self):
        c=monitoring.classroom_example()
        self.assertAlmostEqual(c['bound'],.8153726976,places=12)
        self.assertAlmostEqual(c['bound'],math.exp(log_bound(10,.4,.1,'upper')))
        self.assertEqual(c['advisory'],'Continue monitoring')
        self.assertFalse(c['own_trade_results']);self.assertIn('not independently verified',c['source'])

    def test_advisory_boundaries(self):
        for b,status in [(None,'Awaiting Data'),(1,'Continue monitoring'),(.5,'Review'),(.25,'Warning'),(.1,'Pause and investigate'),(0,'Pause and investigate')]:
            self.assertEqual(monitoring.advisory(b),status)
        for bad in [-1,1.1,float('nan')]:
            with self.assertRaises(ValueError):monitoring.advisory(bad)

    def test_monitor_uses_upper_tail_and_never_resets_baseline(self):
        z=monitoring.assessment(100,40,.2,.3)
        self.assertAlmostEqual(z['upper_tail_bound'],math.exp(log_bound(100,.2,.2,'upper')))
        self.assertEqual(z['regime'],'Performance worse than expected')
        self.assertEqual(monitoring.assessment(100,10,.2,.3)['upper_tail_bound'],1.)
        self.assertEqual(monitoring.assessment(100,10,.2,.3)['regime'],'Performance better than expected')
        self.assertEqual(monitoring.assessment(100,20,.2,.3)['regime'],'Performance consistent with historical expectations')
        within_limit=monitoring.assessment(1000,400,.2,.5)
        self.assertEqual(within_limit['regime'],'Performance worse than expected')
        self.assertFalse(within_limit['joint_deterioration_alert'])
        self.assertFalse(within_limit['acceptable_limit_breached'])
        pending=monitoring.assessment(100,40,.2)
        self.assertEqual(pending['expected_decline_probability'],.2)
        self.assertIsNone(pending['maximum_acceptable_decline_probability'])
        self.assertEqual(pending['regime'],'Insufficient evidence')
        self.assertIn('Pending',pending['status'])

    def test_empty_small_degenerate_and_underflow_samples(self):
        z=monitoring.assessment(0,0,.2)
        self.assertIsNone(z['observed_decline_frequency']);self.assertIsNone(z['upper_tail_bound'])
        self.assertIn('Insufficient',monitoring.assessment(19,10,.2,.3)['status'])
        self.assertIsNone(monitoring.assessment(100,1,0.)['upper_tail_bound'])
        z=monitoring.assessment(100000,100000,.01,.1)
        self.assertEqual(z['upper_tail_bound'],0.)
        self.assertLess(z['log_upper_tail_bound'],-100000) # exact log retained; UI uses a floor
        for args in [(-1,0,.2),(10,11,.2),(10,2,.2,2)]:
            with self.assertRaises(ValueError):monitoring.assessment(*args)

    def test_frozen_original_reproduces_and_cannot_be_overwritten(self):
        r=analyze(self.h)
        self.assertTrue(equivalent_observations(r['full_sample'],self.ref['evidence']['original_full_sample']))
        with self.assertRaises(FileExistsError):reference.freeze(ROOT,datetime.now(timezone.utc))
        if self.d['window']==r['window']:
            self.assertEqual(self.d['reliability'],self.ref['evidence']['original_reliability'])
            self.assertEqual(self.d['rolling'],r['rolling'])

    def test_frozen_hash_tampering_and_missing_reference_fail_closed(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):reference.load(tmp)
            p=Path(tmp)/'investment-thesis/data'/REFERENCE_NAME;p.parent.mkdir(parents=True)
            changed=deepcopy(self.ref);changed['evidence']['tickers']['BAC']['history'][0]['close']*=2
            p.write_text(json.dumps(changed))
            with self.assertRaises(ValueError):reference.load(tmp)

    def test_overlap_revision_or_missing_price_blocks_comparison_not_overwrites(self):
        e=self.ref['evidence'];before=deepcopy(e);other=deepcopy(e)
        self.assertTrue(all(not v['missing_dates'] and not v['conflicting_dates'] for v in overlap_audit(e,other).values()))
        other['tickers']['BAC']['history'][0]['close']*=2
        other['tickers']['F']['history'][1]['close']=None
        a=overlap_audit(e,other)
        self.assertEqual(len(a['BAC']['conflicting_dates']),1)
        self.assertEqual(len(a['F']['missing_dates']),1);self.assertEqual(e,before)

    def test_import_checks_reference_and_never_copies_private_data_into_site(self):
        with TemporaryDirectory() as tmp, TemporaryDirectory() as private:
            p=Path(tmp)/'investment-thesis/data'/REFERENCE_NAME;p.parent.mkdir(parents=True)
            p.write_text(json.dumps(self.ref))
            source=Path(private)/'evidence.json';source.write_text('{}');source.chmod(0o600)
            wrapper={'evidence':{'metadata':{'frozen_reference_sha256':self.ref['evidence_sha256']}}}
            with patch('investment_thesis.download_history.load_download',return_value=wrapper):
                target=import_download(source,tmp);before=target.read_bytes()
                self.assertEqual(import_download(source,tmp),target)
                self.assertEqual(target.read_bytes(),before)
                with self.assertRaises(ValueError):import_download(p,tmp)
            with patch('investment_thesis.download_history.load_download',return_value={'evidence':{'metadata':{'frozen_reference_sha256':'wrong'}}}):
                with self.assertRaises(ValueError):import_download(source,tmp)
            self.assertFalse((p.parent/'historical_download.json').exists())

    def test_manual_workflow_is_read_only_no_order_or_publication_step(self):
        workflow=(ROOT/'.github/workflows/thesis-history-download.yaml').read_text()
        self.assertIn('workflow_dispatch:',workflow);self.assertNotIn('schedule:',workflow)
        self.assertIn('contents: read',workflow);self.assertIn('persist-credentials: false',workflow)
        self.assertIn('cancel-in-progress: false',workflow);self.assertIn('confirm_live_download',workflow)
        for secret in ('LSEG_APP_KEY','LSEG_USERNAME','LSEG_PASSWORD'):
            self.assertIn('${{ secrets.'+secret+' }}',workflow)
        for forbidden in ('contents: write','pages: write','git push','git commit','open_orders.json','final_project.run'):
            self.assertNotIn(forbidden,workflow)
        self.assertIn('artifacts/thesis-history/historical_download.encrypted.json',workflow)
        self.assertIn("github.event_name == 'workflow_dispatch'",workflow)
        self.assertNotIn('refs/heads/main',workflow)

    def test_ablation_real_counts_signs_and_means_reproduce_from_raw_outcomes(self):
        _,rows=outcomes(self.h);a=self.d['lecture_extension']['historical']['original_ablation']
        for mode in ('daily','nonoverlap'):
            dates={r['signal_date'] for r in rows['BAC']} if mode=='daily' else set(nonoverlap_dates([r['signal_date'] for r in rows['BAC']]))
            for t in TICKERS:
                flags={r['signal_date']:r for r in self.h['tickers'][t]['daily_rows']}
                all_rows=[r for r in rows[t] if r['status']=='observed' and r['signal_date'] in dates]
                for arm in ablation.ARMS:
                    selected=[r for r in all_rows if arm=='none' or flags[r['signal_date']]['eligible' if arm=='combined' else arm]]
                    s=a['samples'][mode]['tickers'][t][arm]
                    self.assertEqual(s['n'],len(selected));self.assertEqual(s['events'],sum(r['tail_event'] for r in selected))
                    self.assertAlmostEqual(s['mean_adverse'],statistics.mean(r['adverse_move'] for r in selected))
                    self.assertAlmostEqual(s['frequency_difference'],statistics.mean(r['tail_event'] for r in all_rows)-s['frequency'])
                    self.assertAlmostEqual(s['exclusion_rate'],1-len(selected)/len(all_rows))
                    self.assertEqual([b['block_length'] for b in s['sensitivity']],[7,14,28] if mode=='daily' else [1,2,4])

    def test_combined_original_bootstrap_is_preserved_exactly(self):
        a=self.d['lecture_extension']['historical']['original_ablation']
        for mode in ('daily','nonoverlap'):
            for t in TICKERS:
                s=a['samples'][mode]['tickers'][t]['combined']
                for item in s['sensitivity']:
                    old=next(x for x in self.ref['evidence']['original_reliability']['samples'][mode]['sensitivity'] if x['block_length']==item['block_length'])['tickers'][t]
                    for key in ('frequency_difference','downside_difference'):self.assertEqual(item[key],old[key])

    def test_every_arm_uses_same_rows_seed_plan_and_no_outcome_mutation(self):
        d=analyze(self.h);d['reliability']=self.ref['evidence']['original_reliability']
        before=deepcopy(d);seen=[]
        def fake(changed,reps):
            seen.append(changed);self.assertEqual(reps,5000)
            return d['reliability']
        with patch('investment_thesis.ablation.reliability',side_effect=fake):ablation.analyze(self.h,d)
        self.assertEqual(len(seen),3) # combined reuses validated original
        for arm in seen:
            for t in TICKERS:
                for left,right in zip(arm['rows'][t],d['rows'][t]):
                    self.assertEqual({k:v for k,v in left.items() if k!='cohort'},{k:v for k,v in right.items() if k!='cohort'})
        self.assertEqual(d,before)

    def future_fixture(self):
        d=deepcopy(self.d);d['window']['analysis_end']='2026-12-10'
        d['rows']={t:[dict(signal_date='2026-11-23',outcome_date='2026-12-02',cohort='pass',status='observed',tail_event=True),
                      dict(signal_date='2026-11-24',outcome_date='2026-12-03',cohort='pass',status='observed',tail_event=True),
                      dict(signal_date='2026-11-25',outcome_date='2026-12-04',cohort='fail',status='observed',tail_event=False),
                      dict(signal_date='2026-11-27',outcome_date='2026-12-07',cohort='pass',status='missing_path',tail_event=None),
                      dict(signal_date='2026-12-04',outcome_date='2026-12-14',cohort='pass',status='unmatured',tail_event=None)] for t in TICKERS}
        return d

    def test_prospective_excludes_reference_day_unmatured_and_missing_with_gap(self):
        d=self.future_fixture();before=deepcopy(d);m=monitoring.analyze(d,self.ref)
        for t in TICKERS:
            filtered=m['samples']['daily'][t]['filtered'];all_=m['samples']['daily'][t]['unfiltered']
            self.assertEqual(filtered['current']['n'],1);self.assertEqual(all_['current']['n'],2)
            self.assertEqual(all_['current']['events'],1)
            self.assertEqual(filtered['pending_signal_dates'],['2026-12-04'])
            self.assertEqual(filtered['missing_path_signal_dates'],['2026-11-27'])
            self.assertTrue(filtered['curve'][-1]['gap']);self.assertIsNone(filtered['curve'][-1]['upper_tail_bound'])
            self.assertEqual(filtered['current']['expected_decline_probability'],self.ref['evidence']['original_reliability']['samples']['daily']['tickers'][t]['groups']['filtered']['frequency'])
        self.assertEqual(d,before)

    def test_lost_prospective_source_coverage_stays_blocked(self):
        d=self.future_fixture();d['window']['analysis_start']='2026-11-24'
        self.assertFalse(monitoring.analyze(d,self.ref)['coverage_lost'])
        d['window']['analysis_start']='2026-11-25'
        m=monitoring.analyze(d,self.ref)
        self.assertTrue(m['coverage_lost']);z=m['samples']['daily']['BAC']['filtered']['current']
        self.assertIsNone(z['upper_tail_bound']);self.assertIn('rolled off',z['status'])

    def test_forward_empty_not_zero_risk_and_unimported_extension_pending(self):
        retrospective=analyze(self.h);m=monitoring.analyze(retrospective,self.ref)
        x=self.d['lecture_extension']
        from .fixed_store import load as fixed_load
        fixed=fixed_load(ROOT)
        if fixed:self.assertEqual(x['historical'],fixed['content']['historical'])
        elif private_history_path(ROOT) is None:self.assertIsNone(x['historical']['expanded'])
        for mode in ('daily','nonoverlap'):
            for t in TICKERS:
                for g in ('filtered','unfiltered'):
                    s=m['samples'][mode][t][g]
                    self.assertEqual(s['current']['n'],0);self.assertIsNone(s['current']['observed_decline_frequency'])
                    self.assertEqual(s['curve'],[])
        if fixed:self.assertEqual(x['option_economics'],fixed['content']['option_economics'])
        elif private_history_path(ROOT) is None:self.assertIsNone(x['option_economics']['available_metrics'])


if __name__=='__main__':unittest.main()
