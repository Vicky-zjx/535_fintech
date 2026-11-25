"""Only mock plaintext, never real data or credentials."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from . import private_artifact as p
from . import download_history as d


class PrivateArtifactTests(unittest.TestCase):
    def test_round_trip_randomized_and_authenticated(self):
        key = p.X25519PrivateKey.generate()
        secret = key.private_bytes(p.serialization.Encoding.Raw, p.serialization.PrivateFormat.Raw, p.serialization.NoEncryption())
        public = p.b64(p.raw_public(key.public_key()))
        payload = b'{"mock_price":123.456}'
        first, second = p.encrypt(payload, public), p.encrypt(payload, public)
        self.assertNotEqual(first, second)
        self.assertEqual(p.decrypt(first, secret), payload)
        self.assertNotIn('mock_price', json.dumps(first))
        first['nonce'] = p.b64(b'0'*12)
        with self.assertRaises(Exception): p.decrypt(first, secret)

    def test_bad_keys_fail_before_query(self):
        with tempfile.TemporaryDirectory() as td, patch.object(d, 'query_lseg') as query:
            for recipient in (None, '', 'bad-key'):
                with self.assertRaises(d.DownloadError):
                    d.download(td, confirmed=True, reference_sha256='a'*64, recipient=recipient)
            query.assert_not_called()

    def test_private_files_cannot_be_overwritten_or_in_git(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root/'private.key'
            p.write_private(path, b'mock private key')
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError): p.write_private(path, b'overwrite')
            (root/'.git').mkdir()
            with self.assertRaises(ValueError): p.private_destination(root/'new.json')


if __name__ == '__main__': unittest.main()
