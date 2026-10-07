"""Reproduce the bounded capability audit. Raw responses remain licensed/local.

No P&L is calculated. Current searches are discovery leads, NOT historical
membership. Historical observations and separately verified terms are required.
"""
import argparse
import json
from pathlib import Path

from .fetch_lseg import request_daily, DIV_FIELDS


def probe(output):
    if output.exists(): raise ValueError('Use a new probe directory; do not overwrite licensed snapshots')
    output.mkdir(parents=True)
    import lseg.data as ld
    from lseg.data.content import historical_pricing as hp, search
    def save(name,fn):
        try:
            value=fn()
            if hasattr(value,'to_json'):
                value=json.loads(value.to_json(orient='records',date_format='iso'))
        except Exception as exc:
            value={'error':str(exc)}
        (output/(name+'.json')).write_text(json.dumps(value,default=str,allow_nan=False,indent=2))
        print(name, 'ERROR' if isinstance(value,dict) and 'error' in value else 'saved privately',flush=True)
        return value
    ld.open_session()
    try:
        save('stock_daily',lambda:request_daily(hp,'AAPL.O','2025-09-30','2026-09-30',['TRDPRC_1','BID','ASK']))
        save('dividends',lambda:ld.get_data('AAPL.O',fields=DIV_FIELDS,parameters={'SDate':'2025-09-01','EDate':'2026-09-30'}))
        save('search_metadata',lambda:search.metadata.Definition(view=search.Views.EQUITY_DERIVATIVE_QUOTES).get_data().data.raw)
        base="UnderlyingQuoteRIC eq 'AAPL.O' and CallPutOption eq 'Call' and "
        for name,dates in [('expired','ExpiryDate ge 2025-10-01 and ExpiryDate le 2026-09-30'),('long','ExpiryDate ge 2026-10-01 and ExpiryDate le 2028-04-01')]:
            save('search_'+name,lambda dates=dates:ld.discovery.search(view=ld.discovery.Views.EQUITY_DERIVATIVE_QUOTES,
                filter=base+dates,select='RIC,StrikePrice,ExpiryDate,UnderlyingQuoteRIC,CallPutOption',top=10000))
        save('long_metadata',lambda:ld.discovery.search(view=ld.discovery.Views.EQUITY_DERIVATIVE_QUOTES,
                filter=base+'ExpiryDate ge 2027-06-01 and ExpiryDate le 2028-04-01 and StrikePrice le 255',top=10000,
                select='RIC,StrikePrice,ExpiryDate,UnderlyingQuoteRIC,CallPutOption,LastTradeDate,FirstTradeDate,LotSize,StrikeMultiplier,ExerciseStyle,ExerciseStyleName,Currency,ContractType,ContractTypeCode,ESMADeliveryType,ESMAPriceMultiplier,ListingStatus'))
        # Exact IDs from saved real discovery/cache evidence, not an invented grid.
        save('AAPLI172723000.U',lambda:request_daily(hp,'AAPLI172723000.U','2026-06-29','2026-09-30',['BID','ASK','MID_PRICE','TRDPRC_1']))
        save('quote_metadata',lambda:ld.get_data(['AAPLI172723000.U','AAPLG102633000.U^G26'],
            fields=['CF_NAME','LOT_SIZE','CONTR_SIZE','STRIKE_PRC','EXPIR_DATE','LAST_TRDAY','PUTCALLIND','CURRENCY','UNDERLYING','BCKGRNDPAG','LONGLINK1']))
        save('expired_daily',lambda:request_daily(hp,'AAPLG102631000.U^G26','2026-07-02','2026-07-10',None))
        err=save('expired_terms_history',lambda:request_daily(hp,'AAPLG102631000.U^G26','2026-07-02','2026-07-10',['LOT_SIZE','CONTR_SIZE','EXPIR_DATE','LAST_TRDAY','STRIKE_PRC']))
        if 'error' in err:
            err.update(ric='AAPLG102631000.U^G26',fields=['LOT_SIZE','CONTR_SIZE','EXPIR_DATE','LAST_TRDAY','STRIKE_PRC'])
            (output/'expired_terms_history.json').write_text(json.dumps(err,indent=2))
    finally: ld.close_session()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output-dir',type=Path,required=True)
    args=p.parse_args();probe(args.output_dir)
