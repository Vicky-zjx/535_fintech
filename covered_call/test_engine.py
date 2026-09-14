"""Hand-checkable test fixtures ONLY. Never used by the published data builder."""

from dataclasses import replace
from datetime import date
import unittest

from .accounting import Account, midpoint
from .config import Config
from .engine import run_backtest
from .ric import option_ric


def stock(day, price, time="11:00"):
    return dict(timestamp=f"{day}T{time}:00-04:00", ric="AAPL.O", print=price, bar_minutes=60)


def call(day, expiry, strike, bid=1, ask=3, trade=2, time="11:00"):
    return dict(timestamp=f"{day}T{time}:00-04:00", ric=option_ric("AAPL.O", date.fromisoformat(expiry), strike),
                strike=strike, expiry=expiry, cp="C", bid=bid, ask=ask, print=trade, bar_minutes=60)


class BacktestTests(unittest.TestCase):
    def setUp(self):
        self.config = replace(Config(), start="2026-07-06", end="2026-07-24", initial_cash=10_000)

    def run_book(self, stocks, calls, **kwargs):
        return run_backtest(stocks, calls, replace(self.config, **kwargs))

    def test_cash_assignment_expiry_and_rebuy_by_hand(self):
        # $10,000 -> BUY 100@$100 -> cash $0; SELL@$2 -> cash $200.
        # OTM Friday keeps shares. Monday 103 targets 108.15, chooses 110.
        # Premium $300 -> cash $500. Assignment +$11,000 -> $11,500.
        # Next Monday BUY@$108 -> $700; SELL@$1 -> $800; Friday expires.
        stocks = [stock("2026-07-06",100), stock("2026-07-10",104,"16:00"),
                  stock("2026-07-13",103), stock("2026-07-17",112,"16:00"),
                  stock("2026-07-20",108), stock("2026-07-24",110,"16:00")]
        options = [call("2026-07-06","2026-07-10",105),
                   call("2026-07-13","2026-07-17",107.5),
                   call("2026-07-13","2026-07-17",110,2,4,3),
                   call("2026-07-20","2026-07-24",115,0.5,1.5,1)]
        r = self.run_book(stocks,options)
        self.assertEqual([b['action'] for b in r['blotter']], ['BUY','SELL','EXPIRE','SELL','ASSIGN','BUY','SELL','EXPIRE'])
        self.assertEqual([b['cash_delta'] for b in r['blotter']], [-10000,200,0,300,11000,-10800,100,0])
        self.assertEqual(r['metrics']['ending_cash'],800)
        self.assertEqual(r['metrics']['ending_nav'],11800)
        self.assertEqual(r['metrics']['premium_collected'],600)
        self.assertEqual(r['metrics']['expired'],2)
        self.assertEqual(r['metrics']['assigned'],1)
        self.assertEqual(r['decisions'][1]['selected_strike'],110)
        after_sell = next(row for row in r['ledger'] if row['phase']=='after_sell')
        self.assertEqual(after_sell['nav'],10000)  # premium and short liability cancel
        self.assertEqual(after_sell['option_mv'],-200)
        self.assertEqual(after_sell['initial_margin'],5000)
        self.assertEqual(after_sell['maintenance_margin'],2500)
        self.assertEqual(after_sell['available_funds'],5000)
        self.assertEqual(after_sell['excess'],7500)
        assigned = next(row for row in r['ledger'] if row['phase']=='after_assign')
        self.assertEqual((assigned['shares'],assigned['short_call_quantity']),(0,0))
        self.assertTrue(r['audit']['passed'])

    def test_missing_ask_skips_option_but_keeps_stock(self):
        r=self.run_book([stock('2026-07-06',100)],[call('2026-07-06','2026-07-10',105,ask=None)],end='2026-07-10')
        self.assertEqual([b['action'] for b in r['blotter']],['BUY'])
        self.assertEqual(r['metrics']['ending_shares'],100)
        self.assertEqual(r['metrics']['skipped_weeks'],1)
        self.assertIn('BID/ASK',r['decisions'][0]['reason'])

    def test_no_future_quote_or_future_listing(self):
        options=[call('2026-07-06','2026-07-10',105,time='12:00')]
        r=self.run_book([stock('2026-07-06',100)],options,end='2026-07-10')
        self.assertEqual(r['metrics']['calls_sold'],0)
        self.assertIsNone(r['decisions'][0]['selected_strike'])

    def test_known_missing_nearest_strike_does_not_jump_to_further_quote(self):
        options=[call('2026-07-06','2026-07-10',105,time='10:00'),
                 call('2026-07-06','2026-07-10',110)]
        r=self.run_book([stock('2026-07-06',100)],options,end='2026-07-10')
        self.assertEqual(r['decisions'][0]['selected_strike'],105)
        self.assertEqual(r['metrics']['calls_sold'],0)

    def test_missing_stock_does_not_use_next_hour(self):
        r=self.run_book([stock('2026-07-06',100,'12:00')],[],end='2026-07-10')
        self.assertEqual(r['blotter'],[])
        self.assertIn('No stock print',r['decisions'][0]['reason'])

    def test_reg_t_blocks_before_any_booking(self):
        r=self.run_book([stock('2026-07-06',100)],[call('2026-07-06','2026-07-10',105)],initial_cash=4999,end='2026-07-10')
        self.assertEqual(r['blotter'],[])
        self.assertEqual(r['metrics']['ending_cash'],4999)
        self.assertIn('Reg T rejected',r['decisions'][0]['reason'])

    def test_atm_expiry_is_zero_and_keeps_shares(self):
        r=self.run_book([stock('2026-07-06',100),stock('2026-07-10',105,'16:00')],
                        [call('2026-07-06','2026-07-10',105)],end='2026-07-10')
        self.assertEqual(r['blotter'][-1]['action'],'EXPIRE')
        self.assertEqual(r['metrics']['ending_shares'],100)

    def test_missing_expiry_print_halts_instead_of_inventing_assignment(self):
        r=self.run_book([stock('2026-07-06',100),stock('2026-07-10',120,'15:00'),stock('2026-07-13',125)],
                        [call('2026-07-06','2026-07-10',105)])
        self.assertEqual(r['status'],'incomplete_expiry_data')
        self.assertEqual([b['action'] for b in r['blotter']],['BUY','SELL'])
        self.assertEqual(r['metrics']['ending_short_calls'],-1)

    def test_mark_changes_nav_not_cash_and_missing_marks_are_labeled(self):
        r=self.run_book([stock('2026-07-06',100),stock('2026-07-06',102,'12:00'),stock('2026-07-10',104,'16:00')],
                        [call('2026-07-06','2026-07-10',105),call('2026-07-06','2026-07-10',105,3,5,4,time='12:00')],end='2026-07-10')
        row=next(x for x in r['ledger'] if x['timestamp'].startswith('2026-07-06T12:00'))
        self.assertEqual(row['cash'],200)
        self.assertEqual(row['option_mv'],-400)
        self.assertEqual(row['nav'],10000)
        self.assertEqual(r['blotter'][-1]['cash_delta'],0)

    def test_bad_bars_and_crossed_quotes(self):
        self.assertIsNone(midpoint(dict(bid=3,ask=2)))
        self.assertIsNone(midpoint(dict(bid=-1,ask=2)))
        self.assertEqual(midpoint(dict(bid=0,ask=0.1)),0.05)
        bad=stock('2026-07-06',100); bad['bar_minutes']=1
        with self.assertRaisesRegex(ValueError,'same configured length'):
            self.run_book([bad],[])
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            self.run_book([stock('2026-07-06',100)]*2,[])

    def test_regression_uses_mid_as_x_and_real_print_as_y(self):
        options=[call('2026-07-06','2026-07-10',100,0,2,3),
                 call('2026-07-06','2026-07-10',101,1,3,5),
                 call('2026-07-06','2026-07-10',102,2,4,7),
                 call('2026-07-06','2026-07-10',103,3,5,None)]
        r=self.run_book([stock('2026-07-06',100)],options,end='2026-07-10')
        self.assertEqual(r['validation']['count'],3)
        self.assertAlmostEqual(r['validation']['fit']['slope'],2)
        self.assertAlmostEqual(r['validation']['fit']['intercept'],1)
        self.assertAlmostEqual(r['validation']['fit']['r2'],1)

    def test_ric_examples_and_non_padded_day(self):
        self.assertEqual(option_ric('UUUU.K',date(2026,8,21),14.5),'UUUUH212601450.U^H26')
        self.assertEqual(option_ric('AAPL.O',date(2026,6,5),190),'AAPLF52619000.U^F26')
        self.assertEqual(option_ric('AAPL.O',date(2026,7,17),200),'AAPLG172620000.U^G26')
        self.assertEqual(option_ric('AAPL.O',date(2026,8,7),205),'AAPLH72620500.U^H26')
        self.assertEqual(option_ric('UUUU.K',date(2026,7,31),15,'P'),'UUUUS312601500.U^G26')
        self.assertEqual(option_ric('AAPL.O',date(2026,8,7),325,pad_day=True),'AAPLH072632500.U^H26')
        self.assertEqual(option_ric('AAPL.O',date(2026,9,4),335,pad_day=True),'AAPLI042633500.U^I26')

    def test_reject_unsupported_clock_and_interval(self):
        for settings in ({'entry_time':'09:00'},{'bar_minutes':1},{'initial_cash':0}):
            with self.assertRaises(ValueError):
                replace(self.config,**settings)


if __name__ == '__main__':
    unittest.main()
