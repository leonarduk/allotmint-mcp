# Run the backend test suite from anywhere in the repo (root or
# scripts/developer_tools). Resolve the repo root first so mvnw is invoked
# from the right place regardless of the caller's working directory.
$repoRoot = git rev-parse --show-toplevel 2>$null
if (-not $repoRoot) {
    Write-Error "Not in a git repository"
    exit 1
}

Push-Location $repoRoot
try {
    # `verify` (not `test`) so the jacoco-maven-plugin's `report` goal runs
    # too, producing an HTML/XML coverage report under target/site/jacoco/
    # (the closest Maven equivalent to pytest's --cov-report flags). This
    # also triggers the spotless-check execution bound to the same phase,
    # so a formatting violation will fail this run same as a test failure.
    if ($IsWindows) {
        & "$repoRoot\mvnw.cmd" verify
    } else {
        & "$repoRoot/mvnw" verify
    }
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
