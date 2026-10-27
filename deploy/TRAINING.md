# Warm caretaker GPU

Token Factory supplies camera vision and personality dialogue. The recommended training path uses a separate Nebius Serverless AI GPU endpoint running `training_worker.py`. Start it before play: the base model stays in memory while each game trains a new LoRA adapter. Training and inference share one GPU; no GPU is provisioned per player.

## Start once

Use your authenticated Nebius CLI, a GPU-capable project/subnet, a persistent filesystem and a private endpoint token. Keep token values out of scripts and Git. From the repository root:

```sh
nebius ai endpoint create \
  --name haunted-caretaker-worker \
  --parent-id "$NEBIUS_PROJECT_ID" --subnet-id "$NEBIUS_SUBNET_ID" \
  --image pytorch/pytorch:2.8.0-cuda12.8-cudnn9-runtime \
  --platform gpu-l40s-a --preset 1gpu-8vcpu-32gb \
  --disk-size 200Gi --shm-size 2Gi \
  --container-command bash --args /opt/training-start.sh \
  --inject-file deploy/training-start.sh:/opt/training-start.sh \
  --inject-file training_worker.py:/opt/training_worker.py \
  --volume "$TRAINING_FILESYSTEM_ID:/mnt/persist:rw" \
  --container-port 8000/http --auth token --token "$CARETAKER_WORKER_TOKEN" \
  --env "CARETAKER_WORKER_TOKEN=$CARETAKER_WORKER_TOKEN" \
  --public=false --preemptible=false --async
```

For unattended hosting, use SecretStash selectors with `--token-secret` and `--env-secret` instead of literal token arguments. The CLI can echo literal tokens in errors; treat its output as private.

The worker uses a pinned Qwen3 base revision and pinned training dependencies. `/healthz` starts answering before model loading finishes. Wait for authenticated JSON containing `ready: true`; a RUNNING endpoint alone is insufficient.

Put its managed HTTPS URL and token in the game's server environment:

```sh
CARETAKER_WORKER_URL=https://YOUR_MANAGED_ENDPOINT.nebius.cloud
CARETAKER_WORKER_TOKEN=YOUR_PRIVATE_TOKEN
```

Both the web app and worker must retain their private data directories across restarts. The worker filesystem holds the model cache, per-job datasets, adapters and receipts. Size it for the number of playtests you retain. Stop the GPU endpoint when finished; it remains allocated while warm.

## What a game does

- `POST /jobs` submits chat examples and separate validation records using a persisted UUID request ID. Retrying the same ID recovers the same job; changed data is rejected.
- `GET /jobs/<id>` returns actual queue/training progress and the completed artifact hash.
- `POST /load` verifies the completed checkpoint for that job. The UI makes the change from base weights to the player's adapter explicit.
- `POST /v1/chat/completions` explicitly selects a job ID, or the unchanged base model. Training and adapter selection are serialized so games cannot share the wrong weights.

Personality is a separate Token Factory prompt profile. It never enters equipment command generation or authorizes the exit. A real trained-model response and fresh cooling evidence are required to release the final door. A small practical exam is a teaching assessment, not a general model-reliability guarantee.

The first warm-worker measurement trained a revised 118/29-example pack in about 25 seconds. Cold provisioning remains longer, and concurrent games can queue. Preflight the whole flow before presenting; these timings are not a latency guarantee.

## Optional earlier path

Without warm-worker settings, the game retains the managed Token Factory fine-tuning integration and loopback CPU runner. Install `torch` and `requirements-model.txt`, download the pinned Qwen3 base, and start `caretaker_runner.py` separately. Docker users can build `--target cpu` for that compatibility path. Managed jobs may queue and some accounts require the explicit adapter download/import workaround; they do not gain the warm worker's latency characteristics.
