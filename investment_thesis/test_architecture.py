"""Local regression replay; earlier real dates stand in for future arrivals.

Temporary test state is never published or confused with prospective evidence.
"""
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from final_project.data_provider import digest
from . import forward_store, fixed_store, architecture, publication
from .research import outcomes
from .refresh import refresh

ROOT=Path(__file__).resolve().parents[1]


class ArchitectureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d=json.loads((ROOT/'investment-thesis/data/thesis_tracker.json').read_text())
        cls.h=json.loads((ROOT/'docs/data/historical_signals.json').read_text())
        cls.fixed=fixed_store.load(ROOT)

    def replay(self,end,start='2026-11-02'):
        h=deepcopy(self.h);h['window'].update(analysis_start=start,analysis_end=end)
        for t in h['tickers']:
            h['tickers'][t]['daily_rows']=[r for r in h['tickers'][t]['daily_rows'] if start<=r['signal_date']<=end]
        return dict(rows=outcomes(h)[1],window=h['window'],market_snapshot_sha256=digest(h))

    def test_no_private_environment_is_required_and_fixed_content_is_immutable(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{},clear=True):
            root=Path(tmp);p=root/'investment-thesis/data/fixed_research.json';p.parent.mkdir(parents=True)
            p.write_text(json.dumps(self.fixed));before=p.read_bytes()
            for source in ('', '/unavailable/private/history.json'):
                os.environ['THESIS_PRIVATE_HISTORY']=source
                d=deepcopy(self.d);x,state=architecture.assemble(root,self.h,d)
                self.assertEqual(x['historical'],self.fixed['content']['historical'])
                self.assertEqual(x['hypothetical_put_payoff'],self.fixed['content']['hypothetical_put_payoff'])
                self.assertIsNotNone(state);self.assertEqual(p.read_bytes(),before)
                self.assertEqual(x['monitoring']['frozen_reference_end'],'2026-11-23')

    def test_real_date_replay_matures_and_preserves_history_after_rolloff(self):
        ref={'evidence':{'reference_end':'2026-11-02'},'evidence_sha256':'test-cutoff-not-production'}
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{},clear=True):
            first=self.replay('2026-11-09');state,monitor=forward_store.prepare(tmp,first,ref);forward_store.write(tmp,state)
            second=self.replay('2026-11-23');new,monitor=forward_store.prepare(tmp,second,ref)
            self.assertGreater(len(new['content']['rows']['BAC']),len(state['content']['rows']['BAC']))
            self.assertEqual(new['content']['rows']['BAC'][0]['status'],'observed')
            forward_store.write(tmp,new)
            short=self.replay('2026-11-23','2026-11-16');retained,_=forward_store.prepare(tmp,short,ref)
            self.assertEqual(retained['content']['rows'],new['content']['rows'])
            forward_store.write(tmp,retained)
            repeat,_=forward_store.prepare(tmp,short,ref);self.assertEqual(repeat,retained)
            self.assertEqual(oct(forward_store.path(tmp).stat().st_mode & 0o777),'0o600')
            changed=deepcopy(second);changed['rows']['BAC'][1]['tail_event']=not changed['rows']['BAC'][1]['tail_event']
            with self.assertRaisesRegex(ValueError,'revised'):forward_store.prepare(tmp,changed,ref)
            with self.assertRaisesRegex(ValueError,'older'):forward_store.prepare(tmp,first,ref)

    def test_missing_state_does_not_silently_reset_monitor(self):
        ref={'evidence':{'reference_end':'2026-11-02'},'evidence_sha256':'test-only'}
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{},clear=True):
            with self.assertRaisesRegex(ValueError,'incomplete'):forward_store.prepare(tmp,self.replay('2026-11-23','2026-11-16'),ref)
            p=Path(tmp)/'investment-thesis/data/fixed_research.json';p.parent.mkdir(parents=True);p.write_text(json.dumps(self.fixed))
            with patch('investment_thesis.forward_store.prepare',side_effect=ValueError('coverage lost')):
                x,state=architecture.assemble(tmp,self.h,deepcopy(self.d))
            self.assertIsNone(state);self.assertTrue(x['monitoring']['coverage_lost'])
            self.assertEqual(x['historical'],self.fixed['content']['historical'])

    def test_upstream_failure_retains_public_and_private_state_and_fixed_study(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{},clear=True):
            root=Path(tmp);data=root/'investment-thesis/data';data.mkdir(parents=True)
            (data/'thesis_tracker.json').write_text(json.dumps(self.d))
            (data/'public_tracker.json').write_text(json.dumps(publication.preview_payload(self.d)))
            (data/'fixed_research.json').write_text(json.dumps(self.fixed))
            state,_=forward_store.prepare(root,self.d,self.fixed['content']['reference']);forward_store.write(root,state)
            paths=[data/'thesis_tracker.json',data/'public_tracker.json',data/'fixed_research.json',forward_store.path(root)]
            before=[p.read_bytes() for p in paths]
            with patch('investment_thesis.refresh.build') as build:
                status=refresh(root,datetime.now(timezone.utc),'failure');build.assert_not_called()
            self.assertEqual(status['status'],'failed');self.assertEqual(before,[p.read_bytes() for p in paths])

    def test_summary_has_no_paths_or_quotes_and_permission_is_pending(self):
        d=publication.preview_payload(self.d);publication.assert_summary(d)
        self.assertNotIn('rows',d);self.assertEqual(d['projection']['row_counts']['BAC'],len(self.d['rows']['BAC']))
        for key in ('BID','ASK','reference_close','dated_records','history'):
            with self.assertRaises(ValueError):publication.assert_summary({key:[]})
        self.assertFalse(publication.audit(ROOT)['license_confirmed'])
        self.assertEqual(self.fixed['content_sha256'],digest(self.fixed['content']))
        with self.assertRaises(FileExistsError):fixed_store.create(ROOT,'not-opened')

    def test_private_state_cannot_be_stored_under_website(self):
        with patch.dict(os.environ,{'THESIS_STATE_DIRECTORY':str(ROOT/'investment-thesis/private')}):
            with self.assertRaises(ValueError):forward_store.path(ROOT)


if __name__=='__main__':unittest.main()
