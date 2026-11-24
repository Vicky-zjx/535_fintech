"""Fixed research extension, not production strategy settings."""
PLAN = {
    'version': 'lecture-extension-v1', 'specified_on': '2026-11-24',
    'original_start': '2023-11-23', 'reference_end': '2026-11-23',
    'extended_start': '2021-11-24', 'extended_end': '2026-11-23',
    'warmup_sessions': 55, 'forward_reporting_floor': 20,
    'maximum_acceptable_decline_probability': {'BAC': None, 'KO': None, 'PFE': None, 'F': None},
    'threshold_authority': 'Pending; no acceptable-risk cutoff has been chosen.',
    'baseline_policy': 'Freeze the original three-year estimated frequencies; treat them as hypotheses, not known true means. Never rebase after poor performance.',
    'monitoring_policy': 'Research-only conditional indicators. No order, cancellation or trading-pause actions.',
    'extension_policy': 'Fixed five-year sample, same terminal date as original; acquisition failure does not change the window or replace prices.',
}
REFERENCE_NAME = 'reference_2026-11-23.json'
DOWNLOAD_NAME = 'historical_download.json'
