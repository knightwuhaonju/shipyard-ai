from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import site
import socket
import subprocess
import sys
import time
import tomllib
import urllib.request
import zipfile
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from packages.common.config import load_settings

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _docker_runtime_command() -> list[str]:
    for line in (
        REPOSITORY_ROOT.joinpath("Dockerfile").read_text(encoding="utf-8").splitlines()
    ):
        if line.startswith("CMD "):
            command = json.loads(line.removeprefix("CMD "))
            assert isinstance(command, list)
            return [str(part) for part in command]
    raise AssertionError("Dockerfile has no runtime command")


def _unused_loopback_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_for_health(port: int, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            output = process.communicate()[0]
            raise AssertionError(f"Uvicorn exited before serving health: {output}")
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/health", timeout=0.2
            ) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.05)
    raise AssertionError("Uvicorn did not become ready within 10 seconds")


def test_docker_runtime_does_not_emit_raw_access_request_targets() -> None:
    runtime_command = _docker_runtime_command()
    assert runtime_command[0] == "uvicorn"
    port = _unused_loopback_port()
    arguments = runtime_command[1:]
    arguments[arguments.index("--host") + 1] = "127.0.0.1"
    arguments[arguments.index("--port") + 1] = str(port)
    environment = os.environ.copy()
    environment["DATABASE_URL"] = "postgresql://runtime:synthetic@localhost/test"
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", *arguments],
        cwd=REPOSITORY_ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        _wait_for_health(port, process)
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/health?token=runtime-secret", timeout=2
        ) as response:
            assert response.status == 200
    finally:
        process.terminate()
        output = process.communicate(timeout=5)[0]

    assert "runtime-secret" not in output
    assert "/health?token=" not in output
    assert '"path": "/health"' in output


def _stage_docker_copy_inputs(destination: Path) -> None:
    for line in (
        REPOSITORY_ROOT.joinpath("Dockerfile").read_text(encoding="utf-8").splitlines()
    ):
        if not line.startswith("COPY "):
            continue
        parts = shlex.split(line)
        assert len(parts) == 3
        source = REPOSITORY_ROOT / parts[1]
        target = destination / parts[2]
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            target.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target / source.name)


def _build_package_artifact(build_context: Path, wheel: Path) -> None:
    pyproject = tomllib.loads(
        build_context.joinpath("pyproject.toml").read_text(encoding="utf-8")
    )
    includes = pyproject["tool"]["setuptools"]["packages"]["find"]["include"]
    packaged_files = [
        source
        for source in build_context.rglob("*.py")
        if any(
            fnmatchcase(
                ".".join(source.relative_to(build_context).parent.parts), pattern
            )
            for pattern in includes
        )
    ]
    dist_info = "shipyard_ai-0.1.0.dist-info"
    with zipfile.ZipFile(wheel, "w") as archive:
        for source in packaged_files:
            archive.write(source, source.relative_to(build_context).as_posix())
        archive.writestr(
            f"{dist_info}/METADATA",
            "Metadata-Version: 2.1\nName: shipyard-ai\nVersion: 0.1.0\n",
        )
        archive.writestr(
            f"{dist_info}/WHEEL",
            "Wheel-Version: 1.0\n"
            "Generator: shipyard-ai-deployment-test\n"
            "Root-Is-Purelib: true\n"
            "Tag: py3-none-any\n",
        )
        archive.writestr(f"{dist_info}/RECORD", "")


def test_docker_build_inputs_install_runtime_package_artifact(tmp_path: Path) -> None:
    build_context = tmp_path / "build-context"
    wheel = tmp_path / "shipyard_ai-0.1.0-py3-none-any.whl"
    install_target = tmp_path / "installed"
    isolated_cwd = tmp_path / "isolated"
    build_context.mkdir()
    isolated_cwd.mkdir()
    _stage_docker_copy_inputs(build_context)
    _build_package_artifact(build_context, wheel)

    installation = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--ignore-installed",
            "--no-deps",
            "--target",
            str(install_target),
            str(wheel),
        ],
        capture_output=True,
        check=False,
        text=True,
    )
    assert installation.returncode == 0, installation.stdout + installation.stderr

    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(install_target), *site.getsitepackages()]
    )
    smoke = subprocess.run(
        [
            sys.executable,
            "-S",
            "-c",
            "from adapters.auth.local import LocalAuthenticationAdapter; "
            "from packages.common.logging import REDACTED; "
            "from packages.contracts.auth import AuthorizationScope; "
            "from services.auth.service import authorization_scope_for; "
            "print(REDACTED, AuthorizationScope.__name__, "
            "LocalAuthenticationAdapter.__name__, authorization_scope_for.__name__)",
        ],
        cwd=isolated_cwd,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )

    assert smoke.returncode == 0, smoke.stdout + smoke.stderr
    assert smoke.stdout.strip() == (
        "[REDACTED] AuthorizationScope LocalAuthenticationAdapter "
        "authorization_scope_for"
    )


_COMPOSE_DEFAULT = re.compile(r"\$\{([A-Z][A-Z0-9_]*):-([^}]*)\}")


def _render_compose_environment(
    values: dict[str, Any], environ: dict[str, str]
) -> dict[str, str]:
    rendered: dict[str, str] = {}
    for key, value in values.items():
        assert isinstance(value, str)
        match = _COMPOSE_DEFAULT.fullmatch(value)
        if match is None:
            rendered[key] = value
            continue
        variable, default = match.groups()
        rendered[key] = environ.get(variable) or default
    return rendered


def test_compose_api_propagates_default_and_overridden_log_level() -> None:
    compose = yaml.safe_load(
        REPOSITORY_ROOT.joinpath("docker-compose.yml").read_text(encoding="utf-8")
    )
    values = compose["services"]["api"]["environment"]

    default_settings = load_settings(_render_compose_environment(values, {}))
    overridden_settings = load_settings(
        _render_compose_environment(values, {"LOG_LEVEL": "ERROR"})
    )

    assert default_settings.log_level == "INFO"
    assert overridden_settings.log_level == "ERROR"
