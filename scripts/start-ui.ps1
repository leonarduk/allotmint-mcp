<#
.SYNOPSIS
Start the allotmint-mcp Gradio UI (mcp-client/gradio_ui.py), bringing
everything it depends on up to date first.

.DESCRIPTION
The PowerShell twin of scripts/start-ui.sh - same steps, same messages,
flags in -ThisSpelling. In order:

  1. (-Pull) git pull --ff-only.
  2. Stops a previous gradio_ui.py still holding -Port, so a re-run
     replaces it instead of failing to bind. Anything else on that port is
     left alone.
  3. Resolves mcp-client\.venv (creating it if missing) and runs
     `pip install --upgrade -r mcp-client\requirements.txt`, so a moved pin
     or a newer release actually lands.
  4. Rebuilds target\allotmint-mcp-server.jar with the Maven wrapper when it
     is missing or older than pom.xml / src\ (Java 25+ required). If the jar
     was rebuilt and a server started by an earlier --start-deps run is
     still up on :8080, it is stopped so it comes back on the new jar. A
     server you started by hand is left alone (with a warning).
  5. If Docker is running, rebuilds the research-agent image (a cached no-op
     when research-agent\ has not changed; several minutes the first time)
     and recreates its container if one is already running.
  6. Runs gradio_ui.py with --start-deps, which starts whatever of pgvector,
     Ollama, the allotmint-mcp server and the research-agent sidecar is not
     already reachable, and refuses to serve the UI if one cannot be
     confirmed. Ollama is skipped when .env / the environment configures a
     non-Ollama LLM provider and does not offer ollama.

.PARAMETER BindHost
Interface to bind (default 127.0.0.1).

.PARAMETER Port
Port to serve the UI on (default 8601).

.PARAMETER AllowRemote
Required to bind a non-loopback -BindHost. The UI has no login and shows
portfolio data.

.PARAMETER Pull
git pull --ff-only before anything else.

.PARAMETER Python
Interpreter used to create a new venv (default: py -3.12/-3.13/-3.11/-3.10,
then python on PATH).

.PARAMETER Recreate
Delete and rebuild mcp-client\.venv.

.PARAMETER SkipInstall
Do not run pip (the venv must already exist).

.PARAMETER SkipBuild
Do not rebuild the jar or the research-agent image.

.PARAMETER NoStartDeps
Only launch the UI; start nothing else.

.PARAMETER StartTimeout
Seconds to wait for each started dependency (default 180).

.EXAMPLE
scripts\start-ui.ps1

.EXAMPLE
scripts\start-ui.ps1 -Pull -Port 8602
#>
[CmdletBinding()]
param(
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8601,
    [switch]$AllowRemote,
    [switch]$Pull,
    [string]$Python = "",
    [switch]$Recreate,
    [switch]$SkipInstall,
    [switch]$SkipBuild,
    [switch]$NoStartDeps,
    [int]$StartTimeout = 180
)

# Not "Stop": under Windows PowerShell 5.1 that turns any stderr line from a
# native command redirected with 2>$null (py, docker, lsof) into a
# terminating error. Native exit codes are checked explicitly instead.
$ErrorActionPreference = "Continue"

$LoopbackHosts = @("127.0.0.1", "::1", "localhost")
# Order of preference for a new venv; 3.12 first because it is what CI runs
# the mcp-client tests on.
$TestedPythons = @("3.12", "3.13", "3.11", "3.10")
$MinJava = 25
$McpPort = 8080

function Step([string]$Message) { Write-Host "==> $Message" }
function Note([string]$Message) { Write-Host "    $Message" }
function Warn([string]$Message) { [Console]::Error.WriteLine("warning: $Message") }
function Die([string]$Message) { [Console]::Error.WriteLine("error: $Message"); exit 1 }

if ($Recreate -and $SkipInstall) {
    Die "-Recreate and -SkipInstall contradict each other: one rebuilds the venv, the other refuses to install into it."
}
if (($LoopbackHosts -notcontains $BindHost) -and -not $AllowRemote) {
    Die "-BindHost $BindHost is not loopback and the UI has no login - pass -AllowRemote to bind it anyway."
}

$RepoRoot = Split-Path -Parent $PSScriptRoot
$ClientDir = Join-Path $RepoRoot "mcp-client"
if (-not (Test-Path (Join-Path $RepoRoot "pom.xml")) -or -not (Test-Path (Join-Path $ClientDir "gradio_ui.py"))) {
    Die "no pom.xml / mcp-client\gradio_ui.py under $RepoRoot - this script must stay in allotmint-mcp\scripts."
}

# Windows venvs keep the interpreter in Scripts\, POSIX ones (pwsh on
# Linux/macOS) in bin/.
$OnWindows = ($PSVersionTable.PSEdition -eq "Desktop") -or $IsWindows

# --- helpers ------------------------------------------------------------------

function Test-PortOpen([int]$TcpPort) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $connect = $client.BeginConnect("127.0.0.1", $TcpPort, $null, $null)
        return ($connect.AsyncWaitHandle.WaitOne(500) -and $client.Connected)
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Wait-PortClosed([int]$TcpPort) {
    for ($i = 0; $i -lt 30; $i++) {
        if (-not (Test-PortOpen $TcpPort)) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Get-ListeningPids([int]$TcpPort) {
    if (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue) {
        return @(Get-NetTCPConnection -LocalPort $TcpPort -State Listen -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess -Unique)
    }
    if (Get-Command lsof -ErrorAction SilentlyContinue) {
        return @(& lsof -ti "tcp:$TcpPort" -sTCP:LISTEN 2>$null)
    }
    return @()
}

function Get-CommandLine([int]$ProcessId) {
    try {
        $cim = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction Stop
        return [string]$cim.CommandLine
    } catch {
        return [string](& ps -o command= -p $ProcessId 2>$null)
    }
}

# The value of $Key from the environment if set, else from .env (last
# assignment wins, quotes and inline comments stripped), else "".
function Get-ConfigValue([string]$Key) {
    $fromEnv = [Environment]::GetEnvironmentVariable($Key)
    if ($null -ne $fromEnv) { return $fromEnv }
    $envFile = Join-Path $RepoRoot ".env"
    if (-not (Test-Path $envFile)) { return "" }
    $value = ""
    foreach ($line in Get-Content $envFile) {
        $trimmed = $line.Trim() -replace '^export\s+', ''
        if ($trimmed.StartsWith("$Key=")) { $value = $trimmed.Substring($Key.Length + 1) }
    }
    $value = ($value -replace '\s+#.*$', '').Trim()
    return $value.Trim('"', "'")
}

function Invoke-Checked([string]$Failure, [scriptblock]$Command) {
    & $Command
    if ($LASTEXITCODE -ne 0) { Die $Failure }
}

Push-Location $RepoRoot
try {
    # --- 1. pull --------------------------------------------------------------

    if ($Pull) {
        Step "Pulling latest commits"
        Note "$ git pull --ff-only"
        Invoke-Checked "git pull --ff-only failed - see above." { git pull --ff-only }
    }

    # --- 2. a previous UI on the port -----------------------------------------

    $pids = Get-ListeningPids $Port
    if ($pids.Count -gt 0) {
        foreach ($processId in $pids) {
            $cmd = Get-CommandLine $processId
            if ($cmd -like "*gradio_ui*") {
                Step "Stopping a previous gradio_ui.py (pid $processId) still on port $Port"
                Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
            } else {
                Note "pid $processId holds port $Port but isn't gradio_ui.py ($cmd) - leaving it running."
            }
        }
        [void](Wait-PortClosed $Port)
    }

    # --- 3. Python venv and requirements --------------------------------------

    $VenvDir = Join-Path $ClientDir ".venv"
    $VenvPython = if ($OnWindows) { Join-Path $VenvDir "Scripts\python.exe" } else { Join-Path $VenvDir "bin/python" }

    if ($Recreate -and (Test-Path $VenvDir)) {
        Step "Removing $VenvDir (-Recreate)"
        Remove-Item -Recurse -Force $VenvDir -ErrorAction Stop
    }

    if (-not (Test-Path $VenvPython)) {
        if ($SkipInstall) {
            Die "no venv at $VenvDir and -SkipInstall was passed - drop -SkipInstall for the first run."
        }
        Step "Creating venv at $VenvDir"
        $bootstrap = @()
        if ($Python) {
            $bootstrap = @($Python)
        } elseif (Get-Command py -ErrorAction SilentlyContinue) {
            foreach ($version in $TestedPythons) {
                & py "-$version" -c "pass" 2>$null
                if ($LASTEXITCODE -eq 0) { $bootstrap = @("py", "-$version"); break }
            }
        }
        if ($bootstrap.Count -eq 0) {
            foreach ($candidate in @($TestedPythons | ForEach-Object { "python$_" }) + @("python3", "python")) {
                if (Get-Command $candidate -ErrorAction SilentlyContinue) { $bootstrap = @($candidate); break }
            }
        }
        if ($bootstrap.Count -eq 0 -or -not (Get-Command $bootstrap[0] -ErrorAction SilentlyContinue)) {
            Die "no Python interpreter found - pass -Python <path to a 3.10+ interpreter>."
        }
        $bootstrapArgs = @($bootstrap | Select-Object -Skip 1)
        Note "$ $($bootstrap -join ' ') -m venv $VenvDir"
        Invoke-Checked "creating the venv failed - see above." { & $bootstrap[0] @bootstrapArgs -m venv $VenvDir }
        if (-not (Test-Path $VenvPython)) { Die "venv created at $VenvDir but no interpreter found in it." }
    }

    $pyVersion = & $VenvPython -c 'import sys; print("%d.%d" % sys.version_info[:2])'
    if ($LASTEXITCODE -ne 0 -or -not $pyVersion) {
        Die "could not run $VenvPython - re-run with -Recreate to rebuild it."
    }
    if ([version]"$pyVersion" -lt [version]"3.10") {
        Die "$VenvPython is Python $pyVersion; gradio/mcp need 3.10+. Re-run with -Recreate -Python <path to a 3.10+ interpreter>."
    }
    Note "python $pyVersion at $VenvPython"

    $requirements = Join-Path $ClientDir "requirements.txt"
    if ($SkipInstall) {
        Step "Skipping Python dependency update (-SkipInstall)"
    } else {
        Step "Updating Python dependencies (mcp-client\requirements.txt)"
        Note "$ $VenvPython -m pip install --upgrade pip"
        & $VenvPython -m pip install --disable-pip-version-check --quiet --upgrade pip
        if ($LASTEXITCODE -ne 0) { Warn "could not upgrade pip - carrying on with the venv's own" }
        Note "$ $VenvPython -m pip install --upgrade -r mcp-client\requirements.txt"
        Invoke-Checked "pip install -r mcp-client\requirements.txt failed - see above (re-run with -Recreate if the venv is broken)." {
            & $VenvPython -m pip install --disable-pip-version-check --upgrade -r $requirements
        }
    }

    # --- 4. the allotmint-mcp jar ---------------------------------------------

    $Jar = Join-Path $RepoRoot "target\allotmint-mcp-server.jar"
    if ($SkipBuild) {
        Step "Skipping jar and image builds (-SkipBuild)"
    } else {
        $rebuildReason = ""
        if (-not (Test-Path $Jar)) {
            $rebuildReason = "$Jar does not exist"
        } else {
            $jarTime = (Get-Item $Jar).LastWriteTimeUtc
            $sources = @(Get-Item (Join-Path $RepoRoot "pom.xml")) +
                @(Get-ChildItem -Path (Join-Path $RepoRoot "src") -Recurse -File -ErrorAction SilentlyContinue)
            if ($sources | Where-Object { $_.LastWriteTimeUtc -gt $jarTime } | Select-Object -First 1) {
                $rebuildReason = "pom.xml or src\ changed since $Jar was built"
            }
        }

        if (-not $rebuildReason) {
            Step "allotmint-mcp jar is up to date"
        } else {
            Step "Building allotmint-mcp ($rebuildReason)"
            if (-not (Get-Command java -ErrorAction SilentlyContinue)) {
                Die "'java' isn't on PATH - install Java $MinJava+ (or pass -SkipBuild)."
            }
            # java -version writes to stderr; let the shell merge it into
            # stdout so PowerShell never sees it as an error record.
            $javaReport = if ($OnWindows) { & cmd /c "java -version 2>&1" } else { & sh -c "java -version 2>&1" }
            $javaMajor = 0
            $match = [regex]::Match(($javaReport -join "`n"), 'version "(\d+)')
            if ($match.Success) { $javaMajor = [int]$match.Groups[1].Value }
            if ($javaMajor -lt $MinJava) {
                Die "java on PATH is version $(if ($javaMajor) { $javaMajor } else { 'unknown' }); this project needs $MinJava+ (see pom.xml). Point JAVA_HOME/PATH at a JDK $MinJava."
            }
            $mvnw = if ($OnWindows) { Join-Path $RepoRoot "mvnw.cmd" } else { Join-Path $RepoRoot "mvnw" }
            Note "$ $(Split-Path -Leaf $mvnw) -B -ntp -DskipTests package"
            Invoke-Checked "Maven build failed - see above." { & $mvnw -B -ntp -DskipTests package }

            if (Test-PortOpen $McpPort) {
                if (Test-Path (Join-Path $ClientDir "logs\allotmint-mcp.pid")) {
                    Step "Restarting the allotmint-mcp server on :$McpPort so it runs the new jar"
                    & $VenvPython (Join-Path $ClientDir "stop_deps.py") --mcp-server
                    if (-not (Wait-PortClosed $McpPort)) {
                        Warn ":$McpPort is still open after stopping the server - the UI may talk to the old jar."
                    }
                } else {
                    Warn "an allotmint-mcp you started yourself is on :$McpPort and is still running the old jar - restart it to pick up the rebuild."
                }
            }
        }
    }

    # --- 5. the research-agent image ------------------------------------------

    $dockerUp = $false
    if (Get-Command docker -ErrorAction SilentlyContinue) {
        & docker info *> $null
        $dockerUp = ($LASTEXITCODE -eq 0)
    }

    if (-not $SkipBuild -and -not $NoStartDeps) {
        if ($dockerUp) {
            Step "Updating the research-agent image (cached unless research-agent\ changed)"
            Note "$ docker compose --profile research build research-agent"
            Invoke-Checked "docker compose build research-agent failed - see above." {
                docker compose --profile research build research-agent
            }
            $running = & docker compose --profile research ps -q research-agent 2>$null
            if ($running) {
                Note "$ docker compose --profile research up -d research-agent"
                & docker compose --profile research up -d research-agent
                if ($LASTEXITCODE -ne 0) { Warn "could not recreate the running research-agent container on the new image" }
            }
        } else {
            Warn "Docker isn't running - pgvector and the research-agent sidecar can't be started or updated. Start Docker Desktop (or dockerd) and re-run."
        }
    }

    # --- 6. launch -------------------------------------------------------------

    $uiArgs = @("--host", $BindHost, "--port", "$Port")
    if ($NoStartDeps) {
        Step "Not starting dependencies (-NoStartDeps)"
    } else {
        $provider = Get-ConfigValue "ALLOTMINT_RESEARCH_LLM_PROVIDER"
        $available = Get-ConfigValue "ALLOTMINT_RESEARCH_AVAILABLE_LLM_PROVIDERS"
        $offered = @((@($(if ($provider) { $provider } else { "ollama" })) + ($available -split ',')) |
            ForEach-Object { $_.Trim() })
        if ($offered -contains "ollama") {
            $uiArgs += "--start-deps"
        } else {
            Note "LLM provider is '$provider' and ollama isn't offered - not starting Ollama"
            $uiArgs += @("--start-pgvector", "--start-mcp-server", "--start-research-agent")
        }
        $uiArgs += @("--start-timeout", "$StartTimeout")
    }

    Step "Starting the allotmint UI on http://${BindHost}:$Port  (Ctrl-C to stop)"
    Note "$ $VenvPython mcp-client\gradio_ui.py $($uiArgs -join ' ')"
    & $VenvPython (Join-Path $ClientDir "gradio_ui.py") @uiArgs
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
