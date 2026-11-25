"""Frozen retrospective evidence plus a separate, non-trading forward monitor."""
from pathlib import Path
import math
import statistics
from final_project.validate_publication import equivalent_observations
from . import reference, ablation, monitoring
from .extension_plan import PLAN, DOWNLOAD_NAME
from .import_history import private_history_path


def risk_candidates(original):
    """Unselected economic loss-budget scenarios; not new production thresholds."""
    candidates={}
    for t,rows in original['rows'].items():
        tail=[r['adverse_move'] for r in rows if r['status']=='observed' and r['tail_event']]
        severity=statistics.mean(tail) if tail else None
        candidates[t]=dict(frozen_tail_events=len(tail),conditional_mean_closing_decline=severity,
            scenarios=[dict(expected_tail_loss_budget=b,probability_candidate=min(1.,b/severity) if severity else None,
                            dollar_budget_at_12000_underlying_exposure=12000*b) for b in (.0025,.005,.0075)])
    return dict(status='Pending user choice; no candidate is active',tickers=candidates,
        calibration='Frozen three-year daily unfiltered observations only; not calibrated to the filtered or non-overlapping cohorts.',
        definition='A stock-exposure proxy: expected maximum closing loss contributed by 3% decline events = event probability × conditional mean event severity. The 25/50/75 bp budgets are hypothetical five-session risk budgets, not estimated alpha or option losses. Dollar examples assume $12,000 underlying exposure, not an actual position.',
        limitation='These illustrative budgets use daily unfiltered severity, so they do not guarantee the same budget for filtered or non-overlapping samples. Tail severity is uncertain and may increase in stress. The proxy ignores sub-3% losses, intraday moves, option convexity, premium, assignments and portfolio dependence; it cannot set an executable option-risk limit without judgment.')


def overlap_audit(original, downloaded):
    """Do not attribute provider revisions to a longer sample; never overwrite."""
    report={}
    for t,item in original['tickers'].items():
        old={r['date']:r['close'] for r in item['history']}
        new={r['date']:r['close'] for r in downloaded['tickers'][t]['history']}
        conflicts=[];missing=[];matched=0
        for day,value in old.items():
            if value is None:continue
            other=new.get(day)
            if other is None:missing.append(day)
            elif not math.isclose(value,other,rel_tol=1e-9,abs_tol=1e-8):conflicts.append(day)
            else:matched+=1
        report[t]=dict(matched=matched,missing_dates=missing,conflicting_dates=conflicts)
    return report


def analyze(root,h,current,replicates=5000):
    # Import locally to avoid a circular build import. This module is read-only.
    from .research import analyze as research
    from .reliability import analyze as reliability
    root=Path(root);frozen=reference.load(root);e=frozen['evidence']
    if current['window']['analysis_end']<e['reference_end']:
        raise ValueError('Current data predates frozen reference')
    original_h=reference.history(e,PLAN['original_start'],PLAN['reference_end'])
    original=research(original_h)
    if not equivalent_observations(original['full_sample'],e['original_full_sample']):
        raise ValueError('Frozen original results no longer reproduce; no silent rebasing')
    original['reliability']=e['original_reliability']
    original_a=ablation.analyze(original_h,original,replicates)
    extension=dict(status='Pending authorized historical download',plan=PLAN,
                   original_window=e['window'],reference_sha256=frozen['evidence_sha256'],
                   original_full_sample=e['original_full_sample'],original_ablation=original_a,
                   expanded=None,overlap_audit=None,
                   adjustment_status='Original TR.PriceClose retained as retrieved. Corporate-action factors have not been reconciled for these four stocks.',
                   comparison_status='Not yet possible: no validated five-year download has been imported.')
    economics=dict(status='Awaiting matched historical option panel and account outcomes',available_metrics=None,
        reason='Discovery records and a few capability probes cannot identify both strategy arms, their entry quotes, expiry outcomes, capital utilization and net returns.')
    path=private_history_path(root)
    if path is not None:
        from .download_history import load_download
        downloaded=load_download(path)
        evidence=downloaded['evidence']
        from .economic_probe import analyze as economic_probe
        economics=economic_probe(evidence)
        from .price_audit import analyze as price_audit
        adjustment_audit=price_audit(evidence)
        if evidence['metadata']['frozen_reference_sha256']!=frozen['evidence_sha256']:
            raise ValueError('Downloaded evidence refers to a different original reference')
        audit=overlap_audit(e,evidence);extension['overlap_audit']=audit
        if any(x['missing_dates'] or x['conflicting_dates'] for x in audit.values()):
            extension.update(status='Pending overlap reconciliation',
                comparison_status='The new pull does not reproduce all retained original prices. No price or result has been replaced.')
        else:
            eh=reference.history(evidence,PLAN['extended_start'],PLAN['extended_end'])
            er=research(eh);er['reliability']=reliability(er,replicates)
            added={t:sum(r['signal_date']<PLAN['original_start'] and r['status']=='observed' for r in rows) for t,rows in er['rows'].items()}
            extension.update(status='Expanded historical analysis available' if all(added.values()) else 'Requested window analyzed; earlier mature evidence missing for at least one stock',
                comparison_status='Same-endpoint full-sample comparison; retrospective, not live performance.',
                expanded=dict(window=eh['window'],retrieved_at=evidence['retrieved_at'],
                              market_snapshot_sha256=er['market_snapshot_sha256'],
                              evidence_sha256=downloaded['evidence_sha256'],coverage=er['coverage'],
                              added_mature_paths=added,
                              full_sample=er['full_sample'],reliability=er['reliability'],
                              ablation=ablation.analyze(eh,er,replicates)),
                adjustment_status='New price/adjustment probes are retained in the download. No extra adjustment was applied; probe success alone is not factor reconciliation.')
        # Only coverage and capability counts enter the local page. Raw dated
        # prices/Greeks, response tables and encryption keys stay outside Git.
        option_summary={k:v for k,v in evidence['option_probes'].items() if k!='results'}
        option_summary['results']=[{k:v for k,v in r.items() if k in ('ticker','status','non_null_counts','valid_bid_ask_pairs')}
                                   for r in evidence['option_probes']['results']]
        extension['download_audit']=dict(evidence_sha256=downloaded['evidence_sha256'],
            retrieved_at=evidence['retrieved_at'],audit=evidence.get('audit'),
            price_coverage=evidence['coverage'],option_probes=option_summary,
            historical_discovery=evidence['probes'].get('historical_discovery'),
            adjustment_audit=adjustment_audit,
            license_status='Private research only. API success is not redistribution permission; institutional and third-party licensing remain unverified.')
    mature=[r for rows in original['rows'].values() for r in rows if r['status']=='observed']
    if any(r['outcome_date']>PLAN['reference_end'] for r in mature):
        raise ValueError('Frozen baseline contains an unmatured outcome')
    extension['maturity_audit']=dict(cutoff=PLAN['reference_end'],
        latest_signal_date=max(r['signal_date'] for r in mature),
        latest_outcome_date=max(r['outcome_date'] for r in mature),
        mature_only=True,prospective_rule='signal_date > reference_end; outcome_date <= current as_of')
    return dict(schema_version=1,kind='lecture_research_extension',as_of=current['window']['analysis_end'],
                source_sha256=current['market_snapshot_sha256'],historical=extension,
                acceptable_risk_candidates=risk_candidates(original),
                monitoring=monitoring.analyze(current,frozen),
                option_economics=economics,
                monitoring_inventory=dict(
                    cusum='Not implemented for this four-stock account; future use needs a fixed target, allowance and alarm rule.',
                    portfolio_drawdown='AAPL assignment backtests contain modeled NAV/drawdown, not this four-stock account. Awaiting authoritative four-stock NAV.',
                    rolling_percentile='The 126-session tracker is not a percentile-band monitor; bootstrap percentiles are uncertainty intervals, not rolling performance bands.',
                    actual_trade_performance='Awaiting authoritative fills, stock positions and portfolio NAV. Proposals are not executions.'))
