#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

# ── 1. Create virtual environment if it doesn't exist ────────────────────────
if [ ! -d "$VENV_DIR" ]; then
    # echo "[upload_to_r2.sh] Creating virtual environment at $VENV_DIR ..."
    python3 -m venv "$VENV_DIR"
fi

# ── 2. Activate ───────────────────────────────────────────────────────────────
source "$VENV_DIR/bin/activate"

# ── 3. Install / update requirements ─────────────────────────────────────────
pip install -q --upgrade pip
pip install -q -r "$SCRIPT_DIR/requirements.txt"

# ── 4. Run upload_to_r2.py with all arguments passed to this script ───────────
python3 "$SCRIPT_DIR/upload_to_r2.py" "$@"
