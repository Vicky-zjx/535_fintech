"""Immutable historical summary, separate from daily prices and forward state.

Local preparation only. Aggregation is NOT a redistribution license.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
from final_project.data_provider import digest
from final_project.sanji_orders import atomic_json
from .extension_plan import PLAN

NAME='fixed_research.json'


def load(root):
    p=Path(root)/'investment-thesis/data'/NAME
    if not p.exists():return None
    obj=json.loads(p.read_text());b=obj['content']
    if obj['content_sha256']!=digest(b) or b['reference']['evidence']['reference_end']!=PLAN['reference_end']:
        raise ValueError('Fixed research integrity/cutoff mismatch; no automatic rebuild')
    return obj


def create(root,private_evidence):
    from . import reference
    from .download_history import load_download
    from .put_payoff import analyze
    root=Path(root);p=root/'investment-thesis/data'/NAME
    if p.exists():raise FileExistsError('Fixed research already exists; explicit reviewed version required')
    d=json.loads((root/'investment-thesis/data/thesis_tracker.json').read_text())
    x=d['lecture_extension'];original=reference.load(root)
    e=load_download(private_evidence)['evidence']
    if x['historical']['expanded']['evidence_sha256']!=digest(e):raise ValueError('Use the preserved validated five-year evidence')
    b=dict(version=1,kind='fixed_historical_research_summary',
           licensing='Pending verification of public display rights, including derived statistics. Local use only.',
           historical=deepcopy(x['historical']),acceptable_risk_candidates=deepcopy(x['acceptable_risk_candidates']),
           option_economics=deepcopy(x['option_economics']),monitoring_inventory=deepcopy(x['monitoring_inventory']),
           reference={'evidence_sha256':original['evidence_sha256'],
                      'evidence':{k:deepcopy(original['evidence'][k]) for k in ('reference_end','window','original_reliability')}},
           hypothetical_put_payoff=analyze(e))
    obj=dict(content=b,content_sha256=digest(b));atomic_json(p,obj);return obj


if __name__=='__main__':
    from .import_history import private_history_path
    p=argparse.ArgumentParser();p.add_argument('--initialize',action='store_true',required=True);p.parse_args()
    root=Path(__file__).resolve().parents[1];private=private_history_path(root)
    if private is None:raise SystemExit('THESIS_PRIVATE_HISTORY is required only for explicit fixed research initialization')
    obj=create(root,private);print('Fixed summaries initialized locally; publication permission remains Pending. '+obj['content_sha256'])
