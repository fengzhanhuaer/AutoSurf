param(
    [string]$InstallDir = "C:\Tools\AutoSurf"
)

$ErrorActionPreference = "Stop"
$root = [System.IO.Path]::GetFullPath($InstallDir)
$program = Join-Path $root "program"
$runScript = Join-Path $program "scripts\run.ps1"
$pythonw = Join-Path $program ".venv\Scripts\pythonw.exe"
$supervisor = Join-Path $program "scripts\autosurf-supervisor.py"
$taskName = "AutoSurf Background Service"

if (-not (Test-Path -LiteralPath $runScript -PathType Leaf)) {
    throw "AutoSurf launch script is missing: $runScript"
}

$arguments = "`"$supervisor`" --root `"$root`""
$action = New-ScheduledTaskAction -Execute $pythonw -Argument $arguments `
    -WorkingDirectory $root
$logonTrigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew `
    -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 3650)
$principal = New-ScheduledTaskPrincipal `
    -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive -RunLevel Limited

try {
    Register-ScheduledTask -TaskName $taskName -Action $action `
        -Trigger $logonTrigger `
        -Settings $settings -Principal $principal -Force | Out-Null
} catch {
    Write-Warning "Could not update the AutoSurf service task: $($_.Exception.Message)"
}
Write-Host "Registered $taskName."
