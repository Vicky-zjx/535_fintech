"""Fresh local LSEG API query -> Plotly HTML. Never reads a market-data cache.

Run from the repository: .venv/bin/python -m lseg_chart.local_api
Credentials come from environment variables or hidden terminal prompts only.
"""
import argparse
from datetime import datetime, timezone
import getpass
import os
from pathlib import Path
import signal
import warnings

from lseg_chart.update import (
    DEFAULT_OUTPUT, DEFAULT_SIMPLE_OUTPUT, SECRET_NAMES, make_payload, normalize, publish, query_lseg, query_window,
    safe_failure_detail,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_SIMPLE_OUTPUT)
    parser.add_argument("--data-output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    credentials = {}
    warnings.simplefilter("error", getpass.GetPassWarning)
    try:
        for name in SECRET_NAMES:
            value = os.environ.get(name)
            if not value:
                value = getpass.getpass(f"{name} (hidden): ")
            if not value:
                raise ValueError("All three credentials are required")
            credentials[name] = value
        start, end = query_window(datetime.now(timezone.utc))

        def deadline(*_):
            raise TimeoutError("Local API query exceeded its 120-second deadline")
        signal.signal(signal.SIGALRM, deadline)
        signal.alarm(120)
        print("Querying LSEG Platform once; no cache, no forced sign-on.", flush=True)
        frame = query_lseg(start, end, credentials)
        signal.alarm(0)
        records = normalize(frame, start, end)
        payload = make_payload(records, start, end, datetime.now(timezone.utc), environ={})
        payload["execution"] = "fresh local API query; no cache input"
        payload["provider_columns"] = list(frame.columns)
        payload["column_mapping"] = "Instrument, requested TR.PriceClose.date, requested TR.PriceClose; dates and numeric values validated"
        publish(payload, args.data_output, args.output)
        print(f"SUCCESS: {payload['instrument']}, {payload['valid_prices']} real prices, {payload['first_price_date']} through {payload['last_price_date']}.")
        print(f"Latest returned close: {payload['last_close_usd']:.2f}; HTML: {args.output / 'index.html'}")
        return 0
    except Exception as exc:
        print(f"FAILED: {type(exc).__name__}: {safe_failure_detail(exc, credentials)}")
        print("No cache was used, no data was substituted, and no other session was displaced.")
        return 1
    finally:
        signal.alarm(0)
        credentials.clear()


if __name__ == "__main__":
    raise SystemExit(main())
