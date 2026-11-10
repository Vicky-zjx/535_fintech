"""Offline fixtures test validation only; none are used as published prices."""
import csv
from datetime import date, datetime, timezone
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from lseg_chart import update


class ChartTests(unittest.TestCase):
    start, end = date(2026, 11, 2), date(2026, 11, 6)

    def frame(self, values=(100, None, 102), dates=None):
        dates = dates or ["2026-11-02", "2026-11-03", "2026-11-04"]
        return pd.DataFrame({"Instrument": ["AAPL.O"] * len(values),
                             "TR.PRICECLOSE.DATE": dates, "TR.PRICECLOSE": values})

    def test_window_uses_previous_new_york_date_not_utc_date(self):
        start, end = update.query_window(datetime(2026, 11, 10, 2, tzinfo=timezone.utc))
        self.assertEqual(end, date(2026, 11, 8))
        self.assertEqual((end - start).days, 89)

    def test_timestamp_dates_sort_without_shifting_calendar_date(self):
        frame = self.frame((102, 100, None), [pd.Timestamp("2026-11-04T00:00:00Z"),
                                            pd.Timestamp("2026-11-02T00:00:00Z"),
                                            pd.Timestamp("2026-11-03T00:00:00Z")])
        rows = update.normalize(frame, self.start, self.end)
        self.assertEqual(rows, [{"date": "2026-11-02", "close_usd": 100},
                                {"date": "2026-11-03", "close_usd": None},
                                {"date": "2026-11-04", "close_usd": 102}])

    def test_null_is_not_zero_or_forward_fill(self):
        rows = update.normalize(self.frame(), self.start, self.end)
        self.assertIsNone(rows[1]["close_usd"])
        self.assertEqual(len(rows), 3)

    def test_invalid_prices_rejected(self):
        for price in (0, -1, float("inf"), "invalid"):
            with self.subTest(price=price), self.assertRaises(ValueError):
                update.normalize(self.frame((100, price, 102)), self.start, self.end)

    def test_missing_columns_wrong_ric_and_invalid_dates_rejected(self):
        frames = [self.frame().drop(columns=["TR.PRICECLOSE.DATE"]),
                  self.frame().assign(Instrument="MSFT.O"),
                  self.frame(dates=["not-a-date", "2026-11-03", "2026-11-04"]),
                  self.frame(dates=["2026-11-07", "2026-11-03", "2026-11-04"])]
        for frame in frames:
            with self.assertRaises(ValueError):
                update.normalize(frame, self.start, self.end)

    def test_duplicate_conflicts_rejected(self):
        with self.assertRaises(ValueError):
            update.normalize(self.frame((100, 101, 102), ["2026-11-02"] * 3), self.start, self.end)

    def test_too_few_real_prices_rejected(self):
        for values in ((None, None, None), (100, None, None)):
            with self.assertRaises(ValueError):
                update.normalize(self.frame(values), self.start, self.end)

    def test_no_credentials_no_connection(self):
        with self.assertRaisesRegex(ValueError, "LSEG_APP_KEY"):
            update.query_lseg(self.start, self.end, environ={})

    def test_explicit_platform_request_and_header_type(self):
        import lseg.data as ld
        session = MagicMock()
        session.authentication_token_endpoint_url = "https://api.refinitiv.com/auth/oauth2/v1/token"
        session.stream_auto_reconnection = False
        session.signon_control = False
        session.open.return_value = SimpleNamespace(name="Opened")
        credentials = dict.fromkeys(update.SECRET_NAMES, "offline-fixture-not-a-credential")
        with patch.object(ld.session.platform, "Definition") as definition, \
                patch.object(ld.session, "set_default"), patch.object(ld, "get_data") as get_data:
            definition.return_value.get_session.return_value = session
            get_data.return_value = self.frame()
            update.query_lseg(self.start, self.end, credentials)
            self.assertFalse(definition.call_args.kwargs["signon_control"])
            get_data.assert_called_once_with(universe=["AAPL.O"], fields=update.FIELDS,
                parameters=update.parameters(self.start, self.end), header_type=ld.HeaderType.NAME)
            session.close.assert_called_once()

    def test_failed_auth_never_queries_or_leaks_provider_message(self):
        import lseg.data as ld
        session = MagicMock()
        session.authentication_token_endpoint_url = "https://api.refinitiv.com/auth/oauth2/v1/token"
        session.stream_auto_reconnection = False
        session.signon_control = False
        session.open.side_effect = RuntimeError("PRIVATE_AUTH_RESPONSE")
        credentials = dict.fromkeys(update.SECRET_NAMES, "offline-fixture-not-a-credential")
        with patch.object(ld.session.platform, "Definition") as definition, \
                patch.object(ld, "get_data") as get_data:
            definition.return_value.get_session.return_value = session
            with self.assertRaises(RuntimeError) as error:
                update.query_lseg(self.start, self.end, credentials)
            self.assertNotIn("PRIVATE_AUTH_RESPONSE", str(error.exception))
            get_data.assert_not_called()
            session.open.assert_called_once()

    def payload(self):
        return update.make_payload(update.normalize(self.frame(), self.start, self.end),
                                   self.start, self.end, datetime(2026, 11, 7, tzinfo=timezone.utc), environ={})

    def test_plot_preserves_null_and_matches_metrics(self):
        payload = self.payload()
        self.assertEqual(payload["valid_prices"], 2)
        self.assertEqual(payload["returned_null_prices"], 1)
        self.assertEqual(payload["last_close_usd"], 102)
        fig = update.make_figure(payload)
        self.assertFalse(fig.data[0].connectgaps)
        self.assertEqual(list(fig.data[0].y), [100, None, 102])

    def test_json_csv_and_html_agree_and_contain_no_environment_secrets(self):
        payload = self.payload()
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            with patch.dict("os.environ", {"LSEG_PASSWORD": "UNIT_TEST_NOT_A_REAL_PASSWORD"}):
                update.publish(payload, target)
            saved = json.loads((target / "data.json").read_text())
            with (target / "prices.csv").open() as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(saved, payload)
            self.assertEqual(rows[1]["close_usd"], "")
            self.assertEqual(float(rows[-1]["close_usd"]), payload["last_close_usd"])
            html = (target / "chart.html").read_text()
            self.assertIn(payload["observations_sha256"], html)
            for name in update.OUTPUT_NAMES:
                self.assertNotIn("UNIT_TEST_NOT_A_REAL_PASSWORD", (target / name).read_text())

    def test_failed_render_keeps_previous_publication(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            for name in update.OUTPUT_NAMES:
                (target / name).write_text("previous-success")
            with patch.object(update, "make_figure", side_effect=ValueError("render failed")):
                with self.assertRaises(ValueError):
                    update.publish(self.payload(), target)
            for name in update.OUTPUT_NAMES:
                self.assertEqual((target / name).read_text(), "previous-success")


if __name__ == "__main__":
    unittest.main()
