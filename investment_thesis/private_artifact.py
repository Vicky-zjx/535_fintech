"""Authenticated encryption for private research artifacts; never publish plaintext.

Only the public recipient key goes to Actions. The private key stays on the
researcher's computer. Encryption does not confer redistribution rights.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

CONTEXT = b'FIN535 private historical evidence v1'
CIPHER_NAME = 'historical_download.encrypted.json'


def b64(value):
    return base64.b64encode(value).decode('ascii')


def raw_public(key):
    return key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def public_key(encoded):
    return X25519PublicKey.from_public_bytes(base64.b64decode(encoded, validate=True))


def derive(shared, salt):
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=CONTEXT).derive(shared)


def encrypt(payload, recipient):
    recipient = public_key(recipient)
    ephemeral = X25519PrivateKey.generate()
    salt, nonce = os.urandom(32), os.urandom(12)
    aad = CONTEXT + raw_public(recipient) + raw_public(ephemeral.public_key())
    cipher = AESGCM(derive(ephemeral.exchange(recipient), salt)).encrypt(nonce, payload, aad)
    return dict(version=1, algorithm='X25519-HKDF-SHA256-AES256GCM',
                recipient_sha256=hashlib.sha256(raw_public(recipient)).hexdigest(),
                ephemeral_public_key=b64(raw_public(ephemeral.public_key())),
                salt=b64(salt), nonce=b64(nonce), ciphertext=b64(cipher))


def decrypt(envelope, private):
    if envelope['version'] != 1 or envelope['algorithm'] != 'X25519-HKDF-SHA256-AES256GCM':
        raise ValueError('Unsupported encrypted envelope')
    key = X25519PrivateKey.from_private_bytes(private)
    if envelope['recipient_sha256'] != hashlib.sha256(raw_public(key.public_key())).hexdigest():
        raise ValueError('Wrong recipient')
    ephemeral = public_key(envelope['ephemeral_public_key'])
    aad = CONTEXT + raw_public(key.public_key()) + raw_public(ephemeral)
    decode = lambda value: base64.b64decode(value, validate=True)
    shared = key.exchange(ephemeral)
    return AESGCM(derive(shared, decode(envelope['salt']))).decrypt(
        decode(envelope['nonce']), decode(envelope['ciphertext']), aad)


def write_private(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as handle:
        handle.write(payload)


def private_destination(path):
    path = Path(path).expanduser().resolve()
    if any((parent / '.git').exists() for parent in (path.parent, *path.parents)):
        raise ValueError('Private research data must be outside every Git working tree')
    if path.exists():
        raise ValueError('Refusing to overwrite private evidence')
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    keygen = sub.add_parser('keygen'); keygen.add_argument('private_key', type=Path)
    unseal = sub.add_parser('decrypt')
    unseal.add_argument('encrypted', type=Path); unseal.add_argument('private_key', type=Path)
    unseal.add_argument('output', type=Path)
    args = parser.parse_args()
    try:
        if args.command == 'keygen':
            path = private_destination(args.private_key)
            key = X25519PrivateKey.generate()
            write_private(path, key.private_bytes(serialization.Encoding.Raw,
                          serialization.PrivateFormat.Raw, serialization.NoEncryption()))
            print(b64(raw_public(key.public_key())))  # Public key only; safe dispatch input.
        else:
            path = private_destination(args.output)
            if args.private_key.stat().st_mode & 0o077:
                raise ValueError('Private key permissions must be 0600')
            payload = decrypt(json.loads(args.encrypted.read_text()), args.private_key.read_bytes())
            from .download_history import validate_download
            validate_download(json.loads(payload))
            write_private(path, payload)
            print('Validated evidence decrypted locally. No data published.')
    except Exception:
        print('Private artifact operation failed; no secret or provider payload printed.')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
