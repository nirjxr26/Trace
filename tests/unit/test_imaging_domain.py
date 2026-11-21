import itertools
from typing import cast

import pytest

from trace_core.imaging.domain import ImagingState, ImagingTransitionError, can_transition, require_transition

pytestmark = pytest.mark.unit

VALID_TRANSITIONS = {
    (ImagingState.PREPARING, ImagingState.ACQUIRING),
    (ImagingState.PREPARING, ImagingState.INTERRUPTED),
    (ImagingState.PREPARING, ImagingState.FAILED),
    (ImagingState.ACQUIRING, ImagingState.VERIFYING),
    (ImagingState.ACQUIRING, ImagingState.INTERRUPTED),
    (ImagingState.ACQUIRING, ImagingState.FAILED),
    (ImagingState.VERIFYING, ImagingState.BYTE_VERIFIED),
    (ImagingState.VERIFYING, ImagingState.INTERRUPTED),
    (ImagingState.VERIFYING, ImagingState.FAILED),
    (ImagingState.VERIFYING, ImagingState.QUARANTINED),
    (ImagingState.INTERRUPTED, ImagingState.ACQUIRING),
}


@pytest.mark.parametrize(("current", "target"), list(itertools.product(ImagingState, repeat=2)))
def test_transition_table(current: ImagingState, target: ImagingState) -> None:
    assert can_transition(current, target) == ((current, target) in VALID_TRANSITIONS)


def test_byte_verified_requires_matching_lengths_and_digests() -> None:
    require_transition(
        ImagingState.VERIFYING,
        ImagingState.BYTE_VERIFIED,
        expected_bytes=3,
        copied_bytes=3,
        readback_bytes=3,
        acquisition_sha256="a" * 64,
        readback_sha256="a" * 64,
    )


@pytest.mark.parametrize(
    ("expected", "copied", "readback", "source_hash", "image_hash"),
    [
        (None, 3, 3, "a" * 64, "a" * 64),
        (-1, -1, -1, "a" * 64, "a" * 64),
        (3, 2, 3, "a" * 64, "a" * 64),
        (3, 3, 2, "a" * 64, "a" * 64),
        (3, 3, 3, "a" * 64, "b" * 64),
        (3, 3, 3, "invalid", "invalid"),
    ],
)
def test_byte_verified_rejects_incomplete_or_mismatched_evidence(
    expected: int | None, copied: int, readback: int, source_hash: str, image_hash: str
) -> None:
    with pytest.raises(ImagingTransitionError, match="Byte verification requires"):
        require_transition(
            ImagingState.VERIFYING,
            ImagingState.BYTE_VERIFIED,
            expected_bytes=expected,
            copied_bytes=copied,
            readback_bytes=readback,
            acquisition_sha256=source_hash,
            readback_sha256=image_hash,
        )


def test_terminal_state_cannot_be_reopened() -> None:
    with pytest.raises(ImagingTransitionError, match="Illegal imaging transition"):
        require_transition(ImagingState.BYTE_VERIFIED, ImagingState.ACQUIRING)


def test_string_state_cannot_bypass_byte_verification() -> None:
    target = cast(ImagingState, "BYTE_VERIFIED")
    assert not can_transition(ImagingState.VERIFYING, target)
    with pytest.raises(ImagingTransitionError, match="must be ImagingState"):
        require_transition(ImagingState.VERIFYING, target)
