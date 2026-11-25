"""Independent fixed research, current tracker, and persistent forward monitor."""
from copy import deepcopy
from . import fixed_store, forward_store, monitoring


def assemble(root,h,d):
    fixed=fixed_store.load(root)
    if fixed is None:
        from .lecture import analyze
        return analyze(root,h,d),None
    b=fixed['content'];ref=b['reference'];issue=None
    try:state,prospective=forward_store.prepare(root,d,ref)
    except (ValueError,KeyError,TypeError,OSError):
        state=None;issue='Private prospective history is missing, revised or inconsistent; monitoring withheld, not reset. Restore/reconcile the retained state.'
        prospective=dict(window={**d['window'],'analysis_start':ref['evidence']['reference_end']},
                         rows={t:[] for t in d['rows']})
    monitor=monitoring.analyze(prospective,ref)
    monitor['persistence']=dict(status='blocked' if issue else 'complete',reason=issue,
        retained_signal_dates=len(prospective['rows']['BAC']),state_sha256=state['content_sha256'] if state else None,
        policy='Append-only private evidence; complete source coverage may reconstruct it. No rolling reset or automatic historical rebase.')
    if issue:
        monitor['coverage_lost']=True
        for stock in monitor['samples'].values():
            for groups in stock.values():
                for g in groups.values():g['current'].update(status=issue,regime='Insufficient evidence')
    from .research import comparison
    d['prospective']=comparison(prospective['rows'])
    d['prospective_unavailable_reason']=issue
    extension=dict(schema_version=1,kind='lecture_research_extension',as_of=d['window']['analysis_end'],
        source_sha256=d['market_snapshot_sha256'],fixed_research_sha256=fixed['content_sha256'],
        monitoring=monitor,**{k:deepcopy(b[k]) for k in ('historical','acceptable_risk_candidates','option_economics','monitoring_inventory','hypothetical_put_payoff')})
    return extension,state
