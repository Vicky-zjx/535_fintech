"""Offline synthetic fixtures and mock SDK only; never publish test evidence."""
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pandas as pd

from . import download_history as dh
from . import private_artifact as pa

NOW = datetime(2026, 11, 24, 18, tzinfo=timezone.utc)
REFERENCE_HASH = 'a' * 64


def fixture_seed():
    seed = dict(source=dh.SOURCE, mode='live', calendar={'as_of': dh.SEED_DATE}, tickers={})
    for t, cfg in dh.UNIVERSE.items():
        seed['tickers'][t] = dict(ric=cfg['ric'], identity_verified=True,
            history=[dict(date=dh.SEED_DATE, close=100.)],
            contracts=[dict(ric=f'{t}W2026{strike*100:05d}.U', type='put', strike=float(strike),
                            expiry=dh.OPTION_EXPIRY, observed_on=dh.SEED_DATE,
                            multiplier=100, terms_verified=True) for strike in (95, 100, 105)])
    return seed


class MockSDK:
    """No imports or calls to the actual LSEG SDK, sessions or transport."""
    HeaderType = SimpleNamespace(NAME='name')

    def __init__(self, missing=(), mismatch=False, identity_bad=False, fail_probes=False, partial_option=False):
        self.window, self.sessions = dh.fixed_window()
        self.ordinal = {d: i for i, d in enumerate(self.sessions)}
        self.missing, self.mismatch, self.identity_bad = set(missing), mismatch, identity_bad
        self.fail_probes, self.partial_option = fail_probes, partial_option
        self.calls = []

    def get_data(self, universe, fields, parameters, header_type):
        ric = universe[0]
        self.calls.append(dict(method='get_data', ric=ric, fields=fields, parameters=parameters))
        if fields == ['TR.TickerSymbol']:
            ticker = ric.split('.')[0]
            return pd.DataFrame([[ric, 'WRONG' if self.identity_bad else ticker]], columns=['Instrument', *fields])
        if fields == dh.PRICE_FIELDS:
            days = [d for d in self.sessions if parameters['SDate'] <= d <= parameters['EDate']]
            data = []
            for day in days:
                value = 200. + self.ordinal[day] / 100
                if '.' in ric and day in self.missing:
                    value = None
                elif '.' not in ric and self.mismatch:
                    value += 1
                data.append([ric, day, value])
            return pd.DataFrame(data, columns=['Instrument', *fields])
        if self.fail_probes:
            raise RuntimeError('password=DO_NOT_LEAK_THIS access_token=OPAQUE_TOKEN')
        if fields == dh.CA_FIELDS:
            return pd.DataFrame([[ric, None, None, None]], columns=['Instrument', *fields])
        return pd.DataFrame([[ric, self.sessions[0], 200.]], columns=['Instrument', *fields])

    def get_history(self, universe, fields, **parameters):
        self.calls.append(dict(method='get_history', ric=universe, fields=fields, parameters=parameters))
        if self.fail_probes:
            raise RuntimeError('DO_NOT_LEAK_THIS')
        frame = pd.DataFrame([[0., .2, .1, -.4], [.1, .3, .2, None]], columns=dh.OPTION_FIELDS,
                             index=pd.to_datetime(['2026-11-13', '2026-11-16']))
        if self.partial_option and fields == ['DELTA_EXCH']: raise ValueError('unavailable Greek')
        return frame[fields]


def collect(sdk=None):
    return dh.collect(sdk or MockSDK(), seed=fixture_seed(), reference_sha256=REFERENCE_HASH,
                      environ={'LSEG_PASSWORD': 'DO_NOT_LEAK_THIS'}, clock=lambda: NOW, sleeper=lambda _: None)


class DownloadHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.good = collect()

    def test_window_is_fixed_and_has_exactly_55_prior_sessions(self):
        window, sessions = dh.fixed_window()
        self.assertEqual(window['analysis_start'], '2021-11-24')
        self.assertEqual(window['analysis_end'], '2026-11-23')
        self.assertEqual(sessions.index(window['analysis_start']), 55)
        chunks = list(dh.annual_chunks(window['query_start'], window['analysis_end']))
        self.assertEqual(len(chunks), 6)
        self.assertEqual(chunks[0][0], window['query_start'])
        self.assertEqual(chunks[-1][1], window['analysis_end'])
        for first, second in zip(chunks, chunks[1:]):
            self.assertEqual(date.fromisoformat(first[1])+timedelta(days=1), date.fromisoformat(second[0]))

    def test_complete_download_contract_and_no_cached_stock_prices(self):
        obj = dh.validate_download(self.good)
        self.assertEqual(obj['evidence_sha256'], dh.digest(obj['evidence']))
        e = obj['evidence']
        self.assertEqual(e['retrieved_at'], NOW.isoformat())
        self.assertEqual(e['metadata']['frozen_reference_sha256'], REFERENCE_HASH)
        self.assertEqual(e['option_probes'], e['probes']['historical_options'])
        for t, item in e['tickers'].items():
            self.assertTrue(item['identity_verified'])
            self.assertTrue(item['coverage']['complete'])
            self.assertEqual(item['history'][0]['close'], 200.)
            self.assertNotEqual(next(r['close'] for r in item['history'] if r['date'] == dh.SEED_DATE), 100.)
        annual = [q for q in e['source_queries'] if q['kind'] == 'stock_annual']
        self.assertEqual(len(annual), 24)
        self.assertTrue(all(q['parameters']['Curn'] == 'USD' and 'Adjusted' not in q['parameters'] for q in annual))

    def test_recovery_covers_early_history_with_verified_consolidated_overlap(self):
        _, sessions = dh.fixed_window()
        sdk = MockSDK(missing=sessions[:9])
        e = collect(sdk)['evidence']
        for item in e['tickers'].values():
            recovery = item['recovery'][0]
            self.assertTrue(recovery['accepted'])
            self.assertGreaterEqual(recovery['overlap_matches'], dh.MIN_OVERLAP)
            self.assertEqual(recovery['recovered_dates'], sessions[:9])
            self.assertTrue(item['coverage']['complete'])
        self.assertEqual(sum(q['kind'] == 'consolidated_annual' for q in e['source_queries']), 24)

    def test_mismatched_alternate_never_replaces_prices_or_fills_gaps(self):
        _, sessions = dh.fixed_window()
        obj = collect(MockSDK(missing=sessions[:12], mismatch=True))
        dh.validate_download(obj)  # Incomplete evidence is usable, explicitly incomplete.
        for item in obj['evidence']['tickers'].values():
            self.assertFalse(item['recovery'][0]['accepted'])
            self.assertEqual(item['coverage']['missing_dates'], sessions[:12])
            self.assertTrue(all(r['close'] is None for r in item['history'][:12]))
            self.assertEqual(item['history'][12]['close'], 200.12)
        queries = obj['evidence']['source_queries']
        self.assertEqual(sum(q['kind'] == 'stock_exact_recovery' for q in queries), 4*dh.MAX_EXACT_RECOVERY)

    def test_alternate_needs_five_overlaps_and_rejects_conflicts(self):
        rows = [dict(date=f'2026-11-{i:02d}', close=10.) for i in range(1, 7)]
        with self.assertRaises(dh.DownloadError):
            dh.merge_prices({r['date']: 10. for r in rows[:4]}, rows, alternate=True)
        old = {r['date']: 10. for r in rows[:5]}
        merged, recovered, matches = dh.merge_prices(old, rows, alternate=True)
        self.assertEqual(matches, 5)
        self.assertEqual(recovered, ['2026-11-06'])
        self.assertEqual(len(merged), 6)
        rows[0]['close'] = 11.
        with self.assertRaises(dh.DownloadError):
            dh.merge_prices(old, rows, alternate=True)

    def test_primary_identity_failure_aborts_without_error_payload(self):
        with self.assertRaisesRegex(dh.DownloadError, '^primary_identity_not_verified$'):
            collect(MockSDK(identity_bad=True))

    def test_only_observed_nearspot_puts_and_calendar_month_suffix(self):
        selected = dh.select_option_probes(fixture_seed())
        self.assertEqual(len(selected), 4)
        self.assertTrue(all(x['strike'] == 100. and x['expired_ric'].endswith('^K26') for x in selected))
        self.assertTrue(all('W2026' in x['observed_ric'] for x in selected))
        seed = fixture_seed()
        seed['tickers']['BAC']['contracts'] = []
        self.assertEqual(len(dh.select_option_probes(seed)), 3)
        seed['calendar']['as_of'] = '2026-11-16'
        with self.assertRaises(dh.DownloadError):
            dh.select_option_probes(seed)

    def test_option_dated_fields_counts_zero_bid_and_no_completeness_claim(self):
        probes = self.good['evidence']['probes']['historical_options']
        self.assertFalse(probes['historical_chain_complete'])
        for result in probes['results']:
            self.assertEqual(result['non_null_counts']['BID'], 2)
            self.assertEqual(result['non_null_counts']['DELTA_EXCH'], 1)
            self.assertEqual(result['valid_bid_ask_pairs'], 2)
            self.assertEqual(result['dated_records'][0]['BID'], 0.)
        partial = collect(MockSDK(partial_option=True))['evidence']['probes']['historical_options']
        self.assertEqual(partial['results'][0]['non_null_counts']['DELTA_EXCH'], 0)
        self.assertEqual(partial['results'][0]['valid_bid_ask_pairs'], 2)

    def test_adjustment_probes_remain_separate_and_do_not_double_adjust(self):
        e = self.good['evidence']
        q = [x for x in e['source_queries'] if x['kind'] == 'adjustment_definition_probe']
        self.assertEqual(len(q), 8)
        self.assertEqual({x['fields'][1] for x in q}, {'TR.CLOSEPRICE(Adjusted=0)', 'TR.CLOSEPRICE(Adjusted=1)'})
        self.assertEqual(sum(x['kind'] == 'corporate_action_probe' for x in e['source_queries']), 4)
        self.assertEqual(e['tickers']['BAC']['history'][0]['close'], 200.)

    def test_sdk_error_text_and_unexpected_free_text_are_not_retained(self):
        obj = collect(MockSDK(fail_probes=True))
        payload = json.dumps(obj)
        self.assertNotIn('DO_NOT_LEAK_THIS', payload)
        self.assertNotIn('OPAQUE_TOKEN', payload)
        self.assertIn('request_or_response_unavailable', payload)
        frame = pd.DataFrame([['opaque-unclassified-credential', 'DO_NOT_LEAK_THIS']], columns=['error', 'payload'])
        raw = dh.raw_table(frame, {'LSEG_PASSWORD': 'DO_NOT_LEAK_THIS'}, 'BAC.N', dh.PRICE_FIELDS)
        self.assertNotIn('opaque-unclassified-credential', json.dumps(raw))
        self.assertNotIn('DO_NOT_LEAK_THIS', json.dumps(raw))

    def test_loader_rejects_hash_period_identity_price_and_missing_grid(self):
        changes = [
            lambda e: e['window'].update(analysis_start='2022-01-01'),
            lambda e: e['tickers']['BAC'].update(ric='AAPL.O'),
            lambda e: e['tickers']['BAC'].update(identity_verified=False),
            lambda e: e['tickers']['BAC']['history'][0].update(close=-1.),
            lambda e: e['tickers']['BAC']['history'][0].update(close=199.),
            lambda e: e['tickers']['BAC']['history'][0].update(close=True),
            lambda e: e['tickers']['BAC']['history'].pop(0),
            lambda e: e['coverage']['BAC'].update(complete=False),
            lambda e: e['metadata']['plan'].update(extended_end='2026-11-24'),
            lambda e: e['metadata'].update(currency='EUR'),
            lambda e: e['metadata'].update(field='TR.CLOSEPRICE'),
            lambda e: e.pop('raw_records'),
            lambda e: e['raw_records'][e['tickers']['BAC']['identity']['query_id']]['data'][0].__setitem__(1, 'KO'),
        ]
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)/'evidence.json'
            p.write_text(json.dumps(self.good))
            self.assertEqual(dh.load_download(p), self.good)
            bad = deepcopy(self.good)
            bad['evidence_sha256'] = '0'*64
            p.write_text(json.dumps(bad))
            with self.assertRaises(dh.DownloadError):
                dh.load_download(p)
            for change in changes:
                bad = deepcopy(self.good)
                change(bad['evidence'])
                bad['evidence_sha256'] = dh.digest(bad['evidence'])
                p.write_text(json.dumps(bad))
                with self.assertRaises(dh.DownloadError):
                    dh.load_download(p)

    def test_confirmation_precedes_session_or_file_access(self):
        with patch.object(dh, 'query_lseg') as query:
            with self.assertRaisesRegex(dh.DownloadError, 'confirmation_required'):
                dh.download('/nonexistent', confirmed=False)
            query.assert_not_called()

    def test_dedicated_output_no_overwrite_and_no_session_on_existing_artifact(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            seedpath = root/dh.SEED_FILE
            seedpath.parent.mkdir(parents=True)
            seedpath.write_text(json.dumps(fixture_seed()))
            key = pa.X25519PrivateKey.generate()
            private = key.private_bytes(pa.serialization.Encoding.Raw, pa.serialization.PrivateFormat.Raw, pa.serialization.NoEncryption())
            kwargs = dict(confirmed=True, environ={}, reference_sha256=REFERENCE_HASH,
                          recipient=pa.b64(pa.raw_public(key.public_key())))
            with patch.object(dh, 'query_lseg', return_value=deepcopy(self.good)) as query:
                result = dh.download(root, **kwargs)
                self.assertEqual(query.call_count, 1)
                self.assertTrue(callable(query.call_args.kwargs['operation']))
                target = root/dh.ARTIFACT_DIRECTORY/dh.CIPHER_NAME
                self.assertEqual(json.loads(pa.decrypt(json.loads(target.read_text()), private)), result)
                self.assertNotIn('PriceClose', target.read_text())
                before = target.read_bytes()
                with self.assertRaises(dh.DownloadError):
                    dh.download(root, **kwargs)
                self.assertEqual(query.call_count, 1)
                self.assertEqual(target.read_bytes(), before)
                with self.assertRaises(dh.DownloadError):
                    dh.output_target(root, 'docs/data/historical_download.json')

    def test_cli_never_prints_internal_error(self):
        output = io.StringIO()
        with patch.object(dh, 'download', side_effect=RuntimeError('DO_NOT_LEAK_THIS')), redirect_stdout(output):
            self.assertEqual(dh.main(['--confirm-live-download']), 1)
        self.assertNotIn('DO_NOT_LEAK_THIS', output.getvalue())


if __name__ == '__main__':
    unittest.main()
