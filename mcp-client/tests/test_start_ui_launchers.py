"""Behavioural tests for scripts/start-ui.sh and scripts/start-ui.ps1.

The two launchers are the same script in two shells, so each test runs
against both (whichever this machine can execute) with the option spelling
taken from the table below; a behaviour that drifts between them fails here.

Every run is against a stub checkout in ``tmp_path`` whose venv interpreter
is a shell script that answers the version probe and echoes anything else,
so nothing is installed, built or started. That makes the ``.ps1`` row
POSIX-only as well (it looks for ``Scripts\\python.exe`` on Windows).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")
BASH = shutil.which("bash")

LAUNCHERS = {
    "start-ui.sh": {
        "cmd": [BASH or "bash"],
        "available": bool(BASH),
        "flags": {
            "host": "--host",
            "port": "--port",
            "allow_remote": "--allow-remote",
            "recreate": "--recreate",
            "skip_install": "--skip-install",
            "skip_build": "--skip-build",
            "no_start_deps": "--no-start-deps",
            "start_timeout": "--start-timeout",
        },
        "unknown": "--bogus",
    },
    "start-ui.ps1": {
        "cmd": [POWERSHELL or "pwsh", "-NoProfile", "-File"],
        "available": bool(POWERSHELL),
        "flags": {
            "host": "-BindHost",
            "port": "-Port",
            "allow_remote": "-AllowRemote",
            "recreate": "-Recreate",
            "skip_install": "-SkipInstall",
            "skip_build": "-SkipBuild",
            "no_start_deps": "-NoStartDeps",
            "start_timeout": "-StartTimeout",
        },
        "unknown": "-Bogus",
    },
}

STUB_PYTHON = """#!/bin/sh
if [ "$1" = "-c" ]; then echo "{version}"; exit 0; fi
echo "LAUNCH: $@"
"""

# Env vars the launchers read that the developer running the tests may have set.
CONFIG_KEYS = ("ALLOTMINT_RESEARCH_LLM_PROVIDER", "ALLOTMINT_RESEARCH_AVAILABLE_LLM_PROVIDERS")

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the stub venv interpreter is a shell script")


@pytest.fixture(params=list(LAUNCHERS), ids=list(LAUNCHERS))
def launcher(request):
    spec = LAUNCHERS[request.param]
    if not spec["available"]:
        pytest.skip(f"no interpreter for {request.param} on PATH")
    return request.param, spec


@pytest.fixture
def stub_repo(tmp_path):
    (tmp_path / "scripts").mkdir()
    for name in LAUNCHERS:
        shutil.copy(SCRIPTS / name, tmp_path / "scripts" / name)
    (tmp_path / "pom.xml").write_text("", encoding="utf-8")
    client = tmp_path / "mcp-client"
    client.mkdir()
    (client / "gradio_ui.py").write_text("", encoding="utf-8")
    return tmp_path


def stub_venv(root: Path, version: str = "3.12") -> None:
    bindir = root / "mcp-client" / ".venv" / "bin"
    bindir.mkdir(parents=True)
    python = bindir / "python"
    python.write_text(STUB_PYTHON.format(version=version), encoding="utf-8")
    python.chmod(0o755)


def run(launcher, root: Path, *args: str, env: dict | None = None, **options) -> subprocess.CompletedProcess:
    name, spec = launcher
    argv = [*spec["cmd"], str(root / "scripts" / name), *args]
    for option, value in options.items():
        flag = spec["flags"][option]
        argv += [flag] if value is True else [flag, str(value)]
    run_env = {k: v for k, v in os.environ.items() if k not in CONFIG_KEYS}
    run_env.update(env or {})
    return subprocess.run(argv, capture_output=True, text=True, env=run_env, timeout=60)


def launch_line(result: subprocess.CompletedProcess) -> str:
    lines = [line for line in result.stdout.splitlines() if line.startswith("LAUNCH:")]
    assert lines, f"never launched\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    return lines[0]


# Every launch below skips the install and build steps, which would need a
# real pip, JDK and Docker; the port is one nothing listens on.
OFFLINE = {"skip_install": True, "skip_build": True, "port": 18601}


def test_non_loopback_host_is_refused_without_allow_remote(launcher, stub_repo):
    stub_venv(stub_repo)
    result = run(launcher, stub_repo, host="0.0.0.0", skip_install=True, skip_build=True)

    assert result.returncode == 1
    assert "not loopback" in result.stderr
    assert "LAUNCH:" not in result.stdout


def test_allow_remote_binds_the_requested_host(launcher, stub_repo):
    stub_venv(stub_repo)
    result = run(launcher, stub_repo, host="0.0.0.0", allow_remote=True, no_start_deps=True, **OFFLINE)

    assert result.returncode == 0, result.stderr
    assert "--host 0.0.0.0 --port 18601" in launch_line(result)


def test_an_unknown_option_is_refused(launcher, stub_repo):
    result = run(launcher, stub_repo, launcher[1]["unknown"])

    assert result.returncode != 0
    assert "LAUNCH:" not in result.stdout


def test_recreate_with_skip_install_is_refused(launcher, stub_repo):
    stub_venv(stub_repo)
    result = run(launcher, stub_repo, recreate=True, skip_install=True)

    assert result.returncode == 1
    assert "contradict" in result.stderr
    assert (stub_repo / "mcp-client" / ".venv").exists()


def test_skip_install_without_a_venv_is_refused(launcher, stub_repo):
    result = run(launcher, stub_repo, **OFFLINE)

    assert result.returncode == 1
    assert "no venv" in result.stderr


def test_a_python_older_than_3_10_is_refused(launcher, stub_repo):
    stub_venv(stub_repo, version="3.9")
    result = run(launcher, stub_repo, **OFFLINE)

    assert result.returncode == 1
    assert "3.10+" in result.stderr


def test_dependencies_are_started_by_default(launcher, stub_repo):
    stub_venv(stub_repo)
    result = run(launcher, stub_repo, start_timeout=42, **OFFLINE)

    assert result.returncode == 0, result.stderr
    line = launch_line(result)
    assert "gradio_ui.py" in line
    assert "--start-deps --start-timeout 42" in line


def test_no_start_deps_starts_nothing(launcher, stub_repo):
    stub_venv(stub_repo)
    result = run(launcher, stub_repo, no_start_deps=True, **OFFLINE)

    assert result.returncode == 0, result.stderr
    assert "--start" not in launch_line(result)


def test_a_non_ollama_provider_skips_starting_ollama(launcher, stub_repo):
    stub_venv(stub_repo)
    result = run(launcher, stub_repo, env={"ALLOTMINT_RESEARCH_LLM_PROVIDER": "deepseek"}, **OFFLINE)

    line = launch_line(result)
    assert "--start-deps" not in line
    assert "--start-pgvector --start-mcp-server --start-research-agent" in line


def test_ollama_is_still_started_when_offered_alongside_another_provider(launcher, stub_repo):
    stub_venv(stub_repo)
    env = {
        "ALLOTMINT_RESEARCH_LLM_PROVIDER": "deepseek",
        "ALLOTMINT_RESEARCH_AVAILABLE_LLM_PROVIDERS": "deepseek, ollama",
    }
    result = run(launcher, stub_repo, env=env, **OFFLINE)

    assert "--start-deps" in launch_line(result)


def test_the_provider_is_read_from_a_crlf_dotenv_with_quotes_and_a_comment(launcher, stub_repo):
    stub_venv(stub_repo)
    (stub_repo / ".env").write_bytes(
        b"# ALLOTMINT_RESEARCH_LLM_PROVIDER=ollama\r\nALLOTMINT_RESEARCH_LLM_PROVIDER=\"deepseek\"  # cloud\r\n"
    )
    result = run(launcher, stub_repo, **OFFLINE)

    assert "--start-deps" not in launch_line(result)


def test_a_provider_merely_named_like_ollama_does_not_count_as_ollama(launcher, stub_repo):
    stub_venv(stub_repo)
    env = {
        "ALLOTMINT_RESEARCH_LLM_PROVIDER": "deepseek",
        "ALLOTMINT_RESEARCH_AVAILABLE_LLM_PROVIDERS": "deepseek,ollama-cloud",
    }
    result = run(launcher, stub_repo, env=env, **OFFLINE)

    assert "--start-deps" not in launch_line(result)


def test_a_byte_order_mark_does_not_hide_the_first_dotenv_key(launcher, stub_repo):
    stub_venv(stub_repo)
    (stub_repo / ".env").write_bytes(b"\xef\xbb\xbfALLOTMINT_RESEARCH_LLM_PROVIDER=deepseek\n")
    result = run(launcher, stub_repo, **OFFLINE)

    assert "--start-deps" not in launch_line(result)


def test_the_environment_wins_over_dotenv(launcher, stub_repo):
    stub_venv(stub_repo)
    (stub_repo / ".env").write_text("ALLOTMINT_RESEARCH_LLM_PROVIDER=deepseek\n", encoding="utf-8")
    result = run(launcher, stub_repo, env={"ALLOTMINT_RESEARCH_LLM_PROVIDER": "ollama"}, **OFFLINE)

    assert "--start-deps" in launch_line(result)


def test_every_flag_is_documented():
    sh_help = subprocess.run(
        [BASH or "bash", str(SCRIPTS / "start-ui.sh"), "--help"], capture_output=True, text=True
    ).stdout
    ps1_source = (SCRIPTS / "start-ui.ps1").read_text(encoding="utf-8")

    for flag in LAUNCHERS["start-ui.sh"]["flags"].values():
        assert flag in sh_help, flag
    for flag in LAUNCHERS["start-ui.ps1"]["flags"].values():
        assert f".PARAMETER {flag.lstrip('-')}" in ps1_source, flag
