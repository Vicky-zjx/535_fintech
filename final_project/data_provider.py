"""Fresh LSEG Platform inputs. No desktop, synthetic, stale-price or cache fallback."""
from datetime import date, timedelta
import hashlib
import json
import math
import os
import re
import time
import pandas as pd
from lseg_chart.update import query_lseg, safe_failure_detail
from .strategy_config import UNIVERSE


def table(frame):
    return json.loads(frame.to_json(orient='split', date_format='iso')) if frame is not None else None


def named(frame, fields):
    if frame is None or frame.empty:
        raise ValueError('Empty LSEG response')
    names = [str(x).casefold() for x in frame.columns]
    aliases = {'ticker symbol': 'tr.tickersymbol', 'price close': 'tr.priceclose',
               'event start date': 'tr.eventstartdate', 'event type': 'tr.eventtype',
               'event status': 'tr.eventstatus'}
    if fields == ['TR.PriceClose.date', 'TR.PriceClose']:
        aliases['date'] = 'tr.priceclose.date'
    names = [aliases.get(n, n) for n in names]
    # Known SDK .date header collision; only accept exact declared request order.
    expected = ['instrument'] + [x.casefold() for x in fields]
    collapsed = ['instrument'] + [x.casefold().removesuffix('.date') for x in fields]
    if names == collapsed:
        frame = frame.copy(); frame.columns = ['Instrument'] + fields
    elif names != expected:
        raise ValueError('Unexpected LSEG field schema (no positional guessing)')
    else:
        frame = frame.copy(); frame.columns = ['Instrument'] + fields
    return frame


def normalize_closes(frame, ric, start, as_of):
    frame = named(frame, ['TR.PriceClose.date', 'TR.PriceClose'])
    records = []
    for _, row in frame.iterrows():
        if row['Instrument'] != ric:
            raise ValueError('Unexpected price instrument')
        d = pd.to_datetime(row['TR.PriceClose.date'], errors='coerce')
        if pd.isna(d):
            raise ValueError('Invalid provider price date')
        d = str(d.date())
        if not start <= d <= as_of:
            raise ValueError('Price date outside completed-session window')
        raw = row['TR.PriceClose']
        v = None if pd.isna(raw) else float(raw)
        if v is not None and (not math.isfinite(v) or v <= 0):
            raise ValueError('Invalid closing price')
        records.append({'date': d, 'close': v})
    return records


def normalize_contracts(frame, ticker, ric, as_of):
    required = {'RIC', 'StrikePrice', 'ExpiryDate', 'CallPutOption', 'UnderlyingQuoteRIC',
                'LotSize', 'Currency', 'ContractType', 'ExerciseStyle'}
    if frame is None or not required.issubset(frame.columns):
        raise ValueError('Missing option identification/standard-terms metadata')
    contracts, exclusions = [], []
    for _, r in frame.iterrows():
        ident = str(r['RIC'])
        try:
            m = re.fullmatch(r'([A-Z]+)([A-X])(\d{2})(\d{2})(\d{5})\.U', ident)
            if not m or m[1] != ticker:
                raise ValueError('Nonstandard root/venue/encoding; no inferred deliverable')
            month = (ord(m[2])-ord('A')) % 12+1
            exp = str(date(2000+int(m[4]), month, int(m[3])))
            cp = 'put' if m[2] >= 'M' else 'call'
            strike = int(m[5])/100
            underlying = r['UnderlyingQuoteRIC']
            underlying = underlying if isinstance(underlying, list) else [underlying]
            if ric not in underlying or cp != str(r['CallPutOption']).lower() or strike != float(r['StrikePrice']) or exp != str(pd.Timestamp(r['ExpiryDate']).date()):
                raise ValueError('RIC-derived identity conflicts with provider metadata')
            if r['LotSize'] != 100 or r['Currency'] != 'USD' or r['ContractType'] != 'Standard' or r['ExerciseStyle'] != 'A':
                raise ValueError('Standard 100-share USD American terms not confirmed')
            contracts.append(dict(ric=ident, type=cp, strike=strike, expiry=exp,
                                  multiplier=100, terms_verified=True, observed_on=as_of,
                                  delta=None, delta_date=None,
                                  terms_source='LSEG discovery: LotSize=100, Standard, USD, American; ordinary OPRA root'))
        except (ValueError, TypeError) as e:
            exclusions.append({'ric': ident, 'reason': str(e)})
    unique = {}
    for c in contracts:
        if c['ric'] in unique and unique[c['ric']] != c:
            raise ValueError('Conflicting option metadata')
        unique[c['ric']] = c
    return list(unique.values()), exclusions


def earnings_calendar(frame, ric, as_of, through):
    fields = ['TR.EventStartDate', 'TR.EventType', 'TR.EventStatus']
    frame = named(frame, fields)
    events = []
    for _, r in frame.iterrows():
        if r['Instrument'] != ric:
            raise ValueError('Unexpected earnings instrument')
        if pd.isna(r[fields[0]]):
            continue
        d = str(pd.Timestamp(r[fields[0]]).date())
        if d <= as_of or str(r[fields[1]]).casefold() not in ('res', 'earnings release', 'earnings releases'):
            continue
        estimated = r[fields[2]]
        confirmed = (estimated is False or str(estimated).lower() in ('false', '0'))
        events.append({'date': d, 'confirmed': confirmed})
    events.sort(key=lambda e: e['date'])
    # An empty reply is not proof that there are no earnings. Require the next
    # reported release to be company-confirmed; estimated/unknown => blocked.
    reliable = bool(events and events[0]['confirmed'])
    return {'reliable': reliable, 'known_on': as_of, 'through': through,
            'dates': [e['date'] for e in events], 'events': events,
            'source': 'LSEG RES events; TR.EventStatus False = company-confirmed',
            'limitation': 'Next reported event required; estimated/empty calendar blocks new puts'}


def add_deltas(ld, contracts, as_of):
    """Dated exchange Greeks, never undated TR.OPW snapshots relabeled as history."""
    if not contracts:
        return None
    rics = [c['ric'] for c in contracts]
    frame = ld.get_history(universe=rics, fields=['DELTA_EXCH'], interval='1D', start=as_of, end=as_of)
    if frame is None or frame.empty:
        return table(frame)
    for c in contracts:
        column = (c['ric'], 'DELTA_EXCH') if isinstance(frame.columns, pd.MultiIndex) else 'DELTA_EXCH'
        if not isinstance(frame.columns, pd.MultiIndex) and len(rics) != 1:
            continue
        if column not in frame.columns:
            continue
        for when, value in frame[column].items():
            if str(pd.Timestamp(when).date()) == as_of and not pd.isna(value):
                c['delta'], c['delta_date'] = float(value), as_of
    return table(frame)


def fetch_market(ctx, retrieved_at):
    as_of, session = ctx['as_of'], ctx['target_session']
    start = str(date.fromisoformat(as_of)-timedelta(days=120))
    out = {'mode': 'live', 'source': 'LSEG Data Platform', 'retrieved_at': retrieved_at,
           'calendar': ctx, 'tickers': {}, 'raw': {}}

    def operation(ld):
        last_request = 0.

        def paced(function, *args, **kwargs):
            nonlocal last_request
            time.sleep(max(0., .36-(time.monotonic()-last_request)))
            last_request = time.monotonic()
            return function(*args, **kwargs)

        for ticker, cfg in UNIVERSE.items():
            ric = cfg['ric']; raw = {}; d = {'ric': ric, 'identity_verified': False,
                                            'history': [], 'contracts': [], 'errors': []}
            out['raw'][ticker] = raw; out['tickers'][ticker] = d
            try:
                identity = paced(ld.get_data, [ric], ['TR.TickerSymbol'], header_type=ld.HeaderType.NAME)
                raw['identity'] = table(identity)
                checked = named(identity, ['TR.TickerSymbol'])
                if len(checked) != 1 or checked.iloc[0]['Instrument'] != ric or checked.iloc[0]['TR.TickerSymbol'] != ticker:
                    raise ValueError('LSEG ticker identity mismatch')
                d['identity_verified'] = True
                prices = paced(ld.get_data, [ric], ['TR.PriceClose.date', 'TR.PriceClose'],
                                     parameters={'SDate': start, 'EDate': as_of, 'Frq': 'D', 'Curn': 'USD'},
                                     header_type=ld.HeaderType.NAME)
                raw['closes'] = table(prices)
                d['history'] = normalize_closes(prices, ric, start, as_of)
            except Exception as e:
                d['errors'].append('Price/identity query or validation failed: '+safe_failure_detail(e, os.environ))
            try:
                lo = str(date.fromisoformat(session)+timedelta(days=3))
                hi = str(date.fromisoformat(session)+timedelta(days=10))
                # US NYSE options use the consolidated underlying (e.g. IBM),
                # not its exchange-specific listing (IBM.N). Verify that lookup
                # independently; a constructed identifier is not listing evidence.
                option_underlying = ticker
                option_identity = paced(ld.get_data, [option_underlying], ['TR.TickerSymbol'],
                                        header_type=ld.HeaderType.NAME)
                raw['option_underlying_identity'] = table(option_identity)
                checked = named(option_identity, ['TR.TickerSymbol'])
                if len(checked) != 1 or checked.iloc[0]['Instrument'] != option_underlying or checked.iloc[0]['TR.TickerSymbol'] != ticker:
                    raise ValueError('Consolidated option-underlying identity mismatch')
                d['option_underlying_ric'] = option_underlying
                fields = 'RIC,StrikePrice,ExpiryDate,CallPutOption,UnderlyingQuoteRIC,LotSize,Currency,ContractType,ExerciseStyle'
                # The derivative view exposes the lot/contract metadata already
                # used by the repository's real PMCC capability audit.
                chain = paced(ld.discovery.search, view=ld.discovery.Views.EQUITY_DERIVATIVE_QUOTES, top=1000,
                    filter=f"UnderlyingQuoteRIC eq '{option_underlying}' and RCSAssetClass eq 'OPT' and IsChain eq false and ExpiryDate ge {lo} and ExpiryDate le {hi}", select=fields)
                raw['discovery'] = table(chain)
                if chain is None or len(chain) >= 1000:
                    raise ValueError('Search unavailable or capped; completeness cannot be assessed')
                d['contracts'], d['exclusions'] = normalize_contracts(chain, ticker, option_underlying, as_of)
                d['options_status'] = 'observed'
                d['candidate_count'] = len(d['contracts'])
                d['universe_limitation'] = 'Current observed discovery subset, not a complete historical option chain'
                try:
                    raw['delta'] = []
                    for offset in range(0, len(d['contracts']), 200):
                        raw['delta'].append(paced(add_deltas, ld, d['contracts'][offset:offset+200], as_of))
                    d['delta_status'] = 'Same-session DELTA_EXCH where returned; fallback for incomplete coverage'
                except Exception as e:
                    d['delta_status'] = 'Dated Greeks unavailable; listed-strike fallback: '+type(e).__name__
            except Exception as e:
                d['options_status'] = 'unavailable'
                d['errors'].append('Contract discovery/terms validation failed: '+safe_failure_detail(e, os.environ))
            try:
                through = str(date.fromisoformat(session)+timedelta(days=180))
                events = paced(ld.get_data, [ric], ['TR.EventStartDate', 'TR.EventType', 'TR.EventStatus'],
                    parameters={'SDate': session, 'EDate': through, 'EventType': 'RES'}, header_type=ld.HeaderType.NAME)
                raw['earnings'] = table(events)
                d['earnings'] = earnings_calendar(events, ric, as_of, through)
            except Exception as e:
                d['earnings'] = {'reliable': False, 'reason': 'Earnings query/validation unavailable: '+safe_failure_detail(e, os.environ)}
        return out
    return query_lseg(date.fromisoformat(start), date.fromisoformat(as_of), operation=operation)


def conids_from_course(history):
    """Only explicit ticker/RIC bindings in course price_history.json are accepted."""
    found = {}
    for key, value in history.items():
        if not str(key).isdigit() or int(key) <= 0 or not isinstance(value, dict):
            continue
        for t, cfg in UNIVERSE.items():
            if value.get('symbol') == t or value.get('ticker') == t or value.get('ric') == cfg['ric']:
                if t in found and found[t] != int(key):
                    raise ValueError('Conflicting course conid mapping')
                found[t] = int(key)
    return found


def digest(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False).encode()).hexdigest()
