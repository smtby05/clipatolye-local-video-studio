$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false
$pythonCandidates = @(
  (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"),
  (Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe")
)
$python = $null
foreach ($candidate in $pythonCandidates) {
  if (Test-Path -LiteralPath $candidate) {
    $version = & $candidate --version 2>&1
    if ($version -match "Python 3\.12\.") { $python = $candidate; break }
  }
}
if (-not $python) {
  $cmd = Get-Command python.exe -ErrorAction SilentlyContinue
  if ($cmd -and $cmd.Source -notlike "*WindowsApps*") {
    $version = & $cmd.Source --version 2>&1
    if ($version -match "Python 3\.12\.") { $python = $cmd.Source }
  }
}
if (-not $python) {
  $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
  if ($winget) {
    Write-Host "Python 3.12 kuruluyor (kullanıcı hesabına)..." -ForegroundColor Cyan
    & $winget.Source install --id Python.Python.3.12 --exact --scope user --silent --accept-package-agreements --accept-source-agreements
    $candidate = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
    if (Test-Path -LiteralPath $candidate) { $python = $candidate }
  }
}
if (-not $python) {
  Write-Host "Python 3.12 otomatik kurulamadı. Windows Paket Yöneticisi (winget) kurup tekrar deneyin." -ForegroundColor Yellow
  Read-Host "Kapatmak için Enter"
  exit 1
}
Set-Location -LiteralPath $PSScriptRoot
$localPackages = Join-Path $PSScriptRoot "work\runtime-packages-v5"
New-Item -ItemType Directory -Path $localPackages -Force | Out-Null
$env:CLIP_LOCAL_PACKAGES = $localPackages
$env:PYTHONPATH = "$localPackages;$PSScriptRoot\work\python-packages"
$env:LOCALAPPDATA = Join-Path $PSScriptRoot "work\localappdata"
$env:APPDATA = Join-Path $PSScriptRoot "work\appdata"
# Reuse an already-running updated server before running package checks. This
# avoids trying to replace Python files that the server has loaded.
$port = 8765
try {
  $running = Invoke-RestMethod "http://127.0.0.1:8765/api/status" -TimeoutSec 2
  if ($running.version -eq 22) { Start-Process "http://127.0.0.1:8765"; exit 0 }
  $port = 8766
} catch { }
while ($port -le 8785) {
  try {
    $running = Invoke-RestMethod "http://127.0.0.1:$port/api/status" -TimeoutSec 1
    if ($running.version -eq 22) { Start-Process "http://127.0.0.1:$port"; exit 0 }
    $port++
  } catch { break }
}
# Fill missing Python packages on first launch. They remain inside this app.
$env:PYTHONPATH = "$localPackages;$PSScriptRoot\work\python-packages"
$whisperProbe = & $python -c "from faster_whisper import WhisperModel" 2>&1
if ($LASTEXITCODE -ne 0) {
  Write-Host "Yerel altyazı kütüphaneleri kuruluyor (ilk açılış)..." -ForegroundColor Cyan
  & $python -m pip install --disable-pip-version-check --no-warn-script-location --trusted-host pypi.org --trusted-host files.pythonhosted.org --target $localPackages "faster-whisper==1.2.1" "setuptools<81"
  if ($LASTEXITCODE -ne 0) { Write-Host $whisperProbe; throw "Altyazı kütüphaneleri kurulamadı." }
}
$ytProbe = & $python -c "import server; raise SystemExit(0 if server.has_yt_dlp() else 1)" 2>&1
if ($LASTEXITCODE -ne 0) {
  Write-Host "Video indirme kütüphanesi kuruluyor (ilk açılış)..." -ForegroundColor Cyan
  & $python -m pip install --disable-pip-version-check --no-warn-script-location --trusted-host pypi.org --trusted-host files.pythonhosted.org --target $localPackages yt-dlp
  if ($LASTEXITCODE -ne 0) { Write-Host $ytProbe; throw "yt-dlp kurulamadı." }
}
# Existing packages are used as-is; never reinstall on each launch.
$ffmpegBin = Join-Path $PSScriptRoot "work\tools-v2\ffmpeg\bin"
$legacyFfmpegBin = Join-Path $PSScriptRoot "work\tools\ffmpeg\bin"
$env:PATH = "$ffmpegBin;$legacyFfmpegBin;$localPackages;$env:PATH"
$ffmpegExe = Join-Path $ffmpegBin "ffmpeg.exe"
$ffprobeExe = Join-Path $ffmpegBin "ffprobe.exe"
$legacyFfmpegExe = Join-Path $legacyFfmpegBin "ffmpeg.exe"
$legacyFfprobeExe = Join-Path $legacyFfmpegBin "ffprobe.exe"
$ffmpegOnPath = Get-Command ffmpeg.exe -ErrorAction SilentlyContinue
$ffprobeOnPath = Get-Command ffprobe.exe -ErrorAction SilentlyContinue
$hasFfmpegPair = $false
if ($ffmpegOnPath -and $ffprobeOnPath) { $hasFfmpegPair = $true }
if ([System.IO.File]::Exists($ffmpegExe) -and [System.IO.File]::Exists($ffprobeExe)) { $hasFfmpegPair = $true }
if ([System.IO.File]::Exists($legacyFfmpegExe) -and [System.IO.File]::Exists($legacyFfprobeExe)) { $hasFfmpegPair = $true }
if (-not $hasFfmpegPair) {
  Write-Host "FFmpeg ve FFprobe kuruluyor. İlk indirme yaklaşık 194 MB..." -ForegroundColor Cyan
  $installer = Join-Path $PSScriptRoot "install_ffmpeg.py"
  $installOut = Join-Path $PSScriptRoot "work\ffmpeg-install.stdout.log"
  $installErr = Join-Path $PSScriptRoot "work\ffmpeg-install.stderr.log"
  $proc = Start-Process -FilePath $python -ArgumentList @("-W", "ignore", "`"$installer`"") -WorkingDirectory $PSScriptRoot -Wait -PassThru -NoNewWindow -RedirectStandardOutput $installOut -RedirectStandardError $installErr
  if ($proc.ExitCode -ne 0) {
    Write-Host "FFmpeg kurulumu tamamlanamadı. Ayrıntı:" -ForegroundColor Red
    if (Test-Path -LiteralPath $installErr) { Get-Content -LiteralPath $installErr -Tail 12 | ForEach-Object { Write-Host $_ -ForegroundColor DarkYellow } }
    Read-Host "Kapatmak için Enter"
    exit 1
  }
}
$env:PORT = "$port"
Start-Process "http://127.0.0.1:$port"
& $python (Join-Path $PSScriptRoot "server.py")
