param(
    [string]$InstallDir = "C:\Tools\AutoSurf"
)

$ErrorActionPreference = "Stop"
$root = [System.IO.Path]::GetFullPath($InstallDir)
$program = Join-Path $root "program"
$pythonw = Join-Path $program ".venv\Scripts\pythonw.exe"
$launcher = Join-Path $program "scripts\native_launcher.py"
$taskName = "AutoSurf Background Service"

if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
	throw "AutoSurf native launcher is missing: $launcher"
}

$arguments = "`"$launcher`" --root `"$root`""
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
	throw "Could not update the AutoSurf service task: $($_.Exception.Message)"
}
Write-Host "Registered $taskName."
