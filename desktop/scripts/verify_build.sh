#!/usr/bin/env bash
# desktop/scripts/verify_build.sh
set -euo pipefail
cd "$(dirname "$0")/.."

# electron-builder's extraResources only *warns* (does not exit non-zero) when
# its `from` source is missing, so a stale/unbuilt frontend/dist-electron would
# otherwise silently produce a .exe with an empty bundled dashboard. Guard
# explicitly so this script fails loudly in that case instead.
#
# dist-electron (not dist/) — built via `npm run build:electron`, which sets
# base: "./" so asset paths resolve under Electron's file:// loading. The
# plain `dist/` (base: "/", built via `npm run build`) is for the hosted web
# deployment and renders a BLANK window under file://.
if [ ! -f "../frontend/dist-electron/index.html" ]; then
  echo "FAIL: ../frontend/dist-electron/index.html not found — run (cd frontend && npm run build:electron) first" >&2
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
