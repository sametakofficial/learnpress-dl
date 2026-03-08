param(
    [string]$YtDlpPath = "",
    [string]$FfmpegPath = "",
    [string]$FfprobePath = "",
    [string]$PythonExe = "python"
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$DistRoot = Join-Path $RepoRoot "dist"
$PyInstallerDist = Join-Path $DistRoot "learnpress-dl"
$ReleaseRoot = Join-Path $DistRoot "learnpress-dl-windows"

Push-Location $RepoRoot
try {
    & $PythonExe -m pip install -r requirements-build.txt
    & $PythonExe -m PyInstaller --noconfirm packaging/windows/learnpress-dl.spec

    if (Test-Path $ReleaseRoot) {
        Remove-Item $ReleaseRoot -Recurse -Force
    }
    New-Item -ItemType Directory -Path $ReleaseRoot | Out-Null

    Copy-Item (Join-Path $PyInstallerDist "learnpress-dl.exe") $ReleaseRoot

    if (-not $YtDlpPath) { $YtDlpPath = Join-Path $RepoRoot "yt-dlp.exe" }
    if (-not $FfmpegPath) { $FfmpegPath = Join-Path $RepoRoot "ffmpeg.exe" }
    if (-not $FfprobePath) { $FfprobePath = Join-Path $RepoRoot "ffprobe.exe" }

    foreach ($ToolPath in @($YtDlpPath, $FfmpegPath, $FfprobePath)) {
        if (-not (Test-Path $ToolPath)) {
            throw "Required portable binary not found: $ToolPath"
        }
        Copy-Item $ToolPath $ReleaseRoot
    }

    foreach ($ExtraPath in @(".env.example", "README.md", "packaging/windows/README-Windows.md", "packaging/windows/runtime/run.bat", "packaging/windows/runtime/retry-failed.bat")) {
        $SourcePath = Join-Path $RepoRoot $ExtraPath
        if (Test-Path $SourcePath) {
            Copy-Item $SourcePath $ReleaseRoot
        }
    }

    Write-Host "Portable Windows release ready at: $ReleaseRoot"
}
finally {
    Pop-Location
}
