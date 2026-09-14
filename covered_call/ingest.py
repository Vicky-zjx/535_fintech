"""Strict, source-preserving normalization. No imputation or synthetic fallback."""

import json
from pathlib import Path
import pandas as pd

from .accounting import finite


def validate_bars(stock, options, config):
    for name, rows, extra in (("stock", stock, ["print"]), ("option", options, ["strike", "expiry", "bid", "ask", "print", "cp"])):
        seen = set()
        for row in rows:
            required = {"timestamp", "ric", "bar_minutes", *extra}
            if not required <= row.keys():
                raise ValueError(f"{name} bar is missing {required-row.keys()}")
            ts = pd.Timestamp(row["timestamp"])
            if ts.tzinfo is None:
                raise ValueError("Naive timestamps are forbidden; normalize the source timezone first")
            if row["bar_minutes"] != config.bar_minutes:
                raise ValueError("Stock and option bars must have the same configured length")
            key = (ts, row["ric"])
            if key in seen:
                raise ValueError(f"Duplicate {name} bar: {key}")
            seen.add(key)
            for field in (["print"] if name == "stock" else ["bid", "ask", "print", "strike"]):
                if row[field] is not None and not finite(row[field]):
                    raise ValueError(f"Non-finite {name} {field}")
            if name == "stock" and row["ric"] != config.stock_ric:
                raise ValueError("Unexpected stock instrument")
            if name == "option":
                if row["cp"] != "C" or row["strike"] <= 0:
                    raise ValueError("Only standard positive-strike calls are supported")
                pd.Timestamp(row["expiry"])
    return stock, options


def load_real(path, config):
    raw = Path(path).read_bytes()
    data = json.loads(raw)
    meta = data.get("metadata", {})
    if meta.get("source") != "LSEG" or meta.get("synthetic") is not False:
        raise ValueError("Published builds require an explicitly real LSEG dataset")
    if meta.get("bar_minutes") != config.bar_minutes or meta.get("timestamp_label") != "endPeriod":
        raise ValueError("Dataset must contain configured hourly bar-end timestamps")
    for field in ("ticker", "stock_ric", "start", "end", "entry_time"):
        if meta.get(field) != getattr(config, field):
            raise ValueError(f"Cached query {field} differs from configuration; fetch a matching candidate universe")
    if meta.get("requested_target_otm", 0.05) != config.target_otm:
        raise ValueError("Changed target requires a new candidate-universe pull")
    validate_bars(data["stock"], data["options"], config)
    return data
