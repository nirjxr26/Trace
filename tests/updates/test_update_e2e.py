import os
import subprocess
import venv
from pathlib import Path

import pytest

from trace_core.updates import pip_backend

pytestmark = pytest.mark.unit

_E2E_PROBE = (
    "import importlib.metadata as meta, importlib.util as util;"
    " print(meta.version('trace'));"
    " print(util.find_spec('trace_core') is not None)"
)


def _venv_python(root: Path) -> Path:
    if os.name == "nt":
        return root / "Scripts" / "python.exe"
    return root / "bin" / "python"


@pytest.mark.skipif(not os.environ.get("TRACE_TEST_WHEEL_DIR"), reason="TRACE_TEST_WHEEL_DIR is not set")
def test_a_built_wheel_installs_through_the_pip_backend(tmp_path: Path) -> None:
    wheels = sorted(Path(os.environ["TRACE_TEST_WHEEL_DIR"]).glob("trace-*.whl"))
    assert len(wheels) == 1, f"expected exactly one built trace wheel, found {[w.name for w in wheels]}"

    venv_dir = tmp_path / "venv"
    venv.EnvBuilder(with_pip=True).create(venv_dir)
    python = _venv_python(venv_dir)
    pip_backend.pip_install_wheel(python, wheels[0])

    probe = subprocess.run([str(python), "-I", "-c", _E2E_PROBE], capture_output=True, text=True, check=True)
    assert probe.stdout.split() == [wheels[0].name.split("-")[1], "True"]
