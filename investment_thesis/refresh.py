"""Transactional independent tracker refresh; retain validated evidence on failure.

No credentials, API calls, order writes, or deployment. The downstream workflow
may publish the small failure record without publishing a failed calculation.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
from .research import build
from .validate import check
from final_project.sanji_orders import atomic_json

OUTPUTS = ('thesis_tracker.json', 'thesis_observations.csv', 'public_tracker.json')


def refresh(root, now, upstream='manual', verify_page=False):
    root = Path(root)
    data = root/'investment-thesis/data'
    data.mkdir(parents=True, exist_ok=True)
    saved = {name:(data/name).read_bytes() if (data/name).exists() else None for name in OUTPUTS}
    from .forward_store import path as state_path
    private_state=state_path(root)
    state_saved=private_state.read_bytes() if private_state.exists() else None
    retained = json.loads(saved['thesis_tracker.json']) if saved['thesis_tracker.json'] else {}
    status = dict(schema_version=1, attempted_at=now.isoformat(),
                  context='GitHub Actions' if os.environ.get('GITHUB_ACTIONS')=='true' else 'local verification',
                  upstream_conclusion=upstream, status='running', reason=None,
                  evidence_generated_at=retained.get('generated_at'),
                  market_snapshot_sha256=retained.get('market_snapshot_sha256'))
    atomic_json(data/'refresh_status.json',status)
    try:
        if upstream not in ('manual','success'):
            status['reason']='Upstream nightly workflow did not succeed; previous validated evidence retained.'
            raise RuntimeError('upstream_failure')
        from .fixed_store import load as load_fixed
        if (retained.get('lecture_extension',{}).get('historical',{}).get('expanded')
                and not load_fixed(root) and not os.environ.get('THESIS_PRIVATE_HISTORY')):
            status['reason']='Fixed research summary is missing; initialize it once before daily refresh. Previous results retained.'
            raise RuntimeError('fixed_summary_missing')
        result = build(root, now)
        check(root)
        if verify_page:
            subprocess.run(['node','--test','investment_thesis/test_page.cjs','investment_thesis/test_reliability.cjs','investment_thesis/test_lecture.cjs','investment_thesis/test_payoff.cjs'], cwd=root, check=True)
        status.update(status='success', evidence_generated_at=result['generated_at'],
                      market_snapshot_sha256=result['market_snapshot_sha256'])
    except Exception:
        for name, content in saved.items():
            p=data/name
            if content is not None:
                p.write_bytes(content)
            elif p.exists():
                p.unlink()  # Only a failed, newly generated output, never an input.
        if state_saved is not None:private_state.write_bytes(state_saved)
        elif private_state.exists():private_state.unlink()  # This failed refresh's new private state only.
        status.update(status='failed', reason=status['reason'] or
                      'Tracker build or validation failed; previous validated evidence retained.')
    atomic_json(data/'refresh_status.json',status)
    return status


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--upstream',default='manual',choices=['manual','success','failure','cancelled','timed_out','skipped','action_required','neutral','stale','startup_failure'])
    p.add_argument('--verify-page',action='store_true')
    args=p.parse_args()
    status=refresh(Path(__file__).resolve().parents[1],datetime.now(timezone.utc),args.upstream,args.verify_page)
    print(json.dumps(status,indent=2))
    raise SystemExit(0 if status['status']=='success' else 1)
