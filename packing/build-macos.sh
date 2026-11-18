#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != Darwin ]]; then
    echo "This script must run on macOS." >&2
    exit 1
fi

cd "$(dirname "$0")"
export PLAYWRIGHT_BROWSERS_PATH="$PWD/build/macos-browsers-$(uname -m)"
python3 -m pip install -r ../requirements.txt pyinstaller pillow
python3 -m playwright install chromium --no-shell

python3 -m PyInstaller --noconfirm --onedir --windowed --name SmallCareer \
    --osx-bundle-identifier com.smallwhitestudio.smallcareer --icon icon.ico \
    --specpath build --workpath build --distpath dist --paths .. \
    --collect-all playwright ../main.py

app="$PWD/dist/SmallCareer.app"
# Copy the already signed Chromium bundle intact, preserving symlinks and permissions.
ditto "$PLAYWRIGHT_BROWSERS_PATH" "$app/Contents/Resources/browsers"
codesign --force --sign - "$app"
codesign --verify --deep --strict "$app"

PLAYWRIGHT_BROWSERS_PATH="$app/Contents/Resources/browsers" python3 -c \
    'from playwright.sync_api import sync_playwright
with sync_playwright() as runtime:
    browser = runtime.chromium.launch(channel="chromium")
    browser.close()'

arch="$(lipo -archs "$app/Contents/MacOS/SmallCareer")"
ditto -c -k --sequesterRsrc --keepParent "$app" "dist/SmallCareer-macOS-$arch.zip"
