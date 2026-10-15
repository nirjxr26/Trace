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
    ("script", "name"),
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
    ("script", "name"),
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
    ("script", "name", "flag"),
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


def _shell_function_body(name: str) -> str:
    text = SH.read_text(encoding="utf-8")
    start = text.index(f"{name}() {{")
    return text[start : text.index("\n}", start)]


def test_the_shell_runner_keeps_the_command_it_was_given() -> None:
    body = _shell_function_body("trace_run")
    assert not re.search(r"^\s*shift\b", body, re.M), (
        "trace_run shifts its first argument away, so every call site runs '-m' or "
        "'curl' instead of the command and a fresh machine can never build its virtualenv"
    )


@pytest.mark.parametrize(
    ("script", "name"),
    [(PS1, "install.ps1"), (SH, "install.sh")],
    ids=["ps1", "sh"],
)
def test_a_virtual_environment_without_pip_is_bootstrapped(script: Path, name: str) -> None:
    text = script.read_text(encoding="utf-8")
    assert "-m pip --version" in text, f"{name} never checks whether the new environment has pip"
    assert "-m ensurepip --upgrade" in text, (
        f"{name} never bootstraps pip; 'python -m venv' succeeds without it wherever "
        "python3-venv is absent, and every later pip call then dies on 'No module named pip'"
    )


@pytest.mark.parametrize(
    ("script", "name"),
    [(PS1, "install.ps1"), (SH, "install.sh")],
    ids=["ps1", "sh"],
)
def test_a_failed_pip_self_upgrade_does_not_abort_the_install(script: Path, name: str) -> None:
    text = script.read_text(encoding="utf-8")
    upgrade = text.index("pip==26.2.1")
    locked = text.index("--require-hashes")
    assert upgrade < locked, f"{name} installs locked dependencies before upgrading pip"
    assert "Could not upgrade pip" in text[upgrade:locked], (
        f"{name} kills the install when the pip self-upgrade cannot reach an index, even "
        "though the bundled pip installs the locked set"
    )


@pytest.mark.parametrize(
    ("script", "name"),
    [(PS1, "install.ps1"), (SH, "install.sh")],
    ids=["ps1", "sh"],
)
def test_both_installers_announce_the_same_live_line(script: Path, name: str) -> None:
    assert "Installing Trace v" in script.read_text(encoding="utf-8"), f"{name} never shows the live install line"


@pytest.mark.parametrize(
    ("script", "name"),
    [(PS1, "install.ps1"), (SH, "install.sh")],
    ids=["ps1", "sh"],
)
def test_only_the_editable_install_is_retried(script: Path, name: str) -> None:
    text = script.read_text(encoding="utf-8")
    hashed = text.index("--require-hashes")
    editable = text.index("-e .")
    assert hashed < editable, f"{name} installs the editable package before the locked set"
    assert text.find("of 3 failed") > editable, (
        f"{name} does not retry the editable install; Windows refuses to rewrite a running "
        "trace.exe and pip has already uninstalled the previous one by then, so the host is "
        "left with no package at all"
    )
    assert "of 3 failed" not in text[hashed:editable], f"{name} retries the hash-verified install"


@pytest.mark.parametrize(
    ("script", "name"),
    [(PS1, "install.ps1"), (SH, "install.sh")],
    ids=["ps1", "sh"],
)
def test_neither_installer_still_carries_animation(script: Path, name: str) -> None:
    text = script.read_text(encoding="utf-8")
    for token in ("Start-Job", "SpinMessage", "DotFrames", "trace_spin", "trace_animate", "38;2;"):
        assert token not in text, f"{name} still carries animation machinery: {token}"


@pytest.mark.parametrize(
    ("script", "name", "printed"),
    [
        (PS1, "install.ps1", 'Write-Output ("Installing Trace v{0}"'),
        (SH, "install.sh", "printf 'Installing Trace v%s"),
    ],
    ids=["ps1", "sh"],
)
def test_the_installing_line_is_not_indented(script: Path, name: str, printed: str) -> None:
    text = script.read_text(encoding="utf-8")
    assert printed in text, f"{name} must print the installing line with no leading indent"
    assert f'"  {printed}"' not in text, f"{name} indents the installing line inside the literal"
    assert f"'  {printed}" not in text, f"{name} indents the installing line inside the literal"
    assert any(line.startswith(printed) for line in text.splitlines()), (
        f"{name} indents the statement that prints the installing line"
    )
