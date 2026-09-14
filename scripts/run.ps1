param(
    [string]$InstallDir = "C:\Tools\AutoSurf"
)

$ErrorActionPreference = "Stop"
$root = [System.IO.Path]::GetFullPath($InstallDir)
$envFile = Join-Path $root ".env"
$python = Join-Path $root "program\.venv\Scripts\python.exe"
$pythonw = Join-Path $root "program\.venv\Scripts\pythonw.exe"
$supervisor = Join-Path $root "program\scripts\autosurf-supervisor.py"

if (-not (Test-Path -LiteralPath $envFile -PathType Leaf)) {
    throw "AutoSurf configuration is missing: $envFile"
}
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "AutoSurf Python environment is missing: $python"
}
if (-not (Test-Path -LiteralPath $pythonw -PathType Leaf)) {
    throw "AutoSurf windowless Python environment is missing: $pythonw"
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
$pidFile = Join-Path $root "data\supervisor.pid"
if (Test-Path -LiteralPath $pidFile -PathType Leaf) {
    $existingPid = 0
    [int]::TryParse((Get-Content -LiteralPath $pidFile -Raw).Trim(), [ref]$existingPid) | Out-Null
    if ($existingPid -gt 0 -and (Get-Process -Id $existingPid -ErrorAction SilentlyContinue)) {
        exit 0
    }
}
Start-Process -FilePath $pythonw -ArgumentList @("`"$supervisor`"", "--root", "`"$root`"") `
    -WorkingDirectory $root -WindowStyle Hidden
