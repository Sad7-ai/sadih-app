#!/usr/bin/env bash
# The parts of the team's bootstrap.sh that need no secret (the model code was copied in with git archive, so no
# GH_TOKEN): pinned MaDiS + SOKE (public), the env.lock venv, the service's own packages, MaDiS's Qwen package.
# Pins copied from avatar/exp4_generator/runpod/bootstrap.sh (sprint2-length-pilot). Log: /workspace/prep.log
# Run on the pod: VENV=/root/envs/madis bash prep.sh   (~35 s with a warm uv cache, ~2 min cold).
# Keep VENV on the container disk: uv's managed Python lives there too, so a venv on /workspace breaks on restart.
set -euo pipefail
REPO=/workspace/kitchen
APP=/workspace/kitchen-app
VENV=${VENV:-/root/envs/madis}
export UV_CACHE_DIR=/root/.cache/uv
t0=$(date +%s)
say() { echo "[$(( $(date +%s) - t0 ))s] $*"; }

pin() {  # url dir commit
  [ -d "$2/.git" ] || git clone --quiet "$1" "$2"
  git -C "$2" fetch --quiet origin
  git -C "$2" checkout --quiet "$3"
}
say "MaDiS + SOKE at the pinned commits"
pin https://github.com/2000ZRL/madis.git "$REPO/third_party/madis" 071828ea1b94530dc7ff0a6c009c0a7c6d1f0784
pin https://github.com/2000ZRL/SOKE.git "$REPO/third_party/SOKE" 5cbc55d84b5a7cbf05a9cf020c468052e8d94d00

say "Python 3.10.18 venv from env.lock (hash-checked)"
[ -x "$VENV/bin/python" ] || uv venv --quiet --python 3.10.18 "$VENV"
uv pip sync --quiet --python "$VENV/bin/python" --require-hashes "$REPO/avatar/exp4_generator/runpod/env.lock"
say "env.lock installed: $("$VENV/bin/python" -c 'import torch; print("torch", torch.__version__, "cuda", torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else "")')"

say "the service's own packages"
uv pip install --quiet --python "$VENV/bin/python" -r "$APP/serve/requirements.txt"

say "MaDiS's Qwen package (as notebooks/exp4_demo.ipynb)"
MADIS="$REPO/third_party/madis"
if [ ! -f "$MADIS/deps/Qwen3-0.6B-Base-en-zh-de/map_ids.pkl" ]; then
  z="$("$VENV/bin/python" -c "from huggingface_hub import hf_hub_download as d; print(d('2000zrl/MaDiS', 'Qwen3-0.6B-Base-en-zh-de.zip', revision='ceaed59c964820f2c13401a0870b2988686956ad'))")"
  mkdir -p "$MADIS/deps" && unzip -q -o "$z" -d "$MADIS/deps"
fi
ls "$MADIS/deps/Qwen3-0.6B-Base-en-zh-de" | head -5
say "PREP DONE"
