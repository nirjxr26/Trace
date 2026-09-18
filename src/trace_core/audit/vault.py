"""Passphrase-encrypted evidence bundles. PBKDF2-SHA256 + AES-GCM, JSON envelope."""

import base64
import json
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from trace_core.core.errors import ValidationError

_ALG = "AES-256-GCM/PBKDF2-SHA256-600k"
_ITERATIONS = 600_000
MIN_KDF_ITERATIONS = 1_000
MAX_KDF_ITERATIONS = 5_000_000


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(text: str) -> bytes:
    try:
        return base64.b64decode(text.encode("ascii"))
    except Exception as e:
        raise ValidationError("Bundle is not valid encrypted evidence.") from e


def encrypt_bytes(data: bytes, passphrase: str) -> bytes:
    """Seal plaintext for off-host transport. Empty passphrases refused."""
    if not passphrase:
        raise ValidationError("A non-empty passphrase is required for encrypted export.")
    salt = os.urandom(16)
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=_ITERATIONS).derive(
        passphrase.encode("utf-8")
    )
    nonce = os.urandom(12)
    envelope = {
        "alg": _ALG,
        "iterations": _ITERATIONS,
        "salt": _b64(salt),
        "nonce": _b64(nonce),
        "ciphertext": _b64(AESGCM(key).encrypt(nonce, data, None)),
    }
    return json.dumps(envelope).encode("ascii")


def decrypt_bytes(blob: bytes, passphrase: str) -> bytes:
    """Open a sealed bundle. Wrong passphrase and corruption share one error (no oracle)."""
    if not passphrase:
        raise ValidationError("A non-empty passphrase is required to open this bundle.")
    try:
        envelope = json.loads(blob.decode("ascii"))
        iterations = int(envelope.get("iterations", 0))
        if not MIN_KDF_ITERATIONS <= iterations <= MAX_KDF_ITERATIONS:
            raise ValidationError("Bundle parameters outside acceptable range.")
        key = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=_unb64(envelope["salt"]),
            iterations=iterations,
        ).derive(passphrase.encode("utf-8"))
        return AESGCM(key).decrypt(_unb64(envelope["nonce"]), _unb64(envelope["ciphertext"]), None)
    except ValidationError:
        raise
    except Exception as e:
        raise ValidationError("Cannot open bundle: wrong passphrase or corrupted file.") from e
