"""Predeclared research settings; not optimized from realized returns."""
UNIVERSE = {
    'BAC': {'ric': 'BAC.N', 'name': 'Bank of America', 'sector': 'Financials'},
    'KO': {'ric': 'KO.N', 'name': 'Coca-Cola', 'sector': 'Consumer Staples'},
    'PFE': {'ric': 'PFE.N', 'name': 'Pfizer', 'sector': 'Healthcare'},
    'F': {'ric': 'F.N', 'name': 'Ford Motor Company', 'sector': 'Consumer Discretionary'},
}
# RICs above are lookup inputs, accepted only after LSEG ticker validation.
MAX_HV = .45
MIN_R5 = -.08
PER_NAME = .30
TOTAL_EXPOSURE = .70
RESERVE = .30
MIN_DTE, TARGET_DTE, MAX_DTE = 3, 7, 10
ILLUSTRATIVE_CAPITAL = 40000  # Documentation/test fixtures ONLY; never account input.
