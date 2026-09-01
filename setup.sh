#!/usr/bin/env bash
# One-shot setup for the Organizational Reasoning Engine.
#
#   bash setup.sh          # venv + deps + dataset + vector/graph stores + .env
#   GPU=1 bash setup.sh    # on Linux, install the CUDA PyTorch build instead of CPU-only
#
# Safe to re-run: it reuses an existing .venv and never overwrites an existing .env.
set -euo pipefail

cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
VENV_DIR=".venv"

echo "==> [1/5] Creating virtualenv ($VENV_DIR)"
if [ ! -d "$VENV_DIR" ]; then
  "$PYTHON" -m venv "$VENV_DIR"
fi
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
python -m pip install --upgrade pip >/dev/null

echo "==> [2/5] Installing dependencies"
# On Linux, default to the CPU-only PyTorch wheel so we don't pull ~2-3 GB of CUDA
# packages. Set GPU=1 to use the default (CUDA) build. macOS wheels are already CPU/MPS.
if [ "$(uname -s)" = "Linux" ] && [ "${GPU:-0}" != "1" ]; then
  echo "    (Linux: installing CPU-only torch; run 'GPU=1 bash setup.sh' for CUDA)"
  pip install torch --index-url https://download.pytorch.org/whl/cpu
fi
pip install -r requirements.txt

echo "==> [3/5] Building the synthetic dataset"
python data/build_dataset.py

echo "==> [4/5] Building the vector store and knowledge graph"
python -m ingest.build_vectors
python -m ingest.build_graph

echo "==> [5/5] Preparing .env"
if [ ! -f .env ]; then
  cp .env.example .env
  echo "    Created .env from .env.example — paste your free GROQ_API_KEY into it."
else
  echo "    .env already exists — left untouched."
fi

cat <<'DONE'

Setup complete.

Next:
  source .venv/bin/activate
  # edit .env and paste your free GROQ_API_KEY (https://console.groq.com/keys)
  # — or set LLM_PROVIDER=stub to run fully offline with zero setup —
  python run_all.py            # benchmark: V1 -> learn -> V2 across the scenarios
  streamlit run app.py         # open the dashboard
DONE
