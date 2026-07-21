#!/bin/bash
# Build Continuity Bridge voor Intel Mac en upload naar GitHub release

set -e

VERSION=$(grep "^VERSION" ale_merger_gui.py | grep -o '[0-9][0-9.]*' | head -1)
TAG="v${VERSION}"

echo "Building Continuity Bridge v${VERSION} for Intel..."

# Build
pyinstaller -y --clean continuity_bridge.spec

# Guard: weiger een build die terugvalt op Apple's verouderde systeem-Tcl/Tk 8.5.
# Die crasht gegarandeerd bij opstarten (TkpInit/Tcl_Panic). Als dit triggert, bouw
# opnieuw met een Homebrew python3 die 'python-tk' heeft (zie build-intel.sh commentaar
# / BUILD.md): brew install python-tk@<versie> && which python3 checken.
TKINTER_SO=$(find "dist/Continuity Bridge.app" -iname "_tkinter*.so" | head -1)
if [ -z "$TKINTER_SO" ]; then
  echo "FOUT: geen _tkinter*.so gevonden in de gebouwde app." >&2
  exit 1
fi
if otool -L "$TKINTER_SO" | grep -q "/System/Library/Frameworks/Tcl\|/System/Library/Frameworks/Tk"; then
  echo "FOUT: de gebouwde app linkt naar het verouderde systeem-Tcl/Tk (8.5) i.p.v. een gebundelde versie." >&2
  echo "  Dit crasht gegarandeerd bij opstarten. Installeer een Homebrew python3 met tkinter, bv.:" >&2
  echo "    brew install python-tk@3.11 && brew link --overwrite python-tk@3.11" >&2
  echo "  Controleer 'which python3'/'which pyinstaller' en bouw opnieuw." >&2
  exit 1
fi

# DMG
hdiutil create \
  -volname "Continuity Bridge" \
  -srcfolder "dist/Continuity Bridge.app" \
  -ov -format UDZO \
  -o "/tmp/ContinuityBridge-Intel-${VERSION}.dmg"

echo "DMG created: /tmp/ContinuityBridge-Intel-${VERSION}.dmg"

# Upload
gh release view "$TAG" || gh release create "$TAG" \
  --title "Continuity Bridge $TAG" \
  --notes "Release $TAG" \
  --draft

gh release upload "$TAG" "/tmp/ContinuityBridge-Intel-${VERSION}.dmg" --clobber

echo "✓ Uploaded to GitHub draft release $TAG"
echo "  Publiceer met: gh release edit $TAG --draft=false"
