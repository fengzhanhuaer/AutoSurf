param(
    [string]$InstallDir = "C:\Tools\AutoSurf"
)

$ErrorActionPreference = "Stop"
$root = [System.IO.Path]::GetFullPath($InstallDir)
$program = Join-Path $root "program"
$manifestPath = Join-Path $program "browser-runtime.json"
$runtimeRoot = Join-Path $root "runtime"
$target = Join-Path $runtimeRoot "chrome"
$versionFile = Join-Path $target ".autosurf-version"

if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "Browser runtime manifest is missing: $manifestPath"
}
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$executable = Join-Path $target ([string]$manifest.executable)
$installedVersion = if (Test-Path -LiteralPath $versionFile -PathType Leaf) {
    (Get-Content -LiteralPath $versionFile -Raw).Trim()
} else {
    ""
}
if ($installedVersion -eq [string]$manifest.version -and
    (Test-Path -LiteralPath $executable -PathType Leaf)) {
    Write-Host "AutoSurf browser runtime $installedVersion is already installed."
    exit 0
}

New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
$temporary = Join-Path ([System.IO.Path]::GetTempPath()) ("autosurf-browser-" + [Guid]::NewGuid().ToString("N"))
$archive = Join-Path $temporary "chrome.zip"
$expanded = Join-Path $temporary "expanded"
$staged = Join-Path $runtimeRoot "chrome.new"
$previous = Join-Path $runtimeRoot "chrome.old"
New-Item -ItemType Directory -Path $temporary, $expanded -Force | Out-Null

try {
    Write-Host "Downloading AutoSurf browser runtime $($manifest.version)..."
    Invoke-WebRequest -UseBasicParsing -Uri ([string]$manifest.archive_url) -OutFile $archive
    $archiveInfo = Get-Item -LiteralPath $archive
    if ($archiveInfo.Length -ne [long]$manifest.archive_size) {
        throw "Browser runtime size check failed."
    }
    $hashStream = [System.IO.File]::OpenRead($archive)
    $hashAlgorithm = [System.Security.Cryptography.MD5]::Create()
    try {
        $archiveHash = -join ($hashAlgorithm.ComputeHash($hashStream) | ForEach-Object {
            $_.ToString("x2")
        })
    } finally {
        $hashAlgorithm.Dispose()
        $hashStream.Dispose()
    }
    if ($archiveHash -ne ([string]$manifest.archive_md5).ToLowerInvariant()) {
        throw "Browser runtime checksum check failed."
    }
    Expand-Archive -LiteralPath $archive -DestinationPath $expanded -Force
    $source = Join-Path $expanded ([string]$manifest.archive_root)
    $sourceExecutable = Join-Path $source ([string]$manifest.executable)
    if (-not (Test-Path -LiteralPath $sourceExecutable -PathType Leaf)) {
        throw "Browser runtime executable is missing from the archive."
    }

    Remove-Item -LiteralPath $staged -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $previous -Recurse -Force -ErrorAction SilentlyContinue
    Move-Item -LiteralPath $source -Destination $staged
    Set-Content -LiteralPath (Join-Path $staged ".autosurf-version") `
        -Value ([string]$manifest.version) -Encoding ascii
    if (Test-Path -LiteralPath $target) {
        Move-Item -LiteralPath $target -Destination $previous
    }
    try {
        Move-Item -LiteralPath $staged -Destination $target
    } catch {
        if (Test-Path -LiteralPath $previous) {
            Move-Item -LiteralPath $previous -Destination $target
        }
        throw
    }
    Remove-Item -LiteralPath $previous -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "Installed AutoSurf browser runtime $($manifest.version)."
} finally {
    Remove-Item -LiteralPath $temporary -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $staged -Recurse -Force -ErrorAction SilentlyContinue
}
