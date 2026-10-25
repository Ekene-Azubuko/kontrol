# Kontrol

**SIMULATION (NOT FOR EMERGENCY USE)**

Kontrol is a simulated 911 dispatcher co-pilot. Load a recorded call, let Kontrol locate the incident from the transcript, and select a call type before four agents draft a response. A dispatcher must approve the plan before simulated resources move. No real dispatch messages are sent.

## Run locally

Copy `.env.example` to `.env`, then run:

```sh
docker compose up --build
```

Open [Kontrol Command](http://localhost:3000/coordinator/calls). Load a sample call and wait for transcription. Kontrol automatically detects the spoken address, flies the map into the location, and drops the incident pin. Call type is the only required form input. Select **Start agents**, review the resulting plan, enter a decision note, and approve the simulated response. The Command map shows approved assignments and illustrative movement.

Before starting agents, use **Edit address** to correct a street address, intersection, or exercise landmark, then select **Find location again**. The same button also retries the current lookup without editing. Successful lookups replay the city zoom and pin drop, including when the coordinates are unchanged. An unresolved correction removes the previous pin and keeps Start agents disabled. The original transcript and audio stay intact; address edits and lookup results are audited. Editing is unavailable after agents have started.

To rerun an unapproved response, select **Back to call type** in the recording or response-plan review. This returns the same recording to the call-type form with its transcript and detected location intact. Choose a type and select **Start agents** to create a fresh workflow with new CREAO execution IDs. Returning alone makes no provider request. Previous reports, plans, outputs and errors remain in history; unfinished local stages are cancelled and late results are ignored. Approved or dispatched responses cannot be reopened. **Retry failed stage** in Agent Operations still resumes the existing remote execution and serves a different purpose.

To remove an uploaded or sample recording, select it in Recorded Calls and choose **Delete recording**, then **Delete permanently**. This removes the private audio and call-queue entry. Existing reports, response plans, agent jobs, assignments and communication history remain; deletion does not cancel an ongoing response. Deletion is dispatcher-only, version-checked and audited. In-flight transcription results are discarded. If storage cleanup fails, the recording is immediately inaccessible and the worker retries file removal from a durable deletion marker.

Both `CREAO_MODE=mock` and `TRANSCRIPTION_MODE=mock` work without credentials. Existing `.env` files retain their previous settings; set these two values to `mock` to run the credential-free exercise. Migrations and idempotent bootstrap run automatically. New installations start with an empty call queue and a fictional hospital/fleet network. Bundled audio needs no generation step.

The local application uses a built-in dispatcher identity, not a production login. The persisted role and URL prefix remain `coordinator` to preserve historical authorization. Resident routes and public submission, assistant, subscription, and update endpoints are retired. Historical tables and records are preserved.

## Workflow and architecture

```text
Next.js / TanStack Query / MapLibre
       │ same-origin multipart, audio, JSON and authenticated SSE
       ▼
FastAPI ─────────────────── PostgreSQL / PostGIS
   │                              │ durable claims and agent jobs
   └── private call_audio volume ──┤
                                  ▼
                         Python background worker
                       1 transcription + 2 agent slots
                                  │
                 mock adapters or configured live providers

Recording → transcription + location detection → dispatcher selects call type
 → Intake ──┬── Hospital ──┬── Planning → dispatcher approval → simulated map
            └── Dispatch ──┘
```

API, worker, frontend, and PostgreSQL run separately in Compose. PostgreSQL owns call status, reviewed text, incident state, claims, plans, availability, and audit history. Audio is private on the shared `call_audio` volume; storage keys never appear in API responses. Street tiles require internet access to `tiles.openfreemap.org`; the address and location-edit controls remain available if tiles fail.

Call states are `queued → transcribing → awaiting_review → confirmed`, or `failed`. Failed transcription can be retried explicitly up to three attempts. Expired claims fail for human retry. Late worker results cannot overwrite retries or revive reset exercises. Original machine text and approximate caller coordinates remain distinct from the automatically detected incident location. Caller-device coordinates are never used as a fallback incident pin.

Starting a call creates one Report, Incident, and Plan atomically from server-owned transcript and location metadata. Confirmed calls require the explicit, version-checked return-to-review action before editing or starting again. Each restart creates a new report, incident and plan; prior records are preserved and their IDs are linked in the reopen audit. Agents receive the transcript and inferred incident coordinates. Inference is explicitly marked as not human-verified. Unknown patient counts stay null and extracted counts remain unconfirmed estimates. Hospital suggestions are provisional. Approval rechecks resource availability and known capacity under locks; existing constrained approval remains explicit and audited. AI cannot verify incidents or approve assignments.

Plan review shows four compact checks for incident location, patient count, reported hospital beds, and travel estimates. Explicit unmet requirements and known vehicle/diversion conflicts remain visible. Full constraints, agent narratives, assignment rationale, and transcript provenance are expandable; the saved output and approval rules are unchanged. Only exact repeated notes are deduplicated in the display.

Agent responses remain strictly schema-validated even when CREAO surrounds its JSON result with progress prose. Ambiguous or malformed documents are rejected. Schema errors identify missing or invalid contract fields; formatting-only failures can resume the saved remote run after an adapter fix through **Retry failed stage**.

The hospital comparison defaults to nearest first, with numbered map pins matching the list. Distances are calculated from incident and hospital coordinates and labeled **straight-line miles**, independently of agent prose or travel estimates. Sort by nearest, farthest, or the agent's explicit recommendation list. Pin numbers always retain proximity order, and selecting a pin or list entry highlights the same hospital. Agent choice, estimated travel method, unknown beds/diversion, and expanded suitability/source details stay separate. Proximity does not imply clinical suitability or a confirmed receiving destination.

## Audio and live providers

| Variable                    | Default / purpose                                                                                       |
| --------------------------- | ------------------------------------------------------------------------------------------------------- |
| `TRANSCRIPTION_MODE`        | `mock`; `live` sends audio to the configured provider                                                   |
| `TRANSCRIPTION_API_KEY`     | Empty; server-only live provider credential                                                             |
| `TRANSCRIPTION_BASE_URL`    | `https://api.openai.com/v1`                                                                             |
| `TRANSCRIPTION_MODEL`       | `gpt-4o-mini-transcribe`; configurable                                                                  |
| `TRANSCRIPTION_TIMEOUT`     | 60 seconds per network operation; claim lease adds 30 seconds                                           |
| `CALL_AUDIO_DIR`            | `/app/call_audio` inside API and worker containers                                                      |
| `CALL_MAX_AUDIO_BYTES`      | 20971520 (20 MiB)                                                                                       |
| `CALL_MAX_DURATION_SECONDS` | 300 (five minutes)                                                                                      |
| `CALL_INTERSECTIONS_URL`    | Official SF street-intersection dataset endpoint; set empty to disable cross-street lookup              |
| `CALL_GEOCODING_URL`        | `https://photon.komoot.io/api/`; set empty to disable external address matching                         |
| `CREAO_MODE`                | `mock`; four published agent IDs and credentials required for `live`                                    |
| `CREAO_POLL_SECONDS`        | `2`; seconds between remote completion checks (minimum 1); increase if status requests are rate-limited |
| `LIVE_SIMULATION_ENABLED`   | `false`; explicitly enable fictional calls with live CREAO execution                                    |

Uploads must be decodable audio-only WAV, MP3, WebM, or Ogg. `ffprobe` checks actual media format and duration with a bounded timeout and local-file-only protocols. Optional multipart fields are `caller_latitude`, `caller_longitude`, and `caller_accuracy_m`. The call screen offers an optional address editor; the transcript and coordinates remain read-only. An unclear location leaves Start agents disabled. Mock transcription only recognizes injected bundled samples; arbitrary uploads fail with an actionable message instead of receiving fabricated text. Use live transcription for other fictional recordings.

Authenticated `POST /calls/{id}/locate` accepts `{version, address?}`. Address text is trimmed and limited to 160 characters. Omitting it retries the last dispatcher-entered address, or the original transcript if no correction exists. Location lookup runs outside database locks and saves only if status and version still match; stale edits, reset races, and already-started calls return `409`. Retrying advances the version even when results are identical. Location retries invoke neither transcription nor agents. Coordinates inferred from edited text remain explicitly unverified in the plan and its revisions.

The three scripted locations resolve locally from their spoken phrases using the exercise gazetteer, without network access. Spoken intersections such as “the intersection of Greenwich and Van Ness” or “What is your location? Um, Vaness and Union” resolve against [San Francisco’s official street-intersection dataset](https://data.sf.gov/d/gmfx-8h6i). The resolver recognizes short location answers, ignores filler words, and normalizes spacing and punctuation against the city's street directory. It tolerates one uniquely matching character edit or adjacent transposition in a name of at least five letters, requires the other street to match exactly, and respects explicitly spoken street types. Both normalized streets must share one unique city street node. Ambiguous spellings or two misspelled streets remain unresolved. The original transcript and extracted evidence retain the caller's words; the displayed address uses canonical street names.

Street names are cached in each process for a daily refresh period (up to 24 hours), so subsequent calls need only the shared-node lookup. Failed directory requests are not cached. Requests have bounded time, response size, and row counts; partial datasets are rejected. Only normalized street names reach the public location service, never the full transcript. Other explicit numbered street addresses can use the documented [Photon search API](https://github.com/komoot/photon/blob/master/docs/api-v1.md), sending only the extracted address. Matching is restricted to the San Francisco exercise area and requires one matching address; absent, conflicting, out-of-area, or ambiguous locations stay unavailable. Set `CALL_GEOCODING_URL` or `CALL_INTERSECTIONS_URL` to compatible private endpoints or empty to disable the corresponding lookup. Public services have no availability guarantee and are for light demo use. Existing unconfirmed calls with no location metadata gain it automatically without retranscribing their original audio.

The camera flies in for 2.4 seconds before the pin drops with a pulse. Reduced-motion preferences use an immediate camera change and static pin. Tile failure does not prevent the detected address from appearing.

The live adapter uses the documented multipart `POST /audio/transcriptions` request with `file`, `model`, and `response_format=json`, validates bounded text, and hides provider errors and credentials. See the [OpenAI transcription reference](https://developers.openai.com/api/reference/resources/audio/subresources/transcriptions/methods/create). Compatible providers must implement that contract; changing a URL alone does not guarantee compatibility. Transcript text is limited to 4,000 characters and never silently truncated.

Set live credentials only in environment variables. Update the published CREAO Intake agent to the transcript contract in [backend/CREAO.md](backend/CREAO.md) before setting `CREAO_MODE=live`. Live smoke tests are opt-in and may incur provider charges. Mock CREAO can be combined with live transcription independently.

Hospital and Dispatch already run in parallel. Live latency is usually dominated by remote agent execution, especially repeated facility research and lengthy outputs. Two-second polling reduces completion handoff delay, but the larger improvement requires changes to the published CREAO agents. [Reducing live agent latency](backend/CREAO_PERFORMANCE.md) provides copyable instructions for concise output, supplied-data-only Intake/Dispatch/Planning, and focused Hospital research. Repository changes do not republish external agents. Apply configuration changes with `docker compose up --build -d backend worker` when no agents are running.

Three fictional scripts and spoken recordings ship in `backend/app/fixtures/calls`. Each starts with a simulation notice. Maintainers can regenerate the bundled 16 kHz mono WAVs on macOS with `python3 backend/scripts/generate_call_audio.py` (requires `say` and FFmpeg); users do not need these host tools. Audio persists alongside the database until its recording is deleted or the local exercise volumes are explicitly removed. Demo reset preserves historical call/audio/review records, cancels exercise work, and invalidates transcription claims; load a new sample afterward.

## Checks

```sh
docker compose exec backend pytest -q
docker compose exec backend ruff check .
cd frontend
npm ci
npm run lint
npm run typecheck
npm run build
BASE_URL=http://127.0.0.1:3000 npx playwright test
```

Run browser tests only against a disposable mock deployment: they reset exercise state. Use a separate Compose project and free ports, for example:

```sh
CREAO_MODE=mock TRANSCRIPTION_MODE=mock BACKEND_PORT=8100 FRONTEND_PORT=3100 \
  docker compose -p kontrol-call-test up --build -d
```

PostgreSQL concurrency and migration tests require the explicitly disposable database name `kontrol_response_test`:

```sh
docker compose exec db createdb -U kontrol kontrol_response_test
docker compose exec -e TEST_DATABASE_URL=postgresql+psycopg://kontrol:local-simulation-only@db:5432/kontrol_response_test backend pytest -q
```

Use the configured PostgreSQL password if different from the example. These tests create and remove tables only in that named test database. They are skipped without `TEST_DATABASE_URL`.

## Limitations

This version processes completed recordings, not live calls. That sequencing is a demo choice, not a model of a particular emergency center's procedures. It does not provide medical instructions, validated emergency addresses, real caller location, CAD integration, or real dispatch. Vehicle movement and ETAs are illustrative coordinate calculations. Hospital destinations are advisory and do not establish patient disposition or verified capacity.

The application is for trusted local fictional exercises. Real recordings, production authentication, retention/deletion policy, center-specific protocols, and external integrations require a separate operational-pilot design. No fictional data should be used for real-world emergency guidance.

### Startup animation

A white loading screen appears once per full page load, with a moving fire truck, a progress bar, and KONTROL beneath it. It observes font and initial workspace-query readiness, allows immediate entry via **Enter workspace**, and automatically exits after at most 6.5 seconds plus the fade. Sidebar navigation does not replay it. Reduced-motion preferences skip the animation.

The animated truck is a bundled vector illustration; the intro requires no external model, third-party requests, or WebGL. The progress bar represents workspace preparation.
