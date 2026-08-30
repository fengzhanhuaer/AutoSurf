param(
    [string]$InstallDir = "C:\Tools\AutoSurf"
)

$ErrorActionPreference = "Stop"
$root = [System.IO.Path]::GetFullPath($InstallDir)
$envFile = Join-Path $root ".env"
$python = Join-Path $root "program\.venv\Scripts\python.exe"
$supervisor = Join-Path $root "program\scripts\autosurf-supervisor.py"

if (-not (Test-Path -LiteralPath $envFile -PathType Leaf)) {
    throw "AutoSurf configuration is missing: $envFile"
}
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "AutoSurf Python environment is missing: $python"
}

Get-Content -LiteralPath $envFile | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#")) { return }
    $parts = $line.Split("=", 2)
    if ($parts.Count -eq 2) {
        [Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1].Trim().Trim('"'), "Process")
    }
}

Set-Location -LiteralPath $root
& $python $supervisor --root $root
exit $LASTEXITCODE
