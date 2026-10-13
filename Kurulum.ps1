$ErrorActionPreference = 'Stop'
$sourceRoot = $PSScriptRoot
$installRoot = Join-Path $env:LOCALAPPDATA 'ClipAtolye'
$desktop = Join-Path $env:USERPROFILE 'Desktop'
New-Item -ItemType Directory -Path $desktop -Force | Out-Null
$shortcutPath = Join-Path $desktop 'ClipAtölye.lnk'

Write-Host 'ClipAtölye kuruluyor...' -ForegroundColor Cyan
New-Item -ItemType Directory -Path $installRoot -Force | Out-Null

$appFiles = @('server.py','index.html','extra.js','start.ps1','Başlat.ps1','Başlat.bat','install_ffmpeg.py','README.md')
foreach ($name in $appFiles) {
  $src = Join-Path $sourceRoot $name
  if (Test-Path -LiteralPath $src) { Copy-Item -LiteralPath $src -Destination $installRoot -Force }
}

$sourceWork = Join-Path $sourceRoot 'work'
$targetWork = Join-Path $installRoot 'work'
New-Item -ItemType Directory -Path $targetWork -Force | Out-Null
foreach ($name in @('runtime-packages-v4','python-packages')) {
  $src = Join-Path $sourceWork $name
  if (Test-Path -LiteralPath $src) {
    $dst = Join-Path $targetWork $name
    New-Item -ItemType Directory -Path $dst -Force | Out-Null
    & robocopy $src $dst /E /COPY:DAT /DCOPY:DAT /R:1 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "Kütüphaneler kopyalanamadı: $name" }
  }
}

# Retain this computer's existing projects and exported clips on reinstall.
$projectsSource = Join-Path $sourceWork 'projects.json'
$projectsTarget = Join-Path $targetWork 'projects.json'
if ((Test-Path -LiteralPath $projectsSource) -and -not (Test-Path -LiteralPath $projectsTarget)) {
  Copy-Item -LiteralPath $projectsSource -Destination $projectsTarget
}
$outputsSource = Join-Path $sourceRoot 'outputs'
$outputsTarget = Join-Path $installRoot 'outputs'
if (Test-Path -LiteralPath $outputsSource) {
  New-Item -ItemType Directory -Path $outputsTarget -Force | Out-Null
  & robocopy $outputsSource $outputsTarget /E /COPY:DAT /DCOPY:DAT /R:1 /W:1 /XO /NFL /NDL /NJH /NJS /NP | Out-Null
  if ($LASTEXITCODE -ge 8) { throw 'Dışa aktarılmış klipler kopyalanamadı.' }
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$shortcut.Arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $installRoot 'Başlat.ps1') + '"'
$shortcut.WorkingDirectory = $installRoot
$shortcut.Description = 'ClipAtölye yerel video stüdyosunu başlat'
$shortcut.IconLocation = (Join-Path $env:SystemRoot 'System32\shell32.dll') + ',15'
$shortcut.Save()

Write-Host "Kurulum tamamlandı: $installRoot" -ForegroundColor Green
Write-Host "Masaüstü kısayolu hazır: $shortcutPath" -ForegroundColor Green
Start-Process -FilePath $shortcut.TargetPath -ArgumentList $shortcut.Arguments -WorkingDirectory $installRoot
