"""Read-only IBKR public product-search verification; no login or trading API."""
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.request import Request, urlopen
from .sanji_orders import atomic_json
from .strategy_config import UNIVERSE, VERIFIED_CONIDS

BASE = 'https://www.interactivebrokers.com/portal.proxy/v1/mkt'
NAMES = {'BAC': 'BANK OF AMERICA CORP', 'KO': 'COCA-COLA CO/THE',
         'PFE': 'PFIZER INC', 'F': 'FORD MOTOR CO'}


def verified_mapping(evidence):
    result = {}
    for ticker in UNIVERSE:
        row = evidence['records'][ticker]
        conid = row['conid']
        details = row['detail_response'].get('secdef', [])
        if type(conid) is not int or conid <= 0 or len(details) != 1:
            raise ValueError('Invalid/ambiguous IBKR security definition')
        d = details[0]
        expected = dict(conid=conid, ticker=ticker, name=NAMES[ticker], currency='USD',
                        listingExchange='NYSE', assetClass='STK', type='COMMON', countryCode='US')
        if any(d.get(k) != v for k, v in expected.items()):
            raise ValueError(f'{ticker}: IBKR identity mismatch')
        s = row['search_response']
        if s.get('symbol') != ticker or str(s.get('conid')) != str(conid) or s.get('description') != 'NYSE':
            raise ValueError('Search and security definition disagree')
        if row['search_url'] != BASE + '/iserver/secdef/search' or row['detail_url'] != BASE + '/trsrv/secdef?conids=' + str(conid):
            raise ValueError('Non-official IBKR evidence source')
        result[ticker] = conid
    if len(set(result.values())) != len(result):
        raise ValueError('Duplicate IBKR identifiers')
    return result


def request(url, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = Request(url, data=data, headers={'Content-Type': 'application/json',
                                         'User-Agent': 'FIN535-contract-verification/1.0'})
    with urlopen(req, timeout=30) as response:
        return json.load(response)


def resolve_identifiers(evidence, course, configured=None):
    """Validate static identity; audit course coverage without guessing enrollment.

    Literal-strike/expiry JSON needs the stock identity, not a chain token resolver.
    Missing course coverage is an execution dependency; any conflicting mapping is
    a hard error. No nightly IBKR authentication or discovery request is needed.
    """
    from .data_provider import conids_from_course
    configured = VERIFIED_CONIDS if configured is None else configured
    verified = verified_mapping(evidence)
    if set(configured) != set(UNIVERSE) or any(
            type(configured[t]) is not int or configured[t] != verified[t] for t in UNIVERSE):
        raise ValueError('Configured conids are missing or conflict with verified IBKR identities')
    if not isinstance(course, dict):
        raise ValueError('Invalid course identifier document')
    observed = conids_from_course(course)
    if any(observed[t] != configured[t] for t in observed):
        raise ValueError('Course conid mapping conflicts with verified IBKR identity')
    for t, conid in configured.items():
        entry = course.get(str(conid), {})
        if not isinstance(entry, dict):
            raise ValueError('Invalid course security metadata')
        for key in ('symbol', 'ticker'):
            if entry.get(key) and entry[key] != t:
                raise ValueError('Course security symbol conflicts with verified conid')
        if entry.get('ric') and entry['ric'] != UNIVERSE[t]['ric']:
            raise ValueError('Course security RIC conflicts with verified conid')
    coverage = {t: {'conid': configured[t], 'identity': 'verified_static_IBKR',
                    'course_binding': 'confirmed' if t in observed else 'unconfirmed',
                    'contract_open_coverage': 'unverified'} for t in UNIVERSE}
    return dict(configured), coverage


def verify():
    records = {}
    for ticker in UNIVERSE:
        payload = {'symbol': ticker, 'secType': 'STK'}
        url = BASE + '/iserver/secdef/search'
        rows = request(url, payload)
        selected = [r for r in rows if r.get('symbol') == ticker and r.get('description') == 'NYSE'
                    and any(s.get('secType') == 'STK' for s in r.get('sections', []))]
        if len(selected) != 1:
            raise ValueError(f'{ticker}: ambiguous/missing NYSE common stock')
        row = selected[0]
        conid = int(row['conid'])
        detail_url = BASE + '/trsrv/secdef?conids=' + str(conid)
        detail = request(detail_url)
        records[ticker] = {'conid': conid, 'search_url': url, 'search_payload': payload,
                           'search_response': row, 'detail_url': detail_url, 'detail_response': detail}
    result = {'source': 'IBKR public Products, Exchanges and Contracts Search',
              'retrieved_at': datetime.now(timezone.utc).isoformat(), 'records': records}
    verified_mapping(result)
    return result


if __name__ == '__main__':
    result = verify()
    atomic_json(Path(__file__).resolve().parents[1]/'docs/data/conid_verification.json', result)
    for ticker, row in result['records'].items():
        print(ticker, row['conid'], 'NYSE / USD / COMMON: verified')
