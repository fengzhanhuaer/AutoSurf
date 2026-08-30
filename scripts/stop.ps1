param(
    [string]$InstallDir = "C:\Tools\AutoSurf"
)

$ErrorActionPreference = "Stop"
$pidFile = Join-Path ([System.IO.Path]::GetFullPath($InstallDir)) "data\supervisor.pid"
if (-not (Test-Path -LiteralPath $pidFile -PathType Leaf)) {
    Write-Host "AutoSurf is not running."
    exit 0
}
$processId = [int](Get-Content -LiteralPath $pidFile -Raw).Trim()
& taskkill.exe /PID $processId /T /F | Out-Null
Write-Host "AutoSurf stopped."
