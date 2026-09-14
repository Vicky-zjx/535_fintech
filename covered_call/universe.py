"""Contract membership comes from observations, never from strike arithmetic."""

import hashlib
from pathlib import Path

import pandas as pd

from .accounting import finite

SELECTION_RULE = ('Choose the smallest actually observed same-Friday AAPL call strike '
                  'greater than or equal to 1.05 × the Monday stock print.')
LIMITATION = ('This is an observed candidate universe, not a complete historical chain. '
              'An absent contract is unknown, not proven unlisted. The selected strike is '
              'the minimum within the observed universe; a lower qualifying strike outside '
              'the captured data cannot be ruled out.')


def observed_contracts(options):
    """Keep exact RIC/strike pairs and first source evidence, including single-sided quotes.

    All-null rows, constructed identifiers and request success without observations
    do not establish membership. First evidence is a bar's availability timestamp,
    not the date the API request was made or an inferred listing date.
    """
    contracts = {}
    for row in sorted(options, key=lambda r: pd.Timestamp(r['timestamp'])):
        if row['cp'] != 'C' or not any(finite(row.get(f)) for f in ('bid', 'ask', 'print')):
            continue
        contracts.setdefault(row['ric'], dict(
            ric=row['ric'], strike=row['strike'], expiry=row['expiry'], cp='C',
            first_observed_at=pd.Timestamp(row['timestamp']).isoformat(),
            evidence={f: row.get(f) for f in ('source_timestamp', 'bid', 'ask', 'print')},
        ))
    return sorted(contracts.values(), key=lambda r: (r['expiry'], r['strike'], r['ric']))


def available_contracts(contracts, expiry, entry, target=None):
    """Point-in-time subset; never round the target or fill missing strikes."""
    return sorted((r for r in contracts if r['expiry'] == expiry
                   and pd.Timestamp(r['first_observed_at']) <= pd.Timestamp(entry)
                   and (target is None or r['strike'] >= target - 1e-10)),
                  key=lambda r: (r['strike'], r['ric']))


def universe_provenance(data, cache):
    """Preserve the old acquisition's limitations instead of relabeling it complete."""
    md = data['metadata']
    acquisition = md.get('candidate_universe', {}).get('acquisition_limitation')
    if 'candidate_grid' in md:
        acquisition = (
            f"The retained original pull tested RICs at ${md['candidate_grid']:.2f} increments "
            "in narrow target/ATM bands. That was a discovery limitation, not a listing grid. "
            "Only returned price observations establish the universe here. Off-grid or out-of-band "
            "listed strikes may be missing; the original raw replies/cache are preserved unchanged."
        )
    return dict(basis='historical LSEG quote/print observations',
                complete_historical_chain=False, selection_rule=SELECTION_RULE,
                limitation=LIMITATION,
                acquisition_limitation=acquisition or 'Coverage is limited to the supplied observed-contract cache.',
                source_cache_sha256=hashlib.sha256(Path(cache).read_bytes()).hexdigest())
