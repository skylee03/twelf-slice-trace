#!/usr/bin/env bash
# Clone and build Twelf with the typing-trace patch.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${1:-$ROOT/.twelf-src}"
TWELF_COMMIT="4224d07cf7a32f69321fd0878043e84539163ee0"
REPO="https://github.com/standardml/twelf.git"

if ! command -v sml >/dev/null 2>&1; then
  echo "sml not found. Install SML/NJ first, e.g. 'brew install smlnj'." >&2
  exit 2
fi

if [ ! -d "$DEST/.git" ]; then
  git clone "$REPO" "$DEST"
fi

git -C "$DEST" checkout "$TWELF_COMMIT"
git -C "$DEST" apply "$ROOT/patches/twelf-slice-trace.patch"
make -C "$DEST" smlnj
echo
echo "Built: $DEST/bin/twelf-server"
echo "export TWELF_SERVER=\"$DEST/bin/twelf-server\""
