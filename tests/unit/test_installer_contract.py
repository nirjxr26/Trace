"""Both installers must not report success for a host that failed verification.

Neither propagated `trace doctor`'s exit status: a failing doctor became a log line and the
installer finished with exit 0. Semantic codes 9, 10 and 12 exist precisely to distinguish
device-preflight outcomes, and both scripts flattened all of them — during the one
procedure most likely to run unattended on a fresh box.

These assert the scripts' own text, because executing an installer would download, install
and modify PATH. The PowerShell parser is available on this host, so install.ps1 is also
parsed for real.
"""

import re
from pathlib import Path

import pytest

PS1 = Path(__file__).resolve().parents[2] / "install.ps1"
SH = Path(__file__).resolve().parents[2] / "install.sh"


def test_the_powershell_installer_parses() -> None:
    import sys

    if sys.platform != "win32":
        pytest.skip("the PowerShell parser is not available here")
    pwsh = pytest.importorskip("subprocess")
    script = (
        "$errs=$null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{PS1}', [ref]$null, [ref]$errs) | Out-Null; "
        "if ($errs.Count -gt 0) { $errs | ForEach-Object { Write-Output $_.Message }; exit 1 }; exit 0"
    )
    result = pwsh.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout


@pytest.mark.parametrize(
    "script,name",
    [(PS1, "install.ps1"), (SH, "install.sh")],
    ids=["ps1", "sh"],
)
def test_a_failing_doctor_is_not_swallowed(script: Path, name: str) -> None:
    text = script.read_text(encoding="utf-8")
    marker = "doctor }" if "doctor }" in text else "doctor;"
    block = text[text.index(marker) : text.index(marker) + 900]
    assert "Database unreachable" not in block, (
        f"{name} reports an unreachable database it never diagnosed - doctor also fails on an "
        "unverifiable ledger, a writable source and unknown write protection"
    )
    assert "did not pass" in block, f"{name} must say the check did not pass, not guess at a cause"


@pytest.mark.parametrize(
    "script,name",
    [(PS1, "install.ps1"), (SH, "install.sh")],
    ids=["ps1", "sh"],
)
def test_a_failing_doctor_reaches_the_exit_status(script: Path, name: str) -> None:
    """The flag is set in the doctor block; something must consume it."""
    text = script.read_text(encoding="utf-8")
    assert "DoctorFailed" in text or "DOCTOR_FAILED" in text, f"{name} records no doctor failure"
    assert re.search(r"if .*(DoctorFailed|DOCTOR_FAILED).*?exit 1", text, re.S), (
        f"{name} records the failure but never exits non-zero for it"
    )


def test_the_powershell_installer_rejects_unknown_flags() -> None:
    """A typo'd flag was ignored, so `--purge-date` installed the default ref and
    `--uninstall --purge-data` silently dropped the data removal. install.sh exits 2."""
    text = PS1.read_text(encoding="utf-8")
    assert "UnknownFlags" in text, "unknown flags must be collected"
    assert re.search(r"UnknownFlags\.Count -gt 0.*?exit 2", text, re.S), "and must exit 2 like install.sh"
    assert "Unknown flag" in text, "and must say which flag was wrong"


def test_the_shell_installer_rejects_unknown_flags() -> None:
    """The behaviour install.ps1 now matches."""
    text = SH.read_text(encoding="utf-8")
    assert re.search(r"Unknown flag.*?exit 2", text, re.S), text[:0]


@pytest.mark.parametrize(
    "script,name,flag",
    [(PS1, "install.ps1", "DoctorFailed"), (SH, "install.sh", "DOCTOR_FAILED")],
    ids=["ps1", "sh"],
)
def test_a_doctor_failure_is_actually_recorded(script: Path, name: str, flag: str) -> None:
    """The flag must be set in the catch/else branch, not merely declared."""
    text = script.read_text(encoding="utf-8")
    marker = "doctor }" if "doctor }" in text else "doctor;"
    block = text[text.index(marker) : text.index(marker) + 900]
    value = r"\$?true" if flag.startswith("Doctor") else "1"
    assert re.search(rf"{flag}\s*=\s*{value}", block), f"{name} never sets {flag} when doctor fails"


def test_a_successful_doctor_still_reports_success() -> None:
    """The failure path must not have broken the working one."""
    ps_text = PS1.read_text(encoding="utf-8")
    assert "[OK] Database verified and up to date." in ps_text
    sh_text = SH.read_text(encoding="utf-8")
    assert "[OK] Database verified and up to date." in sh_text
