"""Gate empirical runs and summarize read-only probes without publishing raw prices."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone

from .calendar import Calendar
from .config import Config
from .data import Market, finite, mid
from .selection import long_call


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def audit_dataset(data,cfg):
    issues=[];md=data.get('metadata',{})
    cal=Calendar(cfg.start,cfg.end)
    m=Market(data,cfg,cal)
    if md.get('research_window_locked') is not True or md.get('config')!=cfg.to_dict():
        issues.append('Research window/config must be locked and match the input metadata before P&L.')
    unsupported=[c['id'] for c in m.contracts.values() if not m.standard(c) or not c.get('terms_source')]
    if unsupported:
        issues.append('Unresolved contract terms/identity for: '+', '.join(unsupported))
    if md.get('dividend_coverage_verified') is not True:
        issues.append('Historical cash-dividend coverage is unverified; absence of records is not proof of zero dividends.')
    if not md.get('candidate_universe') or not md.get('window_selection_reason'):
        issues.append('Document historical candidate-universe scope and data-only window-selection rationale.')
    eligible=[w['date'] for w in cal.weekly() if long_call(m,w['date'])[0] is not None]
    if not eligible:
        issues.append('No eligible, observed, standard 365–550 DTE long call at any prior-session signal.')
    if not any(m.standard(c) and c.get('series_friday') for c in m.contracts.values()):
        issues.append('No verified historical Friday-series short-call universe.')
    if not any(finite(s.get('price')) for s in m.stocks.values()):
        issues.append('No actual unadjusted stock observations.')
    return dict(ready=not issues,blocking_issues=issues,eligible_long_signal_dates=eligible,
                stock_observations=len(m.stocks),option_observations=len(m.quotes),contracts=len(m.contracts),
                valid_option_marks=sum(mid(q) is not None for q in m.quotes.values()),dividends=len(m.dividends),
                quote_precision=md.get('source_precision'),candidate_universe=md.get('candidate_universe'),
                availability_policy=md.get('availability_policy'),quote_basis=md.get('quote_basis'),
                dividend_assignment_enabled=md.get('dividend_assignment_enabled',False),
                standard_assumption_policy=md.get('standard_assumption_policy'),
                assumption_contracts=sum(c.get('terms_status')=='research assumption' for c in m.contracts.values()),
                individually_verified_contracts=sum(c.get('standard_verified') is True for c in m.contracts.values()),
                corporate_action_review=md.get('corporate_action_review'),
                excluded_contracts=md.get('exclusions',[]),window_selection_reason=md.get('window_selection_reason'),
                window_lock=md.get('window_lock'),long_mode_note=md.get('long_mode_note'),
                request_errors=[r for r in md.get('requests',[]) if r.get('error')])


def from_probes(probe_dir,old_cache):
    p=Path(probe_dir)
    def read(name): return json.loads((p/name).read_text())
    old=json.loads(Path(old_cache).read_text())
    stock=read('stock_daily.json');div=read('dividends.json');long=read('AAPLI172723000.U.json')
    expired=read('expired_daily.json');terms_error=read('expired_terms_history.json')
    def counts(raw):
        headers=[h['name'] for h in raw.get('headers',[])]
        rows=[dict(zip(headers,row)) for row in raw.get('data',[])]
        dates=sorted(r['DATE'] for r in rows)
        return dict(rows=len(rows),start=dates[0] if dates else None,end=dates[-1] if dates else None,
                    bid_ask_pairs=sum(finite(r.get('BID')) and finite(r.get('ASK')) for r in rows),
                    delta_rows=sum(finite(r.get('DELTA')) for r in rows))
    oldexpiries=sorted({q['expiry'] for q in old['options']})
    oldids=sorted({q['ric'] for q in old['options']})
    blocks=[
      'Target-period expired AAPL option search returned zero records; the existing cache covers only 56 observed short-call identifiers across nine July–September expiries, not a year-long historical chain.',
      'Expired-contract reference snapshot fields were empty. Historical LOT_SIZE, CONTR_SIZE, EXPIR_DATE, LAST_TRDAY and STRIKE_PRC were explicitly rejected (90006) for the observed AAPLG102631000.U^G26 contract.',
      'Verified historical multipliers, standard deliverables and last-trading dates are still required for the expired short calls; current live long-call Standard/100-lot metadata does not validate those expired contracts.'
    ]
    files=sorted(p.glob('*.json'))
    return dict(schema_version=1,status='blocked',ready=False,empirical_backtest_complete=False,
       audit_completed_at=datetime.fromtimestamp(max(f.stat().st_mtime for f in files),timezone.utc).isoformat(),
       target_window=dict(start=Config().start,end=Config().end),actual_backtest_window=None,
       long_selection_mode=Config().long_mode,
       long_mode_reason='Proxy mode predeclared before P&L. Old cache had no Greeks; a later one-contract probe returned short-call DELTA, not a validated long-universe delta panel. No mode switching within a run.',
       window_decision='No valid common window selected. Target dates remain locked; no P&L computed or favorable subperiod selected.',
       blocking_issues=blocks,
       timing_limitations=['Daily responses identify DATE/endPeriod only. Exact quote synchronization and EOD publication times are unknown; no observed 16:00 quote or fill timestamp is available. The proposed next-session 09:00 availability checkpoint remains an assumption without provider evidence.'],
       stock=counts(stock),long_probe=dict(ric='AAPLI172723000.U',**counts(long)),
       expired_probe=dict(ric='AAPLG102631000.U^G26',**counts(expired)),
       dividends=dict(records=len(div),ex_dates=[r['Dividend Ex Date'][:10] for r in div]),
       expired_search_records=len(read('search_expired.json')),live_search_records=len(read('search_long.json')),
       old_cache=dict(sha256=sha(old_cache),stock_rows=len(old['stock']),option_rows=len(old['options']),contracts=len(oldids),
                      expiries=oldexpiries,overlap='2026-07-06 through 2026-09-11; historical assignment only, not a comparable new result'),
       exact_terms_error=terms_error,private_probe_hashes=[dict(file=f.name,sha256=sha(f)) for f in files],
       sources=[
         'https://developers.lseg.com/en/api-catalog/lseg-data-platform/lseg-data-library-for-python/tutorials/content-tutorials/historical-pricing',
         'https://community.developers.lseg.com/discussion/comment/110304',
         'https://community.developers.lseg.com/discussion/82292/query-corporate-action-calendar'],
       missing_data_request=dict(underlying='AAPL.O',observations_from='2025-09-30',observations_through='2026-09-30',
          contract_fields=['historically listed identifiers and first-known dates','expiry','actual last trading date','Friday-series identity',
                           'strike','multiplier','standard deliverable','historical terms source'],
          price_fields=['date-level closing BID/ASK and their consistency definition','TRDPRC_1','signal-time availability evidence'],
          long_eligibility='365–550 DTE at signal, actually observed strikes; proxy <=75% of prior-session stock price',
          route='An authorized historical security-master/chain export (e.g. licensed LSEG Tick History) plus quotes for exact identifiers; no new account or entitlement was assumed.'))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--probe-dir',type=Path,required=True);p.add_argument('--old-cache',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();result=from_probes(args.probe_dir,args.old_cache)
    args.output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps({k:result[k] for k in ('status','stock','long_probe','dividends','expired_search_records')},indent=2))
