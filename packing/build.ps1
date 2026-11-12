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
python -m PyInstaller --noconfirm --onefile --windowed --name SmallCareer --workpath (Join-Path $PSScriptRoot "build") --distpath (Join-Path $PSScriptRoot "dist") --specpath $PSScriptRoot --paths $ProjectRoot --collect-all playwright --add-data "$env:PLAYWRIGHT_BROWSERS_PATH;browsers" (Join-Path $ProjectRoot "main.py")
if ($LASTEXITCODE -ne 0) { throw "Application build failed" }
Write-Host "Ready: packing\dist\SmallCareer.exe. Distribute this single EXE."
