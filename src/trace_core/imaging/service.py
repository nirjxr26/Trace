import hashlib
import json
import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import BinaryIO
from uuid import UUID

from trace_core.audit.builder import for_imaging_event, for_imaging_reservation
from trace_core.audit.domain import AuditAction
from trace_core.audit.service import AuditService
from trace_core.cases.domain import normalize_number, require_no_active_imaging
from trace_core.cases.repository import SqlAlchemyCaseRepository
from trace_core.cases.service import CaseNotFoundError, InvalidCaseStateError
from trace_core.core.canonical import canonical_json
from trace_core.core.clock import now_utc
from trace_core.core.domain import InvariantViolationError, bound_actor
from trace_core.core.errors import AuthorizationError, NotFoundError
from trace_core.core.fs import check_contained, ensure_dir
from trace_core.core.operators import (
    ROLE_ADMIN,
    ROLE_AUDITOR,
    ROLE_INVESTIGATOR,
    current_identity,
    require_mutator,
    require_role,
)
from trace_core.core.service import BaseService
from trace_core.core.settings import settings
from trace_core.devices.domain import WpVerdict
from trace_core.imaging.destination import (
    append_partial,
    checkpoint_path,
    create_partial,
    discard_checkpoint,
    partial_path,
    publish_image,
    read_checkpoint,
    relative_locator,
    verify_image_with_pieces,
    write_checkpoint,
    write_manifest,
)
from trace_core.imaging.domain import (
    ImagingAcquisitionError,
    ImagingBadRegion,
    ImagingDestinationError,
    ImagingDestinationExistsError,
    ImagingEncryption,
    ImagingFailure,
    ImagingInterruptedError,
    ImagingManifest,
    ImagingOperation,
    ImagingPiecewise,
    ImagingPublishError,
    ImagingReadbackError,
    ImagingSource,
    ImagingSourceChangedError,
    ImagingSourceKind,
    ImagingSourceReadError,
    ImagingSourceUnavailableError,
    ImagingState,
    ImagingTransitionError,
    require_eligible_case,
)
from trace_core.imaging.repository import SqlAlchemyImagingRepository
from trace_core.imaging.source import SourceReader, open_source
from trace_core.imaging.stream import CHUNK_SIZE, PIECE_SIZE, copy_raw_with_regions, hash_stream
from trace_core.imaging.vault import ALGORITHM, open_sealed, seal_file
from trace_core.updates.lock import update_lock

_FAILED_STATES = {
    ImagingState.BYTE_VERIFIED,
    ImagingState.INTERRUPTED,
    ImagingState.FAILED,
    ImagingState.QUARANTINED,
}
_CHECKPOINT_BYTES = 64 * 1024 * 1024
Progress = Callable[[int, int], None]
CheckpointProgress = Callable[[int, int, str], None]
Cancelled = Callable[[], bool]


class ImagingService(BaseService):
    def __init__(self, session_manager=None, device_service=None) -> None:
        super().__init__(session_manager)
        self._device_service = device_service

    def list_for_case(self, case_identifier: str) -> list[ImagingOperation]:
        with self.transaction() as uow:
            require_role(uow.session, ROLE_ADMIN, ROLE_AUDITOR, ROLE_INVESTIGATOR, action="view imaging operations")
            cases = SqlAlchemyCaseRepository(uow.session)
            case = cases.resolve(case_identifier)
            if case is not None:
                number = case.number
            else:
                number = normalize_number(case_identifier)
                if not cases.is_purged(number):
                    raise CaseNotFoundError(case_identifier)
            return SqlAlchemyImagingRepository(uow.session).list_for_case(number)

    def list_recent(self, limit: int = 100) -> list[ImagingOperation]:
        with self.transaction() as uow:
            require_role(uow.session, ROLE_ADMIN, ROLE_AUDITOR, ROLE_INVESTIGATOR, action="view imaging operations")
            return SqlAlchemyImagingRepository(uow.session).list_recent(limit)

    def manifest_for(self, operation_id: UUID) -> dict[str, object]:
        root = Path(settings.storage_root)
        with self.transaction() as uow:
            require_role(uow.session, ROLE_ADMIN, ROLE_AUDITOR, ROLE_INVESTIGATOR, action="view imaging operations")
            operation = SqlAlchemyImagingRepository(uow.session).get(operation_id)
            if operation is None:
                raise NotFoundError("Imaging operation", str(operation_id))
            if operation.manifest_relpath is None:
                raise ImagingDestinationError("The operation has no recorded manifest.")
            manifest = check_contained(root / operation.manifest_relpath, root, what="imaging manifest")
        return self._read_manifest_payload(manifest)

    def reserve(self, case_identifier: str) -> ImagingOperation:
        with update_lock(), self.transaction() as uow:
            require_mutator(uow.session, action="reserve imaging")
            cases = SqlAlchemyCaseRepository(uow.session)
            candidate = cases.resolve(case_identifier)
            if candidate is None:
                raise CaseNotFoundError(case_identifier)
            case = cases.lock_for_imaging(candidate.id)
            if case is None:
                raise CaseNotFoundError(case_identifier)
            imaging = SqlAlchemyImagingRepository(uow.session)
            try:
                require_eligible_case(case.status, case.is_deleted)
                require_no_active_imaging(imaging.has_blocking_operation(case.id))
            except (ImagingTransitionError, InvariantViolationError) as exc:
                raise InvalidCaseStateError(str(exc)) from exc
            user, host = current_identity()
            actor = bound_actor(f"{user}@{host}")
            operation = imaging.create(case.id, case.number, actor)
            uow.before_commit(
                AuditService(self.session_manager).record_hook(
                    lambda: for_imaging_reservation(AuditAction.IMAGING_RESERVED, case.number, case.id, operation.id),
                    actor,
                )
            )
            return operation

    def verify_image(self, operation_id: UUID) -> bool:
        root = Path(settings.storage_root)
        with self.transaction() as uow:
            require_role(uow.session, ROLE_ADMIN, ROLE_AUDITOR, ROLE_INVESTIGATOR, action="verify an image")
            operation = SqlAlchemyImagingRepository(uow.session).get(operation_id)
            if operation is None:
                raise NotFoundError("Imaging operation", str(operation_id))
            if operation.state is not ImagingState.BYTE_VERIFIED:
                raise InvalidCaseStateError("Only a byte-verified image can be re-verified.")
            if operation.manifest_relpath is None or operation.image_relpath is None:
                raise ImagingDestinationError("The operation has no recorded image artifacts.")
            manifest_path = check_contained(root / operation.manifest_relpath, root, what="imaging manifest")
            image_path = check_contained(root / operation.image_relpath, root, what="imaging artifact")
            payload = self._read_manifest_payload(manifest_path)
            expected_bytes = payload.get("expected_bytes")
            expected_sha256 = payload.get("acquisition_sha256")
            if not isinstance(expected_bytes, int) or not isinstance(expected_sha256, str):
                raise ImagingDestinationError("The imaging manifest is malformed.")
            if operation.expected_bytes is None or operation.acquisition_sha256 is None:
                raise ImagingDestinationError("The operation has no recorded image digest.")
            if expected_bytes != operation.expected_bytes or expected_sha256 != operation.acquisition_sha256:
                raise ImagingDestinationError("The manifest does not match the recorded imaging operation.")
            verified, pieces = verify_image_with_pieces(image_path, expected_bytes, expected_sha256)
            if not self._manifest_matches(payload, expected_bytes, expected_sha256, pieces):
                verified = False
            uow.before_commit(
                AuditService(self.session_manager).record_hook(
                    lambda: for_imaging_event(
                        AuditAction.IMAGING_VERIFYING,
                        operation.case_number,
                        operation.case_id,
                        operation.id,
                        {"verified": verified, "readback_sha256": expected_sha256, "piecewise_verified": verified},
                    ),
                    self._actor(),
                )
            )
            return verified

    def seal_image(self, operation_id: UUID, passphrase: str) -> ImagingEncryption:
        root = Path(settings.storage_root)
        sealed: Path | None = None
        seal_meta: Path | None = None
        created_files = False
        try:
            with self.transaction() as uow:
                require_mutator(uow.session, action="seal an image")
                operation = SqlAlchemyImagingRepository(uow.session).get(operation_id)
                if operation is None:
                    raise NotFoundError("Imaging operation", str(operation_id))
                if operation.state is not ImagingState.BYTE_VERIFIED or operation.image_relpath is None:
                    raise InvalidCaseStateError("Only a byte-verified image can be sealed.")
                digest = operation.acquisition_sha256
                if not digest:
                    raise ImagingDestinationError("The operation has no acquisition digest.")
                case_dir, _, _, image, _, _, _ = self._operation_paths(operation.case_number, operation.id)
                sealed = image.with_name("image.raw.sealed")
                seal_meta = case_dir / "seal.json"
                if seal_meta.exists() or sealed.exists():
                    raise ImagingDestinationError("This image is already sealed.")
                image_path = check_contained(root / operation.image_relpath, root, what="imaging artifact")
                created_files = True
                sealed_size, header = seal_file(image_path, sealed, passphrase, digest)
                if header.get("alg") != ALGORITHM:
                    raise ImagingDestinationError("The sealed image algorithm is not supported.")
                encryption = ImagingEncryption(
                    algorithm=ALGORITHM,
                    sealed_relpath=relative_locator(root, sealed),
                    plaintext_sha256=digest,
                    sealed_size_bytes=sealed_size,
                )
                write_manifest(
                    seal_meta,
                    canonical_json({"encryption": encryption.model_dump(mode="json")}) + b"\n",
                )
                uow.before_commit(
                    AuditService(self.session_manager).record_hook(
                        lambda: for_imaging_event(
                            AuditAction.IMAGING_SEALED,
                            operation.case_number,
                            operation.case_id,
                            operation.id,
                            {"sealed_relpath": encryption.sealed_relpath, "algorithm": encryption.algorithm},
                        ),
                        self._actor(),
                    )
                )
                return encryption
        except BaseException:
            if created_files:
                if sealed is not None:
                    sealed.unlink(missing_ok=True)
                if seal_meta is not None:
                    seal_meta.unlink(missing_ok=True)
            raise

    def open_sealed_image(self, operation_id: UUID, passphrase: str, out: str | Path) -> Path:
        root = Path(settings.storage_root)
        target = Path(out).expanduser()
        created = False
        try:
            with self.transaction() as uow:
                require_mutator(uow.session, action="unseal an image")
                operation = SqlAlchemyImagingRepository(uow.session).get(operation_id)
                if operation is None:
                    raise NotFoundError("Imaging operation", str(operation_id))
                if operation.state is not ImagingState.BYTE_VERIFIED:
                    raise InvalidCaseStateError("Only a byte-verified image can be unsealed.")
                case_dir, _, _, _, _, _, _ = self._operation_paths(operation.case_number, operation.id)
                seal_meta = case_dir / "seal.json"
                if not seal_meta.is_file():
                    raise ImagingDestinationError("This image has no sealed copy.")
                payload = self._read_manifest_payload(seal_meta)
                try:
                    encryption = ImagingEncryption.model_validate(payload["encryption"])
                except (ValueError, KeyError) as exc:
                    raise ImagingDestinationError("The sealed image metadata is malformed.") from exc
                sealed = check_contained(root / encryption.sealed_relpath, root, what="sealed image")
                if target.exists() and not target.is_file():
                    raise ImagingDestinationError("The unseal destination must be a regular file path.")
                ensure_dir(target.parent)
                created = not target.exists()
                digest = open_sealed(sealed, target, passphrase)
                if digest != operation.acquisition_sha256:
                    raise ImagingReadbackError("Unsealed image does not match the operation digest.")
                uow.before_commit(
                    AuditService(self.session_manager).record_hook(
                        lambda: for_imaging_event(
                            AuditAction.IMAGING_UNSEALED,
                            operation.case_number,
                            operation.case_id,
                            operation.id,
                            {"digest": digest, "out": str(target)},
                        ),
                        self._actor(),
                    )
                )
                return target
        except BaseException:
            if created:
                target.unlink(missing_ok=True)
            raise

    def abandon(self, operation_id: UUID) -> ImagingOperation:
        with update_lock(), self.transaction() as uow:
            require_mutator(uow.session, action="abandon an imaging operation")
            imaging = SqlAlchemyImagingRepository(uow.session)
            candidate = imaging.get(operation_id)
            if candidate is None:
                raise NotFoundError("Imaging operation", str(operation_id))
            case = SqlAlchemyCaseRepository(uow.session).lock_for_imaging(candidate.case_id)
            if case is None:
                raise CaseNotFoundError(candidate.case_number)
            try:
                operation = imaging.abandon(operation_id)
            except ValueError as exc:
                raise InvalidCaseStateError(str(exc)) from exc
            if operation is None:
                raise NotFoundError("Imaging operation", str(operation_id))
            user, host = current_identity()
            actor = bound_actor(f"{user}@{host}")
            if candidate.state is ImagingState.PREPARING:
                hook = for_imaging_reservation(AuditAction.IMAGING_ABANDONED, case.number, case.id, operation.id)
            else:
                hook = for_imaging_event(
                    AuditAction.IMAGING_FAILED,
                    case.number,
                    case.id,
                    operation.id,
                    {
                        "failure_category": ImagingFailure.INTERRUPTED.value,
                        "state": operation.state.value,
                        "copied_bytes": operation.copied_bytes,
                    },
                )
            uow.before_commit(AuditService(self.session_manager).record_hook(lambda: hook, actor))
            return operation

    def acquire(
        self,
        operation_id: UUID,
        source_node: str,
        *,
        fixture_root: str | Path | None = None,
        allow_real_hardware: bool = False,
        progress: Progress | None = None,
        cancelled: Cancelled | None = None,
    ) -> ImagingOperation:
        with update_lock():
            operation = self._load_acquirable(operation_id)
            device_service = self._device_service_for(fixture_root, source_node, allow_real_hardware)
            source, source_stat = self._preflight(
                device_service,
                source_node,
                allow_real_hardware,
                None if operation.state is ImagingState.PREPARING else operation,
            )
            paths = self._operation_paths(operation.case_number, operation.id)
            if operation.state is ImagingState.PREPARING:
                claimed = self._claim(operation, source, paths)
                return self._finish_copy(claimed, source, source_stat, paths, 0, progress, cancelled)
            if operation.state is ImagingState.INTERRUPTED:
                offset, _, _ = self._acquiring_state(operation, paths)
                claimed = self._resume_claim(operation, now_utc())
                return self._finish_copy(claimed, source, source_stat, paths, offset, progress, cancelled)
            if operation.state is ImagingState.ACQUIRING:
                offset, digest, bad_regions = self._acquiring_state(operation, paths)
                if offset == operation.expected_bytes:
                    verifying = self._mark_verifying(operation, offset, digest, bad_regions)
                    return self._verify_and_publish(verifying, source, paths, bad_regions)
                return self._finish_copy(operation, source, source_stat, paths, offset, progress, cancelled)
            return self._verify_and_publish(operation, source, paths, self._checkpoint_regions(paths))

    def _finish_copy(
        self,
        operation: ImagingOperation,
        source: ImagingSource,
        source_stat: os.stat_result | None,
        paths: tuple,
        offset: int,
        progress: Progress | None,
        cancelled: Cancelled | None,
    ) -> ImagingOperation:
        verifying, bad_regions = self._acquire_bytes(
            operation, source, source_stat, paths, offset, progress=progress, cancelled=cancelled
        )
        return self._verify_and_publish(verifying, source, paths, bad_regions)

    def _load_acquirable(self, operation_id: UUID) -> ImagingOperation:
        with self.transaction() as uow:
            require_mutator(uow.session, action="acquire an image")
            operation = SqlAlchemyImagingRepository(uow.session).get(operation_id)
            if operation is None:
                raise NotFoundError("Imaging operation", str(operation_id))
            if operation.state not in {
                ImagingState.PREPARING,
                ImagingState.INTERRUPTED,
                ImagingState.ACQUIRING,
                ImagingState.VERIFYING,
            }:
                raise InvalidCaseStateError("Only an unresolved imaging operation can start acquisition.")
            return operation

    def _device_service_for(self, fixture_root: str | Path | None, source_node: str, allow_real_hardware: bool):
        if self._device_service is not None:
            return self._device_service
        from trace_core.devices.file_device import FileDevice
        from trace_core.devices.service import DeviceService

        if allow_real_hardware:
            return DeviceService(self.session_manager)
        root = Path(fixture_root) if fixture_root is not None else Path(source_node).expanduser().absolute().parent
        adapter = FileDevice(root)
        return DeviceService(self.session_manager, enumerator=adapter, inspector=adapter, probe=adapter)

    def _preflight(
        self, device_service, source_node: str, allow_real_hardware: bool, operation: ImagingOperation | None
    ) -> tuple[ImagingSource, os.stat_result | None]:
        devices = device_service.list_devices()
        cleaned = str(source_node).strip()
        exact = [device for device in devices if device.node == cleaned]
        if not exact:
            requested = Path(cleaned).expanduser()
            if requested.name == cleaned:
                exact = [device for device in devices if Path(device.node).name == cleaned]
            else:
                exact = [device for device in devices if Path(device.node).absolute() == requested.absolute()]
        if len(exact) != 1:
            raise ImagingSourceUnavailableError("The source is absent or ambiguous. Refresh the device list and retry.")
        device = exact[0]
        if device.requires_real_hardware_opt_in and not allow_real_hardware:
            raise AuthorizationError(f"{source_node} is real hardware; pass --physical to proceed")
        inspection = device_service.inspect_device(device.node, allow_real_hardware=allow_real_hardware)
        gate = device_service.check_device(device.node, inspection=inspection, allow_real_hardware=allow_real_hardware)
        if gate.verdict is not WpVerdict.READ_ONLY:
            raise ImagingSourceUnavailableError("The source did not pass the read-only gate.")
        if device.size_bytes is None:
            raise ImagingSourceUnavailableError("The source does not report a byte size.")
        if operation is not None:
            if inspection.fingerprint.serial.value != operation.source_serial:
                raise ImagingSourceChangedError("The resumed source is not the device that was originally selected.")
            if device.size_bytes != operation.expected_bytes:
                raise ImagingSourceChangedError("The resumed source changed size since the original acquisition.")
        kind = ImagingSourceKind(device.kind.value)
        source_stat: os.stat_result | None = None
        if kind is ImagingSourceKind.FILE:
            try:
                source_stat = os.stat(device.node)
            except OSError as exc:
                raise ImagingSourceUnavailableError(
                    "The fixture source could not be inspected before acquisition."
                ) from exc
            if source_stat.st_size != device.size_bytes:
                raise ImagingSourceChangedError("The fixture source changed size before acquisition.")
        source = ImagingSource(
            node=device.node,
            kind=kind,
            serial=inspection.fingerprint.serial.value,
            model=inspection.fingerprint.model,
            size_bytes=device.size_bytes,
            protection=gate.verdict.value,
            adapter=gate.evidence.adapter_version,
            synthetic=gate.evidence.platform == "fake",
            inspected_at=inspection.inspected_at,
        )
        return source, source_stat

    def _operation_paths(self, case_number: str, operation_id: UUID) -> tuple[Path, Path, Path, Path, Path, str, str]:
        root = Path(settings.storage_root)
        case_dir = root / "cases" / case_number / "imaging" / str(operation_id)
        check_contained(case_dir, root, what="imaging operation directory")
        partial = partial_path(case_dir)
        image = case_dir / "image.raw"
        manifest = case_dir / "manifest.json"
        return (
            case_dir,
            partial,
            checkpoint_path(case_dir),
            image,
            manifest,
            relative_locator(root, image),
            relative_locator(root, manifest),
        )

    def _claim(self, operation: ImagingOperation, source: ImagingSource, paths: tuple) -> ImagingOperation:
        case_dir, partial, _, _, _, image_relpath, manifest_relpath = paths
        with self.transaction() as uow:
            require_mutator(uow.session, action="start an imaging acquisition")
            cases = SqlAlchemyCaseRepository(uow.session)
            case = cases.lock_for_imaging(operation.case_id)
            if case is None:
                raise CaseNotFoundError(operation.case_number)
            try:
                require_eligible_case(case.status, case.is_deleted)
            except ImagingTransitionError as exc:
                raise InvalidCaseStateError(str(exc)) from exc
            imaging = SqlAlchemyImagingRepository(uow.session)
            current = imaging.get(operation.id)
            if current is None:
                raise NotFoundError("Imaging operation", str(operation.id))
            if current.state is not ImagingState.PREPARING:
                raise InvalidCaseStateError("Only a preparing imaging reservation can start acquisition.")
            claimed = imaging.claim_for_acquisition(
                operation.id,
                source,
                source.size_bytes,
                relative_locator(Path(settings.storage_root), partial),
                image_relpath,
                manifest_relpath,
                now_utc(),
            )
            if claimed is None:
                raise NotFoundError("Imaging operation", str(operation.id))
            actor = self._actor()
            uow.before_commit(
                AuditService(self.session_manager).record_hook(
                    lambda: for_imaging_event(
                        AuditAction.IMAGING_STARTED,
                        case.number,
                        case.id,
                        operation.id,
                        self._start_details(source, paths, resumed=False),
                    ),
                    actor,
                )
            )
            return claimed

    def _checkpoint_payload(self, operation: ImagingOperation, paths: tuple) -> dict[str, object]:
        case_dir, partial, checkpoint, _, _, _, _ = paths
        payload = read_checkpoint(checkpoint)
        if payload is None or not case_dir.is_dir() or not partial.is_file():
            raise ImagingDestinationError("No usable resume checkpoint exists for this operation.")
        if payload.get("source_serial") != operation.source_serial:
            raise ImagingSourceChangedError("The resume checkpoint belongs to a different source.")
        if payload.get("expected_bytes") != operation.expected_bytes:
            raise ImagingSourceChangedError("The resume checkpoint belongs to a different image size.")
        expected = operation.expected_bytes
        if expected is None:
            raise ImagingDestinationError("The operation has no expected byte count.")
        offset = payload.get("offset")
        if not isinstance(offset, int) or offset < 0 or offset > expected:
            raise ImagingDestinationError("The resume checkpoint has an invalid offset.")
        if partial.stat().st_size != offset:
            raise ImagingDestinationError("The partial image does not match the resume checkpoint.")
        return payload

    def _acquiring_state(
        self, operation: ImagingOperation, paths: tuple
    ) -> tuple[int, str, tuple[ImagingBadRegion, ...]]:
        payload = self._checkpoint_payload(operation, paths)
        offset = payload.get("offset")
        digest = payload.get("digest")
        if not isinstance(offset, int) or not isinstance(digest, str) or len(digest) != 64:
            raise ImagingDestinationError("The checkpoint has no completed-copy digest.")
        partial = paths[1]
        if not partial.is_file() or partial.stat().st_size != offset:
            raise ImagingDestinationError("The partial image does not match the resume checkpoint.")
        if self._partial_digest(partial) != digest:
            raise ImagingDestinationError("The partial image does not match the resume checkpoint.")
        return offset, digest, self._bad_regions_from_payload(payload)

    @staticmethod
    def _bad_regions_from_payload(payload: dict[str, object]) -> tuple[ImagingBadRegion, ...]:
        raw = payload.get("bad_regions")
        if not isinstance(raw, list):
            return ()
        regions: list[ImagingBadRegion] = []
        for item in raw:
            if isinstance(item, dict):
                try:
                    regions.append(ImagingBadRegion.model_validate(item))
                except Exception:
                    continue
        return tuple(regions)

    @staticmethod
    def _checkpoint_regions(paths: tuple) -> tuple[ImagingBadRegion, ...]:
        _, _, checkpoint, _, _, _, _ = paths
        payload = read_checkpoint(checkpoint)
        return ImagingService._bad_regions_from_payload(payload) if payload is not None else ()

    def _resume_claim(self, operation: ImagingOperation, started_at: datetime) -> ImagingOperation:
        with self.transaction() as uow:
            require_mutator(uow.session, action="resume an imaging acquisition")
            cases = SqlAlchemyCaseRepository(uow.session)
            case = cases.lock_for_imaging(operation.case_id)
            if case is None:
                raise CaseNotFoundError(operation.case_number)
            try:
                require_eligible_case(case.status, case.is_deleted)
            except ImagingTransitionError as exc:
                raise InvalidCaseStateError(str(exc)) from exc
            imaging = SqlAlchemyImagingRepository(uow.session)
            claimed = imaging.resume_claim(operation.id, started_at)
            if claimed is None:
                raise NotFoundError("Imaging operation", str(operation.id))
            actor = self._actor()
            uow.before_commit(
                AuditService(self.session_manager).record_hook(
                    lambda: for_imaging_event(
                        AuditAction.IMAGING_STARTED,
                        case.number,
                        case.id,
                        operation.id,
                        self._start_details(self._source_from_operation(operation), (), resumed=True),
                    ),
                    actor,
                )
            )
            return claimed

    def _acquire_bytes(
        self,
        operation: ImagingOperation,
        source: ImagingSource,
        source_stat: os.stat_result | None,
        paths: tuple,
        offset: int,
        *,
        progress: Progress | None,
        cancelled: Cancelled | None,
    ) -> tuple[ImagingOperation, tuple[ImagingBadRegion, ...]]:
        case_dir, partial, checkpoint, _, _, _, _ = paths
        writer: BinaryIO | None = None
        reader = open_source(source, source_stat)
        prior_regions = self._bad_regions_from_payload(read_checkpoint(checkpoint) or {}) if offset else ()
        live_regions = list(prior_regions)
        initial_digest = self._acquiring_state(operation, paths)[1] if offset else ""
        resume_progress, resume_cancelled = self._checkpoint_callbacks(
            operation, source, checkpoint, offset, progress, cancelled, live_regions, initial_digest
        )

        hasher = hashlib.sha256()
        try:
            ensure_dir(case_dir.parent)
            if offset == 0:
                try:
                    case_dir.mkdir(exist_ok=False, mode=0o700)
                except FileExistsError as exc:
                    raise ImagingDestinationExistsError("The imaging operation directory already exists.") from exc
                except OSError as exc:
                    raise ImagingDestinationError("The imaging operation directory could not be created.") from exc
                writer = create_partial(partial)
            else:
                if not case_dir.is_dir() or not partial.is_file():
                    raise ImagingDestinationError("The partial image disappeared before resume.")
                remaining = offset
                with partial.open("rb") as handle:
                    while remaining > 0:
                        chunk = handle.read(min(CHUNK_SIZE, remaining))
                        if not chunk:
                            raise ImagingDestinationError("The partial image does not match the resume checkpoint.")
                        hasher.update(chunk)
                        remaining -= len(chunk)
                if hasher.hexdigest() != initial_digest:
                    raise ImagingDestinationError("The partial image does not match the resume checkpoint.")
                writer = append_partial(partial)
            reader.open(offset)
            self._guard_destination(partial, source)
            copied, stream_digest, new_regions = copy_raw_with_regions(
                reader,
                writer,
                operation.expected_bytes or 0,
                offset=offset,
                progress_with_digest=resume_progress,
                digest=hasher,
                cancelled=resume_cancelled,
                on_bad_region=live_regions.append,
            )
            writer.flush()
            os.fsync(writer.fileno())
            writer.close()
            writer = None
            reader.verify_unchanged()
            reader.close()
            if source.synthetic and not new_regions and source.serial != f"SYNTH-{stream_digest[:32]}" and offset == 0:
                raise ImagingSourceChangedError("The fixture source no longer matches its preflight identity.")
            digest = stream_digest
            bad_regions = tuple(live_regions)
            write_checkpoint(
                checkpoint,
                {
                    "offset": copied + offset,
                    "expected_bytes": operation.expected_bytes or 0,
                    "source_serial": source.serial,
                    "source_node": source.node,
                    "digest": digest,
                    "bad_regions": [region.model_dump() for region in bad_regions],
                    "tool_version": settings.version,
                },
            )
        except ImagingInterruptedError:
            self._close_writer(writer)
            self._close_reader(reader)
            self._fail_operation(operation, ImagingFailure.INTERRUPTED, target=ImagingState.INTERRUPTED)
            raise
        except Exception as exc:
            self._close_writer(writer)
            self._close_reader(reader)
            self._fail_operation(operation, _failure_for(exc))
            raise
        verifying = self._mark_verifying(operation, copied + offset, digest, bad_regions)
        return verifying, bad_regions

    @staticmethod
    def _checkpoint_callbacks(
        operation: ImagingOperation,
        source: ImagingSource,
        checkpoint: Path,
        offset: int,
        progress: Progress | None,
        cancelled: Cancelled | None,
        bad_regions: list[ImagingBadRegion] | None = None,
        digest: str = "",
    ) -> tuple[CheckpointProgress, Cancelled]:
        position = {"bytes": offset}
        digest_state = {"value": digest}
        regions = bad_regions if bad_regions is not None else []

        def _write_checkpoint() -> None:
            if not digest_state["value"]:
                return
            write_checkpoint(
                checkpoint,
                {
                    "offset": position["bytes"],
                    "expected_bytes": operation.expected_bytes or 0,
                    "source_serial": source.serial,
                    "source_node": source.node,
                    "digest": digest_state["value"],
                    "bad_regions": [region.model_dump() for region in regions],
                    "tool_version": settings.version,
                },
            )

        def _progress(done: int, total: int, running_digest: str) -> None:
            position["bytes"] = done
            digest_state["value"] = running_digest
            if done - offset >= _CHECKPOINT_BYTES and done % _CHECKPOINT_BYTES == 0:
                _write_checkpoint()
            if progress is not None:
                progress(done, total)

        def _cancelled() -> bool:
            if cancelled is not None and cancelled():
                _write_checkpoint()
                return True
            return False

        return _progress, _cancelled

    @staticmethod
    def _close_reader(reader: SourceReader) -> None:
        try:
            reader.close()
        except ImagingSourceReadError:
            pass

    @staticmethod
    def _partial_digest(partial: Path) -> str:
        with partial.open("rb") as handle:
            return hash_stream(handle)

    def _mark_verifying(
        self,
        operation: ImagingOperation,
        copied: int,
        acquisition_sha256: str,
        bad_regions: tuple[ImagingBadRegion, ...] = (),
    ) -> ImagingOperation:
        with self.transaction() as uow:
            require_mutator(uow.session, action="verify an imaging acquisition")
            updated = SqlAlchemyImagingRepository(uow.session).mark_verifying(operation.id, copied, acquisition_sha256)
            if updated is None:
                raise NotFoundError("Imaging operation", str(operation.id))
            uow.before_commit(
                AuditService(self.session_manager).record_hook(
                    lambda: for_imaging_event(
                        AuditAction.IMAGING_VERIFYING,
                        operation.case_number,
                        operation.case_id,
                        operation.id,
                        {
                            "copied_bytes": copied,
                            "acquisition_sha256": acquisition_sha256,
                            "bad_region_count": len(bad_regions),
                            "bad_region_bytes": sum(region.length for region in bad_regions),
                        },
                    ),
                    self._actor(),
                )
            )
            return updated

    def _verify_and_publish(
        self,
        operation: ImagingOperation,
        source: ImagingSource,
        paths: tuple,
        bad_regions: tuple[ImagingBadRegion, ...] = (),
    ) -> ImagingOperation:
        _, partial, checkpoint, image, manifest, image_relpath, manifest_relpath = paths
        expected = operation.expected_bytes or 0
        acquisition_sha256 = operation.acquisition_sha256
        if acquisition_sha256 is None:
            raise ImagingAcquisitionError("The acquisition digest was not persisted before verification.")
        try:
            if partial.exists():
                publish_image(partial, image)
            elif not image.exists():
                raise ImagingDestinationError("Neither the partial nor the final image exists.")
            verified, pieces = verify_image_with_pieces(image, expected, acquisition_sha256)
            if not verified:
                self._fail_operation(operation, ImagingFailure.READBACK_MISMATCH, target=ImagingState.QUARANTINED)
                raise ImagingReadbackError("The published image did not match the acquisition stream.")
            finished_at = now_utc()
            piecewise = ImagingPiecewise(chunk_size=PIECE_SIZE, count=len(pieces), hashes=pieces)
            manifest_model = ImagingManifest(
                operation_id=operation.id,
                case_id=operation.case_id,
                case_number=operation.case_number,
                source=source,
                expected_bytes=expected,
                copied_bytes=operation.copied_bytes or 0,
                acquisition_sha256=acquisition_sha256,
                readback_sha256=acquisition_sha256,
                image_relpath=image_relpath,
                piecewise=piecewise,
                bad_regions=bad_regions,
                created_at=operation.created_at,
                finished_at=finished_at,
                tool_version=settings.version,
            )
            if manifest.exists():
                self._check_existing_manifest(manifest, expected, acquisition_sha256, pieces)
            else:
                write_manifest(manifest, canonical_json(manifest_model.model_dump(mode="json")) + b"\n")
            verified_operation = self._mark_verified(operation, expected, acquisition_sha256, finished_at)
            discard_checkpoint(checkpoint)
            return verified_operation
        except ImagingAcquisitionError as exc:
            self._fail_operation(operation, _failure_for(exc))
            raise
        except OSError as exc:
            self._fail_operation(operation, ImagingFailure.PUBLISH_FAILED)
            raise ImagingPublishError("The image could not be finalized safely.") from exc

    @staticmethod
    def _read_manifest_payload(path: Path) -> dict[str, object]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ImagingDestinationError("The imaging manifest could not be read.") from exc
        if not isinstance(payload, dict):
            raise ImagingDestinationError("The imaging manifest is malformed.")
        return payload

    @staticmethod
    def _manifest_matches(
        payload: dict[str, object], expected_bytes: int, expected_sha256: str, pieces: tuple[str, ...] | None = None
    ) -> bool:
        if (
            payload.get("manifest_version") != "trace-imaging-manifest-v1"
            or payload.get("format") != "RAW"
            or payload.get("expected_bytes") != expected_bytes
            or payload.get("acquisition_sha256") != expected_sha256
        ):
            return False
        piecewise = payload.get("piecewise")
        if not isinstance(piecewise, dict):
            return False
        if piecewise.get("algorithm") != "SHA-256" or piecewise.get("chunk_size") != PIECE_SIZE:
            return False
        hashes = piecewise.get("hashes")
        count = piecewise.get("count")
        if not isinstance(hashes, list) or not isinstance(count, int) or len(hashes) != count:
            return False
        if any(not isinstance(item, str) for item in hashes):
            return False
        if pieces is not None and tuple(hashes) != pieces:
            return False
        return True

    @staticmethod
    def _check_existing_manifest(
        manifest: Path, expected_bytes: int, expected_sha256: str, pieces: tuple[str, ...]
    ) -> None:
        payload = ImagingService._read_manifest_payload(manifest)
        if not ImagingService._manifest_matches(payload, expected_bytes, expected_sha256, pieces):
            raise ImagingDestinationError("The existing imaging manifest does not match the verified image.")

    def _mark_verified(
        self, operation: ImagingOperation, readback_bytes: int, readback_sha256: str, finished_at: datetime
    ) -> ImagingOperation:
        with self.transaction() as uow:
            require_mutator(uow.session, action="complete an imaging acquisition")
            updated = SqlAlchemyImagingRepository(uow.session).mark_verified(
                operation.id, readback_bytes, readback_sha256, finished_at
            )
            if updated is None:
                raise NotFoundError("Imaging operation", str(operation.id))
            uow.before_commit(
                AuditService(self.session_manager).record_hook(
                    lambda: for_imaging_event(
                        AuditAction.IMAGING_COMPLETED,
                        operation.case_number,
                        operation.case_id,
                        operation.id,
                        {
                            "expected_bytes": readback_bytes,
                            "copied_bytes": updated.copied_bytes,
                            "acquisition_sha256": readback_sha256,
                            "readback_sha256": readback_sha256,
                            "image_relpath": updated.image_relpath,
                            "manifest_relpath": updated.manifest_relpath,
                            "source_kind": operation.source_kind.value if operation.source_kind else None,
                        },
                    ),
                    self._actor(),
                )
            )
            return updated

    def _fail_operation(
        self, operation: ImagingOperation, failure: ImagingFailure, *, target: ImagingState | None = None
    ) -> ImagingOperation | None:
        with self.transaction() as uow:
            require_mutator(uow.session, action="record an imaging failure")
            imaging = SqlAlchemyImagingRepository(uow.session)
            current = imaging.get(operation.id)
            if current is None:
                raise NotFoundError("Imaging operation", str(operation.id))
            if current.state in _FAILED_STATES:
                return current
            chosen = target or (
                ImagingState.QUARANTINED if current.state is ImagingState.VERIFYING else ImagingState.FAILED
            )
            updated = imaging.mark_failure(operation.id, chosen, failure, now_utc())
            if updated is None:
                raise NotFoundError("Imaging operation", str(operation.id))
            action = (
                AuditAction.IMAGING_QUARANTINED if chosen is ImagingState.QUARANTINED else AuditAction.IMAGING_FAILED
            )
            uow.before_commit(
                AuditService(self.session_manager).record_hook(
                    lambda: for_imaging_event(
                        action,
                        operation.case_number,
                        operation.case_id,
                        operation.id,
                        {
                            "failure_category": failure.value,
                            "state": chosen.value,
                            "copied_bytes": current.copied_bytes,
                        },
                    ),
                    self._actor(),
                )
            )
            return updated

    @staticmethod
    def _guard_destination(partial: Path, source: ImagingSource) -> None:
        if source.kind is not ImagingSourceKind.FILE:
            return
        try:
            source_stat = os.stat(source.node)
            partial_stat = os.stat(partial)
        except OSError:
            return
        if (source_stat.st_dev, source_stat.st_ino) == (partial_stat.st_dev, partial_stat.st_ino):
            raise ImagingDestinationError("The destination is the source; imaging into the source is refused.")

    @staticmethod
    def _actor() -> str:
        user, host = current_identity()
        return bound_actor(f"{user}@{host}")

    @staticmethod
    def _source_from_operation(operation: ImagingOperation) -> ImagingSource:
        return ImagingSource(
            node=operation.source_node or "",
            kind=operation.source_kind or ImagingSourceKind.FILE,
            serial=operation.source_serial or "",
            model=operation.source_model or "",
            size_bytes=operation.source_size_bytes or 0,
            protection=operation.source_protection or "",
            adapter=operation.source_adapter or "",
            synthetic=False,
            inspected_at=operation.source_inspected_at or operation.created_at,
        )

    @staticmethod
    def _start_details(source: ImagingSource, paths: tuple, *, resumed: bool) -> dict[str, object]:
        image_relpath = paths[5] if len(paths) > 5 else None
        manifest_relpath = paths[6] if len(paths) > 6 else None
        return {
            "source_kind": source.kind.value,
            "source_serial": source.serial,
            "source_size_bytes": source.size_bytes,
            "source_protection": source.protection,
            "source_adapter": source.adapter,
            "synthetic": source.synthetic,
            "expected_bytes": source.size_bytes,
            "image_relpath": image_relpath,
            "manifest_relpath": manifest_relpath,
            "resumed": resumed,
        }

    @staticmethod
    def _close_writer(writer: BinaryIO | None) -> None:
        if writer is None:
            return
        try:
            writer.flush()
            os.fsync(writer.fileno())
        except OSError:
            pass
        try:
            writer.close()
        except OSError:
            pass


def _failure_for(exc: Exception) -> ImagingFailure:
    if isinstance(exc, ImagingInterruptedError):
        return ImagingFailure.INTERRUPTED
    if isinstance(exc, ImagingSourceUnavailableError):
        return ImagingFailure.SOURCE_UNAVAILABLE
    if isinstance(exc, ImagingSourceChangedError):
        return ImagingFailure.SOURCE_CHANGED
    if isinstance(exc, (ImagingSourceReadError, EOFError, BlockingIOError)):
        return ImagingFailure.SOURCE_READ_FAILED
    if isinstance(exc, ImagingDestinationExistsError):
        return ImagingFailure.DESTINATION_EXISTS
    if isinstance(exc, ImagingDestinationError):
        return ImagingFailure.DESTINATION_WRITE_FAILED
    if isinstance(exc, ImagingReadbackError):
        return ImagingFailure.READBACK_MISMATCH
    if isinstance(exc, ImagingPublishError):
        return ImagingFailure.PUBLISH_FAILED
    if isinstance(exc, OSError):
        return ImagingFailure.DESTINATION_WRITE_FAILED
    return ImagingFailure.INTERNAL_ERROR
