"""Read-only IBKR public product-search verification; no login or trading API."""
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.request import Request, urlopen
from .sanji_orders import atomic_json
from .strategy_config import UNIVERSE

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
