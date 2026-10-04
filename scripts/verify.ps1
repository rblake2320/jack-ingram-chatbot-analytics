param([switch]$Install)
$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Push-Location $taskRoot
try {
    if ($Install) {
        python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed' }
        & .venv/Scripts/python.exe -m pip install --require-hashes -r requirements.lock
        if ($LASTEXITCODE -ne 0) { throw 'Locked runtime installation failed' }
        & .venv/Scripts/python.exe -m pip install -r requirements-dev.txt
        if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
    }
    $taskPython = Join-Path $taskRoot '.venv/Scripts/python.exe'
    if (!(Test-Path -LiteralPath $taskPython)) { throw 'Run scripts/verify.ps1 -Install first' }
    if (!(Get-Command node -ErrorAction SilentlyContinue)) { throw 'Node.js 24 is required to build and verify the vehicle viewer' }
    if ($Install) {
        npm ci --ignore-scripts --no-fund --no-audit
        if ($LASTEXITCODE -ne 0) { throw 'Locked viewer dependency installation failed' }
    }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw 'Vehicle asset/build gate failed' }
    npm test
    if ($LASTEXITCODE -ne 0) { throw 'Vehicle geometry/action gate failed' }
    npm audit --audit-level=moderate
    if ($LASTEXITCODE -ne 0) { throw 'Viewer dependency audit failed' }
    & $taskPython scripts/check_repository.py
    if ($LASTEXITCODE -ne 0) { throw 'Repository gate failed' }
    & $taskPython -m ruff check src scripts
    if ($LASTEXITCODE -ne 0) { throw 'Lint gate failed' }
    & $taskPython -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw 'Regression gate failed' }
    & $taskPython scripts/verify_http.py
    if ($LASTEXITCODE -ne 0) { throw 'Waitress HTTP gate failed' }
    & $taskPython -m pip_audit -r requirements.lock --require-hashes --progress-spinner off
    if ($LASTEXITCODE -ne 0) { throw 'Dependency audit failed' }
} finally { Pop-Location }
