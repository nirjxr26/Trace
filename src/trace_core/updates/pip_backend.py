"""pip backend for venv layouts. Single source for wheel install/proof/rollback.

Scope: the file-tree updater (stage/activate/rollback pointers) cannot swap code
inside a virtualenv — the venv runs whatever pip put in site-packages. On venv
layouts the verified wheel is therefore pip-installed; frozen layouts keep the
file-tree path and never touch this module. Editable installs converge to wheel
installs on first update; that is intended for release machines.
"""

import subprocess
import sys
from pathlib import Path

from trace_core.updates.errors import UpdateError

_PIP_TIMEOUT_SECONDS = 300
_PROOF_TIMEOUT_SECONDS = 120
_VERSION_PROBE = "from trace_core.core.settings import settings; print(settings.version)"


def venv_python() -> Path | None:
    """Interpreter owning the install, or None outside a venv (frozen/system)."""
    exe = Path(sys.executable)
    if sys.prefix == getattr(sys, "base_prefix", sys.prefix) or not exe.exists():
        return None
    return exe


def pip_layout_for(artifact_path: str | Path) -> bool:
    """True when the staged artifact upgrades via pip: a wheel inside a venv."""
    return Path(artifact_path).suffix == ".whl" and venv_python() is not None


def _run_quiet(cmd: list[str], timeout: int):  # type: ignore[no-untyped-def]
    """Run and capture, returning None when the process never starts.

    Callers own exit-code semantics (raise vs None); startup failure is shared.
    """
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return None


def pip_install_wheel(python: Path, wheel: Path) -> None:
    """Install a verified wheel into its venv. Code-only: deps ride fresh installs."""
    proc = _run_quiet([str(python), "-m", "pip", "install", "--no-deps", str(wheel)], _PIP_TIMEOUT_SECONDS)
    if proc is None:
        raise UpdateError(f"pip install failed to start for {wheel.name}")
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip()[-2000:]
        raise UpdateError(f"pip install failed (exit {proc.returncode}): {tail}")


def pip_installed_version(python: Path | None = None) -> str | None:
    """Version string the venv actually imports, or None when unverifiable.

    Isolated (`-I`) so cwd/PYTHONPATH can never shadow site-packages, and only
    stdout is read so warnings on stderr cannot pollute the parse.
    """
    target = python or venv_python()
    if target is None:
        return None
    proc = _run_quiet([str(target), "-I", "-c", _VERSION_PROBE], _PROOF_TIMEOUT_SECONDS)
    if proc is None or proc.returncode != 0:
        return None
    version = proc.stdout.strip().split()[0] if proc.stdout.strip() else ""
    return version or None


def pip_health(manifest, staged: Path | None) -> bool:  # type: ignore[no-untyped-def]
    """True when no pip proof is required or the venv imports the target.

    A flipped pointer over stale code is a lying update, so a version mismatch
    here must fail the health gate in the lifecycle.
    """
    if staged is None or not pip_layout_for(staged):
        return True
    return pip_installed_version() == manifest.version


def restore_release(base: str | Path, version: str) -> bool:
    """Pip-install the retained wheel for a previous release. True if attempted.

    No wheel staged (frozen layout) or no venv: no-op returning False, and the
    existing pointer-flip rollback stands alone as before.
    """
    candidates = sorted((Path(base) / "releases" / version).glob("*.whl"))
    if not candidates:
        return False
    if len(candidates) > 1:
        raise UpdateError(f"ambiguous previous wheels for {version}; refusing to guess")
    python = venv_python()
    if python is None:
        return False
    pip_install_wheel(python, candidates[0])
    return True
