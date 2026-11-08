#!/bin/sh
# Makes romm-deck.zip, for Decky's "Install plugin from URL" (a release's download link) and "Install plugin
# from ZIP". Decky wants everything in one folder with plugin.json directly inside it; check_package.py checks
# the finished zip the way Decky reads it.
set -e
rm -rf build romm-deck.zip
mkdir -p build/romm-deck
cp -r plugin.json package.json main.py LICENSE README.md dist bin py_modules build/romm-deck/
find build -name '__pycache__' -prune -exec rm -rf {} +
# Python's own zip tool, so the build works on any runner with Python (no `zip` to install)
(cd build && python3 -m zipfile -c ../romm-deck.zip romm-deck)
python3 scripts/check_package.py romm-deck.zip
echo "made romm-deck.zip"
