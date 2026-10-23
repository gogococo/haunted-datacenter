# SEV-0: The Haunted Datacenter

A local Halloween escape-room POC: 2–3 people, one keyboard, 45 minutes. Click objects to discover three rooms. The app uses Python 3.9+ standard library; the optional checkpoint runner has separate model dependencies.

## Start the game

```sh
export NEBIUS_API_KEY='YOUR_KEY'
python3 server.py
```

Open http://127.0.0.1:8765 and click **Play**. Keep credentials in the server environment. The game binds to loopback and saves progress in `.runtime/`. Resetting the game does not delete cloud resources. This is a trusted local, single-team POC.

Room 1 uses the authenticated Tavily CLI. Rehearsal mode permits marked sample clues; Room 2 still uses actual model inference. The gear menu starts a fresh incident. Room previews are available at `/#2` and `/#3`; Room 2 has an isolated playtest button if Room 1 is incomplete.

## Room 1 — The Haunted Switchboard

Read Alex’s note, talk to Pip, Edgar and Mabel, and reconnect their cables. Use Tavily to research protocols. The rack offers a simulated terminal with real Mosquitto command syntax:

```sh
ghostctl apply
mosquitto_pub -h crypt.local -t TOPIC -m OPEN
```

`ghostctl` is fictional. The broker, DNS and message delivery are mocked. Correct wiring and an MQTT documentation reference are required. Mabel forgot her topic: retrieve her launch post before publishing. Guessing the topic does not bypass that clue.

The current playtest uses a clearly marked local draft for Mabel’s post. For live Tavily extraction, publish `web/mabel-post.html` at a public HTTPS URL, remove its local-draft notice, and set `MABEL_POST_URL` before starting the server. Live mode refuses the local draft. Public posting is not performed automatically.

## Room 2 — The Night Operations Center

- **Deployment rack:** connect the Token Factory account and discover the local trained backup. The main experiment restores a real previously trained checkpoint; the optional prompt comparison is a separate, labeled route.
- **Security cameras:** send actual images to Token Factory vision. Review the equipment and fault it observed. The GPU rack has stopped fans, the cooling loop leaks, and the exit latch is stuck. These names are visible on the equipment; there is no invented dialect.
- **Caretaker monitor:** vary temperature, output-token limit and instructions. These are inference settings. Lowering temperature does not teach missing maintenance rules, and lowering the token limit can truncate JSON.
- **Maintenance binder:** repair three damaged records using dropdowns and a visible checklist. Preview the JSONL before and after repair. Nine seed labels expand into 72 training and 18 validation phrasings.
- **Alex’s Mac mini:** record the base model’s behavior, restore the trained checkpoint, then test again. Nine real replies cover three phrasings repeated three times. Checks measure correctness, consistency, brevity, completion, and exactly `action` plus `equipment` JSON.

The final assessment makes three fresh vision calls and feeds the actual observed equipment/fault pairs to the text model. An incorrect visual observation cannot pass through a lucky repair answer. Changed settings or examples invalidate the current assessment.

### Trained backup used for this playtest

Qwen3-0.6B was LoRA-trained on Token Factory before the episode: 10 epochs, rank 16, alpha 32, dropout 0, batch size 16, learning rate 0.0002. The actual run took **8m45s**. The rack’s five-second terminal replay shows recorded API events, not live training or a fabricated progress log.

The final checkpoint was downloaded through the dashboard after API weight downloads returned HTTP 403. Its 392 adapter tensors are loaded with strict name, coverage and value checks. The local runner compares file hashes with the prepared receipt before loading. Job, model, dataset IDs and checkpoint membership are checked against Token Factory when restoring the backup. The API provides no checksum to independently prove that a manually downloaded weight file belongs to the selected checkpoint; the host selects it in the dashboard.

**Serving boundary:** camera inference uses Token Factory, with an existing dedicated vision endpoint when available. Trained text inference runs locally from the Token Factory checkpoint. This POC does not create a new Token Factory-hosted text endpoint. The prompt comparison instead uses Token Factory’s public text endpoint and never claims fine-tuned weights.

The downloaded Qwen3-0.6B checkpoint passed 27/27 test phrasings locally, versus 0/27 for its base weights and 17/27 with three examples in the prompt. These are new phrasings of known reports, not unseen intents or a reliability guarantee. Only this small trained checkpoint has been evaluated; the other two completed jobs still lack downloaded weights. Details: `data/caretaker-benchmark.json`.

### Prepare your own local checkpoint runner

Keep this environment separate from the standard-library game server:

```sh
python3 -m venv .venv
.venv/bin/pip install torch transformers peft safetensors
hf download Qwen/Qwen3-0.6B --local-dir models/base
```

Use your own completed Token Factory job and download its final `adapter_model.safetensors` through the dashboard. Prepare a receipt using that job’s ID and the matching base-model folder:

```sh
python3 checkpoint_setup.py --job YOUR_JOB_ID --weights /path/to/adapter_model.safetensors --base-dir models/base
.venv/bin/python caretaker_runner.py --receipt .runtime/caretaker/receipt.json
```

The setup command reads metadata/configuration and copies the dashboard download; it submits no training or deployment. It verifies the file size, matching configuration and repaired-example recipe. The runner serves only `127.0.0.1:8770`, supports base/adapter comparison, and needs no API key. The game server still needs your key to inspect cameras and verify the job. Match the original training recipe when preparing another checkpoint; a base model alone is not the trained backup.

For Jacquie’s current workspace, the selected receipt and separate runtime are already prepared outside the downloadable app. Viewer setup remains a developer workflow for this POC, not a finished installer. The legacy `tokenfactory.py` CLI supports manual training/deployment inspection; its reports cannot unlock the game.

## Room 3 — The Generator Room

Drag six pipes into the grid, rotate them, and connect SUPPLY → GPU heat exchanger → RETURN. A click-to-place alternative supports keyboards and touchscreens. The routing validator follows actual connected ports and identifies gaps and wrong rotations; fixed equipment and the parts inventory cannot be bypassed.

Recover the cooling controller with dropdowns. The local simulator measures temperature, power, circulation and alarm policy. Token Factory can explain the supplied diagnostic logs, but advice does not replace a passing health check. The emergency exit requires both earlier rooms and the current pipe layout/configuration to pass. No physical equipment is controlled, and no code-writing task remains in Room 3.

## Verification

```sh
python3 -m unittest -q test_game test_caretaker test_plant
```

The automated suite mocks cloud calls and covers routing, inventory, no-bypass gates, current assessment/configuration, incomplete responses, backup identity, prompt-route separation, and stale asynchronous completion after reset. Browser playtests separately verify the controls. Real integration testing uses actual Tavily search, Token Factory vision, the downloaded adapter and diagnostic inference; Mabel’s unpublished post remains a marked rehearsal fixture.

Model weights, virtual environments, API keys and `.runtime/` are excluded from Git and the downloadable archive. Manage existing cloud jobs and endpoints in Token Factory; resetting this game does not cancel or remove them.
