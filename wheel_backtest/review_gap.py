"""Read-only reinspection of existing real responses; never edits market input."""
import argparse
import hashlib
import json
from pathlib import Path
from .config import Config
from .data import Market
from pmcc_backtest.repair_coverage import event_mark


def rows(raw):
    names = [h['name'] for h in raw.get('headers', [])]
    return [dict(zip(names, values)) for values in raw.get('data', [])]


def review(input_path, config_path):
    cfg = Config(**json.loads(config_path.read_text()))
    data = json.loads(input_path.read_text()); market = Market(data, cfg)
    day = '2026-08-13'; ric = 'AAPLH142632250.U^H26'
    root = input_path.parent
    names = [
        'gap_recheck_20261027_v2/daily_all_fields.json',
        'gap_recheck_20261027_v2/minute_regular_session.json',
        'gap_recheck_20261027_v2/quote_final_60s.json',
        'gap_recheck_20261027_v2/quote_final_30m.json',
        'gap_event_verification_20261027_v1/quote_field_timestamps.json',
        'gap_event_verification_20261027_clock_v1/quote_clock_variants.json']
    evidence = []
    for name in names:
        file = root / name; raw_bytes = file.read_bytes(); saved = json.loads(raw_bytes); raw = saved['raw']
        if raw['universe']['ric'] != ric: raise ValueError('Wrong target RIC')
        observed = rows(raw)
        selected = [r for r in observed if r.get('DATE') == day or r.get('DATE_TIME', '').startswith(day+'T19:')]
        evidence.append(dict(file=name, sha256=hashlib.sha256(raw_bytes).hexdigest(),
            row_count=len(observed), parameters=saved['parameters'],
            selected_rows=[{k:r.get(k) for k in ('DATE', 'DATE_TIME', 'EVENT_TYPE', 'SOURCE_DATETIME', 'BID', 'ASK', 'MID_PRICE', 'TRDPRC_1', 'BID_NUMMOV', 'ASK_NUMMOV') if k in r} for r in selected],
            status=raw.get('status'), eligible_under_current_rule=event_mark(raw, day, market.calendar.close(day)) is not None))
    eligible = market.closing_quote(ric, day)
    if eligible is not None or any(e['eligible_under_current_rule'] for e in evidence):
        raise ValueError('Eligible evidence found: review before declaring this gap unresolved')
    return dict(date=day, contract=ric, status='unresolved_existing_valuation_rule',
        input_sha256=hashlib.sha256(input_path.read_bytes()).hexdigest(),
        daily_quote=market.quote(ric, day), evidence=evidence,
        reason='Daily BID and MID_PRICE are null. Quote-only requests return no event in the final 60 seconds (also none in the final 30 minutes). The 15:58:36 record is a trade event with BID=0 / ASK=0.01, but individual quote timestamps were unsupported; its trade timestamp does not establish freshness of both quote legs. The 15:59 endPeriod minute bar has BID=0 / ASK=0.01 and ASK_NUMMOV=1, but BID_NUMMOV is null and synchronized leg times are unknown. It is an aggregate, not the required complete quote event. Zero bid itself is valid. No change to the valuation rule, no trade-price/theoretical-price substitution, no prior/future-price fill.',
        source='https://developers.lseg.com/en/api-catalog/lseg-data-platform/lseg-data-library-for-python/tutorials/content-tutorials/historical-pricing',
        action='Retain NAV null; retain both adjacent return gaps and full-period MDD/Sharpe unavailable. This review makes no new API request.')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path, required=True); p.add_argument('--config', type=Path, default=Path('wheel/config.json'))
    p.add_argument('--output', type=Path, required=True); a = p.parse_args()
    result = review(a.input, a.config)
    a.output.write_text(json.dumps(result, sort_keys=True, indent=2, allow_nan=False)+'\n')
    print(json.dumps({k:result[k] for k in ('date','contract','status','action')}, indent=2))
