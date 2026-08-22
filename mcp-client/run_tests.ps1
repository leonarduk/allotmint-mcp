# Run the mcp-client pytest suite from anywhere in the repo. Resolve the repo
# root first so paths are correct regardless of the caller's working
# directory, mirroring scripts/g_run_tests.ps1's pattern.
$repoRoot = git rev-parse --show-toplevel 2>$null
if (-not $repoRoot) {
    Write-Error "Not in a git repository"
    exit 1
}

Push-Location "$repoRoot/mcp-client"
try {
    python -m pip install -r requirements-dev.txt
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }

    python -m pytest tests/
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
