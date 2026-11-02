# Shared demo host

The shared image runs the Haunted Datacenter website, Crack the Cube website,
caretaker model worker and cooling controller as separate processes on one
Serverless L40S VM. The websites use CPU; only the caretaker uses CUDA.

Ports: cooling 8000, model worker 8001, Haunted 8080, Cube 8081. Port 9000 is an
authenticated maintenance interface. The model and cooling routes require their
own bearer credentials even though the website ports are public.

Retain both original filesystems. Mount Haunted at `/mnt/persist` and Cube at
`/mnt/soma`; compatibility symlinks preserve the applications' original paths.
Each child receives only its application's environment variables. Prefix the
original website variables with `HAUNTED_` or `SOMA_`, and worker variables with
`WORKER_`. Use secret references for credentials. Set `MAINTENANCE_TOKEN` and
`COOLING_TOKEN` as separate private credentials.

On first boot, only maintenance and the caretaker start. Back up both volumes,
download and verify every archive against its manifest, then stop the two old
website endpoints before activating the shared websites. The maintenance
activation stores only the endpoint ID, name and public managed URLs on the
Haunted volume. Later restarts reuse that activation.

The explicit shared cooling configuration verifies its endpoint identity through
Nebius before connecting. It never creates, replaces or stops the shared VM.
Resetting or finishing a game therefore cannot stop another demo. Standalone
deployments keep the existing controller lifecycle when these settings are absent.

Keep stopped original endpoints for rollback. To revert, stop the shared
websites before restarting the old ones, restore their domain upstreams and
restart the original caretaker. Never run two website instances writing the same
application volume. Original filesystems and buckets must remain intact.

## November 2 cutover verification

Both public domains now route to `shared-demos-20261102-v2`. The original
website, caretaker and cooling endpoint definitions remain stopped for rollback.
Two independently downloaded backup sets passed archive and per-file checksum
checks, with consistent SQLite copies. The original persistent filesystems and
training bucket were retained.

Checks preserved 77 Haunted saves, 24 score records (six ranked entries),
27 training jobs and 17 finished Cube races. Both public APIs returned the
original leaderboard and saved results. An existing checkpoint passed identity,
hash and real inference checks; cooling profile checks passed. Twenty parallel
health requests passed through each verification run. This was a migration check,
not a new full training-and-escape playthrough or a new gameplay capacity test.

The change passed 182 backend tests and seven edge tests. A local container check
also confirmed that a failed website process restarts without stopping the other
website. Non-GPU CPU usage fell from 8/8 to 2/8; VM and disk usage each fell from
4/4 to 2/4. Snapshot usage remains 0/1. PostHog remains on PostHog Cloud.
