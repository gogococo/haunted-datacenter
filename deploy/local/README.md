# Local Docker game

Requirements: Docker Desktop (or local Docker Engine with Compose), Python 3.9+
for the launcher, and Tavily / Token Factory API keys. No Nebius CLI, AI Cloud
project, cloud CPU or cloud GPU is required. Docker uses its native CPU platform,
including Apple Silicon; Docker Desktop does not expose the Mac's GPU to PyTorch.
Allow at least 8 GB RAM for Docker and roughly 5 GB of free disk for the images,
cached base model and checkpoints.

From the repository:

```sh
cp .env.example .env
# Set NEBIUS_API_KEY (Token Factory) and TAVILY_API_KEY.
./haunted-datacenter --local
```

The launcher prefers `.env.local` when present, otherwise `.env`. It reads only
those two keys from the file, without executing shell
code. First launch builds the images and downloads the pinned Qwen3-0.6B model.
It waits for the caretaker and cooling app to be ready before starting the game.
Later launches reuse Docker's image layers and persistent model cache.

To install the `haunted-datacenter` command in a virtual environment:

```sh
python3 -m venv .venv-local
source .venv-local/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
haunted-datacenter --local
```

Keep this editable installation with the checkout; the launcher locates its
Compose file and application sources there.

Options:

```sh
haunted-datacenter --local --port 8782 --env-file .env.local
haunted-datacenter --local --status
haunted-datacenter --local --logs
haunted-datacenter --local --stop
```

The web UI binds only to `127.0.0.1` (port 8765 by default). Neither worker
publishes a host port. All three containers run as a non-root user. The web app
gets the Tavily / Token Factory keys; workers receive only their own generated
authentication tokens. No Docker socket, cloud identity, or production save
volume is mounted. The launcher pins the local Docker context.

Room 1 still uses real Tavily Search and Extract. Room 2 uses real Token Factory
vision and personality dialogue, then trains and serves the player's own LoRA
checkpoint on the local CPU. The local CPU recipe uses five epochs, rather than
the hosted GPU's twenty; the same training pack and fresh assessments remain
required. To fit Docker Desktop memory, training and inference share one
model process and serialize access. CPU training takes longer than the hosted GPU.
Room 3 connects to a real local cooling HTTP app and tests the repaired circuit.
The interface labels the local worker and controller rather than claiming a
Nebius deployment occurred. Cloud provisioning and managed fine-tuning calls
are blocked in local mode; there is no cloud fallback.

Game saves and the local leaderboard live in the `local-progress` named volume;
training jobs, adapters and the model cache live in `local-models`. Both are scoped
to the Compose project (`haunted-local` by default). `--stop` keeps these volumes.
Starting again restores existing UUID saves and finished checkpoints. Hosted
leaderboards and saves remain separate. Keep `.local-docker/` private; it stores
the stable worker tokens needed across restarts. Never use `down --volumes` if
you want to retain progress.

## Verification on November 2, 2026

One scripted local playthrough completed all three rooms using live Tavily
Search/Extract, Token Factory vision/dialogue, its own CPU-trained adapter and
the Docker cooling controller. Training took 442.009 seconds (five epochs,
118 training / 29 validation examples); the complete scripted run took
588.64 seconds. The trained caretaker passed all 12 fresh text requests and
the camera assessment. These are measurements on this Mac with four worker
CPU threads, not a guarantee or a test of simultaneous local players.

After stopping and recreating all three containers, the completed UUID save and
checkpoint identity/hash were unchanged. Real inference passed all eight
building safety combinations, and all cooling profiles produced the expected
results. All 224 backend tests and seven edge tests passed. A final targeted
run passed another 31 checks. No cloud resources were provisioned.
