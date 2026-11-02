# Start the TestAgent platform (Windows). Requires uv, Node.js >= 20 and a configured .env.
# Builds the web UI on first run (or with -Rebuild), then launches the server and opens the browser.
param([switch]$Rebuild)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
if ($Rebuild -or -not (Test-Path "src\testagent\web\index.html")) {
    Push-Location web
    try {
        if ($Rebuild -or -not (Test-Path "node_modules")) {
            npm ci --cache .npm-cache --no-audit --no-fund
            if ($LASTEXITCODE -ne 0) { throw "npm ci failed" }
        }
        npm run build
        if ($LASTEXITCODE -ne 0) { throw "npm run build failed" }
    } finally {
        Pop-Location
    }
}
uv run python -m testagent.launch @args
