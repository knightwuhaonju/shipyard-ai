from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_check_target_propagates_pytest_failure(tmp_path: Path) -> None:
    failing_test = tmp_path / "test_deliberate_failure.py"
    failing_test.write_text(
        "def test_deliberate_failure() -> None:\n"
        "    assert False, 'deliberate quality-gate failure'\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "make",
            "check",
            f"PYTHON={sys.executable}",
            f"PYTEST_ARGS={failing_test}",
        ],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "1 failed" in output
    assert "deliberate quality-gate failure" in output


def test_check_target_rejects_broken_dependency_closure(tmp_path: Path) -> None:
    passing_test = tmp_path / "test_deliberate_pass.py"
    passing_test.write_text(
        "def test_deliberate_pass() -> None:\n"
        "    assert True\n",
        encoding="utf-8",
    )
    broken_distribution = (
        tmp_path / "deliberate_broken_dependency-1.0.dist-info"
    )
    broken_distribution.mkdir()
    broken_distribution.joinpath("METADATA").write_text(
        "Metadata-Version: 2.1\n"
        "Name: deliberate-broken-dependency\n"
        "Version: 1.0\n"
        "Requires-Dist: dependency-that-does-not-exist==1.0\n",
        encoding="utf-8",
    )

    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(tmp_path)
    result = subprocess.run(
        [
            "make",
            "check",
            f"PYTHON={sys.executable}",
            f"PYTEST_ARGS={passing_test}",
        ],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        check=False,
        env=environment,
        text=True,
    )

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "deliberate-broken-dependency 1.0 requires" in output
    assert "dependency-that-does-not-exist" in output
