"""Identity/evidence regressions; synthetic fixtures are never published prices."""
from copy import deepcopy
from pathlib import Path
import json
import tempfile
import unittest

from .calendar import Calendar
from .contracts import parse_ric, resolve
from .build import public_provenance, publish, csv_text
from .engine import run
from .test_engine import fixture, market, row


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.cal=Calendar('2026-07-06','2026-09-30')

    def test_calls_and_puts_use_calendar_expired_suffix(self):
        for ric,cp in [('AAPLG102631000.U^G26','C'),('AAPLS102631000.U^G26','P')]:
            c=parse_ric(ric)
            self.assertEqual((c['cp'],c['strike'],c['expiry']),(cp,310.,'2026-07-10'))
        with self.assertRaises(ValueError):parse_ric('AAPLS102631000.U^S26')

    def test_zero_padded_day_and_suffix_checks(self):
        self.assertEqual(parse_ric('AAPLH072632000.U^H26')['expiry'],'2026-08-07')
        self.assertEqual(parse_ric('AAPLI042632000.U^I26')['expiry'],'2026-09-04')
        for ric in ['AAPLH72632000.U^H26','AAPLH072632000.U^G26','AAPLH072632000.U^H25']:
            with self.assertRaises(ValueError):parse_ric(ric)

    def test_adjusted_mini_foreign_roots_excluded(self):
        for ric in ['AAPL1G102631000.U^G26','AAPL7G102631000.U^G26','AAPLG102631000.FO']:
            with self.assertRaisesRegex(ValueError,'NONSTANDARD'):parse_ric(ric)

    def test_put_excluded_from_call_strategy(self):
        with self.assertRaisesRegex(ValueError,'PUT_OUTSIDE'):resolve('AAPLS102631000.U^G26',self.cal)

    def test_assumption_never_becomes_vendor_verification(self):
        c=resolve('AAPLG102631000.U^G26',self.cal)
        self.assertFalse(c['standard_verified']);self.assertTrue(c['standard_assumption_allowed'])
        self.assertEqual(c['terms_status'],'research assumption')
        self.assertTrue(c['terms_source']);self.assertIsNone(c['terms_verified_at'])
        self.assertEqual(c['known_from'],'9999-12-31')
        self.assertIsNone(c['last_observed_quote_date'])

    def test_last_quote_is_not_last_trading_date(self):
        c=resolve('AAPLG102631000.U^G26',self.cal)
        c.update(last_observed_quote_date='2026-07-08')
        self.assertEqual(c['expiry'],'2026-07-10')
        self.assertEqual(c['scheduled_last_trading_date'],'2026-07-10')
        self.assertNotEqual(c['last_observed_quote_date'],c['scheduled_last_trading_date'])

    def test_holiday_expiry_derivation(self):
        c=resolve('AAPLG032631000.U^G26',self.cal)
        self.assertEqual(c['scheduled_last_trading_date'],'2026-07-02')
        self.assertEqual(c['series_friday'],'2026-07-03')

    def test_conflicting_strike_expiry_or_adjustment_excluded(self):
        for old in [dict(strike=315),dict(expiry='2026-07-17')]:
            with self.assertRaisesRegex(ValueError,'CONFLICT'):resolve('AAPLG102631000.U^G26',self.cal,existing=old)
        with self.assertRaisesRegex(ValueError,'UNRESOLVED_CORPORATE'):
            resolve('AAPLG102631000.U^G26',self.cal,corporate_action_review={'unresolved_adjustment_event':True})

    def test_description_conflicts_excluded(self):
        d=dict(LotSize=100,Currency='USD',ContractType='Standard',ExerciseStyle='A',UnderlyingQuoteRIC=['AAPL.O'],CallPutOption='Call',StrikeMultiplier=1)
        self.assertFalse(resolve('AAPLG102631000.U^G26',self.cal,description=d)['standard_verified'])
        for k,v in [('LotSize',10),('CallPutOption','Put'),('StrikeMultiplier',10),('UnderlyingQuoteRIC',['MSFT.O'])]:
            with self.assertRaises(ValueError):resolve('AAPLG102631000.U^G26',self.cal,description=d|{k:v})

    def test_only_explicit_supported_assumptions_pass(self):
        cfg,data=fixture();c=data['contracts'][0]
        c.update(standard_verified=False,standard_assumption_allowed=True,terms_status='research assumption',terms_source=['OCC specification'],risk_flags=[])
        self.assertTrue(market(cfg,data).standard(c))
        for change in [dict(terms_source=[]),dict(risk_flags=['possible adjustment']),dict(standard_assumption_allowed=False),dict(terms_status='unknown')]:
            self.assertFalse(market(cfg,data).standard(c|change))
        self.assertFalse(market(cfg,data).standard(c|dict(standard_verified=True,risk_flags=['terms conflict'])))

    def test_one_sided_history_proves_membership_not_a_fill(self):
        from .data import mid
        cfg,data=fixture();q=row(data,'SHORT1','2026-08-28');q['bid']=None
        self.assertTrue(market(cfg,data).observed(data['contracts'][1],'2026-08-28'))
        self.assertIsNone(mid(q))

    def test_future_quotes_cannot_backfill_membership(self):
        cfg,data=fixture();c=data['contracts'][1]
        data['options']=[q for q in data['options'] if q['id']!=c['id'] or q['date']>'2026-08-28']
        self.assertFalse(market(cfg,data).observed(c,'2026-08-28'))

    def test_valid_terminal_cash_survives_intermediate_mark_gap(self):
        cfg,data=fixture();row(data,'SHORT1','2026-09-02')['bid']=None
        r=run(data,cfg,allow_test=True)
        self.assertEqual(r['status'],'incomplete');self.assertTrue(r['metrics']['terminal_resolved'])
        self.assertIsNotNone(r['metrics']['net_pnl']);self.assertIsNone(r['metrics']['max_drawdown'])
        self.assertTrue(r['audit']['pnl_reconciled'])
        gap=next(x for x in r['ledger'] if x['date']=='2026-09-02')
        self.assertIsNone(gap['nav']);self.assertEqual(gap['n_short'],1)
        self.assertIn('MISSING_BID',r['issues'][0]['details'])
        self.assertTrue(all(x['drawdown'] is None for x in r['ledger'] if x['date']>='2026-09-02'))

    def test_reference_response_not_redistributed(self):
        c={'provenance':{'identity':{'status':'derived'},'current_description':{'status':'current only','values':{'licensed':'reference row'}}}}
        p=public_provenance(c)
        self.assertNotIn('values',p['current_description']);self.assertIn('values',c['provenance']['current_description'])

    def test_nested_csv_is_stable_after_json_roundtrip(self):
        rows=[{'provenance':{'z':'last','a':{'y':2,'b':1}}}]
        restored=json.loads(json.dumps(rows,sort_keys=True))
        self.assertEqual(csv_text(rows,['provenance']),csv_text(restored,['provenance']))

    def test_rerender_preserves_derived_results(self):
        root=Path(__file__).resolve().parents[1]
        result=root/'pmcc/results.json'
        if not result.exists():self.skipTest('No committed publication')
        book=json.loads(result.read_text());original=deepcopy(book.get('runs'))
        with tempfile.TemporaryDirectory(prefix='pmcc-render-') as tmp:
            dest=Path(tmp);(dest/'pmcc_backtest').mkdir()
            (dest/'pmcc_backtest/page.html').write_bytes((root/'pmcc_backtest/page.html').read_bytes())
            publish(dest,book);first=(dest/'pmcc/results.json').read_bytes()
            csv_before=(dest/'pmcc/contracts.csv').read_bytes()
            restored=json.loads(first)
            publish(dest,restored);self.assertEqual(first,(dest/'pmcc/results.json').read_bytes())
            self.assertEqual(csv_before,(dest/'pmcc/contracts.csv').read_bytes())
            self.assertEqual(original,book['runs'])


if __name__=='__main__':unittest.main()
