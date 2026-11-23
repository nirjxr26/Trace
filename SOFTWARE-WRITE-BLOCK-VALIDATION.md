# Software write blocking — development workflow

Software write blocking is not forensic proof. It is for development and training only. Evidentiary acquisitions require a validated hardware write blocker.

## Preflight record

Trace records these fields before a software-only acquisition:

- `kernel_version` from `platform.release()`.
- `automount` must be `DISABLED`.
- `raid_lvm` must be `DISABLED`.
- `udev_rules` must contain at least one kernel write-block rule.
- `source_mounted` must be `False`.
- `block_device_read_only` must be `True` on the parent block device.
- `io_path` is `O_RDONLY source read path; no SG_IO or SMART commands during acquisition`.
- `validation` is `OPERATOR_VALIDATION_REQUIRED`.
- `label` is `SOFTWARE-ONLY · NOT EVIDENTIARY`.

Any unknown preflight value fails closed. A udev rule qualifies only when one logical rule contains `ACTION=="add"` and a `RUN+` command with `blockdev --setro`, `wrtblk`, or `BLKROSET`. Generic `ACTION=="add"` or `ACTION=="remove"` lines do not qualify. `defaults` in `/etc/fstab` implies `auto`, and `noauto,x-systemd.automount` still counts as automount. Generated units under `/run/systemd/generator` are checked. An undefined `auto_activation_volume_list` counts as LVM auto-activation enabled; only `[]` counts as disabled. `/dev/mapper/control` is not a volume.

The evidence class is written into the resume checkpoint. A resume with a different write-blocking opt-in, or with a checkpoint that has no evidence class, is refused. This prevents a software-only acquisition from being republished as hardware-evidentiary.

A physical acquisition is recorded as `HARDWARE_WRITE_BLOCK` only when the operator passes `--hardware-write-block`, which attests to a validated hardware write blocker. Without that attestation the evidence class is `UNVERIFIED_WRITE_PROTECTION`, and without the software opt-in a software read-only device is not claimed as hardware-evidentiary. The device gate alone cannot distinguish hardware protection from `blockdev --setro`.

## Host setup

1. Use a dedicated Linux host, not a VM for end-to-end claims.
2. Disable filesystem automount, RAID auto-assembly, and LVM auto-activation.
3. Install a kernel write-block udev rule for every new block device.
4. Attach the evidence disk only after host controls are active.
5. Mark the parent block device read-only with the installed blocker tool.
6. Confirm `/sys/block/<parent>/ro` is `1`.
7. Confirm the source is not mounted.
8. Open the source only with `O_RDONLY`; never mount it.
9. Do not issue SG_IO, SMART, TRIM, cache-flush, or any other write-capable command during acquisition.

## Disposable-media validation

Before trusting the workflow for development:

1. Use a disposable disk that contains no evidence.
2. Apply the same write-block procedure.
3. Attempt a direct write and a filesystem-level write.
4. Confirm both writes fail.
5. Capture kernel logs showing rejected write or discard requests.
6. Re-read the disk and confirm its hash did not change.
7. Record the tool versions, kernel version, commands, and results with the acquisition records.

## Labels

Trace writes `SOFTWARE-ONLY · NOT EVIDENTIARY` to:

- the Imaging progress popup;
- the acquisition manifest;
- the `IMAGING_STARTED` audit event payload.

Do not remove these labels. Do not describe a software-only acquisition as write-protected evidence.
