# SEV-0: The Haunted Datacenter

A local, single-team Halloween escape-room POC for 2–3 people, one keyboard, and a 45-minute stream. Python 3.9+ standard library; no app dependencies or database. Camera images ship with the game.

## Start

```sh
# Set this in your shell using your own Token Factory key.
export NEBIUS_API_KEY='YOUR_KEY'
python3 server.py
```

Open **http://127.0.0.1:8765** and click Play. Never put a key in the browser, source code, or a shared archive. The server binds to loopback. This is a trusted local demo, not a multi-user hosted service; Room 3 intentionally executes the player's Python in a constrained subprocess, not a hardened sandbox.

Room 1 live web search uses the authenticated [Tavily CLI](https://github.com/tavily-ai/tavily-cli). Rehearsal mode allows clearly marked sample references. Room 2 **always uses real Token Factory calls**, even when Room 1 is in rehearsal mode. No scripted result unlocks the caretaker.

For an isolated Room 2 playtest, open `http://127.0.0.1:8765/#2` and use **Start a Room 2 playtest**. It restarts the timer and permits caretaker operations without marking Room 1 solved. The gear menu resets the game. A reset clears game progress, not cloud resources. Training jobs and endpoints can outlive the server or game; manage them in Token Factory. Never share `.runtime/`, `.env`, endpoint configuration containing private information, or API credentials.

## Room 1 — The Haunted Switchboard

Read Alex's note, talk to Pip, Edgar and Mabel, and reconnect their cables. Research unfamiliar protocols on the Tavily computer. Correct connections plus an MQTT reference permit `ghostctl apply` on the server rack. Publish `OPEN` to Mabel's topic to release the door. These terminal commands simulate routing; no real email, DNS query or MQTT publication is sent.

## Room 2 — The Night Operations Center

Rows of racks behind a NOC desk. Each object has one job:

- **Deployment rack:** connect your Token Factory account. This discovers models, deployment templates and existing endpoints using your server's key. It prefers an existing dedicated vision endpoint when available.
- **Security cameras:** inspect three illustrated incidents with a real vision model. The image contains a dispatch placard written in the building's fictional dialect. The model returns a transcription plus a visual description. Players review/correct the transcription before a practice request reaches the caretaker.
- **Caretaker monitor:** change temperature, maximum output tokens and system instructions. A practice request shows the actual text response and finish reason. Settings are inference parameters, not training changes.
- **Maintenance binder:** use the ledger to repair three damaged examples with dropdowns. Nine seed records expand to 72 training and 18 validation examples. Held-out assessment phrasings are not uploaded.
- **Alex's Mac mini:** run nine real requests (three new phrasings repeated three times). Checks cover brevity (at most 30 words), completion (no token cutoff), exactly `action` and `zone` JSON, correct decisions, and consistency within repeats. Scores inspect behavior, not slider positions. The first run remains available for comparison.

### Real fine-tuning and deployment

1. Connect at the rack and record a Mac mini baseline.
2. Repair and validate the binder. Choose a fine-tunable text model with a matching dedicated-endpoint template.
3. Click **Start real fine-tuning**. The server uploads the training/validation files and submits a real full fine-tuning job: 3 epochs, batch size 16, learning rate 1e-5. The initial model is `Qwen/Qwen3-30B-A3B-Instruct-2507`, an exact match across this account's inference catalog, fine-tuning documentation and deployment templates. It is not a promise of the smallest/cheapest model for every account. Model lists vary. Test a smaller compatible model before distributing broadly.
4. Investigate Room 3 while training runs. **Refresh job & endpoint status** reads real progress; the game does not invent a completion time.
5. Once training succeeds, inspect its checkpoints and register the selected checkpoint as custom weights in the Token Factory console. **This step currently requires account-specific custom-weight access.** The public docs do not provide an automatic registration workflow for this POC.
6. Enter the registered weight ID, select a configuration from the actual template, and click **Create dedicated endpoint**. The POC requests one replica. It does not auto-delete it.
7. Refresh until a replica is ready. Adjust instructions to the JSON contract and rerun the Mac mini against the deployed model.
8. Run the **camera → caretaker assessment**. This performs three fresh image inspections and feeds their transcriptions to the text endpoint. All actions must be correct, structured, brief and complete. Success unlocks the caretaker gate.

Training and deployment are explicit button actions. Connecting, adjusting settings, and inspecting the scene do not create GPU resources. Camera inspection, practice replies and tests are real inference calls. A run with an uncertain training/deployment response is not automatically retried; inspect the cloud console to avoid duplicates.

The final gate checks real job success, ready dedicated replicas, matching model/weight/endpoint IDs, current measured behavior, and new vision-to-text results. **Checkpoint-to-custom-weight lineage remains a user-declared console step**, not independently proven by the public API. Nine text requests and three camera examples are a small teaching assessment, not a general reliability guarantee. The final camera images are revisits of the room's three incidents; the text tests use new phrasings of known intents, not unseen concepts.

Inference currently supports eu-north1, eu-west1 and us-central1 API hosts. Custom deployment configurations are restricted to these regions. API keys remain in server memory and are never included in game state. No Hermes-specific configuration is needed in the downloadable game.

## Room 3 — The Possessed Runbook

Repair a Python authorization guard while training runs. Accept only signed controller metadata and allowed action/zone pairs. Once the caretaker passes, execute the three escape actions in order. The runbook's hostile instructions must never override controller policy.

## Verification and troubleshooting

```sh
python3 -m unittest -q test_game test_caretaker
```

The automated suite mocks cloud operations and covers no-bypass gates, settings propagation, cutoff detection, consistency versus correctness, fresh vision requests, endpoint/weight mismatch, and stale asynchronous completion after a reset. A real browser rehearsal separately exercises the API integration; it does not replace a measured training/deployment rehearsal.

A model error is shown in the room without returning credentials or upstream response bodies. For missing access, check the account and selected model in Token Factory. Custom weights may require enablement. Use the console to cancel unwanted training or delete dedicated endpoints after the session.

The legacy `tokenfactory.py` CLI is retained for host inspection and manual workflows. Its `live-report.json` no longer unlocks Room 2: the NOC's measured final assessment owns that gate.

## Official references

- [Vision requests](https://docs.tokenfactory.nebius.com/api-reference/examples/vision-capabilities)
- [Fine-tunable models](https://docs.tokenfactory.nebius.com/post-training/models)
- [Custom-weight access](https://docs.tokenfactory.nebius.com/ai-models-inference/dedicated-endpoints/custom-weights)
- [Dedicated endpoint creation](https://docs.tokenfactory.nebius.com/api-reference/dedicated-endpoints/create-dedicated-endpoint)

The game is a POC. Room 3 still uses the original code-editor layout; Rooms 1 and 2 are interactive illustrated rooms.
