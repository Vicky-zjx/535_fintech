"""Observed RIC identity, rule-derived dates, and explicitly assumed terms."""
from datetime import date,timedelta
from decimal import Decimal
import re

RIC_SOURCE='https://developers.lseg.com/en/article-catalog/article/functions-to-find-option-rics-traded-on-different-exchanges'
OCC_SOURCE='https://www.theocc.com/clearance-and-settlement/clearing/equity-options-product-specifications'
ADJUSTMENT_SOURCE='https://www.optionseducation.org/referencelibrary/faq/splits-mergers-spinoffs-bankruptcies'
APPLE_SOURCE='https://investor.apple.com/faq./default.aspx'
OCC_AAPL_2020='https://infomemo.theocc.com/infomemos?number=47369'


def candidate_call_ric(expiry,strike):
    """A request candidate, NOT a listing. Only historical replies admit it."""
    d=date.fromisoformat(expiry);cents=Decimal(str(strike))*100
    if cents!=cents.to_integral_value() or not 0<cents<100000:
        raise ValueError('Unsupported strike encoding')
    month=chr(ord('A')+d.month-1)
    return f'AAPL{month}{d.day:02d}{d:%y}{int(cents):05d}.U^{month}{d:%y}'


def parse_ric(ident):
    # Scope: ordinary AAPL OPRA RICs below $1,000; no mini/adjusted/index roots.
    m=re.fullmatch(r'(AAPL)([A-X])(\d{2})(\d{2})(\d{5})\.U(?:\^([A-L])(\d{2}))?',ident)
    if not m: raise ValueError('NONSTANDARD_ROOT_VENUE_OR_UNSUPPORTED_ENCODING')
    root,code,dd,yy,cents,suffix,sy=m.groups()
    month=(ord(code)-ord('A'))%12+1
    expiry=date(2000+int(yy),month,int(dd))
    if suffix and (ord(suffix)-ord('A')+1!=month or sy!=yy):
        raise ValueError('EXPIRED_SUFFIX_CONFLICT')
    return dict(id=ident,underlying='AAPL.O',cp='C' if code<='L' else 'P',strike=int(cents)/100,expiry=str(expiry))


def resolve(ident,calendar,*,description=None,existing=None,corporate_action_review=None):
    c=parse_ric(ident)
    if c['cp']!='C': raise ValueError('PUT_OUTSIDE_CALL_STRATEGY')
    d=description or {};old=existing or {}
    for key,value in [('StrikePrice',c['strike']),('ExpiryDate',c['expiry'])]:
        if d.get(key) is not None and (str(d[key])[:10] if key=='ExpiryDate' else d[key])!=value:
            raise ValueError('PROVIDER_DESCRIPTION_RIC_CONFLICT_'+key)
    if old.get('strike') is not None and old['strike']!=c['strike']: raise ValueError('CACHE_STRIKE_CONFLICT')
    if old.get('expiry') is not None and old['expiry']!=c['expiry']: raise ValueError('CACHE_EXPIRY_CONFLICT')
    if d:
        if d.get('CallPutOption') not in (None,'Call') or d.get('StrikeMultiplier') not in (None,1):
            raise ValueError('OPTION_TYPE_OR_STRIKE_MULTIPLIER_CONFLICT')
        if d.get('LotSize')!=100 or d.get('Currency')!='USD' or d.get('ContractType')!='Standard' or d.get('ExerciseStyle')!='A':
            raise ValueError('NONSTANDARD_MINI_OR_DESCRIPTION_CONFLICT')
        underlying=d.get('UnderlyingQuoteRIC',[])
        if 'AAPL.O' not in underlying: raise ValueError('UNDERLYING_DESCRIPTION_CONFLICT')
    review=corporate_action_review or {}
    if review.get('unresolved_adjustment_event'):
        raise ValueError('UNRESOLVED_CORPORATE_ACTION_IN_SAMPLE')
    expiry=date.fromisoformat(c['expiry'])
    last=str(calendar.exchange.date_to_session(c['expiry'],direction='previous').date())
    friday=None
    if expiry.weekday()==4: friday=str(expiry)
    elif expiry.weekday()==3 and not calendar.exchange.is_session(str(expiry+timedelta(days=1))):
        friday=str(expiry+timedelta(days=1))
    c.update(currency='USD',multiplier=100,deliverable='100 AAPL shares',last_trade_date=last,
             scheduled_last_trading_date=last,series_friday=friday,known_from='9999-12-31',
             first_observed_quote_date=None,last_observed_quote_date=None,
             standard_verified=False,standard_assumption_allowed=True,terms_status='research assumption',
             terms_source=[OCC_SOURCE,ADJUSTMENT_SOURCE,APPLE_SOURCE,OCC_AAPL_2020],
             terms_verified_at=None,risk_flags=[],
             terms_assumption='Treat ordinary AAPL OPRA calls as unadjusted standard American 100-share contracts, based on OCC specifications, ordinary identifiers, available descriptions and the corporate-action review. Not vendor-confirmed contract-by-contract historical deliverables.',
             provenance=dict(identity={'status':'derived from official RIC rules','source':RIC_SOURCE,
                'fields':['underlying','cp','strike','expiry'],'day_convention':'zero-padded DD, instructor correction and retained real paired tests'},
                current_description={'status':'directly retrieved current metadata; not historical listing evidence' if d else 'not available for expired RIC',
                    'checks':['identity matched','100 lot','USD','Standard','American'] if d else []},
                expiry={'status':'RIC-derived; checked against source description/cache when available'},
                scheduled_last_trading_date={'status':'rule/calendar-derived, not last observed quote','source':OCC_SOURCE},
                multiplier={'status':'research assumption; supporting current lot-size metadata when available','value':100},
                deliverable={'status':'research assumption, not individually historically verified','value':'100 AAPL shares'},
                corporate_actions=review))
    return c
