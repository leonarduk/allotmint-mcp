"""Tests for the --start-deps auto-start logic.

Every ensure_* function is exercised with tcp_open/http_ok/subprocess.run/
spawn_background monkeypatched out - nothing here touches a real socket,
Docker, Ollama, or Java. wait_until's own polling loop is real, but tests
keep it fast by making the check succeed immediately or by using a timeout
of 0.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import deps


def test_ensure_python_packages_installs_missing_packages(monkeypatch):
    monkeypatch.setattr(
        deps.importlib.util,
        "find_spec",
        lambda name: None if name == "missing" else object(),
    )
    commands = []
    messages = []
    monkeypatch.setattr(deps.subprocess, "check_call", lambda command: commands.append(command))
    monkeypatch.setattr(
        deps, "log", lambda message, level="INFO": messages.append((level, message))
    )

    deps.ensure_python_packages({"present": "present>=1", "missing": "missing>=2"})

    assert commands == [[deps.sys.executable, "-m", "pip", "install", "missing>=2"]]
    assert any(
        "all necessary Python dependencies have been installed" in message
        for _, message in messages
    )


def test_log_writes_a_timestamped_line_to_the_log_file(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(deps, "LOG_DIR", tmp_path)

    deps.log("pgvector: already reachable on :5432")

    captured = capsys.readouterr()
    assert "pgvector: already reachable on :5432" in captured.out
    assert captured.err == ""
    log_file = tmp_path / "mcp-client.log"
    assert log_file.exists()
    content = log_file.read_text()
    assert "pgvector: already reachable on :5432" in content
    assert "INFO" in content


def test_log_sends_warning_and_error_to_stderr(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(deps, "LOG_DIR", tmp_path)

    deps.log("something's off", level="WARNING")
    deps.log("something broke", level="ERROR")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "something's off" in captured.err
    assert "something broke" in captured.err


def test_log_appends_across_calls_instead_of_overwriting(monkeypatch, tmp_path):
    monkeypatch.setattr(deps, "LOG_DIR", tmp_path)

    deps.log("first")
    deps.log("second")

    content = (tmp_path / "mcp-client.log").read_text()
    assert "first" in content
    assert "second" in content


def test_jar_is_stale_when_a_source_file_is_newer(tmp_path, monkeypatch):
    monkeypatch.setattr(deps, "REPO_ROOT", tmp_path)
    jar = tmp_path / "target" / "allotmint-mcp-server.jar"
    jar.parent.mkdir(parents=True)
    jar.write_text("jar")
    os.utime(jar, (1000, 1000))

    src = tmp_path / "src" / "main" / "java" / "Thing.java"
    src.parent.mkdir(parents=True)
    src.write_text("class Thing {}")
    os.utime(src, (2000, 2000))

    assert deps._jar_is_stale(jar) is True


def test_jar_is_not_stale_when_built_after_all_source(tmp_path, monkeypatch):
    monkeypatch.setattr(deps, "REPO_ROOT", tmp_path)
    src = tmp_path / "src" / "main" / "java" / "Thing.java"
    src.parent.mkdir(parents=True)
    src.write_text("class Thing {}")
    os.utime(src, (1000, 1000))

    jar = tmp_path / "target" / "allotmint-mcp-server.jar"
    jar.parent.mkdir(parents=True)
    jar.write_text("jar")
    os.utime(jar, (2000, 2000))

    assert deps._jar_is_stale(jar) is False


def test_ensure_mcp_server_warns_but_still_starts_a_stale_jar(monkeypatch, tmp_path):
    jar = tmp_path / "target" / "allotmint-mcp-server.jar"
    jar.parent.mkdir(parents=True)
    jar.write_text("not a real jar")
    monkeypatch.setattr(deps, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(deps, "tcp_open", lambda host, port, timeout=1.5: False)
    monkeypatch.setattr(deps.shutil, "which", lambda name: "/usr/bin/java")
    monkeypatch.setattr(deps, "_jar_is_stale", lambda jar_path: True)
    monkeypatch.setattr(deps, "spawn_background", lambda command, **kwargs: Path("x.log"))
    monkeypatch.setattr(deps, "wait_until", lambda check, timeout_seconds, interval=2.0: True)
    warnings = []
    monkeypatch.setattr(
        deps, "log", lambda message, level="INFO": warnings.append((level, message))
    )

    problem = deps.ensure_mcp_server("http://localhost:8080/mcp", timeout_seconds=5)

    assert problem is None
    assert any(level == "WARNING" and "older than source" in message for level, message in warnings)


def test_host_port_uses_the_url_when_present():
    assert deps.host_port("http://localhost:9999/mcp", 8080) == ("localhost", 9999)


def test_host_port_falls_back_to_the_default_port():
    assert deps.host_port("http://example.com/mcp", 8080) == ("example.com", 8080)


def test_wait_until_returns_true_immediately_when_already_ready():
    assert deps.wait_until(lambda: True, timeout_seconds=0) is True


def test_wait_until_returns_false_after_the_timeout(monkeypatch):
    calls = []
    monkeypatch.setattr(deps.time, "sleep", lambda seconds: calls.append(seconds))

    assert deps.wait_until(lambda: False, timeout_seconds=0) is False


def test_ensure_pgvector_is_a_noop_when_already_reachable(monkeypatch):
    monkeypatch.setattr(deps, "tcp_open", lambda host, port, timeout=1.5: True)

    assert deps.ensure_pgvector(timeout_seconds=5) is None


def test_ensure_pgvector_reports_missing_docker(monkeypatch):
    monkeypatch.setattr(deps, "tcp_open", lambda host, port, timeout=1.5: False)
    monkeypatch.setattr(deps.shutil, "which", lambda name: None)

    problem = deps.ensure_pgvector(timeout_seconds=5)

    assert problem is not None
    assert "docker" in problem


def test_ensure_pgvector_starts_it_and_waits(monkeypatch):
    reachable = {"value": False}
    monkeypatch.setattr(deps, "tcp_open", lambda host, port, timeout=1.5: reachable["value"])
    monkeypatch.setattr(deps.shutil, "which", lambda name: "/usr/bin/docker")

    commands = []

    class FakeCompletedProcess:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(command, **kwargs):
        commands.append(command)
        reachable["value"] = True
        return FakeCompletedProcess()

    monkeypatch.setattr(deps.subprocess, "run", fake_run)

    assert deps.ensure_pgvector(timeout_seconds=5) is None
    assert commands == [["docker", "compose", "up", "-d", "pgvector"]]


def test_ensure_pgvector_reports_a_failed_compose_command(monkeypatch):
    monkeypatch.setattr(deps, "tcp_open", lambda host, port, timeout=1.5: False)
    monkeypatch.setattr(deps.shutil, "which", lambda name: "/usr/bin/docker")

    class FakeCompletedProcess:
        returncode = 1

    monkeypatch.setattr(deps.subprocess, "run", lambda command, **kwargs: FakeCompletedProcess())

    problem = deps.ensure_pgvector(timeout_seconds=5)

    assert problem is not None
    assert "exited 1" in problem


def test_ensure_pgvector_reports_a_timeout_after_starting(monkeypatch):
    monkeypatch.setattr(deps, "tcp_open", lambda host, port, timeout=1.5: False)
    monkeypatch.setattr(deps.shutil, "which", lambda name: "/usr/bin/docker")

    class FakeCompletedProcess:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(deps.subprocess, "run", lambda command, **kwargs: FakeCompletedProcess())
    monkeypatch.setattr(deps, "wait_until", lambda check, timeout_seconds, interval=2.0: False)

    problem = deps.ensure_pgvector(timeout_seconds=0)

    assert problem is not None
    assert ":5432" in problem


def test_ensure_ollama_is_a_noop_when_already_reachable(monkeypatch):
    monkeypatch.setattr(deps, "http_ok", lambda url, timeout=2.0: True)

    assert deps.ensure_ollama(timeout_seconds=5) is None


def test_ensure_ollama_reports_missing_binary(monkeypatch):
    monkeypatch.setattr(deps, "http_ok", lambda url, timeout=2.0: False)
    monkeypatch.setattr(deps.shutil, "which", lambda name: None)

    problem = deps.ensure_ollama(timeout_seconds=5)

    assert problem is not None
    assert "ollama" in problem


def test_ensure_ollama_spawns_and_waits(monkeypatch):
    monkeypatch.setattr(deps, "http_ok", lambda url, timeout=2.0: False)
    monkeypatch.setattr(deps.shutil, "which", lambda name: "/usr/local/bin/ollama")
    spawned = []
    monkeypatch.setattr(
        deps, "spawn_background", lambda command, **kwargs: spawned.append(command) or Path("x.log")
    )
    monkeypatch.setattr(deps, "wait_until", lambda check, timeout_seconds, interval=2.0: True)

    assert deps.ensure_ollama(timeout_seconds=5) is None
    assert spawned == [["ollama", "serve"]]


def test_ensure_mcp_server_is_a_noop_when_already_reachable(monkeypatch):
    monkeypatch.setattr(deps, "tcp_open", lambda host, port, timeout=1.5: True)

    assert deps.ensure_mcp_server("http://localhost:8080/mcp", timeout_seconds=5) is None


def test_ensure_mcp_server_reports_a_missing_jar(monkeypatch, tmp_path):
    monkeypatch.setattr(deps, "tcp_open", lambda host, port, timeout=1.5: False)
    monkeypatch.setattr(deps, "REPO_ROOT", tmp_path)

    problem = deps.ensure_mcp_server("http://localhost:8080/mcp", timeout_seconds=5)

    assert problem is not None
    assert "./mvnw.cmd package -DskipTests" in problem


def test_ensure_mcp_server_starts_it_with_research_enabled(monkeypatch, tmp_path):
    jar = tmp_path / "target" / "allotmint-mcp-server.jar"
    jar.parent.mkdir(parents=True)
    jar.write_text("not a real jar")
    monkeypatch.setattr(deps, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(deps, "tcp_open", lambda host, port, timeout=1.5: False)
    monkeypatch.setattr(deps.shutil, "which", lambda name: "/usr/bin/java")
    spawned = []
    monkeypatch.setattr(
        deps,
        "spawn_background",
        lambda command, **kwargs: spawned.append((command, kwargs)) or Path("x.log"),
    )
    monkeypatch.setattr(deps, "wait_until", lambda check, timeout_seconds, interval=2.0: True)

    assert deps.ensure_mcp_server("http://localhost:8080/mcp", timeout_seconds=5) is None
    assert len(spawned) == 1
    command, kwargs = spawned[0]
    assert command == ["java", "-jar", str(jar), "--spring.profiles.active=http"]
    assert kwargs["env"]["ALLOTMINT_MCP_RESEARCH_ENABLED"] == "true"


def test_ensure_research_agent_is_a_noop_when_already_reachable(monkeypatch):
    monkeypatch.setattr(deps, "http_ok", lambda url, timeout=2.0: True)
    seeded = []
    monkeypatch.setattr(deps, "_seed_sample_corpus", lambda: seeded.append(True))

    assert deps.ensure_research_agent("http://localhost:8100", timeout_seconds=5) is None
    assert seeded == []


def test_ensure_research_agent_starts_the_compose_profile_and_seeds_it(monkeypatch):
    monkeypatch.setattr(deps, "http_ok", lambda url, timeout=2.0: False)
    monkeypatch.setattr(deps.shutil, "which", lambda name: "/usr/bin/docker")

    class FakeCompletedProcess:
        returncode = 0
        stdout = ""
        stderr = ""

    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        return FakeCompletedProcess()

    monkeypatch.setattr(deps.subprocess, "run", fake_run)
    monkeypatch.setattr(deps, "wait_until", lambda check, timeout_seconds, interval=2.0: True)
    seeded = []
    monkeypatch.setattr(deps, "_seed_sample_corpus", lambda: seeded.append(True))

    assert deps.ensure_research_agent("http://localhost:8100", timeout_seconds=5) is None
    assert commands == [
        ["docker", "compose", "--profile", "research", "up", "-d", "--no-deps", "research-agent"]
    ]
    assert seeded == [True]


def test_ensure_research_agent_does_not_seed_if_the_container_never_came_up(monkeypatch):
    monkeypatch.setattr(deps, "http_ok", lambda url, timeout=2.0: False)
    monkeypatch.setattr(deps.shutil, "which", lambda name: "/usr/bin/docker")

    class FakeCompletedProcess:
        returncode = 0

    monkeypatch.setattr(deps.subprocess, "run", lambda command, **kwargs: FakeCompletedProcess())
    monkeypatch.setattr(deps, "wait_until", lambda check, timeout_seconds, interval=2.0: False)
    seeded = []
    monkeypatch.setattr(deps, "_seed_sample_corpus", lambda: seeded.append(True))

    problem = deps.ensure_research_agent("http://localhost:8100", timeout_seconds=5)

    assert problem is not None
    assert seeded == []


def test_seed_sample_corpus_runs_ingest_inside_the_container(monkeypatch):
    commands = []

    class FakeCompletedProcess:
        returncode = 0

    def fake_run(command, **kwargs):
        commands.append(command)
        return FakeCompletedProcess()

    monkeypatch.setattr(deps.subprocess, "run", fake_run)

    deps._seed_sample_corpus()

    assert commands == [
        [
            "docker",
            "compose",
            "--profile",
            "research",
            "exec",
            "-T",
            "research-agent",
            "python",
            "ingest.py",
            "--sample",
        ]
    ]


def test_seed_sample_corpus_logs_a_warning_on_failure_without_raising(monkeypatch):
    class FakeCompletedProcess:
        returncode = 1

    monkeypatch.setattr(deps.subprocess, "run", lambda command, **kwargs: FakeCompletedProcess())
    warnings = []
    monkeypatch.setattr(deps, "log", lambda message, level="INFO": warnings.append((level, message)))

    deps._seed_sample_corpus()  # must not raise

    assert any(level == "WARNING" and "ingest.py" in message for level, message in warnings)


def test_ensure_running_only_runs_requested_steps_in_order(monkeypatch):
    calls = []
    monkeypatch.setitem(deps._STEPS, "pgvector", lambda mcp, research, timeout: calls.append("pgvector") or None)
    monkeypatch.setitem(deps._STEPS, "ollama", lambda mcp, research, timeout: calls.append("ollama") or None)
    monkeypatch.setitem(
        deps._STEPS, "mcp-server", lambda mcp, research, timeout: calls.append("mcp-server") or "not ready"
    )
    monkeypatch.setitem(
        deps._STEPS, "research-agent", lambda mcp, research, timeout: calls.append("research-agent") or None
    )

    problems = deps.ensure_running(
        "http://localhost:8080/mcp", "http://localhost:8100", 5.0, {"ollama", "mcp-server"}
    )

    assert calls == ["ollama", "mcp-server"]
    assert problems == ["mcp-server: not ready"]


def test_spawn_background_writes_a_log_and_a_pid_file(monkeypatch, tmp_path):
    monkeypatch.setattr(deps, "LOG_DIR", tmp_path)

    class FakeProcess:
        pid = 4321

    monkeypatch.setattr(deps.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())

    log_path = deps.spawn_background(["true"], log_name="thing")

    assert log_path == tmp_path / "thing.log"
    assert log_path.exists()
    assert (tmp_path / "thing.pid").read_text() == "4321"


def test_terminate_pid_on_posix_sends_sigterm(monkeypatch):
    if deps.os.name == "nt":
        pytest.skip("POSIX-only path")
    sent = []
    monkeypatch.setattr(deps.os, "kill", lambda pid, sig: sent.append((pid, sig)))

    assert deps.terminate_pid(1234) is True
    assert sent == [(1234, deps.signal.SIGTERM)]


def test_terminate_pid_on_posix_reports_an_already_gone_process(monkeypatch):
    if deps.os.name == "nt":
        pytest.skip("POSIX-only path")

    def _raise(pid, sig):
        raise ProcessLookupError()

    monkeypatch.setattr(deps.os, "kill", _raise)

    assert deps.terminate_pid(1234) is False


def test_stop_via_pid_file_stops_a_process_this_script_started(monkeypatch, tmp_path):
    monkeypatch.setattr(deps, "LOG_DIR", tmp_path)
    (tmp_path / "ollama.pid").write_text("999")
    terminated = []
    monkeypatch.setattr(deps, "terminate_pid", lambda pid: terminated.append(pid) or True)

    problem = deps._stop_via_pid_file("ollama", still_running=True)

    assert problem is None
    assert terminated == [999]
    assert not (tmp_path / "ollama.pid").exists()


def test_stop_via_pid_file_leaves_an_externally_started_process_alone(monkeypatch, tmp_path):
    monkeypatch.setattr(deps, "LOG_DIR", tmp_path)

    problem = deps._stop_via_pid_file("ollama", still_running=True)

    assert problem is not None
    assert "wasn't started by this script" in problem


def test_stop_via_pid_file_is_a_noop_when_nothing_is_running(monkeypatch, tmp_path):
    monkeypatch.setattr(deps, "LOG_DIR", tmp_path)

    assert deps._stop_via_pid_file("ollama", still_running=False) is None


def test_stop_pgvector_is_a_noop_when_not_reachable(monkeypatch):
    monkeypatch.setattr(deps, "tcp_open", lambda host, port, timeout=1.5: False)

    assert deps.stop_pgvector() is None


def test_stop_pgvector_runs_docker_compose_stop(monkeypatch):
    monkeypatch.setattr(deps, "tcp_open", lambda host, port, timeout=1.5: True)
    monkeypatch.setattr(deps.shutil, "which", lambda name: "/usr/bin/docker")

    class FakeCompletedProcess:
        returncode = 0
        stdout = ""
        stderr = ""

    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        return FakeCompletedProcess()

    monkeypatch.setattr(deps.subprocess, "run", fake_run)

    assert deps.stop_pgvector() is None
    assert commands == [["docker", "compose", "stop", "pgvector"]]


def test_stop_research_agent_runs_the_compose_profile_stop(monkeypatch):
    monkeypatch.setattr(deps, "http_ok", lambda url, timeout=2.0: True)
    monkeypatch.setattr(deps.shutil, "which", lambda name: "/usr/bin/docker")

    class FakeCompletedProcess:
        returncode = 0
        stdout = ""
        stderr = ""

    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        return FakeCompletedProcess()

    monkeypatch.setattr(deps.subprocess, "run", fake_run)

    assert deps.stop_research_agent("http://localhost:8100") is None
    assert commands == [["docker", "compose", "--profile", "research", "stop", "research-agent"]]


def test_stop_running_only_runs_requested_steps_in_reverse_order(monkeypatch):
    calls = []
    monkeypatch.setitem(deps._STOP_STEPS, "pgvector", lambda mcp, research: calls.append("pgvector") or None)
    monkeypatch.setitem(deps._STOP_STEPS, "ollama", lambda mcp, research: calls.append("ollama") or None)
    monkeypatch.setitem(
        deps._STOP_STEPS, "mcp-server", lambda mcp, research: calls.append("mcp-server") or "still up"
    )
    monkeypatch.setitem(
        deps._STOP_STEPS, "research-agent", lambda mcp, research: calls.append("research-agent") or None
    )

    problems = deps.stop_running(
        "http://localhost:8080/mcp", "http://localhost:8100", {"pgvector", "mcp-server"}
    )

    assert calls == ["mcp-server", "pgvector"]
    assert problems == ["mcp-server: still up"]
