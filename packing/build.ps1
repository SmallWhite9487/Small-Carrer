$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$ProjectRoot = Split-Path $PSScriptRoot -Parent
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $PSScriptRoot "browsers"
python -m pip install -r (Join-Path $ProjectRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed" }
python -m pip install pyinstaller
if ($LASTEXITCODE -ne 0) { throw "PyInstaller installation failed" }
python -m playwright install chromium
if ($LASTEXITCODE -ne 0) { throw "Browser installation failed" }
python -m PyInstaller --noconfirm --workpath (Join-Path $PSScriptRoot "build") --distpath (Join-Path $PSScriptRoot "dist") (Join-Path $PSScriptRoot "SmallCareer.spec")
if ($LASTEXITCODE -ne 0) { throw "Application build failed" }
Write-Host "Ready: packing\dist\SmallCareer.exe. Distribute this single EXE."
