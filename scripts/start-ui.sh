#!/usr/bin/env bash
#
# Start the allotmint-mcp Gradio UI (mcp-client/gradio_ui.py) on this
# machine, bringing everything it depends on up to date first. The POSIX
# twin of scripts/start-ui.ps1 - same flags in --this-spelling, same steps,
# same messages.
#
# In order:
#
#   1. (--pull) git pull --ff-only.
#   2. Stops a previous gradio_ui.py still holding --port, so a re-run
#      replaces it instead of failing to bind. Anything else on that port
#      is left alone.
#   3. Resolves mcp-client/.venv (creating it if missing) and runs
#      `pip install --upgrade -r mcp-client/requirements.txt`, so a moved
#      pin or a newer release actually lands.
#   4. Rebuilds target/allotmint-mcp-server.jar with the Maven wrapper when
#      it is missing or older than pom.xml / src/ (Java 25+ required). If
#      the jar was rebuilt and a server started by an earlier --start-deps
#      run is still up on :8080, it is stopped so it comes back on the new
#      jar. A server you started by hand is left alone (with a warning).
#   5. If Docker is running, rebuilds the research-agent image (a cached
#      no-op when research-agent/ has not changed; several minutes the
#      first time) and recreates its container if one is already running.
#   6. Execs gradio_ui.py with --start-deps, which starts whatever of
#      pgvector, Ollama, the allotmint-mcp server and the research-agent
#      sidecar is not already reachable, and refuses to serve the UI if one
#      cannot be confirmed. Ollama is skipped when .env / the environment
#      configures a non-Ollama LLM provider and does not offer ollama.
#
# Usage: scripts/start-ui.sh [options]
#
#   --host HOST          Interface to bind (default 127.0.0.1).
#   --port PORT          Port to serve the UI on (default 8601).
#   --allow-remote       Required to bind a non-loopback --host. The UI has
#                        no login and shows portfolio data.
#   --pull               git pull --ff-only before anything else.
#   --python PATH        Interpreter used to create a new venv (default:
#                        newest of python3.12/3.13/3.11/3.10 on PATH).
#   --recreate           Delete and rebuild mcp-client/.venv.
#   --skip-install       Do not run pip (the venv must already exist).
#   --skip-build         Do not rebuild the jar or the research-agent image.
#   --no-start-deps      Only launch the UI; start nothing else.
#   --start-timeout SEC  Seconds to wait for each started dependency
#                        (default 180).
#   -h, --help           Show this help.

set -euo pipefail

LOOPBACK_HOSTS=(127.0.0.1 ::1 localhost)
# Newest-first order of preference for a new venv; 3.12 first because it is
# what CI runs the mcp-client tests on.
TESTED_PYTHONS=(python3.12 python3.13 python3.11 python3.10)
MIN_JAVA=25
MCP_PORT=8080

bind_host="127.0.0.1"
port="8601"
allow_remote=""
pull=""
bootstrap_python=""
recreate=""
skip_install=""
skip_build=""
no_start_deps=""
start_timeout="180"

step() { printf '==> %s\n' "$1"; }
note() { printf '    %s\n' "$1"; }
warn() { printf 'warning: %s\n' "$1" >&2; }
die() { printf 'error: %s\n' "$1" >&2; exit 1; }

usage() {
    awk 'NR == 1 { next }
         /^#/ { sub(/^# ?/, ""); print; next }
         /^[[:space:]]*$/ { print ""; next }
         { exit }' "$0"
}

while [ $# -gt 0 ]; do
    case "$1" in
        --host) [ $# -ge 2 ] || die "--host needs a value"; bind_host="$2"; shift 2 ;;
        --port) [ $# -ge 2 ] || die "--port needs a value"; port="$2"; shift 2 ;;
        --python) [ $# -ge 2 ] || die "--python needs a value"; bootstrap_python="$2"; shift 2 ;;
        --start-timeout) [ $# -ge 2 ] || die "--start-timeout needs a value"; start_timeout="$2"; shift 2 ;;
        --allow-remote) allow_remote=1; shift ;;
        --pull) pull=1; shift ;;
        --recreate) recreate=1; shift ;;
        --skip-install) skip_install=1; shift ;;
        --skip-build) skip_build=1; shift ;;
        --no-start-deps) no_start_deps=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) die "unknown option: $1 (try --help)" ;;
    esac
done

case "$port" in ''|*[!0-9]*) die "--port must be a number, got: $port" ;; esac
case "$start_timeout" in ''|*[!0-9]*) die "--start-timeout must be a whole number of seconds, got: $start_timeout" ;; esac
if [ -n "$recreate" ] && [ -n "$skip_install" ]; then
    die "--recreate and --skip-install contradict each other: one rebuilds the venv, the other refuses to install into it."
fi

is_loopback() {
    local candidate
    for candidate in "${LOOPBACK_HOSTS[@]}"; do
        [ "$1" = "$candidate" ] && return 0
    done
    return 1
}
if ! is_loopback "$bind_host" && [ -z "$allow_remote" ]; then
    die "--host $bind_host is not loopback and the UI has no login - pass --allow-remote to bind it anyway."
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(dirname "$script_dir")"
client_dir="$repo_root/mcp-client"
[ -f "$repo_root/pom.xml" ] && [ -f "$client_dir/gradio_ui.py" ] ||
    die "no pom.xml / mcp-client/gradio_ui.py under $repo_root - this script must stay in allotmint-mcp/scripts."
cd "$repo_root"

# --- helpers ----------------------------------------------------------------

listening_pids() {
    if command -v lsof >/dev/null 2>&1; then
        lsof -ti tcp:"$1" -sTCP:LISTEN 2>/dev/null || true
    elif command -v fuser >/dev/null 2>&1; then
        fuser -n tcp "$1" 2>/dev/null || true
    fi
}

port_open() {
    (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null
}

wait_port_closed() {
    local _
    for _ in $(seq 1 30); do
        port_open "$1" || return 0
        sleep 0.5
    done
    return 1
}

# The value of KEY from the environment if set, else from .env (last
# assignment wins, quotes and inline comments stripped), else empty.
config_value() {
    local key="$1" line value=""
    if [ -n "${!key+x}" ]; then
        printf '%s' "${!key}"
        return 0
    fi
    [ -f "$repo_root/.env" ] || return 0
    while IFS= read -r line || [ -n "$line" ]; do
        line="${line%$'\r'}"
        line="${line#$'\xEF\xBB\xBF'}"                # Notepad's UTF-8 BOM
        line="${line#"${line%%[![:space:]]*}"}"
        line="${line#export }"
        case "$line" in "$key="*) value="${line#*=}" ;; esac
    done < "$repo_root/.env"
    value="${value%%[[:space:]]#*}"
    value="${value%"${value##*[![:space:]]}"}"
    value="${value#[\"\']}"
    value="${value%[\"\']}"
    printf '%s' "$value"
}

# --- 1. pull ----------------------------------------------------------------

if [ -n "$pull" ]; then
    step "Pulling latest commits"
    note "$ git pull --ff-only"
    git pull --ff-only
fi

# --- 2. a previous UI on the port -------------------------------------------

pids="$(listening_pids "$port")"
stopped=""
for pid in $pids; do
    cmd="$(ps -o command= -p "$pid" 2>/dev/null || true)"
    case "$cmd" in
        *gradio_ui*)
            step "Stopping a previous gradio_ui.py (pid $pid) still on port $port"
            kill "$pid" 2>/dev/null || true
            stopped="$stopped $pid"
            ;;
        *)
            note "pid $pid holds port $port but isn't gradio_ui.py ($cmd) - leaving it running."
            ;;
    esac
done
if [ -n "$stopped" ] && ! wait_port_closed "$port"; then
    # Same end state as the .ps1's Stop-Process -Force.
    for pid in $stopped; do kill -9 "$pid" 2>/dev/null || true; done
    wait_port_closed "$port" || true
fi

# --- 3. Python venv and requirements ----------------------------------------

venv_dir="$client_dir/.venv"
venv_python="$venv_dir/bin/python"

if [ -n "$recreate" ] && [ -d "$venv_dir" ]; then
    step "Removing $venv_dir (--recreate)"
    rm -rf "$venv_dir"
fi

if [ ! -x "$venv_python" ]; then
    [ -z "$skip_install" ] ||
        die "no venv at $venv_dir and --skip-install was passed - drop --skip-install for the first run."
    step "Creating venv at $venv_dir"
    bootstrap="$bootstrap_python"
    if [ -z "$bootstrap" ]; then
        for candidate in "${TESTED_PYTHONS[@]}"; do
            if command -v "$candidate" >/dev/null 2>&1; then
                bootstrap="$candidate"
                break
            fi
        done
    fi
    bootstrap="${bootstrap:-python3}"
    command -v "$bootstrap" >/dev/null 2>&1 ||
        die "no interpreter at '$bootstrap' - pass --python <path to a 3.10+ interpreter>."
    note "$ $bootstrap -m venv $venv_dir"
    "$bootstrap" -m venv "$venv_dir"
    [ -x "$venv_python" ] || die "venv created at $venv_dir but no interpreter found in it."
fi

py_version="$("$venv_python" -c 'import sys; print("%d.%d" % sys.version_info[:2])')" ||
    die "could not run $venv_python - re-run with --recreate to rebuild it."
case "$py_version" in
    3.1[0-9]|3.[2-9][0-9]|[4-9].*) ;;
    *) die "$venv_python is Python $py_version; gradio/mcp need 3.10+. Re-run with --recreate --python <path to a 3.10+ interpreter>." ;;
esac
note "python $py_version at $venv_python"

if [ -n "$skip_install" ]; then
    step "Skipping Python dependency update (--skip-install)"
else
    step "Updating Python dependencies (mcp-client/requirements.txt)"
    note "$ $venv_python -m pip install --upgrade pip"
    "$venv_python" -m pip install --disable-pip-version-check --quiet --upgrade pip ||
        warn "could not upgrade pip - carrying on with the venv's own"
    note "$ $venv_python -m pip install --upgrade -r mcp-client/requirements.txt"
    "$venv_python" -m pip install --disable-pip-version-check --upgrade -r "$client_dir/requirements.txt" ||
        die "pip install -r mcp-client/requirements.txt failed - see above (re-run with --recreate if the venv is broken)."
fi

# --- 4. the allotmint-mcp jar -----------------------------------------------

jar="$repo_root/target/allotmint-mcp-server.jar"
if [ -n "$skip_build" ]; then
    step "Skipping jar and image builds (--skip-build)"
else
    rebuild_reason=""
    if [ ! -f "$jar" ]; then
        rebuild_reason="$jar does not exist"
    elif [ -n "$(find "$repo_root/pom.xml" "$repo_root/src" -type f -newer "$jar" -print -quit 2>/dev/null)" ]; then
        rebuild_reason="pom.xml or src/ changed since $jar was built"
    fi

    if [ -z "$rebuild_reason" ]; then
        step "allotmint-mcp jar is up to date"
    else
        step "Building allotmint-mcp ($rebuild_reason)"
        command -v java >/dev/null 2>&1 || die "'java' isn't on PATH - install Java $MIN_JAVA+ (or pass --skip-build)."
        java_major="$(java -version 2>&1 | sed -n 's/.*version "\([0-9][0-9]*\).*/\1/p' | head -1)"
        [ -n "$java_major" ] && [ "$java_major" -ge "$MIN_JAVA" ] ||
            die "java on PATH is version ${java_major:-unknown}; this project needs $MIN_JAVA+ (see pom.xml). Point JAVA_HOME/PATH at a JDK $MIN_JAVA."
        note "$ ./mvnw -B -ntp -DskipTests package"
        ./mvnw -B -ntp -DskipTests package || die "Maven build failed - see above."

        if port_open "$MCP_PORT"; then
            if [ -f "$client_dir/logs/allotmint-mcp.pid" ]; then
                step "Restarting the allotmint-mcp server on :$MCP_PORT so it runs the new jar"
                "$venv_python" "$client_dir/stop_deps.py" --mcp-server || true
                wait_port_closed "$MCP_PORT" ||
                    warn ":$MCP_PORT is still open after stopping the server - the UI may talk to the old jar."
            else
                warn "an allotmint-mcp you started yourself is on :$MCP_PORT and is still running the old jar - restart it to pick up the rebuild."
            fi
        fi
    fi
fi

# --- 5. the research-agent image --------------------------------------------

docker_up=""
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    docker_up=1
fi

if [ -z "$skip_build" ] && [ -z "$no_start_deps" ]; then
    if [ -n "$docker_up" ]; then
        step "Updating the research-agent image (cached unless research-agent/ changed)"
        note "$ docker compose --profile research build research-agent"
        docker compose --profile research build research-agent || die "docker compose build research-agent failed - see above."
        if [ -n "$(docker compose --profile research ps -q research-agent 2>/dev/null)" ]; then
            note "$ docker compose --profile research up -d research-agent"
            docker compose --profile research up -d research-agent ||
                warn "could not recreate the running research-agent container on the new image"
        fi
    else
        warn "Docker isn't running - pgvector and the research-agent sidecar can't be started or updated. Start Docker Desktop (or dockerd) and re-run."
    fi
fi

# --- 6. launch ---------------------------------------------------------------

ui_args=(--host "$bind_host" --port "$port")
if [ -n "$no_start_deps" ]; then
    step "Not starting dependencies (--no-start-deps)"
else
    provider="$(config_value ALLOTMINT_RESEARCH_LLM_PROVIDER)"
    available="$(config_value ALLOTMINT_RESEARCH_AVAILABLE_LLM_PROVIDERS)"
    offered=",${provider:-ollama},${available},"
    offered="${offered//[[:space:]]/}"
    case "$offered" in
        *,ollama,*)
            ui_args+=(--start-deps)
            ;;
        *)
            note "LLM provider is '$provider' and ollama isn't offered - not starting Ollama"
            ui_args+=(--start-pgvector --start-mcp-server --start-research-agent)
            ;;
    esac
    ui_args+=(--start-timeout "$start_timeout")
fi

step "Starting the allotmint UI on http://$bind_host:$port  (Ctrl-C to stop)"
note "$ $venv_python mcp-client/gradio_ui.py ${ui_args[*]}"
exec "$venv_python" "$client_dir/gradio_ui.py" "${ui_args[@]}"
