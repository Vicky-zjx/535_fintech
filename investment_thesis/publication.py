"""Local aggregate preview and deny-by-default publication audit.

Sanitization is not permission. No export, git or deployment is performed here.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
from final_project.data_provider import digest

FORBIDDEN={'rows','history','daily_rows','raw_records','dated_records','reference_close',
           'end_close','selection_spot','underlying_close','BID','ASK','DELTA_EXCH',
           'recipient_private_key','password','app_key'}


def assert_summary(obj):
    if isinstance(obj,dict):
        if FORBIDDEN.intersection(obj):raise ValueError('Private record/price field in proposed browser payload')
        for v in obj.values():assert_summary(v)
    elif isinstance(obj,list):
        for v in obj:assert_summary(v)


def preview_payload(d):
    z=deepcopy(d);z.pop('rows')
    # Counts are not quotes. Give audit counts unambiguous names while keeping
    # quote-field names forbidden everywhere in the browser data.
    audit=z.get('lecture_extension',{}).get('historical',{}).get('download_audit',{})
    for result in audit.get('option_probes',{}).get('results',[]):
        counts=result.pop('non_null_counts',{})
        result['non_null_field_counts']={k+'_count':v for k,v in counts.items()}
    z['projection']=dict(version=1,kind='aggregate_local_preview_not_licensed_publication',
        row_counts={t:len(v) for t,v in d['rows'].items()},
        source_proof={k:deepcopy(d[k]) for k in ('source','strategy_revision','market_snapshot_sha256','market_retrieved_at','historical_generated_at','window')},
        historical_signals_sha256=d['historical_signals_sha256'],
        permission='Pending: aggregated research, chart series and prospective statistics also require license verification.',
        raw_price_paths_included=False)
    # Monitoring curves contain cumulative aggregate statistics, not price paths.
    assert_summary(z)
    z['projection']['summary_sha256']=digest(z)
    return z


def audit(root):
    root=Path(root);config=root/'investment_thesis/publication_permission.json'
    approval=json.loads(config.read_text()) if config.exists() else {}
    scopes=['historical_aggregate_statistics','daily_aggregate_charts','prospective_aggregate_charts']
    allowed=(approval.get('status')=='confirmed' and all(approval.get('scopes',{}).get(s) is True for s in scopes)
             and bool(approval.get('verified_by')) and bool(approval.get('evidence_reference'))
             and approval.get('safe_hosting_plan_verified') is True)
    p=root/'investment-thesis/data/public_tracker.json'
    if p.exists():assert_summary(json.loads(p.read_text()))
    return dict(publication_allowed=bool(allowed),status='Approved scope recorded' if allowed else 'Pending license confirmation; no public export authorized',
        candidate_assets=['investment-thesis/index.html','investment-thesis/style.css','investment-thesis/app.js',
            'investment-thesis/reliability.js','investment-thesis/lecture.js','investment-thesis/payoff.js',
            'investment-thesis/data/public_tracker.json','investment-thesis/data/refresh_status.json'],
        never_publish=['investment-thesis/data/thesis_tracker.json','investment-thesis/data/thesis_observations.csv',
            'investment-thesis/data/reference_2026-11-23.json','.thesis-state/',
            'docs/data/market_snapshot.json','docs/data/historical_signals.json','private historical download','recipient.key'],
        deployment_warning='Existing main/root Pages hosting and public Git history are NOT an allowlisted export. A new safe bundle alone does not retract previously published raw files. Review existing exposure and choose a publication plan before any main push.',
        code_only='Original source code, generic methodology and classroom formulas do not themselves contain downloaded prices; license, security and repository review still precede publication.',
        evidence_needed='Written institutional/LSEG and relevant exchange permission covering public derived statistics, chart time series and this GitHub Pages audience; not merely API entitlement.')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--require-approval',action='store_true');args=p.parse_args()
    r=audit(Path(__file__).resolve().parents[1]);print(json.dumps(r,indent=2))
    raise SystemExit(2 if args.require_approval and not r['publication_allowed'] else 0)
