# The model service on a RunPod pod

Proven on 2026-11-08 (pod `knpn0w4j1hfkl7`, L4, team Sadih): `madis_a_v4_joint_r2` + frozen `sadih_tok_v1` + the
heuristic length predictor, models untouched. Ready in ~2 min after the data is synced. A new clause generates in
~0.5 s; a recorded sentence returns in ~0.2 s (round trip from the app server ~0.6 s).

## 1. The pod (RunPod console, team **Sadih**)
- GPU: L4 (any 24 GB card), Secure Cloud, On-Demand. Template: the official **Runpod Pytorch 2.x** (not the cluster one).
- Container disk 50 GB, volume 60 GB at `/workspace`. Expose HTTP port **8100** and TCP port **22**.
- Environment variable `RCLONE_CONF_B64` = `{{ RUNPOD_SECRET_RCLONE_CONF_B64 }}` **with the spaces inside the braces**.
  Without them RunPod passes the literal text and nothing resolves.
- Your SSH public key in Settings → SSH Public Keys (or append it to `~/.ssh/authorized_keys` from the web terminal;
  that copy is lost on every stop or restart).

## 2. The code (no GitHub token needed on the pod)
```
git archive origin/sprint2-length-pilot | ssh -p <port> root@<ip> "mkdir -p /workspace/kitchen && tar -x -C /workspace/kitchen"
git archive model-in-app               | ssh -p <port> root@<ip> "mkdir -p /workspace/kitchen-app && tar -x -C /workspace/kitchen-app"
```

## 3. Install, sync, serve
```
ssh -p <port> root@<ip> "VENV=/root/envs/madis bash /workspace/kitchen-app/serve/runpod/prep.sh"
printf '%s\n' "$SECRET" | ssh -p <port> root@<ip> \
  'read -r S; SADIH_MODEL_SECRET="$S" nohup setsid bash /workspace/kitchen-app/serve/runpod/serve.sh > /workspace/serve.log 2>&1 &'
```
`serve.sh` builds the rclone config from the pod's main process (`/proc/1/environ`: SSH sessions do not inherit pod
environment variables), runs the team's `sync_in.sh` into `/workspace/data`, copies the run's own files, and starts
`model_server.py` (combined: recorded sentences first, then the generator). The address is
`https://<pod id>-8100.proxy.runpod.net`; point the app server's `SADIH_MODEL_URL` and `SADIH_MODEL_SECRET` at it.

## Traps we hit
- `invalid_grant: Token has been expired or revoked` from rclone: the team's Drive login expired. Nawaf re-authorises
  and updates the secret, then the pod needs a restart to read it.
- A stopped pod can lose its GPU to another user; RunPod then offers "Automatically migrate", which keeps `/workspace`
  but gives a new pod id and SSH address.
- RunPod's proxy answers 403 to Python urllib's default User-Agent; the app server sends `sadih-app/1.0`.
- `cat file | ssh 'cat > /workspace/x'` once wrote an empty file on the network volume: copy files with `scp`.
