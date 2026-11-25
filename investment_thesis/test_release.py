"""Offline release checks; temporary replay outputs never become market evidence."""
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from final_project.data_provider import digest
from . import architecture, fixed_store, forward_store, publication, research
from .refresh import refresh

ROOT = Path(__file__).resolve().parents[1]


class ReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixed = fixed_store.load(ROOT)
        cls.h = json.loads((ROOT/'docs/data/historical_signals.json').read_text())
        cls.d = json.loads((ROOT/'investment-thesis/data/thesis_tracker.json').read_text())

    def stage(self, root):
        data = root/'investment-thesis/data'; data.mkdir(parents=True)
        public = ROOT/'investment-thesis/data'/fixed_store.PUBLIC_NAME
        (data/fixed_store.PUBLIC_NAME).write_bytes(public.read_bytes())
        for name in ('historical_signals.json', 'market_snapshot.json'):
            p = root/'docs/data'/name; p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes((ROOT/'docs/data'/name).read_bytes())
        return data

    def test_portable_fixed_summary_restores_exact_original_without_private_files(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            root=Path(tmp); data=self.stage(root); p=data/fixed_store.PUBLIC_NAME
            before=p.read_bytes(); publication.assert_summary(json.loads(before))
            self.assertFalse((data/fixed_store.NAME).exists())
            self.assertFalse((data/'reference_2026-11-23.json').exists())
            self.assertEqual(fixed_store.load(root),self.fixed)
            self.assertEqual(fixed_store.prepare_release(root),p)
            self.assertEqual(p.read_bytes(),before)
            d=deepcopy(self.d); x,_=architecture.assemble(root,self.h,d)
            for k in ('historical','hypothetical_put_payoff','acceptable_risk_candidates','option_economics'):
                self.assertEqual(x[k],self.fixed['content'][k])

    def test_fixed_release_integrity_and_forbidden_prices_fail_closed(self):
        for change in (lambda z:z['content'].update(version=99),
                       lambda z:z.update(BID=1.0),
                       lambda z:z.update(source_content_sha256='wrong')):
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp); p=self.stage(root)/fixed_store.PUBLIC_NAME
                d=json.loads(p.read_text()); change(d); p.write_text(json.dumps(d))
                with self.assertRaises(ValueError):fixed_store.load(root)

    def test_original_failure_date_and_weekend_boundaries_are_supported(self):
        for start,first in [('2023-11-23','2023-11-24'),('2023-11-25','2023-11-27')]:
            h=deepcopy(self.h); h['window']['analysis_start']=start
            for item in h['tickers'].values():
                item['daily_rows']=[r for r in item['daily_rows'] if r['signal_date']>=start]
            dates,rows=research.outcomes(h)
            self.assertEqual(dates[0],first); self.assertNotIn(start,dates)
            self.assertEqual(rows['BAC'][0]['signal_date'],first)

    def test_later_real_session_changes_daily_tracker_not_fixed_research(self):
        earlier=deepcopy(self.h); earlier['window']['analysis_end']='2026-11-20'
        for item in earlier['tickers'].values():
            item['daily_rows']=[r for r in item['daily_rows'] if r['signal_date']<='2026-11-20']
        before=digest(self.fixed)
        a=research.analyze(earlier); b=research.analyze(self.h)
        self.assertLess(a['window']['analysis_end'],b['window']['analysis_end'])
        self.assertLess(len(a['rows']['BAC']),len(b['rows']['BAC']))
        self.assertEqual(digest(self.fixed),before)

    def test_corrupt_forward_history_is_not_reset_and_does_not_block_tracker(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{},clear=True):
            root=Path(tmp); self.stage(root); p=forward_store.path(root)
            p.parent.mkdir(); p.write_text('incomplete private JSON')
            d=deepcopy(self.d); before=deepcopy(d['rolling'])
            x,state=architecture.assemble(root,self.h,d)
            self.assertIsNone(state); self.assertTrue(x['monitoring']['coverage_lost'])
            self.assertEqual(d['rolling'],before)
            self.assertEqual(x['historical'],self.fixed['content']['historical'])
            self.assertEqual(p.read_text(),'incomplete private JSON')

    def test_unavailable_forward_backup_does_not_prevent_daily_refresh(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{},clear=True):
            root=Path(tmp); self.stage(root)
            with (patch('investment_thesis.forward_store.path',side_effect=PermissionError('private test')),
                 patch('investment_thesis.refresh.build',return_value=self.d) as build,
                 patch('investment_thesis.refresh.check') as check):
                status=refresh(root,datetime.now(timezone.utc))
            build.assert_called_once(); check.assert_called_once()
            self.assertEqual(status['status'],'success')
            self.assertIn('storage is unavailable',status['forward_storage_warning'])
            self.assertNotIn('private test',json.dumps(status))

    def test_unwritable_forward_save_does_not_discard_daily_results_or_print_findings(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{},clear=True):
            root=Path(tmp); data=self.stage(root); frozen=(data/fixed_store.PUBLIC_NAME).read_bytes()
            output=io.StringIO()
            with (patch('investment_thesis.forward_store.write',side_effect=PermissionError('private test')),
                 patch('investment_thesis.reliability.analyze',return_value=self.d['reliability']),
                 redirect_stdout(output)):
                result=research.build(root,datetime.now(timezone.utc))
            self.assertIn('could not be saved',result['forward_storage_warning'])
            actual=json.loads((data/'thesis_tracker.json').read_text())
            self.assertEqual(actual['full_sample'],self.d['full_sample'])
            self.assertEqual(actual['rolling'],self.d['rolling'])
            self.assertEqual((data/fixed_store.PUBLIC_NAME).read_bytes(),frozen)
            publication.assert_summary(json.loads((data/'public_tracker.json').read_text()))
            self.assertNotIn('baseline_downside_benefit',output.getvalue())
            self.assertNotIn('private test',output.getvalue())

    def test_upstream_failure_keeps_all_valid_results_and_explains_stop(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{},clear=True):
            root=Path(tmp); data=self.stage(root)
            for name in ('thesis_tracker.json','public_tracker.json','thesis_observations.csv'):
                (data/name).write_bytes((ROOT/'investment-thesis/data'/name).read_bytes())
            before={p.name:p.read_bytes() for p in data.iterdir()}
            with patch('investment_thesis.refresh.build') as build:
                status=refresh(root,datetime.now(timezone.utc),'failure')
            build.assert_not_called(); self.assertEqual(status['status'],'failed')
            self.assertIn('Upstream nightly workflow did not succeed',status['reason'])
            self.assertEqual(status['evidence_generated_at'],self.d['generated_at'])
            for name,value in before.items():self.assertEqual((data/name).read_bytes(),value)

    def test_publication_stays_closed_and_monitoring_is_not_a_prerequisite(self):
        # This is a permission-gate fixture, never a declaration of real rights.
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); p=root/'investment_thesis/publication_permission.json'
            p.parent.mkdir(); p.write_text('{"status":"pending"}')
            self.assertFalse(publication.audit(root)['publication_allowed'])
            approval=dict(status='confirmed',safe_hosting_plan_verified=True,
                          verified_by='unit-test-only',evidence_reference='not-a-real-license',
                          scopes={k:True for k in ('historical_aggregate_statistics','daily_aggregate_charts','prospective_aggregate_charts')})
            p.write_text(json.dumps(approval))
            self.assertTrue(publication.audit(root)['publication_allowed'])
            self.assertFalse((root/'.thesis-state').exists())
        html=(ROOT/'investment-thesis/index.html').read_text()
        self.assertIn('Experimental feature.',html)
        self.assertIn('not a prerequisite for this thesis assignment',html)
        self.assertNotIn('href="data/thesis_observations.csv"',html)
        workflow=(ROOT/'.github/workflows/investment-thesis.yaml').read_text()
        self.assertIn('investment_thesis.test_release',workflow)
        self.assertNotIn('investment_thesis.test_lecture -q',workflow)
        self.assertNotIn('final_project.run',workflow)
        self.assertNotIn('workflow_dispatch --',workflow)

    def test_course_authorization_does_not_claim_vendor_confirmation(self):
        approval=json.loads((ROOT/'investment_thesis/publication_permission.json').read_text())
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); p=root/'investment_thesis/publication_permission.json'; p.parent.mkdir()
            p.write_text(json.dumps(approval))
            result=publication.audit(root)
            self.assertTrue(result['publication_allowed'])
            self.assertFalse(result['license_confirmed'])
            for key,value in [('owner_authorized',False),('aggregate_only',False),('raw_downloads',True)]:
                changed=deepcopy(approval); changed['course_publication'][key]=value
                p.write_text(json.dumps(changed))
                self.assertFalse(publication.audit(root)['publication_allowed'])

    def test_aggregate_only_checkout_retains_timestamps_on_upstream_failure(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{},clear=True):
            root=Path(tmp); data=self.stage(root)
            content=(ROOT/'investment-thesis/data/public_tracker.json').read_bytes()
            (data/'public_tracker.json').write_bytes(content)
            self.assertFalse((data/'thesis_tracker.json').exists())
            with patch('investment_thesis.refresh.build') as build:
                status=refresh(root,datetime.now(timezone.utc),'failure')
            build.assert_not_called()
            self.assertEqual(status['evidence_generated_at'],json.loads(content)['generated_at'])
            self.assertEqual((data/'public_tracker.json').read_bytes(),content)
            self.assertEqual(status['status'],'failed')


if __name__=='__main__':unittest.main()
