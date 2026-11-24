"""Artificial test fixtures are never published as financial evidence."""
from copy import deepcopy
import math
import unittest
import numpy as np
from .research import analyze as tracker
from .test_research import fixture
from .reliability import (kl, log_bound, iid_kl_interval, nonoverlap_dates,
                          block_indices, panel, bootstrap, analyze)


class ReliabilityTests(unittest.TestCase):
    def test_kl_direction_endpoints_and_bounds(self):
        self.assertEqual(kl(0,0),0)
        self.assertEqual(kl(1,1),0)
        self.assertEqual(kl(.1,0), math.inf)
        self.assertAlmostEqual(kl(0,.2),-math.log(.8))
        self.assertAlmostEqual(kl(1,.2),-math.log(.2))
        self.assertAlmostEqual(log_bound(100,.2,.05),log_bound(100,.8,.05,'upper'))
        self.assertEqual(log_bound(20,.2,0),0)
        self.assertLess(log_bound(200,.2,.05),log_bound(100,.2,.05))
        self.assertLess(log_bound(100,.2,.1),log_bound(100,.2,.05))

    def test_invalid_domains_never_silently_become_probability(self):
        for args in [(0,.2,.1),(True,.2,.1),(20,0,.1),(20,.2,.2),(20,.8,.3,'upper'),(20,.2,float('nan'))]:
            with self.assertRaises(ValueError):log_bound(*args)
        for q,p in [(float('nan'),.2),(-.1,.2),(.2,1.1)]:
            with self.assertRaises(ValueError):kl(q,p)

    def test_small_tolerances_never_produce_negative_divergence(self):
        for p in (.001,.1,.2,.5,.9,.999):
            for t in (1e-16,1e-12,1e-8):
                self.assertGreaterEqual(kl(p+t,p),0)
                self.assertLessEqual(log_bound(100,p,t,'upper'),0)

    def test_inversion_unknown_mu_not_sample_mean(self):
        lo,hi=iid_kl_interval(20,100)
        self.assertLess(lo,.2);self.assertGreater(hi,.2)
        self.assertAlmostEqual(100*kl(.2,lo),math.log(40))
        self.assertAlmostEqual(100*kl(.2,hi),math.log(40))
        self.assertAlmostEqual(iid_kl_interval(0,100)[1],1-.025**.01)
        self.assertAlmostEqual(iid_kl_interval(100,100)[0],.025**.01)

    def test_kl_two_sided_interval_has_at_least_nominal_binomial_coverage(self):
        for n in (10,30,60):
            for p in (.01,.1,.3,.5,.9,.99):
                coverage=sum(math.comb(n,k)*p**k*(1-p)**(n-k) for k in range(n+1)
                             if iid_kl_interval(k,n)[0]<=p<=iid_kl_interval(k,n)[1])
                self.assertGreaterEqual(coverage,.95-1e-10)

    def test_nonoverlap_phase_fixed_as_source_start_slides_and_missing_paths_do_not_shift_it(self):
        d=tracker(fixture());dates=[r['signal_date'] for r in d['rows']['BAC']]
        chosen=nonoverlap_dates(dates)
        self.assertEqual(nonoverlap_dates(dates[11:]),[x for x in chosen if x>=dates[11]])
        indexes=[dates.index(x) for x in chosen]
        self.assertTrue(all(b-a==7 for a,b in zip(indexes,indexes[1:])))
        selected=[r for r in d['rows']['BAC'] if r['signal_date'] in chosen]
        self.assertTrue(all(a['outcome_date']<b['signal_date'] for a,b in zip(selected,selected[1:])))

    def test_shared_blocks_are_contiguous_not_independent_per_ticker(self):
        idx=block_indices(25,7,100,np.random.default_rng(42))
        self.assertEqual(idx.shape,(100,25))
        for start,end in [(0,7),(7,14),(14,21),(21,25)]:
            self.assertTrue(np.all(np.diff(idx[:,start:end],axis=1)==1))
        self.assertTrue(np.all((idx>=0)&(idx<25)))

    def test_missing_observations_have_zero_weight_not_zero_outcome(self):
        d=tracker(fixture());dates=[r['signal_date'] for r in d['rows']['BAC'][:20]]
        d['rows']['BAC'][2].update(status='missing_path',tail_event=None,adverse_move=None)
        a=panel(d['rows'],dates)
        self.assertEqual(a[:,0,0].sum(),19)
        self.assertEqual(a[:,1,0].sum(),20)
        self.assertEqual(len(a),20)

    def test_bootstrap_preserves_nested_groups_and_cross_stock_identity(self):
        # Identical stocks must have identical resampled intervals in every draw.
        a=np.zeros((80,4,6))
        for i in range(80):
            event=i%5==0; passed=i%2==0
            a[i,:,:]=[1,passed,event,event*passed,.04*event,.04*event*passed]
        r=bootstrap(a,[7,14],300,42)
        self.assertEqual(r,bootstrap(a,[7,14],300,42))
        for case in r:
            for t in ('KO','PFE','F'):self.assertEqual(case['tickers']['BAC'],case['tickers'][t])
            ci=case['tickers']['BAC']['frequency_difference']['ci95']
            self.assertLess(ci[0],0);self.assertGreater(ci[1],0)

    def test_empty_cohorts_and_no_events_withhold_bootstrap_not_zero_risk_guarantee(self):
        a=np.zeros((40,4,6));a[:,:,0]=1
        r=bootstrap(a,[7],100,42)[0]['tickers']['BAC']
        self.assertIsNone(r['frequency_difference']['ci95'])
        self.assertEqual(r['groups']['filtered']['valid_replicates'],0)
        self.assertEqual(r['groups']['unfiltered']['reason'],'no_observed_outcome_variation')

    def test_constant_resampled_statistic_is_not_a_zero_width_guarantee(self):
        a=np.zeros((28,4,6))
        for i in range(28):a[i,:,:]=[1,i%4<2,i%2,(i%2)*(i%4<2),.04*(i%2),.04*(i%2)*(i%4<2)]
        for b in bootstrap(a,[14,28],100,42):
            c=b['tickers']['BAC']['groups']['unfiltered']
            self.assertIsNone(c['ci95'])
            self.assertEqual(c['reason'],'degenerate_resampling_interval')

    def test_no_filtered_events_does_not_create_a_favorable_frequency_interval(self):
        a=np.zeros((80,4,6))
        for i in range(80):
            p=i%2==0;e=(not p) and i%3==0
            a[i,:,:]=[1,p,e,0,.04*e,0]
        c=bootstrap(a,[7],100,42)[0]['tickers']['BAC']['frequency_difference']
        self.assertIsNone(c['ci95'])
        self.assertEqual(c['reason'],'no_observed_outcome_variation')

    def test_extension_no_mutation_counts_maturity_and_alignment(self):
        d=tracker(fixture());old=deepcopy(d);r=analyze(d,100)
        self.assertEqual(d,old)
        for t in ('BAC','KO','PFE','F'):
            g=r['samples']['daily']['tickers'][t]['groups']
            self.assertEqual(g['filtered']['n'],d['full_sample']['tickers'][t]['pass']['n'])
            self.assertEqual(g['unfiltered']['n'],d['full_sample']['tickers'][t]['all']['n'])
        self.assertEqual(len(r['samples']['daily']['matured_dates']),len(d['rows']['BAC'])-6)
        d['rows']['KO'].pop(0)
        with self.assertRaises(ValueError):analyze(d,100)


if __name__=='__main__':unittest.main()
