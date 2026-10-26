# Escape the Haunted Datacenter

A Halloween coding escape room for a 45-minute livestream: haunted infrastructure, questionable maintenance notes and three rooms to escape. One person controls each game while friends or viewers help solve; different players can keep separate games. Verified escapes earn a place on the persistent leaderboard.

**[Open the hosted demo](https://halloween.curiousjaxx.dev/)** — enter your name to start your own game. No host code is needed.

## Run locally

You need Python 3.12, the Nebius CLI authenticated to a project with Serverless AI access, and your own Tavily and Token Factory API keys. Your Token Factory account needs access to a vision model and fine-tuning.

1. Set up the project and download the caretaker's base model:

   ```sh
   git clone https://github.com/gogococo/haunted-datacenter.git
   cd haunted-datacenter
   python3 -m venv .venv
   source .venv/bin/activate
   pip install torch -r requirements-model.txt
   hf download Qwen/Qwen3-0.6B --local-dir models/base
   cp .env.example .env
   ```

2. Fill in `.env` with your API keys, Nebius project ID and subnet ID. Configure the Nebius CLI for that project with `nebius profile create` if needed. The Token Factory key does not authenticate AI Cloud deployments.

3. Start the caretaker model runner in this terminal:

   ```sh
   python caretaker_runner.py --base-dir models/base
   ```

4. From the repository directory in a second terminal, start the game:

   ```sh
   source .venv/bin/activate
   set -a
   source .env
   set +a
   python server.py
   ```

Open **http://127.0.0.1:8765**, choose **New game** or **Resume**, then **Enter The Datacenter**. New games need a display name; resuming needs a saved UUID or link. Each game gets a UUID and private resume link; keep either to continue in another browser. Progress and checkpoints live in `.runtime/runs/<UUID>/`, with a shared persistent leaderboard. Keep keys server-side and out of Git.

Playthroughs share one real cooling-controller endpoint. Finishing or starting over releases your game’s share; it stops when nobody else is using it. Starting over keeps your previous UUID save and scores. Training jobs continue independently; manage them in Token Factory. For Docker and cloud hosting, see the [deployment guide](deploy/README.md).

## The rooms

- **Room 1 — The Haunted Switchboard:** The old computer uses Tavily Search and Extract to research web sources as you untangle the ghosts' communications.
- **Room 2 — The NOC:** Use Token Factory vision to interpret camera images and LoRA fine-tuning to teach the AI caretaker how to respond.
- **Room 3 — The Generator Room:** Restore cooling through a pipe puzzle and deploy a control application on Nebius Serverless AI.

## Deployment architecture

```mermaid
flowchart TD
    Browser[Player browsers · independent UUID saves] --> Edge[Cloudflare Worker<br/>halloween.curiousjaxx.dev]
    Edge --> Game[Nebius Serverless AI CPU endpoint<br/>Web UI, Python API and caretaker runner]
    Game -->|Search and Extract| Tavily[Tavily]
    Game -->|Vision inference and LoRA training| TF[Token Factory]
    TF -->|Trained adapter| Game
    Game -->|Create once, start/stop and call| Cooling[Separate Serverless AI CPU endpoint<br/>Room 3 control application]
    Game --> Storage[Persistent filesystem<br/>Per-UUID saves, checkpoints and leaderboard]
    Secrets[SecretStash<br/>Runtime credentials] -.-> Game
```

Token Factory handles vision inference and training; the trained text model runs in the game's own model runner, inside the hosted app or on your computer during local play. Room 3's control service runs in a separate cloud endpoint. The building, broker traffic and sensor readings are simulated; the web research, model calls, training and cloud deployments are real.

Locally, the browser connects directly to the Python server, with the same external service integrations. Players have independent progress and training jobs. The CPU runner serializes model tests and restores each player’s own adapter; it does not provision a model server per player. Shared co-op clicking and synchronization are still planned.
