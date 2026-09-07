param(
    [string]$InstallDir = "C:\Tools\AutoSurf"
)

$ErrorActionPreference = "Stop"
$root = [System.IO.Path]::GetFullPath($InstallDir)
$pidFile = Join-Path $root "data\supervisor.pid"
$taskName = "AutoSurf Local Service"
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
}
if (-not (Test-Path -LiteralPath $pidFile -PathType Leaf)) {
    Write-Host "AutoSurf is not running."
    exit 0
}
$processId = [int](Get-Content -LiteralPath $pidFile -Raw).Trim()
& taskkill.exe /PID $processId /T /F | Out-Null
Write-Host "AutoSurf stopped."
