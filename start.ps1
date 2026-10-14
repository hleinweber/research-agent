# Run from any PowerShell working directory.
Push-Location $PSScriptRoot
try {
    uv run python (Join-Path $PSScriptRoot 'web.py') @args
} finally {
    Pop-Location
}
