"""D17: trusted-root symlink resolution for device nodes.

`check_contained` is correct for storage and trust roots and is left alone here (H-21).
`check_device_contained` exists because `/dev/disk/by-id/...` is a symlink by design, and
is unreachable from any storage or trust-root call site.

`file_lock` and O_NOFOLLOW are likewise untouched; the H-52 regression guards that.
"""

import os
import sys

import pytest

from trace_core.core.fs import check_contained, check_device_contained

pytestmark = pytest.mark.unit

# Creating a symlink on Windows needs Administrator or Developer Mode (WinError 1314).
# Same convention as test_security_regressions.py; D17 resolution itself is POSIX-shaped.


def _can_symlink() -> bool:
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        target = base / "t"
        target.write_text("x")
        try:
            os.symlink(target, base / "l")
        except OSError:
            return False
        return True


_CAN_SYMLINK = _can_symlink() if sys.platform == "win32" else True

requires_symlinks = pytest.mark.skipif(
    not _CAN_SYMLINK, reason="host cannot create symlinks (Windows: needs elevation or Developer Mode)"
)


def _by_id(dev_root, link_name: str = "by-id-link") -> str:
    """Build a /dev-shaped tree: <dev>/by-id/<link> -> <dev>/<target>."""
    by_id = dev_root / "by-id"
    by_id.mkdir()
    target = dev_root / "nvme0n1"
    target.write_bytes(b"")
    link = by_id / link_name
    link.symlink_to(target)
    return str(link)


@requires_symlinks
def test_by_id_symlink_inside_the_trusted_root_is_accepted(tmp_path) -> None:  # type: ignore[no-untyped-def]
    dev = tmp_path / "dev"
    dev.mkdir()
    link = _by_id(dev)

    resolved = check_device_contained(link, dev)

    assert resolved == (dev / "nvme0n1").resolve()
    assert resolved.name == "nvme0n1"


def test_direct_device_path_under_the_root_is_accepted(tmp_path) -> None:  # type: ignore[no-untyped-def]
    dev = tmp_path / "dev"
    dev.mkdir()
    direct = dev / "sdb"
    direct.write_bytes(b"")

    assert check_device_contained(direct, dev) == direct.resolve()


@requires_symlinks
def test_nested_by_id_symlink_resolving_outside_the_root_is_rejected(tmp_path) -> None:  # type: ignore[no-untyped-def]
    dev = tmp_path / "dev"
    dev.mkdir()
    escape_target = tmp_path / "etc" / "shadow"
    escape_target.parent.mkdir()
    escape_target.write_bytes(b"")
    by_id = dev / "by-id"
    by_id.mkdir()
    escape_link = by_id / "evil"
    escape_link.symlink_to(escape_target)

    with pytest.raises(ValueError, match="escaping the trusted device root"):
        check_device_contained(escape_link, dev)


def test_dotdot_traversal_out_of_the_root_is_rejected(tmp_path) -> None:  # type: ignore[no-untyped-def]
    dev = tmp_path / "dev"
    dev.mkdir()
    sibling = tmp_path / "outside"
    sibling.write_bytes(b"")

    with pytest.raises(ValueError, match="escaping the trusted device root"):
        check_device_contained(dev / ".." / "outside", dev)


def test_nonexistent_device_path_fails_closed(tmp_path) -> None:  # type: ignore[no-untyped-def]
    dev = tmp_path / "dev"
    dev.mkdir()

    with pytest.raises(ValueError, match="does not exist"):
        check_device_contained(dev / "absent", dev)


@requires_symlinks
def test_dangling_symlink_fails_closed(tmp_path) -> None:  # type: ignore[no-untyped-def]
    dev = tmp_path / "dev"
    dev.mkdir()
    by_id = dev / "by-id"
    by_id.mkdir()
    dangling = by_id / "gone"
    dangling.symlink_to(dev / "never-created")

    with pytest.raises(ValueError, match="does not exist"):
        check_device_contained(dangling, dev)


def test_unresolvable_or_non_directory_root_fails_closed(tmp_path) -> None:  # type: ignore[no-untyped-def]
    dev = tmp_path / "dev"
    dev.mkdir()
    node = dev / "sdb"
    node.write_bytes(b"")

    with pytest.raises(ValueError, match="unresolvable device root"):
        check_device_contained(node, tmp_path / "no-such-root")

    with pytest.raises(ValueError, match="non-directory device root"):
        check_device_contained(node, node)


def test_the_root_itself_is_not_a_valid_device(tmp_path) -> None:  # type: ignore[no-untyped-def]
    dev = tmp_path / "dev"
    dev.mkdir()

    with pytest.raises(ValueError, match="device root itself"):
        check_device_contained(dev, dev)


def test_empty_path_fails_closed(tmp_path) -> None:  # type: ignore[no-untyped-def]
    dev = tmp_path / "dev"
    dev.mkdir()

    with pytest.raises(ValueError):
        check_device_contained("", dev)


@requires_symlinks
def test_check_contained_still_rejects_a_by_id_symlink(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """The storage primitive stays literal, so the by-id shape is still refused there.

    This is the separation the two functions exist to preserve: D17 must not have widened
    the storage or trust-root boundary to make device paths work.
    """
    dev = tmp_path / "dev"
    dev.mkdir()
    link = _by_id(dev)

    with pytest.raises(ValueError, match="escaping storage root"):
        check_contained(link, dev / "by-id")
