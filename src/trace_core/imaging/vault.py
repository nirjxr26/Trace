import base64
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Literal

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from trace_core.core.errors import ValidationError
from trace_core.core.fs import fsync_dir

ALGORITHM: Literal["AES-256-GCM/PBKDF2-SHA256-600k"] = "AES-256-GCM/PBKDF2-SHA256-600k"
ITERATIONS = 600_000
MIN_ITERATIONS = 1_000
MAX_ITERATIONS = 5_000_000
AAD = b"trace-imaging-seal-v1"
CHUNK_SIZE = 1024 * 1024
MAX_HEADER = 4096


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(text: str) -> bytes:
    try:
        return base64.b64decode(text.encode("ascii"), validate=True)
    except Exception as exc:
        raise ValidationError("Sealed image header is malformed.") from exc


def _derive_key(passphrase: str, salt: bytes, iterations: int):
    if not passphrase:
        raise ValidationError("A non-empty passphrase is required for sealed images.")
    if not MIN_ITERATIONS <= iterations <= MAX_ITERATIONS:
        raise ValidationError("Sealed image parameters outside acceptable range.")
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations).derive(
        passphrase.encode("utf-8")
    )


def seal_file(source: Path, target: Path, passphrase: str, plaintext_sha256: str) -> tuple[int, dict]:
    salt = os.urandom(16)
    nonce = os.urandom(12)
    key = _derive_key(passphrase, salt, ITERATIONS)
    header = {
        "alg": ALGORITHM,
        "iterations": ITERATIONS,
        "salt": _b64(salt),
        "nonce": _b64(nonce),
        "plaintext_sha256": plaintext_sha256,
    }
    header_line = json.dumps(header).encode("ascii") + b"\n"

    fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=f"{target.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(header_line)
            encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
            encryptor.authenticate_additional_data(AAD)
            digest = hashlib.sha256()
            with source.open("rb") as reader:
                while True:
                    chunk = reader.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    digest.update(chunk)
                    out.write(encryptor.update(chunk))
            if digest.hexdigest() != plaintext_sha256:
                raise ValidationError("The image changed before it could be sealed.")
            out.write(encryptor.finalize())
            out.write(encryptor.tag)
            out.flush()
            os.fsync(out.fileno())
        os.chmod(tmp, 0o600)
        _publish(tmp, target)
        fsync_dir(target.parent)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return target.stat().st_size, header


def open_sealed(source: Path, target: Path, passphrase: str) -> str:
    try:
        with source.open("rb") as reader:
            header_line = reader.readline(MAX_HEADER + 1)
            if len(header_line) > MAX_HEADER or not header_line.endswith(b"\n"):
                raise ValidationError("Sealed image header is missing or too large.")
            header = json.loads(header_line.decode("ascii"))
            if header.get("alg") != ALGORITHM:
                raise ValidationError("Sealed image algorithm does not match this build.")
            salt = _unb64(str(header["salt"]))
            nonce = _unb64(str(header["nonce"]))
            expected_hash = str(header["plaintext_sha256"])
            key = _derive_key(passphrase, salt, int(header["iterations"]))
            tag = source.stat().st_size - len(header_line) - 16
            if tag < 0:
                raise ValidationError("Sealed image body is missing.")
            decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).decryptor()
            decryptor.authenticate_additional_data(AAD)

            fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=f"{target.name}.", suffix=".tmp")
            tmp = Path(tmp_name)
            digest = hashlib.sha256()
            try:
                with os.fdopen(fd, "wb") as out:
                    left = tag
                    while left:
                        chunk = reader.read(min(CHUNK_SIZE, left))
                        if not chunk:
                            raise ValidationError("Sealed image body is truncated.")
                        plain = decryptor.update(chunk)
                        digest.update(plain)
                        out.write(plain)
                        left -= len(chunk)
                    final_tag = reader.read(16)
                    if len(final_tag) != 16:
                        raise ValidationError("Sealed image tag is truncated.")
                    tail = decryptor.finalize_with_tag(final_tag)
                    if tail:
                        digest.update(tail)
                        out.write(tail)
                    out.flush()
                    os.fsync(out.fileno())
                if digest.hexdigest() != expected_hash:
                    raise ValidationError("Decrypted image does not match its recorded SHA-256.")
                os.chmod(tmp, 0o600)
                _publish(tmp, target)
                fsync_dir(target.parent)
            except BaseException:
                tmp.unlink(missing_ok=True)
                raise
    except ValidationError:
        raise
    except Exception as exc:
        raise ValidationError("Cannot open sealed image: wrong passphrase or corrupted file.") from exc
    return expected_hash


def _publish(temp: Path, target: Path) -> None:
    if target.exists():
        raise ValidationError(f"Refusing to overwrite existing file: {target}")
    try:
        os.link(temp, target)
    except FileExistsError as exc:
        raise ValidationError(f"Refusing to overwrite existing file: {target}") from exc
    except OSError:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        try:
            fd = os.open(target, flags, 0o600)
        except FileExistsError as exc:
            raise ValidationError(f"Refusing to overwrite existing file: {target}") from exc
        try:
            out = os.fdopen(fd, "wb")
        except BaseException:
            os.close(fd)
            raise
        with out, temp.open("rb") as reader:
            while True:
                chunk = reader.read(CHUNK_SIZE)
                if not chunk:
                    break
                out.write(chunk)
            out.flush()
            os.fsync(out.fileno())
    os.unlink(temp)
