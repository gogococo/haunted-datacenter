# SEV-0: The Haunted Datacenter

Three clickable rooms for 2–3 people, one keyboard, and a 45-minute livestream. The game mixes real cloud/API operations with an explicitly simulated haunted building.

## Start

Use a recent Python with OpenSSL/TLS 1.3 support (Python 3.11+ recommended), an authenticated Tavily CLI, and the Nebius AI Cloud CLI. Model serving has a separate optional Python environment.

```sh
export NEBIUS_API_KEY='YOUR_TOKEN_FACTORY_KEY'
export NEBIUS_PROJECT_ID='YOUR_AI_CLOUD_PROJECT'
export NEBIUS_SUBNET_ID='YOUR_SUBNET'
python3 server.py
```

Open http://127.0.0.1:8765 and click **Play**. Keep credentials in the server environment. The game binds to loopback and saves progress in `.runtime/`. The gear menu starts a genuinely fresh incident, including an untrained caretaker and new room gates.

**Cloud resources survive a game reset.** Each full playthrough submits one real fine-tuning job and creates one real CPU Serverless endpoint. A repeated click cannot submit another resource while a submission is pending or its outcome is uncertain. Manage completed jobs and stop unneeded endpoints in the cloud console. Runtime receipts retain their IDs across resets.

## Room 1: research, inspect, apply

Talk to Pip, Edgar and Mabel, then restore DNS, SMTP and MQTT wiring. Mabel's announcement speaker subscribes to service announcements. Its broad initial filter also broadcasts private mail and debugging.

Search wildcard documentation with real **Tavily Search**, choose a returned source, and read it with **Tavily Extract**. Search alone does not satisfy the evidence gate. Enter a topic filter and send rehearsal messages; the UI shows every broadcast and every excluded message. MQTT matching handles whole-level `+`, terminal `#`, empty levels and the special `$` root rule.

Read Mabel's saved bookmark for the separate door-control topic, then use the rack:

```sh
ghostctl apply
mosquitto_pub -h crypt.local -t midnight/door -m OPEN
```

`ghostctl` is fictional. Mosquitto syntax is real; broker traffic, DNS, devices and ghosts are simulated. Wildcards belong in subscriptions, not publish topic names. The door requires correct wiring, an inspected documentation source, a passing speaker filter, retrieved control topic, applied wiring and the actual publish command.

Mabel's bookmark is authored local game content. To additionally extract a public version with Tavily, publish `web/mabel-post.html` yourself and set `MABEL_POST_URL` to its public HTTPS URL. The game never pretends local content came from the web.

## Room 2: observe, demonstrate, train, compare

The camera view sends PNG pixels to the account's actual Token Factory vision endpoint and displays the model's observation. The text caretaker receives that actual description. Players try its command in a rehearsal, read an equipment service sticker, demonstrate a working repair and record the input/output lesson. The rehearsal is a simulator; physical cooling is repaired in Room 3.

Three recorded demonstrations produce three actual vision-derived training records. These are added to 72 prepared practice prompts (nine known fault reports with eight introductions each). Eighteen separate prompts are used for validation. The Mac mini uses three different fault descriptions, each repeated three times; this small assessment is a teaching aid, not a broad reliability test.

The player must measure a base-model baseline and **submit a real Token Factory LoRA job**. The UI shows its actual ID and status. Uploads and job submission happen through the Token Factory API; there is no scripted training timer. Ten epochs, rank 16, alpha 32, dropout 0, batch 16 and learning rate 0.0002 match the small-model benchmark recipe.

The player path has one model: **the checkpoint produced by this playthrough's submitted job**. Submitting training opens the maintenance hatch. Alex asks the team to carry his terminal downstairs while the caretaker studies. In Room 3, repair the loop and deploy the CPU controller while training runs. Finish at the portable terminal: load your checkpoint, compare behavior with the baseline, and pass the safety checks. There is no required return trip to the NOC.

The terminal attempts the official checkpoint download API. If storage returns AccessDenied, it offers a download/import step for **that same job's final adapter**. The player selects `adapter_model.safetensors`; the server checks the cloud job, file size, configuration and checkpoint metadata, prepares a hashed receipt, and loads the adapter into the existing local runner. A manually selected dashboard download has no independent cloud checksum, so the player must select the correct job's final file. The retrieval sequence follows the [Token Factory checkpoint documentation](https://docs.tokenfactory.nebius.com/post-training/how-to-fine-tune). It is never silently replaced with an earlier run.

Alex's old checkpoint and the larger-model prompt comparison are **host-only overrides**, visibly labeled when selected. The default certificate gate rejects a model from a different job. Actual inference results must match the loaded artifact identity; changed weights/settings invalidate the certificate.

Tooltips explain generation settings. The portable terminal compares correctness, JSON schema, completion, brevity and consistency. Its final assessment makes three fresh vision calls and sends the actual observed descriptions to the trained text model. Both the caretaker certificate and the real cloud cooling test are required at the final exit.

**Serving boundary:** vision and training use Token Factory. The small LoRA text model runs locally. Room 3 deploys the real application on Nebius Serverless AI. This POC does not claim a new Token Factory-hosted text endpoint.

### Start the local model runner

A fresh viewer needs the base model, not an earlier fine-tuning job:

```sh
python3 -m venv .venv
.venv/bin/pip install torch transformers peft safetensors huggingface_hub
.venv/bin/hf download Qwen/Qwen3-0.6B --local-dir models/base
.venv/bin/python caretaker_runner.py --base-dir models/base
```

The runner starts with base weights on `127.0.0.1:8770`. Its control token is private in `.runtime/caretaker/runner-control.json`; the game uses it to load prepared receipts inside the configured runtime folder. Model loading checks every adapter tensor and its actual loaded value. A failed load retains the current model. Keep the model environment separate from the standard-library game server.

For a host fallback, the existing `checkpoint_setup.py --job ... --weights ... --base-dir ...` workflow still prepares an earlier receipt. It is loaded only by the explicit host override. Historical benchmark results are in `data/caretaker-benchmark.json`.

## Room 3: deploy and verify

Repair the actual closed circuit: **pump → GPU cold plate → heat exchanger → reservoir → pump**. Six movable pipes must connect all four fixed components without a gap or disconnected spare. A pressure test validates ports and the complete return path. Warm return and cooled supply are visually distinct.

The local control service is dead. Players deploy `cloud_controller.py` as a real **Nebius Serverless AI CPU endpoint** using `python:3.12-slim` and file injection; no Docker build is required. The UI exposes port, temperature target and power budget, shows equivalent CLI syntax, reads actual container logs, and retrieves the managed HTTPS URL.

1. Deployment status proves that cloud resources started.
2. `GET /healthz` proves the application answers.
3. `POST /simulate` sends the game's actual circuit status and a fresh nonce to the deployed app. The app chooses a fan/pump profile and returns measured simulator results. The game independently checks its limits and request identity.

The exit requires a current passing cloud report for the current circuit and endpoint, plus both earlier rooms. No locally calculated report alone can unlock it. Sensor values and physical hardware remain simulated; the control application executes in the cloud.

Cloud startup can take several minutes. Start deployment before working on the pipe puzzle. The first tested CPU endpoint took roughly six minutes to reach RUNNING, so preflight project access and allow time for provisioning/image pulling.

### Serverless setup

Authenticate the Nebius CLI using your own AI Cloud account, select your project, and set `NEBIUS_PROJECT_ID` and `NEBIUS_SUBNET_ID` in the game-server environment. The Token Factory API key alone does not configure AI Cloud access. Alternatively, an ignored `.runtime/serverless/config.json` may contain:

```json
{"project_id":"YOUR_PROJECT_ID","subnet_id":"YOUR_SUBNET_ID","platform":"cpu-d3","preset":"2vcpu-8gb"}
```

Endpoint authentication tokens are generated server-side, written only to private runtime receipts and omitted from browser state. The CLI response is projected to safe metadata. Uncertain creates are not automatically retried. If a request fails after submission, check the console before making another resource.

Documentation: https://docs.nebius.com/serverless/quickstart/endpoints

## Verification

```sh
python3 -m unittest -q test_game test_caretaker test_plant test_upgrade test_checkpoint_flow
```

Automated tests mock external APIs. Separate browser/integration playtests use real Tavily Search + Extract, Token Factory vision and training, the prepared adapter, and the actual deployed CPU application.

API keys, runtime state, cloud authentication tokens, model weights and virtual environments are excluded from Git and the downloadable archive.
