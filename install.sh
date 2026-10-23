#!/bin/sh
# One-line installer (macOS / Linux):
#   curl -fsSL https://raw.githubusercontent.com/tejgokani/bufferlab/main/install.sh | sh
# Clones BufferLab to $BUFFERLAB_DIR (default ~/bufferlab), links a global `bufferlab` command, and
# builds the environment inside the clone. The command re-checks Python and the environment on every run.
set -e
REPO_URL="${BUFFERLAB_REPO:-https://github.com/tejgokani/bufferlab.git}"
DEST="${BUFFERLAB_DIR:-$HOME/bufferlab}"
BIN="${BUFFERLAB_BIN:-$HOME/.local/bin}"
say() { printf '%s\n' "$*"; }

command -v git >/dev/null 2>&1 || { say "git is required (macOS: xcode-select --install; Debian/Ubuntu: sudo apt install git)"; exit 1; }
if [ -d "$DEST/.git" ]; then
  say "Updating $DEST"; git -C "$DEST" pull --ff-only
elif [ -e "$DEST" ]; then
  say "$DEST exists and is not a BufferLab clone; set BUFFERLAB_DIR to another folder."; exit 1
else
  git clone --depth 1 "$REPO_URL" "$DEST"
fi
mkdir -p "$BIN"
ln -sf "$DEST/bin/bufferlab" "$BIN/bufferlab"
"$DEST/bin/bufferlab" --version     # creates .venv and installs on first use
case ":$PATH:" in
  *":$BIN:"*) ;;
  *) say ""; say "Add $BIN to your PATH, e.g.:  echo 'export PATH=\"$BIN:\$PATH\"' >> ~/.profile" ;;
esac
say ""; say "Done. Start it with:  bufferlab"
