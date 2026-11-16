#!/usr/bin/env bash
# After the Drive works: the team's sync_in.sh (tokens + motion packs, frozen tokenizer, SMPL-X), the run's own files,
# then the model service: generator, recorded sentences first (SADIH_RECORDED). Data and code on /workspace, so a pod
# restart keeps them (rerun prep.sh first: the venv is on the container disk). Needs SADIH_MODEL_SECRET in the environment (sent over ssh stdin, never stored on the pod).
# Log: /workspace/serve.log
set -euo pipefail
set +x
: "${SADIH_MODEL_SECRET:?pass SADIH_MODEL_SECRET}"
REPO=/workspace/kitchen
APP=/workspace/kitchen-app
VENV=${VENV:-/root/envs/madis}
DATA=/workspace/data
RUN_ID="${SADIH_RUN_ID:-madis_a_v4_joint_r2}"
GEN="$REPO/avatar/exp4_generator"
DRIVE=gdrive:sadih
t0=$(date +%s)
say() { echo "[$(( $(date +%s) - t0 ))s] $*"; }

say "rclone config from the team secret (the main process has it; ssh sessions do not)"
V="$(tr '\0' '\n' < /proc/1/environ | grep '^RCLONE_CONF_B64=' | cut -d= -f2-)"
case "$V" in ""|*RUNPOD_SECRET_*) echo "RCLONE_CONF_B64 is missing or unresolved"; exit 2 ;; esac
mkdir -p "$HOME/.config/rclone"
( umask 077; printf '%s' "$V" | base64 -d > "$HOME/.config/rclone/rclone.conf" )
unset V
rclone lsd "$DRIVE" --max-depth 1 > /dev/null || { echo "Drive refused the login (see the line above)"; exit 3; }
say "Drive OK"

say "the team's sync_in.sh: packs, frozen tokenizer, SMPL-X"
DATA="$DATA" PACKS=/workspace/packs REPO="$REPO" PYTHON="$VENV/bin/python" bash "$GEN/runpod/sync_in.sh"

say "the run's own files ($RUN_ID)"
RUN="$DATA/exp4_generator/runs/$RUN_ID"
mkdir -p "$RUN/checkpoints"
for f in checkpoints/best.ckpt probe.npz length_model.json known_vocab.json; do
  [ -s "$RUN/$f" ] || rclone copyto "$DRIVE/exp4_generator/runs/$RUN_ID/$f" "$RUN/$f" --stats 60s
done
ls -la "$RUN" "$RUN/checkpoints"

MADIS="$REPO/third_party/madis"
smplx="$(find "$DATA/deps/smpl_models" -name 'SMPLX_NEUTRAL.npz' | head -1)"
[ -n "$smplx" ] || { echo "no SMPLX_NEUTRAL.npz under $DATA/deps/smpl_models"; exit 4; }
mkdir -p "$MADIS/deps/smpl_models/smplx"
ln -sf "$smplx" "$MADIS/deps/smpl_models/smplx/SMPLX_NEUTRAL.npz"
RECORDED="$(find "$DATA/motion" -mindepth 1 -maxdepth 1 -type d | head -1)"
say "recorded sentences from: ${RECORDED:-none}"

say "model service on :8100 (https://${RUNPOD_POD_ID:-<pod id>}-8100.proxy.runpod.net)"
cd "$APP/serve"
exec env SADIH_MODEL_CODE="$REPO" SADIH_DATA="$DATA" SADIH_RUN_ID="$RUN_ID" SADIH_SMPLX="$smplx" \
  SADIH_RECORDED="$RECORDED" SADIH_WORK=/workspace/serve_work SADIH_SIGNER=02 PYTHONUNBUFFERED=1 \
  "$VENV/bin/python" model_server.py --host 0.0.0.0 --port 8100
