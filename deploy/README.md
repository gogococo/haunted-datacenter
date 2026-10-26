# Stream hosting

One host controls one shared incident. Viewers discuss the solution on stream. Co-op clicking, independent visitor games and state synchronization are future work.

The welcome screen takes a display name. Each fresh incident has a UUID, visible in Host controls. Refreshing or reconnecting resumes the current incident. Resetting creates a new UUID without deleting previous scores or cloud resources.

## Persistent leaderboard

The final exit records the name, run ID, finish time and full elapsed time server-side. The leaderboard ranks the fastest 25 verified escapes; clients cannot submit a score. It is accessible from the welcome and celebration screens and at `GET /api/leaderboard`.

A ranked run must use Tavily Search + Extract, submit its own real Token Factory job, load that job's checkpoint, pass the fresh camera assessment, and pass the deployed cooling service's checks. Pauses, prepared evidence, host solutions and model experiments make a run practice. Practice results are retained privately and excluded from rankings. Hints are allowed. Cloud waiting time counts. The pacing timer can enter overtime without ending a run.

Scores are separate JSON records in `GAME_DATA_DIR/scores/`, alongside the saved incident. Keep the dedicated filesystem when replacing or stopping an endpoint. Back up this directory independently of Git; it can also contain credentials and model artifacts. Local and cloud boards are separate unless their data is intentionally migrated.

## Local Python

Follow the main README for CLI authentication and the model runner. `python3 server.py` binds to loopback. Host sign-in is optional locally. Set `HOST_ACCESS_CODE` and `SESSION_SECRET` to test sign-in; add `PUBLIC_DEPLOYMENT=true` only behind HTTPS, because its session cookie is Secure.

`GAME_DATA_DIR` changes the private data folder (default `.runtime/`). Use the same folder for `caretaker_runner.py --runtime ...`. Changing it gives an independent save, useful for testing.

## Local Docker

```sh
cp .env.example .env
# Edit .env with your own server-side keys and project IDs.
docker compose up --build
```

Open http://127.0.0.1:8765. The image includes the small base model and CPU runner. The named volume retains progress, imported checkpoints and scores. `docker compose down` keeps it; do not add `--volumes` unless deliberately discarding all data.

Room 3 additionally needs authenticated Nebius CLI access. For an unattended container, provide `NEBIUS_SERVICE_ACCOUNT_ID`, `NEBIUS_PUBLIC_KEY_ID`, and `NEBIUS_PRIVATE_KEY` using secret injection. The bootstrap configures the CLI for that identity. Never add a private key to `.env.example`, the image, or Git. A token-factory API key alone cannot deploy AI Cloud endpoints.

## Nebius deployment

Build a Linux amd64 image and push it to the project's private registry. The `.dockerignore` is an allowlist: no local runtime, environment files, model adapters, or cloud credentials enter the build context. The public Qwen base model is fetched at a pinned revision during build.

Create a CPU Serverless AI endpoint exposing **8080**, initially **cpu-d3 / 4vcpu-16gb**, with 30 GiB container disk. Mount a dedicated persistent filesystem at **`/app/runtime-data`**. Keep one instance: this release intentionally has one host and one incident.

Ordinary environment variables:

- `PUBLIC_DEPLOYMENT=true`
- `NEBIUS_PROJECT_ID`, `NEBIUS_SUBNET_ID`
- `NEBIUS_SERVICE_ACCOUNT_ID`, `NEBIUS_PUBLIC_KEY_ID`

SecretStash-injected environment variables:

- `NEBIUS_API_KEY`, `TAVILY_API_KEY`
- `NEBIUS_PRIVATE_KEY` for the project-scoped deployment identity
- `HOST_ACCESS_CODE` (at least 12 characters)
- `SESSION_SECRET` (at least 32 characters)

The bootstrap prepares the dedicated volume, drops to uid 1000, configures the service-account CLI profile, starts the loopback-only model runner and then the HTTP app. It reloads the active persisted checkpoint on a container replacement. `/healthz` is available after startup. Provider keys remain on the backend.

The game uses its own host-code sign-in with an HttpOnly, SameSite=Strict cookie. Only the leaderboard, health and static assets are public. Cost-bearing operations, game progress and host controls require the signed host session and current game token. Retired Python editor/execution routes are disabled in public hosting.

Cloudflare's `haunted-datacenter-edge` Worker connects only `halloween.curiousjaxx.dev` to the Nebius HTTPS upstream. It forwards the host session cookie, rejects foreign browser origins, disables caching and translates the exact app origin for the backend check. Its source has only public routing configuration. The existing Cube demo is separate.

Endpoint-secret references pin a SecretStash version. To change credentials, create a new version and replace the endpoint with the same persistent filesystem. Do not delete that filesystem. A reset does not cancel training jobs or stop cooling endpoints; manage those separately in Nebius.

## Verification

```sh
GAME_DATA_DIR=$(mktemp -d) python3 -m unittest -q test_game test_caretaker test_plant test_upgrade test_checkpoint_flow test_hosting
node --test deploy/cloudflare/test-worker.mjs
```

Automated tests use temporary data and mocked cloud operations. Real browser and container smoke checks cover login, run start/resume, leaderboard visibility, API access, provider connectivity and persistence. Model artifact downloads may still require the existing explicit dashboard download/import workaround; this release does not silently substitute another model.
