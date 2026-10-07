"""Synthetic regression fixtures only; never exported as market observations."""
from copy import deepcopy
from dataclasses import replace
import unittest

from .contracts import candidate_call_ric
from .data import fill,mid
from .engine import run
from .repair_coverage import event_mark
from .selection import short_call
from .test_engine import fixture,market,row

DAY='2026-09-01'
CLOSE=DAY+'T16:00:00-04:00'


def raw_event(bid=0.,ask=.02,source=DAY+'T19:59:40Z',stamp=DAY+'T19:59:45Z'):
    return dict(headers=[dict(name=k) for k in ('EVENT_TYPE','DATE_TIME','SOURCE_DATETIME','BID','ASK')],
                data=[['quote',stamp,source,bid,ask]])


def attach(data,ident='SHORT1',day=DAY):
    q=row(data,ident,day);q['bid']=None
    event=event_mark(raw_event(source=day+'T19:59:40Z',stamp=day+'T19:59:45Z'),day,day+'T16:00:00-04:00')
    event['raw_sha256']='synthetic-unit-fixture-only';q['valuation_quote']=event
    data['metadata']['closing_execution_quote_policy']='daily_bbo_then_last_event_final_60_seconds'
    return q


class RepairTests(unittest.TestCase):
    def test_actual_zero_bid_event_accepted_null_not_zero(self):
        self.assertEqual(mid(event_mark(raw_event(),DAY,CLOSE)),.01)
        self.assertIsNone(event_mark(raw_event(bid=None),DAY,CLOSE))

    def test_source_or_event_future_rejected(self):
        for kwargs in ({'source':DAY+'T20:00:01Z'},{'stamp':DAY+'T20:00:01Z'}):
            self.assertIsNone(event_mark(raw_event(**kwargs),DAY,CLOSE))

    def test_old_source_even_with_recent_event_rejected(self):
        self.assertIsNone(event_mark(raw_event(source=DAY+'T19:50:00Z'),DAY,CLOSE))

    def test_prior_day_or_timezone_unknown_rejected(self):
        for source in ('2026-08-31T19:59:40Z',DAY+'T19:59:40',None):
            self.assertIsNone(event_mark(raw_event(source=source),DAY,CLOSE))

    def test_later_invalid_event_does_not_reuse_earlier_valid_quote(self):
        r=raw_event();r['data']+=raw_event(bid=None,stamp=DAY+'T19:59:59Z')['data']
        self.assertIsNone(event_mark(r,DAY,CLOSE))

    def test_later_unknown_source_not_replaced_by_earlier_quote(self):
        r=raw_event();r['data']+=raw_event(source=None,stamp=DAY+'T19:59:59Z')['data']
        self.assertIsNone(event_mark(r,DAY,CLOSE))

    def test_crossed_and_negative_events_rejected(self):
        for b,a in ((.03,.02),(-.01,.02),(0.,0.)):
            self.assertIsNone(event_mark(raw_event(bid=b,ask=a),DAY,CLOSE))

    def test_event_does_not_overwrite_raw_daily_fields(self):
        cfg,d=fixture();q=attach(d);m=market(cfg,d)
        self.assertEqual(m.mark('SHORT1',DAY),.01)
        self.assertIsNone(q['bid']);self.assertIsNone(mid(q))
        self.assertEqual(fill(m.execution_quote('SHORT1',DAY),'BUY','quoted_side'),.02)
        self.assertEqual(fill(m.execution_quote('SHORT1',DAY),'BUY','midpoint'),.01)

    def test_daily_quote_preferred(self):
        cfg,d=fixture();q=attach(d);q.update(bid=.9,ask=1.1)
        self.assertEqual(market(cfg,d).mark('SHORT1',DAY),1.)

    def test_bad_daily_consistency_not_masked(self):
        cfg,d=fixture();q=attach(d);q['quote_inconsistent']=True
        self.assertIsNone(market(cfg,d).mark('SHORT1',DAY))

    def test_event_gate_rechecks_timestamp_and_hash(self):
        for key,value in [('date','2026-08-31'),('source_timestamp',DAY+'T20:01:00Z'),('raw_sha256',None)]:
            cfg,d=fixture();q=attach(d);q['valuation_quote'][key]=value
            self.assertIsNone(market(cfg,d).mark('SHORT1',DAY))

    def test_legacy_valuation_only_quote_never_fills(self):
        cfg,d=fixture();q=attach(d);q['valuation_quote']['valuation_only']=True
        m=market(cfg,d);self.assertEqual(m.mark('SHORT1',DAY),.01)
        self.assertIsNone(m.execution_quote('SHORT1',DAY))

    def test_event_zero_bid_does_not_permit_new_short(self):
        cfg,d=fixture();attach(d,day=cfg.start)
        result=run(d,cfg,allow_test=True)
        self.assertEqual(result['weekly_coverage'][0]['reason'],'SHORT_BID_NOT_POSITIVE')

    def test_strict_stops_observed_resumes_and_keeps_hole(self):
        cfg,d=fixture();row(d,'SHORT1',DAY)['bid']=None
        result=run(d,cfg,allow_test=True);ledger=result['ledger']
        gap=next(i for i,r in enumerate(ledger) if r['date']==DAY)
        self.assertIsNone(result['metrics']['max_drawdown'])
        self.assertEqual(result['metrics']['valuation_gap_dates'],[DAY])
        self.assertTrue(all(r['drawdown'] is None for r in ledger[gap:]))
        self.assertIsNone(ledger[gap]['observed_drawdown'])
        self.assertIsNotNone(ledger[gap+1]['observed_drawdown'])
        self.assertTrue(result['metrics']['observed_drawdown_is_lower_bound'])

    def test_complete_paths_match_full_mdd(self):
        cfg,d=fixture();r=run(d,cfg,allow_test=True)
        self.assertEqual(r['metrics']['max_drawdown'],r['metrics']['max_observed_drawdown'])
        self.assertTrue(all(x['drawdown']==x['observed_drawdown'] for x in r['ledger']))
        self.assertFalse(r['metrics']['observed_drawdown_is_lower_bound'])

    def test_observed_magnitude_lower_bound_not_full_mdd(self):
        cfg,d=fixture();row(d,'LONG',DAY).update(bid=1.,ask=3.)
        full=run(d,cfg,allow_test=True)
        row(d,'LONG',DAY)['bid']=None
        partial=run(d,cfg,allow_test=True)
        self.assertGreater(abs(full['metrics']['max_drawdown']),abs(partial['metrics']['max_observed_drawdown']))

    def test_expiry_after_sample_end_allowed_and_terminal_closed(self):
        cfg,d=fixture();cfg=replace(cfg,end='2026-09-02')
        r=run(d,cfg,allow_test=True)
        self.assertEqual(r['weekly_coverage'][0]['friday_series'],'2026-09-04')
        self.assertTrue(r['metrics']['terminal_resolved'])
        self.assertTrue(any(e['leg']=='SHORT_CALL' and e['action']=='BUY' and e['date']==cfg.end for e in r['blotter']))

    def test_new_candidate_ric_not_membership_without_historical_evidence(self):
        cfg,d=fixture();d['options']=[q for q in d['options'] if q['id']!='SHORT1' or q['date']>=cfg.start]
        self.assertIsNone(short_call(market(cfg,d),cfg.start)[0])
        self.assertEqual(candidate_call_ric('2026-10-02',360),'AAPLJ022636000.U^J26')

    def test_missing_coverage_not_market_absence(self):
        cfg,d=fixture();d['contracts'][1]['strike']=100
        self.assertEqual(short_call(market(cfg,d),cfg.start)[1],'CANDIDATE_DATA_NOT_COVERED')
        d['metadata']['short_universe_coverage']=[dict(expiry='2026-09-04',historical_contracts=1,signal_observed_contracts=1,complete=False)]
        self.assertEqual(short_call(market(cfg,d),cfg.start)[1],'NO_ELIGIBLE_CONTRACT_IN_PARTIAL_OBSERVED_UNIVERSE')
        d['metadata']['short_universe_coverage'][0]['complete']=True
        self.assertEqual(short_call(market(cfg,d),cfg.start)[1],'NO_ELIGIBLE_CONTRACT_IN_VERIFIED_UNIVERSE')


if __name__=='__main__':unittest.main()
