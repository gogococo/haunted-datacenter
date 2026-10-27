# Stream hosting

Players start separate games without a host code. Each gets a random UUIDv4 and a private resume link. The UUID is a bearer secret: anyone with it can resume that game. It is never listed by the leaderboard. A browser remembers its last UUID; an explicit `?run=<UUID>` URL keeps tabs on different saves independent. Shared co-op interactions remain future work.

State, per-game CSRF tokens, training packs and checkpoints live in `GAME_DATA_DIR/runs/<UUID>/`. Scores and cloud-controller receipts remain shared at the data root. Starting over creates a new UUID and keeps the old save. The original host incident stays at the data root and remains resumable by its existing UUID, so the upgrade does not move its training artifacts.

## Persistent leaderboard

The final exit records the name, run ID, finish time and full elapsed time server-side. The leaderboard ranks the fastest 25 verified escapes; clients cannot submit a score. It is accessible from the welcome and celebration screens and at `GET /api/leaderboard`.

A ranked run must use Tavily Search + Extract, submit its own real training job (warm Serverless GPU recommended; managed Token Factory remains a compatibility path), load that job's checkpoint, pass the fresh camera assessment, and pass the deployed cooling service's checks. Pauses, prepared evidence, host solutions and model experiments make a run practice. Practice results are retained privately and excluded from rankings. Hints are allowed. Cloud waiting time counts. Games expire when the 45-minute timer reaches zero. Expired saves are retained but cannot resume or submit more game actions; start a new game instead. Saved pauses stop the timer.

Scores are separate JSON records in `GAME_DATA_DIR/scores/`, alongside the saved incident. Keep the dedicated filesystem when replacing or stopping an endpoint. Back up this directory independently of Git; it can also contain credentials and model artifacts. Local and cloud boards are separate unless their data is intentionally migrated.

## Local Python

Follow the main README and [warm GPU setup](TRAINING.md). The current web app uses the remote training/serving worker; a separate CPU runner is only needed for earlier managed-training saves. `python3 server.py` binds to loopback. Host sign-in is optional locally. Set `HOST_ACCESS_CODE` and `SESSION_SECRET` to test sign-in; add `PUBLIC_DEPLOYMENT=true` only behind HTTPS, because its session cookie is Secure.

`GAME_DATA_DIR` changes the private data folder (default `.runtime/`). Use the same folder for `caretaker_runner.py --runtime ...`. Changing it gives an independent save, useful for testing.

## Local Docker

```sh
cp .env.example .env
# Edit .env with your own server-side keys and project IDs.
docker compose up --build
```

Open http://127.0.0.1:8765. The default image contains the web app and Tavily CLI. It uses the configured warm GPU. Build the `cpu` target to include the earlier base model and CPU runner. The named volume retains progress, imported checkpoints and scores. `docker compose down` keeps it; do not add `--volumes` unless deliberately discarding all data.

Room 3 additionally needs authenticated Nebius CLI access. For an unattended container, provide `NEBIUS_SERVICE_ACCOUNT_ID`, `NEBIUS_PUBLIC_KEY_ID`, and `NEBIUS_PRIVATE_KEY` using secret injection. The bootstrap configures the CLI for that identity. Never add a private key to `.env.example`, the image, or Git. A token-factory API key alone cannot deploy AI Cloud endpoints.

## Nebius deployment

Build a Linux amd64 image and push it to the project's private registry. The `.dockerignore` is an allowlist: no local runtime, environment files, model adapters, or cloud credentials enter the build context. The default stream image excludes model weights and PyTorch; the warm worker loads its pinned model separately.

Create a CPU Serverless AI endpoint exposing **8080**, initially **cpu-d3 / 4vcpu-16gb**, with 30 GiB container disk. Mount a dedicated persistent filesystem at **`/app/runtime-data`**. Keep one application instance: it serves independent player saves from the same volume. Request locks and background jobs are scoped to each UUID.

Ordinary environment variables:

- `PUBLIC_DEPLOYMENT=true`
- `NEBIUS_PROJECT_ID`, `NEBIUS_SUBNET_ID`
- `CARETAKER_WORKER_URL`
- `NEBIUS_SERVICE_ACCOUNT_ID`, `NEBIUS_PUBLIC_KEY_ID`

SecretStash-injected environment variables:

- `NEBIUS_API_KEY`, `TAVILY_API_KEY`
- `CARETAKER_WORKER_TOKEN`
- `NEBIUS_PRIVATE_KEY` for the project-scoped deployment identity
- `HOST_ACCESS_CODE` (at least 12 characters)
- `SESSION_SECRET` (at least 32 characters)

The bootstrap prepares the dedicated volume, drops to uid 1000, configures the service-account CLI profile and starts the HTTP app. The optional `cpu` image also starts the loopback runner for earlier saves, while new shifts use the warm GPU. The default stream image requires the warm-worker URL. It reloads the active persisted checkpoint on a container replacement. `/healthz` is available after startup. Provider keys remain on the backend.

Normal players need a UUID save and its per-game request token, supplied automatically by the UI. Host-code sign-in is only for optional presentation tools, prepared checkpoints and prompt experiments; its cookie is HttpOnly and SameSite=Strict. New-shift creation is limited to 30 per connection per hour, and training submission remains once per game. Retired Python execution routes stay disabled in public hosting. Provider credentials never reach the browser.

Cloudflare's `haunted-datacenter-edge` Worker connects only `halloween.curiousjaxx.dev` to the Nebius HTTPS upstream. It forwards the host session cookie, rejects foreign browser origins, disables caching and translates the exact app origin for the backend check. Its source has only public routing configuration. The existing Cube demo is separate.

Endpoint-secret references pin a SecretStash version. To change credentials, create a new version and replace the endpoint with the same persistent filesystem. Do not delete that filesystem. Finishing or starting over releases only that UUID’s cooling-controller lease. The controller stops after the last active lease is released. Abandoned browser leases expire after 20 minutes and a minute-interval sweep stops an unused controller. An open game that has claimed the controller keeps its lease alive; returning after expiry can wake the same endpoint. A new shift wakes an existing, verified shared controller in the background while Rooms 1–2 are played; this never creates an extra app or fills the player’s commissioning fields. Room 3 still requires the maintenance-book settings and actual readiness/cooling checks. Public games share its equipment-plate configuration and cannot replace another player’s controller. Training jobs continue independently.

The app uses 4 vCPUs; one shared cooling controller uses 2 vCPUs while running. No additional CPU model server or cooling endpoint is created per player. The private pool receipt is `GAME_DATA_DIR/serverless/controller.json`; only verified game-owned resources are reused or stopped. Keep one active application deployment per Nebius project. If a stop fails, the cooling panel shows the cleanup error. The warm worker serializes training and inference and selects the requested job adapter explicitly. A busy GPU can queue jobs without mixing checkpoints.

## Verification

```sh
GAME_DATA_DIR=$(mktemp -d) python3 -m unittest -q test_game test_caretaker test_plant test_upgrade test_checkpoint_flow test_hosting test_serverless test_sessions
node --test deploy/cloudflare/test-worker.mjs
```

Automated tests use temporary data and mocked cloud operations. Real browser and container smoke checks cover login, run start/resume, leaderboard visibility, API access, provider connectivity and persistence. The warm-worker path loads its own adapter directly without a dashboard transfer. Earlier managed Token Factory jobs may still require the explicit download/import workaround. No path silently substitutes another player’s job.

## Current release

- Public URL: **https://halloween.curiousjaxx.dev/**
- Project: `jc-kubecon-demo` (`project-e00nm584pr00c9xab0myzw`), `eu-north1`
- Host endpoint: `aiendpoint-e00r1xmcwvx7net6zy`
- Persistent filesystem: `computefilesystem-e00ybmwmaz7tm6290n`
- Image: `cr.eu-north1.nebius.cloud/e00qmygzhgqbsky5mh/haunted-datacenter:rescue-v5`
- Checked image manifest: `sha256:157f2c136ba99b7a4024af0676638aa7ebe6f3130f56bfc3f4b21e53a9b30ccd`

The project deployment identity's current public key expires November 30, 2026. Rotate it in SecretStash before then if keeping the demo online. Keep the host access code private; it unlocks presentation shortcuts and model experiments. Normal games use the configured backend integrations without this code.

The UUID-save update passed 156 Python tests and four edge tests. Separate players and tab resumes were verified in a browser, and both saves survived a real process restart. Earlier release checks passed 120 Python tests, followed by 135 for controller reuse. Its lifecycle tests check wake/reuse, stop-on-reset/finish, configuration replacement, private receipts, quota errors and stale-cleanup races. A real cloud smoke run completed Room 1 with live Tavily Search + Extract, connected to Token Factory, inspected the cooling camera with its vision endpoint and received a real CPU caretaker response. An isolated container check loaded an actual trained adapter, verified the learned repair, then restored the adapter, incident name/UUID and private fixture leaderboard after restart. These checks do not claim a new full cloud training-and-escape playthrough.

The entry and expiry update passed 164 Python tests and four edge tests. Browser checks covered both entry actions, resuming an active save, automatic expiry while a room was open, and starting a new UUID after expiry.

## Caretaker rescue flow

Room 2 now uses separate Token Factory personality dialogue and camera vision, a revised teaching curriculum, and an explicitly selected LoRA checkpoint on the warm Serverless GPU. Room 3 sends per-game fan/pump settings to the shared CPU app; its health route and cooling result are separate checks. Only a measured caretaker command can release the final door, and a control change during inference invalidates that approval. Existing UUID files and leaderboard records are retained. New games use the new teaching flow.

The current model worker should stay warm before a stream. Cold provisioning is outside the measured training time. Stop it when finished presenting. See [training setup](TRAINING.md) for resource and persistence details.

This release passed 179 Python tests, four edge tests, and a real isolated browser playthrough of Rooms 2–3. That playthrough submitted and loaded its own adapter (24.807 seconds of warm GPU training), improved from 0/12 to 12/12 fresh command checks, passed four image-to-command checks, and used a measured caretaker response to open the final door. Quiet and turbo cooling failures and the balanced success were tested against the real CPU app. Room 1 was deliberately pre-completed for this isolated QA run, which was saved as practice and excluded from the leaderboard. The completed adapter also retained its identity, hash and safe/unsafe exit behavior after replacing the worker. These measurements exclude cold provisioning and are not a latency guarantee.

A fresh anonymous cloud integration run also completed all three rooms using live Tavily Search/Extract, Token Factory vision/dialogue, its own Serverless training job (25.463 seconds), checkpoint loading, certification, the reused CPU controller and the trained caretaker’s final door command. Its deliberately paused practice result was excluded from the leaderboard. The public domain, deployed asset hashes and preservation of the earlier paused save/job were checked after cutover.
