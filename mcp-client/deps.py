"""Best-effort auto-start for allotmint_research's prerequisites (--start-deps).

Everything here is opt-in: client.py only calls into this module when the user
passes --start-deps or one of the individual --start-* flags. Nothing is
started implicitly, and this never touches anything the user didn't ask for.

Started processes are left running in the background (logs under
mcp-client/logs/) rather than tied to this script's lifetime - that
matches how a developer would run them by hand in separate terminals, and it
means a second invocation of this client doesn't redundantly restart a
service that's already up; ensure_* functions all check reachability first
and are no-ops when it's already there.
"""

from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen

REPO_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = Path(__file__).resolve().parent / "logs"
DEFAULT_START_TIMEOUT = 90.0
DEFAULT_MCP_URL = "http://localhost:8080/mcp"
DEFAULT_RESEARCH_URL = "http://localhost:8100"
ALL_DEPENDENCIES = ("pgvector", "ollama", "mcp-server", "research-agent")


def tcp_open(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def http_ok(url: str, timeout: float = 2.0) -> bool:
    try:
        with urlopen(url, timeout=timeout):  # noqa: S310 - localhost dev services only
            return True
    except (URLError, OSError, ValueError):
        return False


def host_port(url: str, default_port: int) -> tuple[str, int]:
    parsed = urlparse(url)
    return parsed.hostname or "localhost", parsed.port or default_port


def wait_until(check, timeout_seconds: float, interval: float = 2.0) -> bool:
    """Polls `check` until it returns truthy or the timeout elapses.

    Always checks at least once more after the deadline passes, so a very
    small timeout still gets one real answer rather than an instant False.
    """
    deadline = time.monotonic() + timeout_seconds
    while True:
        if check():
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(interval)


def spawn_background(
    command: list[str], *, cwd: Path | None = None, env: dict | None = None, log_name: str
) -> Path:
    """Launches `command` detached from this process; returns its log file path.

    Also records the child's PID next to the log (`<log_name>.pid`) - the only
    way a later, separate `stop_deps.py` invocation can find and stop it,
    since a spawned process outlives this one.
    """
    LOG_DIR.mkdir(exist_ok=True)
    log_path = LOG_DIR / f"{log_name}.log"
    log_file = open(log_path, "w", encoding="utf-8")  # noqa: SIM115 - handed to Popen, outlives this function
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    process = subprocess.Popen(
        command,
        cwd=str(cwd) if cwd else None,
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        creationflags=creationflags,
        start_new_session=(os.name != "nt"),
    )
    (LOG_DIR / f"{log_name}.pid").write_text(str(process.pid), encoding="utf-8")
    return log_path


def ensure_pgvector(timeout_seconds: float) -> str | None:
    """Starts the pgvector container if :5432 isn't already open.

    Returns None on success (including "was already running"), else a
    human-readable problem description.
    """
    if tcp_open("localhost", 5432):
        return None
    if shutil.which("docker") is None:
        return "not reachable on :5432 and 'docker' isn't on PATH - start it yourself (docker compose up -d pgvector)"

    print("Starting pgvector (docker compose up -d pgvector)...")
    result = subprocess.run(["docker", "compose", "up", "-d", "pgvector"], cwd=REPO_ROOT)
    if result.returncode != 0:
        return f"docker compose up -d pgvector exited {result.returncode} - see the output above"
    if not wait_until(lambda: tcp_open("localhost", 5432), timeout_seconds):
        return "container started but :5432 never opened - check `docker compose logs pgvector`"
    return None


def ensure_ollama(timeout_seconds: float) -> str | None:
    """Starts a local Ollama server if :11434 isn't already open.

    Most installs already run this as a background service, so the common
    case is the reachability check passing and nothing being spawned.
    """
    url = "http://localhost:11434/api/tags"
    if http_ok(url):
        return None
    if shutil.which("ollama") is None:
        return "not reachable on :11434 and 'ollama' isn't on PATH - install it or start it yourself"

    print("Starting Ollama (ollama serve)...")
    spawn_background(["ollama", "serve"], log_name="ollama")
    if not wait_until(lambda: http_ok(url), timeout_seconds):
        return "'ollama serve' started but :11434 never became reachable - check mcp-client/logs/ollama.log"
    return None


def ensure_mcp_server(mcp_url: str, timeout_seconds: float) -> str | None:
    """Starts the allotmint-mcp Java server if its port isn't already open.

    Requires an already-built jar (`./mvnw package`); building one is far
    slower than anything else this module starts, so that step is left to the
    caller rather than run implicitly.
    """
    host, port = host_port(mcp_url, 8080)
    if tcp_open(host, port):
        return None

    jar = REPO_ROOT / "target" / "allotmint-mcp-server.jar"
    if not jar.exists():
        return f"not reachable on {host}:{port} and {jar} doesn't exist - build it first with './mvnw package'"
    if shutil.which("java") is None:
        return f"not reachable on {host}:{port} and 'java' isn't on PATH"

    print("Starting allotmint-mcp (java -jar target/allotmint-mcp-server.jar --spring.profiles.active=http)...")
    env = {**os.environ, "ALLOTMINT_MCP_RESEARCH_ENABLED": "true"}
    spawn_background(
        ["java", "-jar", str(jar), "--spring.profiles.active=http"],
        cwd=REPO_ROOT,
        env=env,
        log_name="allotmint-mcp",
    )
    if not wait_until(lambda: tcp_open(host, port), timeout_seconds):
        return f"started but {host}:{port} never opened - check mcp-client/logs/allotmint-mcp.log"
    return None


def ensure_research_agent(research_url: str, timeout_seconds: float) -> str | None:
    """Starts the research-agent sidecar if its /health isn't reachable.

    Uses the `research-agent` service already defined in docker-compose.yml
    (behind the `research` profile) instead of a hand-rolled uvicorn/venv
    invocation, so this reuses the same image and dependency setup as anyone
    else running the stack. A first run builds that image, which can take
    several minutes - pass a larger --start-timeout for that.
    """
    health_url = f"{research_url.rstrip('/')}/health"
    if http_ok(health_url):
        return None
    if shutil.which("docker") is None:
        return f"not reachable at {research_url} and 'docker' isn't on PATH"

    print(
        "Starting research-agent (docker compose --profile research up -d research-agent)...\n"
        "  First run builds the image (installs sentence-transformers/PyTorch) - this can take "
        "several minutes with no output in between. It has NOT hung; docker's own build/pull "
        "progress prints below."
    )
    result = subprocess.run(
        ["docker", "compose", "--profile", "research", "up", "-d", "research-agent"], cwd=REPO_ROOT
    )
    if result.returncode != 0:
        return f"docker compose up -d research-agent exited {result.returncode} - see the output above"
    if not wait_until(lambda: http_ok(health_url), timeout_seconds):
        return f"container started but {health_url} never responded - check `docker compose logs research-agent`"
    return None


_STEPS = {
    "pgvector": lambda mcp_url, research_url, timeout: ensure_pgvector(timeout),
    "ollama": lambda mcp_url, research_url, timeout: ensure_ollama(timeout),
    "mcp-server": lambda mcp_url, research_url, timeout: ensure_mcp_server(mcp_url, timeout),
    "research-agent": lambda mcp_url, research_url, timeout: ensure_research_agent(research_url, timeout),
}


def ensure_running(mcp_url: str, research_url: str, timeout_seconds: float, which: set[str]) -> list[str]:
    """Runs the requested ensure_* steps in dependency order.

    Order matters even though each step only checks reachability: pgvector
    and Ollama are what the research-agent sidecar needs, so starting them
    first means a freshly-started sidecar has somewhere to actually connect
    on its first real question, matching the order in research-agent/README.md.

    Each problem is printed to stderr as soon as its step finishes, not
    batched up for the caller to print once every step is done - a later step
    (building the research-agent image) can take minutes, and a problem from
    an earlier one (say, the Java server never came up) would otherwise stay
    invisible for all of that time. Still returns the same list, for a caller
    that wants to act on it (e.g. deciding an exit code).
    """
    problems = []
    for name in ALL_DEPENDENCIES:
        if name not in which:
            continue
        problem = _STEPS[name](mcp_url, research_url, timeout_seconds)
        if problem:
            print(f"Warning: {name}: {problem}", file=sys.stderr)
            problems.append(f"{name}: {problem}")
    return problems


def terminate_pid(pid: int) -> bool:
    """Best-effort kill of one process by PID. Returns False if it was already gone.

    `taskkill /T` on Windows also kills the process's own children (relevant
    for `java`/`ollama`, which may spawn helpers); POSIX processes were
    started with `start_new_session=True` in `spawn_background`, so a plain
    SIGTERM to the PID we recorded is the whole session leader.
    """
    if os.name == "nt":
        result = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True
        )
        return result.returncode == 0
    try:
        os.kill(pid, signal.SIGTERM)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _stop_via_pid_file(log_name: str, still_running: bool) -> str | None:
    """Stops whatever spawn_background(..., log_name=log_name) started, if anything.

    A missing PID file means this tool never started it - a real caveat since
    that's also true after a system reboot (the file is stale/still there
    only if the process itself is also gone, so this stays safe either way),
    or if it's a pre-existing install (e.g. Ollama as a system service). Either
    way, the right thing is to leave it alone and say so if it's still up.
    """
    pid_file = LOG_DIR / f"{log_name}.pid"
    if not pid_file.exists():
        if still_running:
            return "running but wasn't started by this script (no PID recorded) - stop it yourself"
        return None
    pid = int(pid_file.read_text().strip())
    terminate_pid(pid)
    pid_file.unlink(missing_ok=True)
    return None


def stop_pgvector() -> str | None:
    """Stops the pgvector container via docker compose, if docker is available."""
    if not tcp_open("localhost", 5432):
        return None
    if shutil.which("docker") is None:
        return "reachable on :5432 but 'docker' isn't on PATH - stop it yourself"
    result = subprocess.run(
        ["docker", "compose", "stop", "pgvector"], cwd=REPO_ROOT, capture_output=True, text=True
    )
    if result.returncode != 0:
        return f"docker compose stop pgvector failed: {(result.stderr or result.stdout).strip()}"
    return None


def stop_ollama() -> str | None:
    """Stops Ollama only if this script started it (see _stop_via_pid_file)."""
    return _stop_via_pid_file("ollama", still_running=http_ok("http://localhost:11434/api/tags"))


def stop_mcp_server(mcp_url: str) -> str | None:
    """Stops the allotmint-mcp server only if this script started it."""
    host, port = host_port(mcp_url, 8080)
    return _stop_via_pid_file("allotmint-mcp", still_running=tcp_open(host, port))


def stop_research_agent(research_url: str) -> str | None:
    """Stops the research-agent container via docker compose, if docker is available."""
    health_url = f"{research_url.rstrip('/')}/health"
    if not http_ok(health_url):
        return None
    if shutil.which("docker") is None:
        return f"reachable at {research_url} but 'docker' isn't on PATH - stop it yourself"
    result = subprocess.run(
        ["docker", "compose", "--profile", "research", "stop", "research-agent"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return f"docker compose stop research-agent failed: {(result.stderr or result.stdout).strip()}"
    return None


_STOP_STEPS = {
    "pgvector": lambda mcp_url, research_url: stop_pgvector(),
    "ollama": lambda mcp_url, research_url: stop_ollama(),
    "mcp-server": lambda mcp_url, research_url: stop_mcp_server(mcp_url),
    "research-agent": lambda mcp_url, research_url: stop_research_agent(research_url),
}


def stop_running(mcp_url: str, research_url: str, which: set[str]) -> list[str]:
    """Stops the requested dependencies, in the reverse of their start order.

    Consumers first, then what they depend on: the research-agent sidecar and
    the allotmint-mcp server before pgvector and Ollama underneath them.
    Returns one "name: problem" string per step that couldn't be confirmed
    stopped; an empty list means everything requested is down (or was never
    running, or wasn't this script's to stop).
    """
    problems = []
    for name in reversed(ALL_DEPENDENCIES):
        if name not in which:
            continue
        problem = _STOP_STEPS[name](mcp_url, research_url)
        if problem:
            problems.append(f"{name}: {problem}")
    return problems
