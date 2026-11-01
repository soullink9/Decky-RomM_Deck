#!/bin/sh
# Makes romm-deck.zip for Decky's "Install plugin from ZIP".
set -e
rm -rf build romm-deck.zip
mkdir -p build/romm-deck
cp -r plugin.json package.json main.py LICENSE README.md dist bin py_modules build/romm-deck/
find build -name '__pycache__' -prune -exec rm -rf {} +
(cd build && zip -qr ../romm-deck.zip romm-deck)
echo "made romm-deck.zip"
