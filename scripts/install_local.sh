#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ "$(uname -s)" != Darwin && "$(uname -s)" != Linux ]]; then
  echo 'Fast-KV local installer currently supports macOS and Linux only.' >&2
  exit 1
fi
for tool in cmake python3 c++; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "Missing $tool. Install CMake, Python 3, and a C++20 compiler, then retry." >&2
    exit 1
  fi
done

if [[ "${FASTKV_SKIP_BUILD:-0}" != 1 ]]; then
  echo 'Building Fast-KV...'
  cmake -S . -B build-debug -DCMAKE_BUILD_TYPE=Release
  cmake --build build-debug -j "${FASTKV_BUILD_JOBS:-4}"
fi

PREFIX="${FASTKV_INSTALL_PREFIX:-$HOME/.local/bin}"
mkdir -p "$PREFIX"
TARGET="$PREFIX/fastkv"
SOURCE="$ROOT/bin/fastkv"
if [[ -e "$TARGET" || -L "$TARGET" ]]; then
  if [[ "$(readlink "$TARGET" 2>/dev/null || true)" != "$SOURCE" ]]; then
    echo "Refusing to overwrite existing $TARGET. Remove or rename it manually if intended." >&2
    exit 1
  fi
else
  ln -s "$SOURCE" "$TARGET"
fi
printf '\nFast-KV installed!\n'
printf 'Try now: %s start\n' "$TARGET"
printf 'Other commands: %s status | stop | dashboard | logs | shutdown\n' "$TARGET"
if [[ ":$PATH:" != *":$PREFIX:"* ]]; then
  printf '\nTo use just `fastkv` in zsh, add this line to ~/.zprofile and open a new Terminal:\n'
  printf '  export PATH="%s:$PATH"\n' "$PREFIX"
fi
