#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

# ── 1. Create virtual environment if it doesn't exist ────────────────────────
if [ ! -d "$VENV_DIR" ]; then
    echo "[run.sh] Creating virtual environment at $VENV_DIR ..."
    python3 -m venv "$VENV_DIR"
fi

# ── 2. Activate ───────────────────────────────────────────────────────────────
source "$VENV_DIR/bin/activate"

# ── 3. Install / update requirements ─────────────────────────────────────────
echo "[run.sh] Installing requirements ..."
pip install -q --upgrade pip
pip install -q -r "$SCRIPT_DIR/requirements.txt"

# ── 4. Run image_creator.py with all arguments passed to this script ──────────
echo "[run.sh] Running image_creator.py ..."
python3 "$SCRIPT_DIR/image_creator.py" "$@"
