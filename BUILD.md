# Building Continuity Bridge

## Local Builds (Recommended)

Each platform build is done locally due to GitHub Actions runner limitations.

### Silicon Mac
On your Silicon Mac:
```bash
./build-silicon.sh
```
Produces: `ContinuityBridge-Silicon-X.Y.Z.dmg`

### Intel Mac
On an Intel Mac:
```bash
./build-intel.sh
```
Produces: `ContinuityBridge-Intel-X.Y.Z.dmg`

### Windows
Requires a Windows machine with Python 3.13+:
```bash
pip install pyinstaller pdfplumber pillow certifi
pyinstaller -y --clean continuity_bridge_win.spec
# Creates: dist/ContinuityBridge-X.Y.Z.exe
# Then upload to GitHub release v1.3.Y manually
```

## Release Workflow

1. Update version in `ale_merger_gui.py` and `continuity_bridge.spec`
2. Commit & tag: `git tag vX.Y.Z && git push --tags`
3. Build Silicon on Silicon Mac: `./build-silicon.sh`
4. Build Intel on Intel Mac: `./build-intel.sh`
5. Build Windows on Windows machine & upload manually
6. Assets appear on GitHub release page with versioned filenames

All downloads automatically have version numbers:
- `ContinuityBridge-Silicon-1.3.4.dmg`
- `ContinuityBridge-Intel-1.3.4.dmg`
- `ContinuityBridge-1.3.4.exe`
