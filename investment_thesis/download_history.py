"""Explicit, independent LSEG research download; never a production refresh.

No login/query happens on import. CLI requires --confirm-live-download. Existing
prices, frozen references, orders, and account files are never changed. An SDK
failure is recorded only as a fixed classification, never exception/server text.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import re
import time

import exchange_calendars as xcals
import pandas as pd

from final_project.data_provider import digest, named, normalize_closes
from final_project.strategy_config import UNIVERSE
from lseg_chart.update import query_lseg, safe_failure_detail
from .extension_plan import PLAN, DOWNLOAD_NAME
from .private_artifact import CIPHER_NAME, encrypt, public_key

SOURCE = 'LSEG Data Platform'
SCHEMA_VERSION = 1
PRICE_FIELDS = ['TR.PriceClose.date', 'TR.PriceClose']
OPTION_FIELDS = ['BID', 'ASK', 'TRDPRC_1', 'DELTA_EXCH']
CA_FIELDS = ['TR.CAEffectiveDate', 'TR.CAAdjustmentFactor', 'TR.CAAdjustmentType']
SEED_FILE = 'docs/data/entry_example_market.json'
SEED_DATE, OPTION_EXPIRY = '2026-11-13', '2026-11-20'
MAX_EXACT_RECOVERY = 8  # Per ticker, across the entire fixed window, not just warmup.
MIN_OVERLAP = 5
ARTIFACT_DIRECTORY = 'artifacts/thesis-history'
GUIDANCE = {
    'field_parameters': 'https://community.developers.lseg.com/discussion/121346/query-prices-adjustes-and-unadjusted-for-time-series',
    'us_dividends': 'https://community.developers.lseg.com/discussion/77129/download-prices-adjusted-for-split-but-unadjusted-for-dividends/p1',
    'corporate_actions': 'https://developers.lseg.com/en/article-catalog/article/workspace-corporate-actions-content-set-guide',
}


class DownloadError(ValueError):
    """Messages are fixed local codes, never provider exceptions or raw data."""


def utc_now():
    return datetime.now(timezone.utc)


def timestamp(clock):
    value = clock()
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise DownloadError('invalid_download_clock')
    return value.astimezone(timezone.utc).isoformat()


def valid_price(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def fixed_window():
    start, end = PLAN['extended_start'], PLAN['extended_end']
    cal = xcals.get_calendar(
        'XNYS', start=str(date.fromisoformat(start) - timedelta(days=180)),
        end=str(date.fromisoformat(end) + timedelta(days=30)))
    sample = cal.sessions_in_range(start, end)
    if not len(sample) or str(sample[0].date()) != start or str(sample[-1].date()) != end:
        raise DownloadError('plan_requires_exchange_session_endpoints')
    first = cal.sessions.get_loc(sample[0]) - PLAN['warmup_sessions']
    if first < 0:
        raise DownloadError('warmup_calendar_unavailable')
    query_start = str(cal.sessions[first].date())
    sessions = [str(x.date()) for x in cal.sessions_in_range(query_start, end)]
    return dict(analysis_start=start, analysis_end=end, query_start=query_start,
                warmup_sessions_requested=PLAN['warmup_sessions'],
                expected_sample_sessions=len(sample), expected_total_sessions=len(sessions)), sessions


def annual_chunks(start, end):
    """Calendar-year chunks, with no gaps or double-counted boundary dates."""
    current, last = date.fromisoformat(start), date.fromisoformat(end)
    while current <= last:
        stop = min(date(current.year, 12, 31), last)
        yield current.isoformat(), stop.isoformat()
        current = stop + timedelta(days=1)


def price_parameters(start, end):
    # TR.PriceClose does NOT support Adjusted. Keep the original field semantics.
    return dict(SDate=start, EDate=end, Frq='D', Curn='USD')


def safe_cell(value, environ, approved=()):
    """Keep response data, not SDK objects, headers, auth payloads or errors.

    The raw record tables are content-only and redacted, not HTTP wire captures.
    No arbitrary object's __str__ or exception text enters an artifact.
    """
    if value is None:
        return None
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return None if pd.isna(value) else value.isoformat()
    if isinstance(value, str):
        if re.search(r'(?i)authorization|password|app[_ -]?key|secret|token|bearer', value):
            return '[REDACTED]'
        cleaned = safe_failure_detail(value, environ)
        if cleaned != value:
            return '[REDACTED]'
        # Unknown free text is not needed for these numeric/date/content probes.
        # In particular, never retain an opaque token disguised as a data cell.
        if (value in approved or value in ('', 'CCH', 'CRE', 'RPO', 'LPO', 'RTS', 'Put', 'Call', 'Standard', 'USD', 'A')
                or re.fullmatch(r'(?:BAC|KO|PFE|F)[A-X]\d{9}\.U(?:\^[A-L]\d{2})?', value)
                or re.fullmatch(r'[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?', value)
                or re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)?', value)):
            return value
        return '[UNRETAINED TEXT]'
    if isinstance(value, (bool, int, float)):
        return None if isinstance(value, float) and not math.isfinite(value) else value
    if hasattr(value, 'item'):
        try:
            return safe_cell(value.item(), environ, approved)
        except Exception:
            return None
    return None


def raw_table(frame, environ, ric, fields):
    if not isinstance(frame, pd.DataFrame):
        raise DownloadError('response_not_dataframe')
    approved = {ric, *UNIVERSE, *(c['ric'] for c in UNIVERSE.values()), *fields,
                'Instrument', 'Date', 'Price Close', 'Close Price', 'Ticker Symbol',
                'Effective Date', 'Adjustment Factor', 'Adjustment Type'}
    approved.update(re.sub(r'\(.*\)', '', f).removesuffix('.Date').removesuffix('.date') for f in fields)
    approved.update(x.lower() for x in list(approved))
    approved.update(x.upper() for x in list(approved))
    return dict(format='redacted_content_table',
                columns=[safe_cell(x, environ, approved) for x in frame.columns],
                index=[safe_cell(x, environ, approved) for x in frame.index],
                data=[[safe_cell(x, environ, approved) for x in row]
                      for row in frame.itertuples(index=False, name=None)])


class Requests:
    """Bounded request ledger, one SDK session, pacing, no automatic retries."""

    def __init__(self, ld, environ, clock, sleeper):
        self.ld, self.environ, self.clock, self.sleeper = ld, environ, clock, sleeper
        self.queries, self.raw = [], {}

    def call(self, kind, ric, fields, parameters, history=False, search=False):
        if self.queries:
            self.sleeper(.36)
        q = dict(id=f'q{len(self.queries)+1:04d}', kind=kind, ric=ric, fields=list(fields),
                 parameters=dict(parameters), method='discovery.search' if search else 'get_history' if history else 'get_data',
                 requested_at=timestamp(self.clock), status='pending', row_count=0)
        self.queries.append(q)
        try:
            if search:
                frame = self.ld.discovery.search(view=self.ld.discovery.Views.EQUITY_DERIVATIVE_QUOTES,
                                                 select=','.join(fields), **parameters)
            elif history:
                frame = self.ld.get_history(universe=ric, fields=fields, **parameters)
            else:
                frame = self.ld.get_data(universe=[ric], fields=fields, parameters=parameters,
                                         header_type=self.ld.HeaderType.NAME)
            self.raw[q['id']] = raw_table(frame, self.environ, ric, fields)
            q.update(status='returned', row_count=len(frame))
        except Exception:
            # Even non-auth SDK exceptions can embed credentials, request URLs or tokens.
            q.update(status='failed', error_code='request_or_response_unavailable')
            frame = None
        q['completed_at'] = timestamp(self.clock)
        return q, frame

    @staticmethod
    def reject(q, code):
        q.update(status='rejected', error_code=code)


def identify(requests, ric, ticker):
    q, frame = requests.call('identity', ric, ['TR.TickerSymbol'], {})
    try:
        result = named(frame, ['TR.TickerSymbol'])
        if len(result) != 1 or result.iloc[0]['Instrument'] != ric or result.iloc[0]['TR.TickerSymbol'] != ticker:
            raise DownloadError('identity_mismatch')
    except Exception:
        requests.reject(q, 'identity_not_verified')
        return None
    q['status'] = 'validated'
    return dict(ric=ric, ticker=ticker, query_id=q['id'])


def price_request(requests, kind, ric, start, end, session_set):
    q, frame = requests.call(kind, ric, PRICE_FIELDS, price_parameters(start, end))
    if frame is None:
        return q, []
    try:
        # Reject booleans before normalize_closes can coerce True into 1.0.
        shaped = named(frame, PRICE_FIELDS)
        if any(isinstance(v, bool) for v in shaped['TR.PriceClose']):
            raise DownloadError('boolean_price')
        rows = normalize_closes(frame, ric, start, end)
        if any(r['date'] not in session_set for r in rows):
            raise DownloadError('non_session_price')
        seen = {}
        for row in rows:
            day, value = row['date'], row['close']
            if day in seen and seen[day] != value:
                raise DownloadError('conflicting_duplicate_price')
            seen[day] = value
    except Exception:
        requests.reject(q, 'invalid_price_response')
        return q, []
    q.update(status='validated', valid_price_count=sum(v is not None for v in seen.values()))
    return q, [dict(date=d, close=v) for d, v in sorted(seen.items())]


def merge_prices(existing, incoming, *, alternate=False):
    """Recover absent/null observations only; never replace an observed close."""
    new = {}
    for row in incoming:
        value, day = row['close'], row['date']
        if value is None:
            continue
        if not valid_price(value) or (day in new and new[day] != value):
            raise DownloadError('invalid_or_conflicting_recovery')
        new[day] = value
    overlap = set(existing) & set(new)
    if any(not math.isclose(existing[d], new[d], rel_tol=0, abs_tol=1e-8) for d in overlap):
        raise DownloadError('recovery_overlap_mismatch')
    if alternate and len(overlap) < MIN_OVERLAP:
        raise DownloadError('insufficient_alternate_overlap')
    recovered = sorted(set(new) - set(existing))
    return {**new, **existing}, recovered, len(overlap)


def coverage(history, window):
    missing = [r['date'] for r in history if r['close'] is None]
    return dict(expected_sessions=len(history), observed_sessions=len(history)-len(missing),
                missing_dates=missing, complete=not missing,
                analysis_observed_sessions=sum(r['date'] >= window['analysis_start'] and r['close'] is not None for r in history),
                warmup_observed_sessions=sum(r['date'] < window['analysis_start'] and r['close'] is not None for r in history))


def stock_history(requests, ticker, ric, window, sessions):
    identity = identify(requests, ric, ticker)
    if identity is None:
        raise DownloadError('primary_identity_not_verified')
    session_set, values, provenance, recovery = set(sessions), {}, {}, []
    chunks = list(annual_chunks(window['query_start'], window['analysis_end']))
    for start, end in chunks:
        q, rows = price_request(requests, 'stock_annual', ric, start, end, session_set)
        values, added, _ = merge_prices(values, rows)
        provenance.update({d: q['id'] for d in added})

    # Try the verified consolidated RIC over ALL years, not only the latest 55 sessions.
    # The entire alternate series must agree with every available primary overlap.
    if len(values) < len(sessions):
        alternate_identity = identify(requests, ticker, ticker)
        if alternate_identity:
            alternate_rows, alternate_ids = [], {}
            for start, end in chunks:
                q, rows = price_request(requests, 'consolidated_annual', ticker, start, end, session_set)
                alternate_rows.extend(rows)
                alternate_ids.update({r['date']: q['id'] for r in rows if r['close'] is not None})
            try:
                combined, added, matches = merge_prices(values, alternate_rows, alternate=True)
            except DownloadError:
                recovery.append(dict(method='consolidated', accepted=False,
                                     reason='overlap_validation_failed', identity=alternate_identity))
            else:
                values = combined
                provenance.update({d: alternate_ids[d] for d in added})
                recovery.append(dict(method='consolidated', accepted=True, identity=alternate_identity,
                                     overlap_matches=matches, recovered_dates=added))
        else:
            recovery.append(dict(method='consolidated', accepted=False, reason='identity_not_verified'))

    # Final bounded exact-date retries use the primary RIC only. Earlier returned
    # dates are rejected, never relabelled as the requested missing session.
    missing = [d for d in sessions if d not in values]
    for day in missing[:MAX_EXACT_RECOVERY]:
        q, rows = price_request(requests, 'stock_exact_recovery', ric, day, day, session_set)
        values, added, _ = merge_prices(values, rows)
        provenance.update({d: q['id'] for d in added})
        recovery.append(dict(method='primary_exact_date', query_id=q['id'], recovered_dates=added))
    if len(values) < 2:
        raise DownloadError('insufficient_real_stock_observations')
    history = [dict(date=d, close=values.get(d)) for d in sessions]
    return dict(ric=ric, identity_verified=True, identity=identity, history=history,
                coverage=coverage(history, window), price_query_ids=provenance, recovery=recovery)


def select_option_probes(seed, limit=1):
    """Bounded actual observed near-spot Nov-20 puts; no invented strike grid."""
    if seed.get('source') != SOURCE or seed.get('mode') != 'live' or seed.get('calendar', {}).get('as_of') != SEED_DATE:
        raise DownloadError('invalid_option_seed')
    selected = []
    expiry = date.fromisoformat(OPTION_EXPIRY)
    suffix = f'^{"ABCDEFGHIJKL"[expiry.month-1]}{expiry:%y}'
    for ticker, cfg in UNIVERSE.items():
        item = seed['tickers'][ticker]
        if item.get('identity_verified') is not True or item.get('ric') != cfg['ric']:
            raise DownloadError('unverified_option_seed_identity')
        spots = [r['close'] for r in item['history'] if r['date'] == SEED_DATE]
        if len(spots) != 1 or not valid_price(spots[0]):
            raise DownloadError('invalid_option_seed_spot')
        candidates = []
        for c in item['contracts']:
            if c.get('type') != 'put' or c.get('expiry') != OPTION_EXPIRY or c.get('observed_on') != SEED_DATE:
                continue
            match = re.fullmatch(r'([A-Z]+)([M-X])(\d{2})(\d{2})(\d{5})\.U', c.get('ric', ''))
            if (not match or match[1] != ticker or c.get('terms_verified') is not True
                    or c.get('multiplier') != 100 or not valid_price(c.get('strike'))):
                continue
            encoded = date(2000+int(match[4]), ord(match[2])-ord('M')+1, int(match[3])).isoformat()
            if encoded != OPTION_EXPIRY or int(match[5])/100 != c['strike']:
                continue
            candidates.append(c)
        if not candidates:
            continue
        for c in sorted(candidates, key=lambda x: (abs(x['strike']-spots[0]), x['ric']))[:limit]:
            selected.append(dict(ticker=ticker, observed_ric=c['ric'], expired_ric=c['ric']+suffix,
                                 strike=c['strike'], expiry=OPTION_EXPIRY, observed_on=SEED_DATE,
                                 selection_spot=spots[0], selection=f'nearest {limit} observed put strikes; availability sample, not a strategy selection'))
    return selected


def probe_options(requests, selected):
    results = []
    for option in selected:
        params = dict(start=SEED_DATE, end=OPTION_EXPIRY, interval='1D',
                      adjustments=['exchangeCorrection', 'manualCorrection'])
        # Request Greeks separately so an unsupported field cannot hide valid BBO.
        q, frame = requests.call('historical_option_probe', option['expired_ric'], OPTION_FIELDS[:3], params, history=True)
        dq, delta = requests.call('historical_delta_probe', option['expired_ric'], ['DELTA_EXCH'], params, history=True)
        if frame is not None and delta is not None and list(delta.columns) == ['DELTA_EXCH']:
            if delta.index.is_unique and frame.index.is_unique:
                frame = frame.join(delta, how='outer')  # Exact dated join; no filling.
        result = dict(**option, query_id=q['id'], status='unavailable', dated_records=[],
                      delta_query_id=dq['id'],
                      non_null_counts={f: 0 for f in OPTION_FIELDS}, valid_bid_ask_pairs=0)
        if frame is not None:
            try:
                if len(set(frame.columns)) != len(frame.columns) or not set(frame.columns).issubset(OPTION_FIELDS):
                    raise DownloadError('option_probe_schema')
                result['unreturned_fields'] = [f for f in OPTION_FIELDS if f not in frame.columns]
                records = []
                seen = set()
                for when, row in frame.iterrows():
                    if not isinstance(when, (str, date, datetime, pd.Timestamp)):
                        raise DownloadError('option_probe_date')
                    parsed = pd.to_datetime(when, errors='coerce')
                    if pd.isna(parsed):
                        raise DownloadError('option_probe_date')
                    day = str(parsed.date())
                    if not SEED_DATE <= day <= OPTION_EXPIRY or day in seen:
                        raise DownloadError('option_probe_date')
                    seen.add(day)
                    record = {'date': day}
                    for field in OPTION_FIELDS:
                        value = row[field] if field in frame.columns else None
                        if pd.isna(value):
                            record[field] = None
                        else:
                            if isinstance(value, bool):
                                raise DownloadError('option_probe_value')
                            value = float(value)
                            if not math.isfinite(value) or (field != 'DELTA_EXCH' and value < 0) or (field == 'DELTA_EXCH' and not -1 <= value <= 1):
                                raise DownloadError('option_probe_value')
                            record[field] = value
                    records.append(record)
                result.update(status='observations_returned' if records else 'empty',
                              dated_records=sorted(records, key=lambda r: r['date']),
                              non_null_counts={f: sum(r[f] is not None for r in records) for f in OPTION_FIELDS},
                              valid_bid_ask_pairs=sum(r['BID'] is not None and r['ASK'] is not None and
                                                      0 <= r['BID'] <= r['ASK'] and r['ASK'] > 0 for r in records))
                q['status'] = 'validated'
            except Exception:
                requests.reject(q, 'invalid_option_probe_response')
                result['status'] = 'invalid_response'
        results.append(result)
    return dict(scope='Availability probes, not a chain, fills, synchronized BBO or historical strategy returns',
                historical_chain_complete=False, requested_contracts=len(selected), results=results)


def probe_discovery(requests, window):
    """Test expired discovery coverage; never relabel current search as historical membership."""
    fields = ['RIC', 'StrikePrice', 'ExpiryDate', 'CallPutOption', 'UnderlyingQuoteRIC',
              'LotSize', 'Currency', 'ContractType', 'ExerciseStyle']
    results = {}
    for ticker, cfg in UNIVERSE.items():
        # This is the existing authorized search service, not a new DSS login.
        params = dict(top=100, filter=f"UnderlyingQuoteRIC eq '{cfg['ric']}' and RCSAssetClass eq 'OPT' and IsChain eq false and ExpiryDate ge {window['analysis_start']} and ExpiryDate le {window['analysis_end']}")
        q, frame = requests.call('expired_discovery_capability', cfg['ric'], fields, params, search=True)
        results[ticker] = dict(query_id=q['id'], status=q['status'], row_count=q['row_count'],
                               capped=frame is not None and len(frame) >= 100,
                               historical_membership_verified=False)
    return dict(results=results, historical_chain_complete=False,
                limitation='Current search for expired instruments is a capability probe, not historical chain membership. Empty results do not prove absence of listed options.',
                alternative='Tick History HistoricalChainResolution requires separate DSS/Tick History entitlement; not attempted with Platform credentials.',
                source='https://developers.lseg.com/en/article-catalog/article/how-expand-chain-ric-using-tick-history-rest-api-python')


def collect(ld, *, seed, reference_sha256, environ=None, clock=utc_now, sleeper=time.sleep):
    """Operation callback body. Only called inside query_lseg after confirmation."""
    environ = os.environ if environ is None else environ
    window, sessions = fixed_window()
    selected = select_option_probes(seed, limit=6)
    requests = Requests(ld, environ, clock, sleeper)
    started = timestamp(clock)
    stocks = {t: stock_history(requests, t, cfg['ric'], window, sessions) for t, cfg in UNIVERSE.items()}
    adjustments = {}
    for ticker, cfg in UNIVERSE.items():
        results = []
        for adjusted in (0, 1):
            fields = ['TR.CLOSEPRICE.Date', f'TR.CLOSEPRICE(Adjusted={adjusted})']
            q, _ = requests.call('adjustment_definition_probe', cfg['ric'], fields,
                                 price_parameters(window['query_start'], window['analysis_end']))
            results.append(dict(adjusted=adjusted, query_id=q['id'], status=q['status'], row_count=q['row_count']))
        q, _ = requests.call('corporate_action_probe', cfg['ric'], CA_FIELDS,
                             dict(SDate=window['query_start'], EDate=window['analysis_end']))
        adjustments[ticker] = dict(validation='raw_probe_only; not reconciled with primary prices; empty response is not proof of no events',
                                  price_comparisons=results, corporate_actions=dict(
            query_id=q['id'], status=q['status'], row_count=q['row_count']))
    options = probe_options(requests, selected)
    discovery = probe_discovery(requests, window)
    for result in options['results']:
        stock = stocks[result['ticker']]
        expiry_close = next((r['close'] for r in stock['history'] if r['date'] == result['expiry']), None)
        result['expiry_outcome'] = dict(underlying_close=expiry_close,
            put_intrinsic_per_share=None if expiry_close is None else max(0., result['strike']-expiry_close),
            definition='Hypothetical terminal intrinsic from actual expiry-day stock close; not proof of exercise, assignment, execution or net strategy return.')
    evidence = dict(
        schema_version=SCHEMA_VERSION, kind='independent_historical_download', source=SOURCE,
        mode='fresh_platform_download', retrieved_at=timestamp(clock), window=window, tickers=stocks,
        metadata=dict(plan=dict(PLAN), field='TR.PriceClose', currency='USD', calendar='XNYS',
                      frozen_reference_sha256=reference_sha256, option_seed_sha256=digest(seed),
                      option_seed_path=SEED_FILE, acquisition_started_at=started,
                      caching='none; seed selects option identities only, never supplies downloaded prices',
                      price_semantics='TR.PriceClose as retrieved; no Adjusted parameter or additional adjustment. US regular cash dividends are not total-return adjusted.',
                      probe_semantics='TR.CLOSEPRICE and corporate-action responses are separate audit evidence; never substituted into stock history.',
                      sources=GUIDANCE),
        source_queries=requests.queries, raw_records=requests.raw,
        coverage={t: item['coverage'] for t, item in stocks.items()},
        audit=dict(no_price_filling=True, production_data_unchanged=True, orders_written=False,
                   original_overlap_comparison='not_performed; caller must compare with frozen reference',
                   maximum_annual_chunks_per_ric=len(list(annual_chunks(window['query_start'], window['analysis_end']))),
                   maximum_exact_recovery_queries_per_ticker=MAX_EXACT_RECOVERY,
                   maximum_option_contracts=6*len(UNIVERSE), raw_records_policy='Content tables only; encrypted artifact; error text and credential-like strings redacted'),
        probes=dict(adjustments=adjustments, historical_options=options, historical_discovery=discovery), option_probes=options)
    return dict(evidence=evidence, evidence_sha256=digest(evidence))


def validate_download(obj):
    """Validate the normalized contract, independently of download success flags."""
    try:
        if set(obj) != {'evidence', 'evidence_sha256'}:
            raise DownloadError('wrapper_schema')
        e = obj['evidence']
        if obj['evidence_sha256'] != digest(e):
            raise DownloadError('digest_mismatch')
        required = {'schema_version', 'kind', 'source', 'mode', 'retrieved_at', 'window',
                    'tickers', 'metadata', 'source_queries', 'raw_records', 'coverage',
                    'audit', 'probes', 'option_probes'}
        if not required.issubset(e) or not isinstance(e['raw_records'], dict):
            raise DownloadError('evidence_schema')
        window, sessions = fixed_window()
        if (e['schema_version'] != SCHEMA_VERSION or e['source'] != SOURCE
                or e['kind'] != 'independent_historical_download' or e['mode'] != 'fresh_platform_download'
                or e['window'] != window or e['metadata']['plan'] != PLAN
                or e['metadata']['field'] != 'TR.PriceClose' or e['metadata']['currency'] != 'USD'
                or set(e['tickers']) != set(UNIVERSE)):
            raise DownloadError('fixed_contract_mismatch')
        retrieved = datetime.fromisoformat(e['retrieved_at'])
        started = datetime.fromisoformat(e['metadata']['acquisition_started_at'])
        if (retrieved.tzinfo is None or started.tzinfo is None or retrieved < started
                or started.date() <= date.fromisoformat(window['analysis_end'])):
            raise DownloadError('retrieval_timestamp_invalid')
        for key in ('frozen_reference_sha256', 'option_seed_sha256'):
            if not re.fullmatch(r'[0-9a-f]{64}', e['metadata'][key]):
                raise DownloadError('source_digest_invalid')
        queries = {q['id']: q for q in e['source_queries']}
        if len(queries) != len(e['source_queries']):
            raise DownloadError('duplicate_query_ids')
        for q in queries.values():
            if q['status'] not in ('validated', 'returned', 'failed', 'rejected'):
                raise DownloadError('incomplete_query_audit')
            if q['status'] in ('validated', 'returned'):
                raw = e['raw_records'][q['id']]
                if (raw['format'] != 'redacted_content_table' or len(raw['data']) != q['row_count']
                        or len(raw['index']) != q['row_count']
                        or any(len(row) != len(raw['columns']) for row in raw['data'])):
                    raise DownloadError('raw_query_audit_invalid')
        normalized_queries={}
        for t, cfg in UNIVERSE.items():
            item = e['tickers'][t]
            identity = item['identity']
            q = queries[identity['query_id']]
            if (item['identity_verified'] is not True or item['ric'] != cfg['ric']
                    or identity['ric'] != cfg['ric'] or identity['ticker'] != t
                    or q['kind'] != 'identity' or q['status'] != 'validated' or q['ric'] != cfg['ric']):
                raise DownloadError('ticker_identity_invalid')
            if e['raw_records'][q['id']]['data'] != [[cfg['ric'], t]]:
                raise DownloadError('identity_response_invalid')
            rows = item['history']
            if [r['date'] for r in rows] != sessions:
                raise DownloadError('session_grid_or_period_invalid')
            for row in rows:
                if set(row) != {'date', 'close'} or (row['close'] is not None and not valid_price(row['close'])):
                    raise DownloadError('historical_price_invalid')
                if row['close'] is not None:
                    pq = queries[item['price_query_ids'][row['date']]]
                    if (pq['status'] != 'validated' or pq['fields'] != PRICE_FIELDS
                            or pq['kind'] not in ('stock_annual', 'consolidated_annual', 'stock_exact_recovery')
                            or pq['parameters']['Curn'] != 'USD' or pq['parameters']['Frq'] != 'D'
                            or 'Adjusted' in pq['parameters'] or pq['ric'] not in (cfg['ric'], t)
                            or not pq['parameters']['SDate'] <= row['date'] <= pq['parameters']['EDate']):
                        raise DownloadError('price_query_provenance_invalid')
                    # A digest is an integrity check, not proof that a positive
                    # normalized value was actually present in the raw response.
                    if pq['id'] not in normalized_queries:
                        raw=e['raw_records'][pq['id']]
                        frame=pd.DataFrame(raw['data'],columns=raw['columns'])
                        actual=normalize_closes(frame,pq['ric'],pq['parameters']['SDate'],pq['parameters']['EDate'])
                        normalized_queries[pq['id']]={r['date']:r['close'] for r in actual}
                    observed=normalized_queries[pq['id']].get(row['date'])
                    if observed is None or not math.isclose(row['close'],observed,rel_tol=0,abs_tol=1e-8):
                        raise DownloadError('price_not_in_raw_response')
                    if pq['ric'] == t and not any(
                            r.get('method') == 'consolidated' and r.get('accepted') is True
                            and r.get('overlap_matches', 0) >= MIN_OVERLAP
                            and row['date'] in r.get('recovered_dates', [])
                            and r.get('identity', {}).get('ric') == t
                            and r.get('identity', {}).get('ticker') == t
                            and queries[r['identity']['query_id']]['status'] == 'validated'
                            and e['raw_records'][r['identity']['query_id']]['data'] == [[t, t]]
                            for r in item['recovery']):
                        raise DownloadError('consolidated_recovery_audit_invalid')
            calculated = coverage(rows, window)
            if calculated['observed_sessions'] < 2 or item['coverage'] != calculated or e['coverage'][t] != calculated:
                raise DownloadError('coverage_invalid')
        if (e['probes']['historical_options']['historical_chain_complete'] is not False
                or e['option_probes'] != e['probes']['historical_options']):
            raise DownloadError('unsupported_chain_completeness')
    except Exception:
        # Do not echo malformed files, paths, embedded values or parsing exceptions.
        raise DownloadError('download_contract_validation_failed') from None
    return obj


def load_download(path):
    """Return the validated {evidence, evidence_sha256} wrapper, not just evidence."""
    try:
        with Path(path).open(encoding='utf-8') as handle:
            obj = json.load(handle)
        return validate_download(obj)
    except Exception:
        raise DownloadError('download_file_invalid_or_unavailable') from None


def output_target(root, output=None):
    root = Path(root).resolve()
    directory = root / ARTIFACT_DIRECTORY
    target = Path(output) if output is not None else directory / CIPHER_NAME
    if not target.is_absolute():
        target = root / target
    if (directory.resolve() != directory or target.resolve().parent != directory
            or target.name != CIPHER_NAME or target.exists() or target.is_symlink()):
        raise DownloadError('output_must_be_new_dedicated_artifact')
    return target


def download(root, *, confirmed=False, output=None, environ=None, reference_sha256=None, recipient=None):
    """Fresh pull only. Refuse an existing artifact BEFORE opening a session."""
    if confirmed is not True:
        raise DownloadError('explicit_live_download_confirmation_required')
    try:
        root = Path(root).resolve()
        target = output_target(root, output)
        if not isinstance(reference_sha256, str) or not re.fullmatch(r'[0-9a-f]{64}', reference_sha256):
            raise DownloadError('frozen_reference_digest_required')
        public_key(recipient)  # Fail before authentication if encryption input is invalid.
        with (root / SEED_FILE).open(encoding='utf-8') as handle:
            seed = json.load(handle)
        select_option_probes(seed)  # Validate metadata before opening a session.
        window, _ = fixed_window()
        environ = os.environ if environ is None else environ
        obj = query_lseg(date.fromisoformat(window['query_start']), date.fromisoformat(window['analysis_end']),
                         environ=environ, operation=lambda ld: collect(
                             ld, seed=seed, reference_sha256=reference_sha256, environ=environ))
        validate_download(obj)
        # Only this new artifact is written. Never write to docs/data or thesis data.
        plaintext = json.dumps(obj, sort_keys=True, allow_nan=False).encode()
        payload = json.dumps(encrypt(plaintext, recipient), sort_keys=True, allow_nan=False) + '\n'
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('x', encoding='utf-8') as handle:
            handle.write(payload)
        return obj
    except Exception:
        raise DownloadError('independent_download_failed_no_fallback') from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--confirm-live-download', action='store_true',
                        help='Explicitly authorize this one fresh LSEG Platform download')
    parser.add_argument('--output', help='New encrypted artifact in artifacts/thesis-history only')
    parser.add_argument('--reference-sha256', default=os.environ.get('THESIS_REFERENCE_SHA256'))
    parser.add_argument('--recipient', default=os.environ.get('THESIS_RECIPIENT_PUBLIC_KEY'))
    args = parser.parse_args(argv)
    try:
        obj = download(Path(__file__).resolve().parents[1], confirmed=args.confirm_live_download, output=args.output,
                       reference_sha256=args.reference_sha256, recipient=args.recipient)
    except Exception:
        print('Independent historical download not completed. Confirmation, frozen reference, valid inputs and authorized Platform access are required. No cached evidence substituted.')
        return 1
    print(json.dumps(dict(status='downloaded', evidence_sha256=obj['evidence_sha256'],
                          complete=all(c['complete'] for c in obj['evidence']['coverage'].values()))))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
