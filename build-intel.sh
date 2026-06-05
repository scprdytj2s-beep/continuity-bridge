#!/bin/bash
# Build Continuity Bridge voor Intel Mac en upload naar GitHub release

set -e

VERSION=$(grep "^VERSION" ale_merger_gui.py | grep -o '[0-9][0-9.]*' | head -1)
TAG="v${VERSION}"

echo "Building Continuity Bridge v${VERSION} for Intel..."

# Build
pyinstaller -y --clean continuity_bridge.spec

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
