"""Bounded real LSEG pull. Raw replies retained; never touches Assignment 1.1."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import time

import pandas as pd

from .accounting import finite
from .config import Config
from .engine import local_timestamp
from .ric import option_ric

FIELDS = ['TRDPRC_1', 'BID', 'ASK', 'NUM_MOVES', 'ACVOL_UNS']


def parse_reply(raw, ric, config, contract=None):
    if raw.get('summaryTimestampLabel') != 'startPeriod':
        raise ValueError('Unexpected source timestamp label')
    headers = [x['name'] for x in raw['headers']]
    result = []
    seen = set()
    for values in raw.get('data', []):
        source = dict(zip(headers, values))
        source_ts = pd.Timestamp(source['DATE_TIME']).as_unit('ns')
        if source_ts.tzinfo is None:
            raise ValueError('Source DATE_TIME must explicitly identify its timezone')
        # The real start/end probe confirms the same print shifts by +1 hour.
        end_ts = (source_ts + pd.Timedelta(minutes=config.bar_minutes)).tz_convert(config.timezone)
        if end_ts.weekday() > 4 or not '10:00' <= end_ts.strftime('%H:%M') <= config.expiry_time:
            continue
        if end_ts in seen:
            raise ValueError(f'Duplicate timestamp in raw reply: {ric} {end_ts}')
        seen.add(end_ts)
        def value(field):
            v = source.get(field)
            if v is None:
                return None
            if not finite(v):
                raise ValueError(f'Non-finite source field {ric} {field}')
            return float(v)
        row = dict(timestamp=end_ts.isoformat(), source_timestamp=source_ts.isoformat(),
                   ric=ric, print=value('TRDPRC_1'), bar_minutes=config.bar_minutes,
                   num_moves=value('NUM_MOVES'), volume=value('ACVOL_UNS'))
        if contract:
            row.update(contract, bid=value('BID'), ask=value('ASK'), cp='C')
        result.append(row)
    return sorted(result, key=lambda r: r['timestamp'])


def fetch(output: Path, config=Config()):
    import lseg.data as ld
    from lseg.data.content import historical_pricing as hp

    raw_dir = output.parent / 'raw'
    raw_dir.mkdir(parents=True, exist_ok=True)
    logs = []

    def get(ric, start, end, contract=None):
        signature = json.dumps([ric,start,end,FIELDS,config.bar_minutes,'startPeriod'])
        digest = hashlib.sha256(signature.encode()).hexdigest()[:20]
        cache = raw_dir / f'{digest}.json'
        if cache.exists():
            saved = json.loads(cache.read_text())
        else:
            saved = dict(ric=ric,start=start,end=end)
            for attempt in range(3):
                try:
                    response = hp.summaries.Definition(
                        universe=ric, start=start, end=end, interval=hp.Intervals.HOURLY,
                        sessions=hp.MarketSession.NORMAL,
                        adjustments=[hp.Adjustments.EXCHANGE_CORRECTION, hp.Adjustments.MANUAL_CORRECTION],
                        fields=FIELDS, extended_params={'summaryTimestampLabel':'startPeriod'},
                    ).get_data()
                    saved['raw'] = response.data.raw
                    saved['success'] = bool(response.is_success)
                    break
                except Exception as exc:
                    message = str(exc)
                    saved.update(success=False, error=message)
                    # Invalid candidates are expected, not evidence of a listed strike.
                    if '90001' in message or 'universe is not found' in message.lower() or attempt == 2:
                        break
                    time.sleep(0.5 * (attempt+1))
            cache.write_text(json.dumps(saved,allow_nan=False,default=str),encoding='utf-8')
        logs.append(dict(ric=ric,start=start,end=end,success=saved.get('success',False),
                         raw_file=cache.name,error=saved.get('error')))
        if not saved.get('success'):
            error = saved.get('error','')
            if '90001' not in error and 'universe is not found' not in error.lower():
                raise RuntimeError(f'LSEG request failed rather than an absent candidate: {ric}: {error}')
            return []
        return parse_reply(saved['raw'],ric,config,contract)

    ld.open_session()
    try:
        stock_start = local_timestamp(config.start,'09:00',config).tz_convert('UTC').isoformat()
        stock_end = local_timestamp(config.end,'17:00',config).tz_convert('UTC').isoformat()
        stock = get(config.stock_ric,stock_start,stock_end)
        if not stock:
            raise RuntimeError('No real stock bars; refusing to synthesize a dataset')
        print(f'Stock: {len(stock)} hourly bars; {stock[0]["timestamp"]} to {stock[-1]["timestamp"]}',flush=True)
        stock_at = {pd.Timestamp(r['timestamp']):r for r in stock}
        options, week_searches = [], []
        for monday in pd.date_range(config.start,config.end,freq='W-MON'):
            ts = local_timestamp(monday.date(),config.entry_time,config)
            expiry = monday.date()+timedelta(days=4)
            s = stock_at.get(ts)
            if not s or not finite(s['print']):
                week_searches.append(dict(monday=str(monday.date()),reason='No exact Monday stock print'))
                print(f'{monday.date()}: no exact entry stock print',flush=True)
                continue
            spot = s['print']; target=spot*(1+config.target_otm)
            first = math.ceil((target-1e-10)*2)/2
            center = round(spot*2)/2
            # $0.50 candidate grid: validate every intermediate target strike in order.
            # A small ATM band is for the separate regression, not strike selection.
            atm = [center+i/2 for i in range(-5,6)]
            target_band = [first+i/2 for i in range(21)]
            strikes = sorted(set(atm+target_band))
            begin = local_timestamp(monday.date()-timedelta(days=7),'09:00',config).tz_convert('UTC').isoformat()
            finish = local_timestamp(expiry,'17:00',config).tz_convert('UTC').isoformat()
            def one(strike):
                ric = option_ric(config.stock_ric,expiry,strike,pad_day=True)
                return get(ric,begin,finish,dict(strike=strike,expiry=expiry.isoformat()))
            with ThreadPoolExecutor(max_workers=3) as pool:
                frames=list(pool.map(one,strikes))
            week_rows=[row for frame in frames for row in frame]
            options.extend(week_rows)
            known={row['ric']:row['strike'] for row in week_rows
                   if pd.Timestamp(row['timestamp']) <= ts and
                   any(finite(row.get(f)) for f in ['bid','ask','print'])}
            found=sorted(k for k in known.values() if k>=target-1e-10)
            week_searches.append(dict(monday=str(monday.date()),expiry=str(expiry),spot=spot,target=target,
                                     tested_strikes=strikes,entry_known_strikes=sorted(set(known.values())),
                                     chosen_strike=found[0] if found else None,observations=len(week_rows)))
            print(f'{monday.date()}: spot={spot:.4f} target={target:.4f} selected={found[0] if found else None}; {len(week_rows)} real rows',flush=True)
    finally:
        ld.close_session()
    data=dict(metadata=dict(source='LSEG',synthetic=False,ticker=config.ticker,stock_ric=config.stock_ric,
                           fetched_at=datetime.now(timezone.utc).isoformat(),bar_minutes=config.bar_minutes,
                           source_timestamp_label='startPeriod',timestamp_label='endPeriod',
                           timestamp_normalization='UTC source bar start + 60 minutes, converted to America/New_York',
                           adjustments=['exchangeCorrection','manualCorrection'],sessions='normal',
                           start=config.start,end=config.end,entry_time=config.entry_time,
                           requested_target_otm=config.target_otm,
                           candidate_grid=0.5,week_searches=week_searches,requests=logs,
                           ric_day_convention='AAPL provider uses two-digit days; confirmed with paired real tests on 2026-08-07 and 2026-09-04. Assignment constructor defaults to the screenshot non-padded form.',
                           ric_probe=[{'unpadded':'AAPLH72632500.U^H26','result':'90001 universe not found','padded':'AAPLH072632500.U^H26','bid':0.27,'ask':0.29,'print':0.28,'source_bar_start':'2026-08-03T14:00:00Z'},
                                      {'unpadded':'AAPLI42633500.U^I26','result':'90001 universe not found','padded':'AAPLI042633500.U^I26','bid':0.05,'ask':0.07,'print':0.06,'source_bar_start':'2026-08-31T14:00:00Z'}]),
              stock=stock,options=sorted(options,key=lambda r:(r['timestamp'],r['ric'])))
    # Atomic write to a cache used only by this new assignment.
    temporary = output.with_suffix('.pending.json')
    temporary.write_text(json.dumps(data,allow_nan=False,indent=2),encoding='utf-8')
    temporary.replace(output)
    print(f'Wrote {output}: {len(stock)} stock and {len(options)} option bars',flush=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path('covered_call/data/aapl_hourly_verified.json'))
    args=parser.parse_args()
    if args.output.exists():
        raise SystemExit('Output already exists. Choose a new --output path to preserve the real cache.')
    fetch(args.output)
