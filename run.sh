#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
TWELF_SERVER="${TWELF_SERVER:-twelf-server}"
exec python3 -m twelf_slicer.cli \
  corpus/list.elf append_cons \
  --server "$TWELF_SERVER" \
  --mode exact \
  "$@"
