#!/usr/bin/env bash
# desktop/scripts/verify_build.sh
set -euo pipefail
cd "$(dirname "$0")/.."

# electron-builder's extraResources only *warns* (does not exit non-zero) when
# its `from` source is missing, so a stale/unbuilt frontend/dist would
# otherwise silently produce a .exe with an empty bundled dashboard. Guard
# explicitly so this script fails loudly in that case instead.
if [ ! -f "../frontend/dist/index.html" ]; then
  echo "FAIL: ../frontend/dist/index.html not found — run (cd frontend && npm run build) first" >&2
  exit 1
fi

npm run dist

INSTALLER=$(find dist_installer -name "FullPOS-Setup-*.exe" | head -n1)
if [ -z "$INSTALLER" ]; then
  echo "FAIL: no .exe installer produced" >&2
  exit 1
fi

BUNDLED=$(find dist_installer -path "*/resources/frontend/dist/index.html" | head -n1)
if [ -z "$BUNDLED" ]; then
  echo "FAIL: installer produced but frontend/dist was not bundled into resources/frontend/dist" >&2
  exit 1
fi

echo "PASS: installer produced at $INSTALLER (frontend bundled at $BUNDLED)"
