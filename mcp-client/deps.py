"""Best-effort auto-start for allotmint_research's prerequisites (--start-deps).

Everything here is opt-in: client.py only calls into this module when the user
passes --start-deps or one of the individual --start-* flags. Nothing is
started implicitly, and this never touches anything the user didn't ask for.

Started processes are left running in the background (logs under
mcp-client/.dep-logs/) rather than tied to this script's lifetime - that
matches how a developer would run them by hand in separate terminals, and it
means a second invocation of this client doesn't redundantly restart a
service that's already up; ensure_* functions all check reachability first
and are no-ops when it's already there.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen

REPO_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = Path(__file__).resolve().parent / ".dep-logs"
DEFAULT_START_TIMEOUT = 90.0
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
    """Launches `command` detached from this process; returns its log file path."""
    LOG_DIR.mkdir(exist_ok=True)
    log_path = LOG_DIR / f"{log_name}.log"
    log_file = open(log_path, "w", encoding="utf-8")  # noqa: SIM115 - handed to Popen, outlives this function
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    subprocess.Popen(
        command,
        cwd=str(cwd) if cwd else None,
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        creationflags=creationflags,
        start_new_session=(os.name != "nt"),
    )
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
    result = subprocess.run(
        ["docker", "compose", "up", "-d", "pgvector"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return f"docker compose up -d pgvector failed: {(result.stderr or result.stdout).strip()}"
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
        return "'ollama serve' started but :11434 never became reachable - check mcp-client/.dep-logs/ollama.log"
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
        return f"started but {host}:{port} never opened - check mcp-client/.dep-logs/allotmint-mcp.log"
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

    print("Starting research-agent (docker compose --profile research up -d research-agent)...")
    result = subprocess.run(
        ["docker", "compose", "--profile", "research", "up", "-d", "research-agent"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return f"docker compose up -d research-agent failed: {(result.stderr or result.stdout).strip()}"
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
    Returns one "name: problem" string per step that couldn't be confirmed
    ready; an empty list means everything requested is up.
    """
    problems = []
    for name in ALL_DEPENDENCIES:
        if name not in which:
            continue
        problem = _STEPS[name](mcp_url, research_url, timeout_seconds)
        if problem:
            problems.append(f"{name}: {problem}")
    return problems
