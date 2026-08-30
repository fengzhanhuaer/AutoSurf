param(
    [string]$InstallDir = "C:\Tools\AutoSurf",
    [string]$Repository = "https://github.com/fengzhanhuaer/AutoSurf.git",
    [string]$Branch = "main",
    [string]$Username = "admin",
    [string]$Password = ""
)

$ErrorActionPreference = "Stop"
$root = [System.IO.Path]::GetFullPath($InstallDir)
$program = Join-Path $root "program"
$data = Join-Path $root "data"
$browser = Join-Path $root "browser"
$envFile = Join-Path $root ".env"
$python = Join-Path $program ".venv\Scripts\python.exe"

function New-RandomBase64([int]$ByteCount) {
    $bytes = New-Object byte[] $ByteCount
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($bytes) } finally { $generator.Dispose() }
    return [Convert]::ToBase64String($bytes)
}

foreach ($command in @("git.exe", "py.exe")) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "Required command is missing: $command"
    }
}
if (-not (Test-Path -LiteralPath $program)) {
    New-Item -ItemType Directory -Path $root -Force | Out-Null
    & git.exe clone --branch $Branch --single-branch $Repository $program
    if ($LASTEXITCODE -ne 0) { throw "Cannot clone AutoSurf." }
} elseif (-not (Test-Path -LiteralPath (Join-Path $program ".git"))) {
    throw "Program directory is not an AutoSurf Git checkout: $program"
}

New-Item -ItemType Directory -Path $data, $browser -Force | Out-Null
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    & py.exe -3.13 -m venv (Join-Path $program ".venv")
    if ($LASTEXITCODE -ne 0) { throw "Python 3.13 is required." }
}
& $python -m pip install --disable-pip-version-check --upgrade -e $program
if ($LASTEXITCODE -ne 0) { throw "Cannot install AutoSurf dependencies." }
& (Join-Path $program "scripts\install-browser.ps1") -InstallDir $root

$createdPassword = $false
if (-not (Test-Path -LiteralPath $envFile -PathType Leaf)) {
    if (-not $Password) {
        $Password = New-RandomBase64 18
        $createdPassword = $true
    }
    $secret = New-RandomBase64 32
    $rootEnv = $root.Replace("\", "/")
    $programEnv = $program.Replace("\", "/")
    @(
        "AUTOSURF_DATA_DIR=$rootEnv/data"
        "AUTOSURF_PROGRAM_DIR=$programEnv"
        "AUTOSURF_BROWSER_PROFILE_DIR=$rootEnv/browser/profiles"
        "AUTOSURF_BROWSER_EXECUTABLE_PATH=$rootEnv/runtime/chrome/chrome.exe"
        "AUTOSURF_BROWSER_HEADLESS=false"
        "AUTOSURF_HOST=127.0.0.1"
        "AUTOSURF_PORT=18980"
        "AUTOSURF_SECRET_KEY=$secret"
        "AUTOSURF_USERNAME=$Username"
        "AUTOSURF_PASSWORD=$Password"
        "AUTOSURF_REPOSITORY=$Repository"
        "AUTOSURF_BRANCH=$Branch"
        "AUTOSURF_UPGRADE_REQUEST_FILE=$rootEnv/data/upgrade-request.json"
        "AUTOSURF_UPGRADE_LOCK_FILE=$rootEnv/data/upgrade-in-progress.lock"
    ) | Set-Content -LiteralPath $envFile -Encoding ascii
}

$shell = New-Object -ComObject WScript.Shell
$arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$program\scripts\run.ps1`" -InstallDir `"$root`""
foreach ($shortcutPath in @(
    (Join-Path ([Environment]::GetFolderPath("Startup")) "AutoSurf.lnk"),
    (Join-Path ([Environment]::GetFolderPath("Desktop")) "AutoSurf.lnk")
)) {
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = "powershell.exe"
    $shortcut.Arguments = $arguments
    $shortcut.WorkingDirectory = $root
    $shortcut.Save()
}

Start-Process powershell.exe -WindowStyle Hidden -ArgumentList $arguments
Write-Host "AutoSurf installed at $root"
Write-Host "Open http://127.0.0.1:18980/"
if ($createdPassword) {
    Write-Host "Username: $Username"
    Write-Host "Generated password: $Password"
}
