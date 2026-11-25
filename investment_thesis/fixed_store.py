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
PUBLIC_NAME='fixed_research_public.json'


def load(root):
    p=Path(root)/'investment-thesis/data'/NAME
    if p.exists():
        obj=json.loads(p.read_text())
    else:
        p=p.with_name(PUBLIC_NAME)
        if not p.exists():return None
        public=json.loads(p.read_text())
        from .publication import assert_summary
        assert_summary(public)
        if (public.get('kind')!='fixed_research_aggregate_release'
                or public.get('content_sha256')!=digest(public.get('content'))):
            raise ValueError('Fixed release integrity mismatch')
        content=deepcopy(public['content'])
        for result in content.get('historical',{}).get('download_audit',{}).get('option_probes',{}).get('results',[]):
            counts=result.pop('non_null_field_counts',{})
            if any(not k.endswith('_count') or type(v) is not int or v<0 for k,v in counts.items()):
                raise ValueError('Invalid fixed audit count')
            result['non_null_counts']={k[:-6]:v for k,v in counts.items()}
        obj=dict(content=content,content_sha256=public['source_content_sha256'])
    b=obj['content']
    if obj['content_sha256']!=digest(b) or b['reference']['evidence']['reference_end']!=PLAN['reference_end']:
        raise ValueError('Fixed research integrity/cutoff mismatch; no automatic rebuild')
    return obj


def prepare_release(root):
    """Package existing aggregates only; no recalculation or permission claim."""
    root=Path(root);obj=load(root)
    if obj is None:raise ValueError('Preserved fixed research is required')
    content=deepcopy(obj['content'])
    for result in content.get('historical',{}).get('download_audit',{}).get('option_probes',{}).get('results',[]):
        counts=result.pop('non_null_counts',{})
        if any(type(v) is not int or v<0 for v in counts.values()):
            raise ValueError('Audit field counts must not contain quotes')
        result['non_null_field_counts']={k+'_count':v for k,v in counts.items()}
    public=dict(kind='fixed_research_aggregate_release',content=content,
                source_content_sha256=obj['content_sha256'],content_sha256=digest(content))
    from .publication import assert_summary
    assert_summary(public)
    target=root/'investment-thesis/data'/PUBLIC_NAME
    if target.exists():
        if json.loads(target.read_text())!=public:raise FileExistsError('Do not replace a different frozen release')
    else:atomic_json(target,public)
    return target


def create(root,private_evidence):
    from . import reference
    from .download_history import load_download
    from .put_payoff import analyze
    root=Path(root);p=root/'investment-thesis/data'/NAME
    if p.exists() or p.with_name(PUBLIC_NAME).exists():
        raise FileExistsError('Fixed research already exists; explicit reviewed version required')
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
    p=argparse.ArgumentParser();mode=p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--initialize',action='store_true');mode.add_argument('--prepare-release',action='store_true')
    args=p.parse_args();root=Path(__file__).resolve().parents[1]
    if args.prepare_release:
        prepare_release(root);print('Fixed aggregate release prepared locally; display permission remains Pending.')
    else:
        private=private_history_path(root)
        if private is None:raise SystemExit('THESIS_PRIVATE_HISTORY is required only for explicit fixed research initialization')
        obj=create(root,private);print('Fixed summaries initialized locally; publication permission remains Pending. '+obj['content_sha256'])
