"""Exploratory common-sample filter comparisons; not a strategy optimizer."""
from .reliability import analyze as reliability, TICKERS
import statistics

ARMS={'none':'No filters','trend':'Trend only','volatility':'HV20 only',
      'sudden_drop':'Five-day return only','combined':'All filters combined'}


def diagnostics(h,d):
    """Fixed calendar partitions and overlapping exclusions, not chosen regimes."""
    overlap={}; years={}
    for t in TICKERS:
        flags={r['signal_date']:r for r in h['tickers'][t]['daily_rows']}
        mature=[r for r in d['rows'][t] if r['status']=='observed']
        overlap[t]=dict(
            mature_paths=len(mature),
            price_below_sma50=sum(flags[r['signal_date']]['close']<flags[r['signal_date']]['sma50'] for r in mature),
            sma20_below_sma50=sum(flags[r['signal_date']]['sma20']<flags[r['signal_date']]['sma50'] for r in mature),
            hv_fail_already_trend_fail=sum(not flags[r['signal_date']]['volatility'] and not flags[r['signal_date']]['trend'] for r in mature),
            return_fail_already_trend_fail=sum(not flags[r['signal_date']]['sudden_drop'] and not flags[r['signal_date']]['trend'] for r in mature),
            additional_exclusions_after_trend=sum(flags[r['signal_date']]['trend'] and not flags[r['signal_date']]['eligible'] for r in mature))
        bins=[]
        for year in sorted({r['signal_date'][:4] for r in h['tickers'][t]['daily_rows']}):
            rows=[r for r in h['tickers'][t]['daily_rows'] if r['signal_date'].startswith(year)]
            obs=[r for r in mature if r['signal_date'].startswith(year)]
            valid=[r for r in rows if r['valid']]
            first,last=rows[0],rows[-1]
            bins.append(dict(year=year,first_date=first['signal_date'],last_date=last['signal_date'],
                valid_signals=len(valid),mature_paths=len(obs),
                endpoint_price_return=last['close']/first['close']-1 if first['close'] and last['close'] else None,
                median_hv20=statistics.median(r['hv20'] for r in valid) if valid else None,
                maximum_hv20=max((r['hv20'] for r in valid),default=None),
                trend_exclusion_rate=sum(not r['trend'] for r in valid)/len(valid) if valid else None,
                decline_frequency=sum(r['tail_event'] for r in obs)/len(obs) if obs else None))
        years[t]=bins
    return dict(filter_overlap=overlap,calendar_partitions=years,
                interpretation='Every calendar year in the fixed sample is shown, including partial endpoint years. Descriptive price returns exclude dividends; these bins are not pre-labeled macro regimes or independent tests.')


def analyze(h,d,replicates=5000):
    flags={t:{r['signal_date']:r for r in h['tickers'][t]['daily_rows']} for t in TICKERS}
    arms={}
    for arm,label in ARMS.items():
        if arm=='none':continue
        changed={**d,'rows':{t:[{**r,'cohort':('pass' if flags[t][r['signal_date']]['eligible' if arm=='combined' else arm] else 'fail')
                               if flags[t][r['signal_date']]['valid'] else None} for r in d['rows'][t]] for t in TICKERS}}
        # Every arm uses exactly the same bootstrap seed/date vectors. Stock and
        # arm comparisons are paired, not independently resampled experiments.
        evidence=d.get('reliability') if arm=='combined' and replicates==5000 else None
        arms[arm]=evidence or reliability(changed,replicates)
    result=dict(kind='exploratory_filter_ablation',benchmark='No filters on the same valid, mature paths',
                window=h['window'],market_snapshot_sha256=d['market_snapshot_sha256'],
                definitions=ARMS,replicates=replicates,samples={},diagnostics=diagnostics(h,d))
    for mode in ('daily','nonoverlap'):
        base=arms['combined']['samples'][mode];stocks={}
        for t in TICKERS:
            all_group=base['tickers'][t]['groups']['unfiltered'];all_n=all_group['n'];groups={}
            for arm,label in ARMS.items():
                s=base if arm=='none' else arms[arm]['samples'][mode]
                x=s['tickers'][t];g=all_group if arm=='none' else x['groups']['filtered']
                sensitivity=[]
                for b in s['sensitivity']:
                    c=b.get('tickers',{}).get(t)
                    sensitivity.append(dict(block_length=b['block_length'],
                        frequency_difference=c['frequency_difference'] if c and arm!='none' else dict(ci95=None,valid_replicates=0,reason='benchmark_identity'),
                        downside_difference=c['downside_difference'] if c and arm!='none' else dict(ci95=None,valid_replicates=0,reason='benchmark_identity')))
                groups[arm]=dict(label=label,n=g['n'],events=g['events'],frequency=g['frequency'],mean_adverse=g['mean_adverse'],
                    benchmark_n=all_n,pass_rate=g['n']/all_n if all_n else None,
                    opportunities_excluded=all_n-g['n'],exclusion_rate=1-g['n']/all_n if all_n else None,
                    frequency_difference=0. if arm=='none' else x['frequency_difference'],
                    downside_difference=0. if arm=='none' else x['downside_difference'],
                    sensitivity=sensitivity,sparse_event_warning=x['sparse_event_warning'] if arm!='none' else False)
            stocks[t]=groups
        result['samples'][mode]=dict(tickers=stocks,matured_dates=base['matured_dates'])
    return result
