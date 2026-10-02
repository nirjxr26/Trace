"""H-09: a release key id is validated before it is ever turned into a path.

Key ids reach these functions from signed manifests and from operator input. Before
the grammar check, `ed25519:` stripped to the empty string, so the revocation marker
pathed to the revoked *directory* and the write put a file where a directory belongs
— silently un-revoking every key. `ed25519:../../x` reached check_contained as a
traversal rather than being refused as a malformed id.
"""

import pytest

from trace_core.core.settings import settings
from trace_core.updates.errors import UpdateVerificationError
from trace_core.updates.trust import _key_suffix, revoked_path, trust_key_path, trust_root

VALID = "ed25519:53712e8bb8a774e6"


def test_valid_id_yields_the_documented_stem():
    assert _key_suffix(VALID) == "53712e8bb8a774e6"


def test_surrounding_whitespace_is_normalised_not_rejected():
    assert _key_suffix(f"  {VALID}  ") == "53712e8bb8a774e6"


@pytest.mark.parametrize(
    ("key_id", "why"),
    [
        ("", "empty"),
        ("ed25519:", "prefix only — collapsed to the revoked directory itself"),
        ("ed25519", "prefix without the separator"),
        ("../../x", "traversal with no prefix"),
        ("ed25519:../../x", "traversal behind a valid prefix"),
        ("ed25519:../../etc/passwd", "traversal to an absolute-looking target"),
        ("ed25519:53712E8BB8A774E6", "uppercase hex — the fingerprint is lowercase-derived"),
        ("ed25519:53712e8bb8a7746", "15 hex chars, one short"),
        ("ed25519:53712e8bb8a774e67", "17 hex chars, one long"),
        ("ed25519:zzzzzzzzzzzzzzzz", "not hex"),
        ("ed25519:../../../windows/system32", "windows traversal"),
        ("rsa:53712e8bb8a774e6", "unsupported algorithm prefix"),
        ("ed25519:53712e8bb8a774e6\x00", "embedded NUL via a valid-looking prefix"),
        ("éd25519:53712e8bb8a774e6", "unicode homoglyph prefix"),
    ],
)
def test_malformed_ids_are_refused_before_path_construction(key_id: str, why: str):
    with pytest.raises(UpdateVerificationError):
        _key_suffix(key_id)
    with pytest.raises(UpdateVerificationError):
        trust_key_path(key_id)
    with pytest.raises(UpdateVerificationError):
        revoked_path(key_id)


def test_no_malformed_id_ever_becomes_a_path(monkeypatch, tmp_path):
    """The removed possibility: nothing under the trust root other than <16 hex>[.pub|revoked]."""
    monkeypatch.setattr(settings, "storage_root", tmp_path / "storage")
    monkeypatch.setattr("trace_core.updates.trust._TRUST_ROOT_CACHE", None)
    root = trust_root()
    for key_id in ("ed25519:", "ed25519:../../x", "", "ed25519:53712e8bb8a774e6\x00"):
        for build in (trust_key_path, revoked_path):
            try:
                built = build(key_id)
            except UpdateVerificationError:
                continue
            assert built.parent in (root, root / "revoked"), f"{key_id!r} escaped the trust root"
            assert ".." not in built.parts


def test_revoking_creates_a_directory_not_a_file(monkeypatch, tmp_path):
    """The live defect: the empty id wrote a file over the revoked directory."""
    monkeypatch.setattr(settings, "storage_root", tmp_path / "storage")
    monkeypatch.setattr("trace_core.updates.trust._TRUST_ROOT_CACHE", None)
    root = trust_root()
    with pytest.raises(UpdateVerificationError):
        revoked_path("ed25519:")
    assert not (root / "revoked").exists(), "refusal must happen before any directory or file is created"


def test_revoked_marker_round_trips_for_a_valid_id(monkeypatch, tmp_path):
    from trace_core.updates.signing import import_release_pubkey, revoke_release_key

    monkeypatch.setattr(settings, "storage_root", tmp_path / "storage")
    monkeypatch.setattr("trace_core.updates.trust._TRUST_ROOT_CACHE", None)
    pub_hex = "11" * 32
    key_id = import_release_pubkey(pub_hex)
    revoke_release_key(key_id)
    marker = revoked_path(key_id)
    assert marker.is_file()
    assert marker.parent.name == "revoked"


def test_a_revoked_key_cannot_load(monkeypatch, tmp_path):
    from trace_core.updates.signing import import_release_pubkey, load_release_pubkey, revoke_release_key

    monkeypatch.setattr(settings, "storage_root", tmp_path / "storage")
    monkeypatch.setattr("trace_core.updates.trust._TRUST_ROOT_CACHE", None)
    key_id = import_release_pubkey("22" * 32)
    assert load_release_pubkey(key_id)
    revoke_release_key(key_id)
    with pytest.raises(UpdateVerificationError):
        load_release_pubkey(key_id)
