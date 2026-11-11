"""Query real closes via Platform; publish only validated chart inputs.

Secrets are environment-only. No desktop fallback, config credentials, synthetic
prices, forward filling, or authentication retries. Run: python -m lseg_chart.update
"""
from __future__ import annotations

import argparse
import contextlib
import csv
from datetime import date, datetime, timedelta, timezone
import hashlib
from html import escape
import io
import json
import logging
import math
import os
from pathlib import Path
import re
import signal
import tempfile
from urllib.parse import quote
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go

# Change this one RIC, then run locally or push to main. Labels follow the response.
RIC = "MSFT.O"
FIELDS = ["TR.PriceClose.date", "TR.PriceClose"]
SECRET_NAMES = ("LSEG_APP_KEY", "LSEG_USERNAME", "LSEG_PASSWORD")
OUTPUT_NAMES = ("chart.html", "data.json", "prices.csv")
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "lseg-live"
DEFAULT_SIMPLE_OUTPUT = Path(__file__).resolve().parents[1] / "lseg-local"


def safe_failure_detail(value, environ):
    """Return bounded diagnostics, never configured credentials or bearer tokens."""
    text = str(value)
    for name in SECRET_NAMES:
        secret = environ.get(name, "")
        if secret:
            text = text.replace(secret, "[REDACTED]").replace(quote(secret, safe=""), "[REDACTED]")
    text = re.sub(r"(?i)Bearer\s+\S+", "Bearer [REDACTED]", text)
    text = re.sub(r"(?i)(access_token|refresh_token|id_token)([\s\"':=]+)([^\s,}]+)", r"\1\2[REDACTED]", text)
    text = re.sub(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "[REDACTED TOKEN]", text)
    return text.replace("\n", " ").replace("\r", " ")[:500]


def query_window(now: datetime) -> tuple[date, date]:
    """90 calendar days, ending yesterday in New York (no partial current day)."""
    if now.tzinfo is None:
        raise ValueError("Query clock must be timezone-aware")
    end = now.astimezone(ZoneInfo("America/New_York")).date() - timedelta(days=1)
    return end - timedelta(days=89), end


def parameters(start: date, end: date) -> dict:
    return {"SDate": start.isoformat(), "EDate": end.isoformat(), "Frq": "D", "Curn": "USD"}


def normalize(frame: pd.DataFrame, start: date, end: date) -> list[dict]:
    """Use provider date + field names. Retain returned nulls; reject ambiguity."""
    if frame is None or frame.empty:
        raise ValueError("LSEG returned no rows")
    names = [str(c).strip().casefold() for c in frame.columns]
    # Observed with lseg-data 2.1.1 + HeaderType.NAME: the date extension
    # loses its '.date' suffix, producing two identical TR.PriceClose headers.
    # Accept only this exact three-column shape in our declared request order;
    # validate every date and price below rather than guessing arbitrary columns.
    if names == ["instrument", "tr.priceclose", "tr.priceclose"]:
        frame = frame.copy()
        frame.columns = ["Instrument", "TR.PriceClose.date", "TR.PriceClose"]
    elif len(set(names)) != len(names):
        raise ValueError("Ambiguous duplicate response columns")
    columns = {str(c).strip().casefold(): c for c in frame.columns}
    required = ("instrument", "tr.priceclose.date", "tr.priceclose")
    if not all(key in columns for key in required):
        raise ValueError("Response lacks requested instrument/date/price columns")
    observed = {}
    for _, row in frame.iterrows():
        if row[columns["instrument"]] != RIC:
            raise ValueError("Response contains an unexpected instrument")
        raw_date = row[columns["tr.priceclose.date"]]
        if not isinstance(raw_date, (str, date, datetime, pd.Timestamp)):
            raise ValueError("Observation date is not a date/string value")
        parsed = pd.to_datetime(raw_date, utc=True, errors="coerce")
        if pd.isna(parsed):
            raise ValueError("Response contains an invalid observation date")
        # This is the vendor's calendar-date field, not an intraday timestamp.
        day = parsed.date()
        if not start <= day <= end:
            raise ValueError("Observation falls outside the requested completed-date window")
        value = row[columns["tr.priceclose"]]
        if pd.isna(value):
            price = None
        else:
            price = float(value)
            if not math.isfinite(price) or price <= 0:
                raise ValueError("Response contains a non-positive or non-finite price")
        day_text = day.isoformat()
        if day_text in observed and observed[day_text] != price:
            raise ValueError("Conflicting observations for the same date")
        observed[day_text] = price
    records = [{"date": key, "close_usd": observed[key]} for key in sorted(observed)]
    if sum(row["close_usd"] is not None for row in records) < 2:
        raise ValueError("Fewer than two valid historical prices; previous publication retained")
    return records


def query_lseg(start: date, end: date, environ=os.environ) -> pd.DataFrame:
    missing = [name for name in SECRET_NAMES if not environ.get(name)]
    if missing:
        raise ValueError("Missing environment variable(s): " + ", ".join(missing))

    # Suppress SDK output rather than trusting that log messages omit credentials.
    # No raw authentication response, session object or exception text is printed.
    prior_logging = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    session = None
    stage = "initialization"
    auth_code = "not supplied"
    auth_http = "no response captured"
    with io.StringIO() as captured, contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
        try:
            import lseg.data as ld
            from lseg.data._configure import get_config

            config = get_config()
            for key, value in {
                "logs.transports.file.enabled": False,
                "logs.transports.console.enabled": False,
                "usage_logger.enabled": False,
                "config-change-notifications-enabled": False,
                "http.request-timeout": 30,
                "http.auto-retry.number-of-retries": 0,
                "sessions.platform.default.auto-reconnect": False,
                "sessions.platform.default.server-mode": False,
                "sessions.platform.default.base-url": "https://api.refinitiv.com",
            }.items():
                config.set_param(key, value)
            session = ld.session.platform.Definition(
                app_key=environ["LSEG_APP_KEY"],
                grant=ld.session.platform.GrantPassword(
                    username=environ["LSEG_USERNAME"], password=environ["LSEG_PASSWORD"]
                ),
                signon_control=False,
            ).get_session()
            if session.authentication_token_endpoint_url != "https://api.refinitiv.com/auth/oauth2/v1/token":
                raise RuntimeError("Unexpected authentication endpoint")
            if session.stream_auto_reconnection or session.signon_control:
                raise RuntimeError("Unsafe session configuration")

            # Observe the existing SDK request; do NOT issue another login request.
            # SDK failure callbacks race with open() returning when retries are off.
            original_request = session.http_request

            def observe_request(request, *args, **kwargs):
                nonlocal auth_http
                response = original_request(request, *args, **kwargs)
                if request.url == session.authentication_token_endpoint_url:
                    auth_http = f"HTTP {response.status_code}"
                    if response.status_code != 200:
                        try:
                            body = response.json()
                            detail = {key: body.get(key) for key in ("error", "error_description")}
                            auth_http += "; " + safe_failure_detail(detail, environ)
                        except (ValueError, AttributeError):
                            auth_http += "; non-JSON error response (body suppressed)"
                return response

            session.http_request = observe_request

            def on_event(event, message, _session):
                nonlocal auth_code
                if getattr(event, "name", "") == "SessionAuthenticationFailed":
                    # Only preapproved classification labels, never server text.
                    auth_code = next((code for code in (
                        "invalid_grant", "invalid_client", "access_denied", "insufficient_scope"
                    ) if code in str(message)), "authentication rejected")

            session.on_event(on_event)
            stage = "Platform authentication"
            if getattr(session.open(), "name", "") != "Opened":
                raise RuntimeError("Platform session did not open")
            ld.session.set_default(session)
            stage = f"{RIC} historical price query"
            return ld.get_data(
                universe=[RIC], fields=FIELDS, parameters=parameters(start, end),
                header_type=ld.HeaderType.NAME,
            )
        except Exception as exc:
            raise RuntimeError(
                f"{stage} failed ({type(exc).__name__}; authentication category: {auth_code}). "
                f"Auth response: {auth_http}. Detail: {safe_failure_detail(exc, environ)}. "
                "Check the three Actions Secrets and Platform/data entitlements. "
                "No retry, desktop fallback or replacement prices were used."
            ) from None
        finally:
            if session is not None:
                try:
                    session.close()
                except Exception:
                    pass  # Never print a token-bearing SDK exception.
            logging.disable(prior_logging)


def make_payload(records, start, end, retrieved_at, environ=os.environ):
    canonical = json.dumps(records, allow_nan=False, separators=(",", ":"))
    valid = [row for row in records if row["close_usd"] is not None]
    run_id = environ.get("GITHUB_RUN_ID", "")
    run_url = f"https://github.com/Vicky-zjx/535_fintech/actions/runs/{run_id}" if run_id.isdigit() else None
    return {
        "schema_version": 1,
        "source": "LSEG Data Platform",
        "connection": "lseg.data Platform Session / GrantPassword",
        "instrument": RIC,
        "fields": FIELDS,
        "parameters": parameters(start, end),
        "retrieved_at_utc": retrieved_at.isoformat(),
        "requested_start": start.isoformat(),
        "requested_end": end.isoformat(),
        "first_price_date": valid[0]["date"],
        "last_price_date": valid[-1]["date"],
        "last_close_usd": valid[-1]["close_usd"],
        "valid_prices": len(valid),
        "returned_null_prices": len(records) - len(valid),
        "observations_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
        "workflow_run_url": run_url,
        "notes": [
            "Provider-reported TR.PriceClose in USD; not live quotes or total return.",
            "90-calendar-day request ending yesterday in America/New_York.",
            "Dates come from TR.PriceClose.date; no forward filling, interpolation or zero substitution.",
            "Weekends, holidays and dates absent from the response are not fabricated; returned nulls remain gaps.",
            "The observation count describes the response, not a guarantee of complete exchange-session coverage.",
        ],
        "observations": records,
    }


def make_figure(payload):
    rows = payload["observations"]
    fig = go.Figure(go.Scatter(
        x=[r["date"] for r in rows], y=[r["close_usd"] for r in rows],
        mode="lines+markers", name="TR.PriceClose", connectgaps=False,
        line={"color": "#167765", "width": 2.3}, marker={"size": 5},
        hovertemplate="%{x|%b %d, %Y}<br>Close: $%{y:,.2f}<extra>" + escape(payload["instrument"]) + "</extra>",
    ))
    fig.update_layout(
        template="plotly_white", autosize=True, height=430,
        paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
        font={"family": "Arial, sans-serif", "color": "#182c38", "size": 12},
        margin={"l": 60, "r": 25, "t": 25, "b": 65}, hovermode="x unified",
        xaxis={"title": "Observation date", "type": "date", "showgrid": False},
        yaxis={"title": "Closing price · USD", "tickprefix": "$", "gridcolor": "#e8edeb", "zeroline": False},
        meta={"instrument": payload["instrument"], "observations_sha256": payload["observations_sha256"]},
    )
    return fig


def publish(payload, output: Path, simple_output: Path | None = None):
    """Render all outputs from one response before replacing known targets."""
    if simple_output is not None and output.resolve() == simple_output.resolve():
        raise ValueError("Detailed and simple output directories must differ")
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".build-", dir=output) as temp:
        staging = Path(temp)
        (staging / "data.json").write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n")
        with (staging / "prices.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["date", "close_usd"], lineterminator="\n")
            writer.writeheader()
            writer.writerows(payload["observations"])
        figure = make_figure(payload)
        figure.write_html(
            staging / "chart.html", full_html=True,
            include_plotlyjs="../covered-call/assets/plotly.min.js",
            div_id="lseg-price-close", config={"responsive": True, "displaylogo": False},
        )
        if simple_output is not None:
            from lseg_chart.page import render
            render(payload, figure, staging / "simple")
            simple_output.mkdir(parents=True, exist_ok=True)
        for name in OUTPUT_NAMES:
            (staging / name).replace(output / name)
        if simple_output is not None:
            for name in ("index.html", "data.json"):
                (staging / "simple" / name).replace(simple_output / name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--simple-output", type=Path, default=DEFAULT_SIMPLE_OUTPUT)
    args = parser.parse_args()
    start, end = query_window(datetime.now(timezone.utc))
    try:
        # GitHub job timeout is a second guard; one attempt only.
        def deadline(*_):
            raise TimeoutError("API deadline exceeded")
        signal.signal(signal.SIGALRM, deadline)
        signal.alarm(120)
        frame = query_lseg(start, end)
        signal.alarm(0)
        records = normalize(frame, start, end)
        payload = make_payload(records, start, end, datetime.now(timezone.utc))
        payload["execution"] = "fresh API query; no cache input"
        payload["provider_columns"] = list(frame.columns)
        publish(payload, args.output, args.simple_output)
    except Exception as exc:
        # Do not dump an SDK traceback or provider response into public CI logs.
        print(f"FAILED ({type(exc).__name__}): no new publication. Check secrets, Platform access and response validation.")
        if isinstance(exc, RuntimeError):
            print(str(exc))  # query_lseg constructs this sanitized text itself.
        return 1
    finally:
        signal.alarm(0)
    print(f"Saved real {RIC} prices: {payload['valid_prices']} observations; "
          f"{payload['first_price_date']} to {payload['last_price_date']}; "
          f"{payload['returned_null_prices']} returned null(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
