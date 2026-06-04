#!/bin/bash
# Build Continuity Bridge voor Silicon Mac en upload naar GitHub release

set -e

VERSION=$(grep "^VERSION" ale_merger_gui.py | grep -o '[0-9][0-9.]*' | head -1)
TAG="v${VERSION}"

echo "Building Continuity Bridge v${VERSION} for Silicon..."

# Build
pyinstaller -y --clean continuity_bridge.spec

# DMG
hdiutil create \
  -volname "Continuity Bridge" \
  -srcfolder "dist/Continuity Bridge.app" \
  -ov -format UDZO \
  -o "/tmp/ContinuityBridge-Silicon-${VERSION}.dmg"

echo "DMG created: /tmp/ContinuityBridge-Silicon-${VERSION}.dmg"

# Upload
gh release view "$TAG" || gh release create "$TAG" \
  --title "Continuity Bridge $TAG" \
  --notes "Release $TAG"

gh release upload "$TAG" "/tmp/ContinuityBridge-Silicon-${VERSION}.dmg" --clobber

echo "✓ Uploaded to GitHub release $TAG"
