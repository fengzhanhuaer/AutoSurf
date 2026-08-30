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

function Save-RemoteFile([string]$Uri, [string]$Path, [long]$ExpectedSize) {
    $chunkSize = 4MB
    $maximumAttempts = 8
    if (Test-Path -LiteralPath $Path -PathType Leaf) {
        $existingSize = (Get-Item -LiteralPath $Path).Length
        if ($existingSize -gt $ExpectedSize) {
            Remove-Item -LiteralPath $Path -Force
        }
    }

    while ($true) {
        $offset = if (Test-Path -LiteralPath $Path -PathType Leaf) {
            (Get-Item -LiteralPath $Path).Length
        } else {
            0L
        }
        if ($offset -eq $ExpectedSize) { break }
        $lastByte = [Math]::Min($offset + $chunkSize - 1, $ExpectedSize - 1)
        $expectedChunkSize = $lastByte - $offset + 1
        $completed = $false

        for ($attempt = 1; $attempt -le $maximumAttempts; $attempt++) {
            $request = $null
            $response = $null
            $inputStream = $null
            $outputStream = $null
            try {
                $request = [System.Net.HttpWebRequest]::Create($Uri)
                $request.Method = "GET"
                $request.AddRange($offset, $lastByte)
                $request.KeepAlive = $false
                $request.Timeout = 120000
                $request.ReadWriteTimeout = 120000
                $response = $request.GetResponse()
                $statusCode = [int]$response.StatusCode
                $wholeFileResponse = (
                    $statusCode -eq 200 -and $offset -eq 0 -and $lastByte -eq ($ExpectedSize - 1)
                )
                if ($statusCode -ne 206 -and -not $wholeFileResponse) {
                    throw "Download server did not honor the requested byte range."
                }

                $inputStream = $response.GetResponseStream()
                $outputStream = [System.IO.File]::Open(
                    $Path,
                    [System.IO.FileMode]::OpenOrCreate,
                    [System.IO.FileAccess]::Write,
                    [System.IO.FileShare]::None
                )
                $outputStream.SetLength($offset)
                $outputStream.Position = $offset
                $buffer = New-Object byte[] 65536
                while (($count = $inputStream.Read($buffer, 0, $buffer.Length)) -gt 0) {
                    $outputStream.Write($buffer, 0, $count)
                }
                $outputStream.Flush()
                $received = $outputStream.Length - $offset
                if ($received -ne $expectedChunkSize) {
                    throw "Downloaded byte range was incomplete."
                }
                $completed = $true
                break
            } catch {
                if ($outputStream) {
                    $outputStream.SetLength($offset)
                    $outputStream.Flush()
                } elseif (Test-Path -LiteralPath $Path -PathType Leaf) {
                    $repairStream = [System.IO.File]::Open(
                        $Path,
                        [System.IO.FileMode]::Open,
                        [System.IO.FileAccess]::Write,
                        [System.IO.FileShare]::None
                    )
                    try { $repairStream.SetLength($offset) } finally { $repairStream.Dispose() }
                }
                if ($attempt -eq $maximumAttempts) { throw }
                Write-Warning "Browser download interrupted; retrying byte $offset (attempt $($attempt + 1)/$maximumAttempts)."
                Start-Sleep -Seconds ([Math]::Min($attempt * 2, 10))
            } finally {
                if ($outputStream) { $outputStream.Dispose() }
                if ($inputStream) { $inputStream.Dispose() }
                if ($response) { $response.Dispose() }
                if ($request) { $request.Abort() }
            }
        }
        if (-not $completed) { throw "Browser download failed." }
        $downloaded = (Get-Item -LiteralPath $Path).Length
        $percent = [Math]::Floor(($downloaded * 100.0) / $ExpectedSize)
        Write-Progress -Activity "Downloading AutoSurf browser" `
            -Status "$percent%" -PercentComplete $percent
    }
    Write-Progress -Activity "Downloading AutoSurf browser" -Completed
}

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
$archive = Join-Path $runtimeRoot ("chrome-" + [string]$manifest.version + ".zip.part")
$expanded = Join-Path $temporary "expanded"
$staged = Join-Path $runtimeRoot "chrome.new"
$previous = Join-Path $runtimeRoot "chrome.old"
New-Item -ItemType Directory -Path $temporary, $expanded -Force | Out-Null

try {
    Write-Host "Downloading AutoSurf browser runtime $($manifest.version)..."
    Save-RemoteFile `
        -Uri ([string]$manifest.archive_url) `
        -Path $archive `
        -ExpectedSize ([long]$manifest.archive_size)
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
        Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue
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
    Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue
    Write-Host "Installed AutoSurf browser runtime $($manifest.version)."
} finally {
    Remove-Item -LiteralPath $temporary -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $staged -Recurse -Force -ErrorAction SilentlyContinue
}
