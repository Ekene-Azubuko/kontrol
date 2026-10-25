# Kontrol — current codebase context

Snapshot: October 25, 2026. Based on the current repository and a read-only inspection of the local Compose deployment. Read this file with `AGENTS.md`, `README.md`, and `backend/CREAO.md` before making changes. Source code is authoritative if behavior changes later.

## Product and current scope

Kontrol is a hackathon **call-intake dispatcher co-pilot** supporting uploaded recordings and optional live inbound phone calls for simulated emergency-response exercises in San Francisco. The dispatcher uploads a recording or answers through the browser; separate batch and streaming transcription paths converge on location review, call type selection, and the existing four-agent response workflow. A human approves assignments before simulated resources move.

- Product/repository: **Kontrol / kontrol**.
- Application title: **Kontrol | Emergency Intelligence**.
- Dispatcher interface: **Kontrol Command**.
- AI system: **Kontrol Agents**.
- Main entry for the workflow: `/coordinator/calls`; `/` redirects to `/coordinator/overview`.
- There is no login/signup screen. The trusted local UI uses the built-in `demo-coordinator` identity. Server authorization still checks the persisted `coordinator` role.
- The old resident portal, public report submission, public updates, subscriptions, and resident assistant are retired. Historical records/tables remain. Do not rebuild around the old resident-report workflow or send users to `/resident/report`.
- Current code and docs present the application as **SIMULATION / NOT FOR EMERGENCY USE**. It sends no real dispatch messages and provides no medical instructions.

## Stack and ownership

| Layer | Implementation |
| --- | --- |
| Frontend | Next.js App Router, React, TypeScript, Tailwind CSS, Radix UI, Lucide icons |
| Frontend data | TanStack Query; same-origin `/api/*` proxy; authenticated SSE invalidation |
| Map | MapLibre GL with OpenFreeMap street tiles |
| API | FastAPI, Pydantic, SQLAlchemy |
| Database | PostgreSQL/PostGIS; Alembic migrations through `0007` |
| Worker | Python; database-backed jobs, one batch transcription slot, two agent slots, and separate live finalization |
| Agent provider | Deterministic mock adapter or live CREAO v1 adapter |
| Transcription | Mock bundled-sample adapter or configured live transcription provider |
| Storage | `postgres_data` volume and private shared `call_audio` volume |
| Deployment | Separate frontend, backend, worker, and database services; optional signed-only phone ingress |

PostgreSQL owns recordings' metadata, reports, incidents, agent runs, plans, resource availability, assignments, and audit history. CREAO memory is never authoritative. Private audio storage keys and worker lease tokens are excluded from call API responses.

## End-to-end workflow

```text
Recording → transcription + location detection → dispatcher selects call type
                                            → Intake
                                                 ├─ Hospital ─┐
                                                 └─ Dispatch ─┴─ Planning
                                                                  ↓
                                                        dispatcher approval
                                                                  ↓
                                                       simulated map response
```

1. Upload fictional audio or load a bundled sample. WAV, MP3, WebM, and Ogg are supported; actual media/duration are checked with FFprobe. Limits default to 20 MiB and five minutes.
2. A durable worker claim transcribes the recording and detects its location. Call states are `queued → transcribing → awaiting_review → confirmed`, with a separate `failed` path.
3. The UI flies the map to the detected incident location and drops a pin. Call type is the only required form input, but agents cannot start until location resolves.
4. Before starting, the dispatcher may use **Edit address** and **Find location again**. A failed correction removes the previous pin. A successful retry replays the animation even for unchanged coordinates. Edits preserve the original transcript and are version-checked and audited.
5. **Start agents** atomically creates a Report, Incident, and ResponsePlan from server-owned transcript/location data, then queues Intake.
6. Intake completes; Hospital and Dispatch run in parallel. Planning waits for both validated outputs. An upstream failure blocks Planning.
7. Suggested plans appear automatically in Command and Response Plans. Review shows compact location/patient/bed/travel checks, with narratives, constraints, alternatives, and provenance expandable.
8. Human approval creates assignments and internal communication records. The map shows approved ongoing responses, filterable together or individually. Approved markers remain stationary. The response stays approved/assigned; no timer fabricates travel, arrivals, occupancy changes, completion, or unit release.

SSE currently emits content-free refresh events approximately every two seconds. The frontend invalidates query data, reconnects when needed, and has a 15-second polling fallback. Browser refresh is not required for progress or plan arrival.

## Location and provenance rules

- Keep caller-device coordinates separate from the inferred incident location. Device coordinates are never a fallback incident pin and are excluded from agent context.
- The legacy input key `confirmed_location` now normally carries **automatically inferred, unverified** coordinates. Its name does not mean a human verified the location.
- Bundled exercise phrases resolve locally. Spoken intersections use the official San Francisco street-node dataset and cached street directory. Other explicit numbered addresses can use configurable Photon geocoding restricted to San Francisco.
- Intersection matching handles filler words, spacing/punctuation, and one unique character edit/transposition in a sufficiently long street name when the other street matches exactly. Ambiguous matches stay unresolved.
- Only extracted/normalized address or street text reaches public lookup services, not the entire transcript. Requests are bounded; directory caching is per process, up to 24 hours.
- Original transcript, extracted evidence, address edits, inferred coordinates, and verification uncertainty are preserved separately.
- Patient counts are transcript-derived **unconfirmed estimates**. Unknown means `null`, never an invented zero.

## Four agents and current contracts

Exact output models: `backend/app/response_schemas.py`. Unexpected fields are rejected, including nested fields. Do not disable validation to accommodate conversational or incomplete output.

### Intake

Current input is exactly:

```json
{
  "incident_id": "SOURCE_REPORT_ID",
  "transcript": "Original machine transcript",
  "confirmed_location": {
    "address": "Detected incident address",
    "latitude": 37.7787,
    "longitude": -122.4148
  },
  "call_received_at": "ISO-8601 timestamp",
  "category": "collision"
}
```

`incident_id` is the **Report ID**, not the Incident table ID. All four agents must echo it unchanged. The former Intake input with `description`, `location`, and a separately supplied injury count is obsolete for new jobs.

Output includes `incident_id`, `incident_type`, `summary`, nullable `reported_injuries`, `required_response_types`, and `reasoning`; optional `limitations`, completion `status` (`complete`, `completed`, or `success`), `caller_stated_location`, and `key_statements` are supported. Injury counts are integers 0–100 or null. Intake receives no fleet or hospital snapshots.

### Hospital Finder

Input: incident ID/type, location object, nullable reported injuries, required capabilities, search radius (15 miles), and known hospital statuses. **No fleet.** Null injuries are valid input, not a reason to ask a follow-up question.

Output: `incident_id`, `hospitals`, `recommended_hospitals`, `reasoning`, optional `limitations`. Each hospital contains name/address, required coordinates, documented capabilities, nullable bed/diversion/travel information, optional source URLs, and suitability notes. Recommendations reference returned hospital names. Top-level completion `status` is not part of this schema.

### Dispatch Finder

Input: incident ID/type, location, required response types, search radius (10 miles), and `available_vehicles`. **Only Dispatch receives the raw fleet.** Each vehicle includes ID, type, status, capabilities, base location, and current latitude/longitude. Busy/already-assigned units are excluded.

Output: `incident_id`, `recommended_vehicles`, `reasoning`, optional `discovered_facilities`, `unfilled_requirements`, and `limitations`. Recommended IDs must belong to supplied available units and cannot repeat. Facilities can have null coordinates; they remain in the result but are omitted from map markers. Discovered stations are not automatically available vehicles. Top-level completion `status` is not part of this schema.

### Response Planner

Input: `incident_id`, `intake_result`, `hospital_result`, `dispatch_result`. It receives Dispatch recommendations rather than the full fleet. Local worker resource snapshots are for validation and are not sent to CREAO.

Output: `incident_id`, `plan_summary`, `reasoning`, and `status` (`awaiting_approval` or `needs_information`), plus hospital/vehicle assignments, unmet requirements, constraints, and limitations. Supported metadata includes `schema_version`, `incident_type`, `location`, nullable `planned_patient_count`, and `vehicle_assignment_count`. Hospital assignments accept nullable `available_beds`; vehicle assignments accept nullable arrival estimates.

Assigned hospital names and vehicle IDs must come from upstream recommendations. A valid completed `needs_information` result is not an execution failure. Limitations survive into coordinator constraints.

## CREAO transport and recurring failure lessons

- Start runs with `POST /api/v1/runs` using `appId`, `inputs.context` containing a JSON string, and a job-derived `idempotencyKey`. The input field/path are configurable.
- Poll `GET /api/v1/runs/{run_id}`; default interval is two seconds. Polling honors rate limits/backoff and a configured timeout.
- Prefer the authenticated JSON artifact under `result.artifacts`. Inline `text` often contains only summary counts and lacks the required output fields. Fall back to `output`, `data`, `text`, or `chatText` only through schema validation.
- The parser supports bare JSON, JSON-string wrappers, one fenced JSON document surrounded by prose, and one unambiguous unfenced document following progress prose. It rejects malformed/ambiguous documents rather than inventing missing fields.
- Artifact downloads must use the configured HTTPS origin. Allowed AWS redirects use a clean client so CREAO credentials are not forwarded to storage.
- Raw run responses and remote execution IDs are saved on AgentRun. UI errors now identify invalid/missing schema fields without echoing provider values.
- Published CREAO instructions/manifests are external configuration. Changing repository code does **not** republish those agents. They must support the transcript contract and nullable injury counts.
- A provider response such as `{"response":"Please provide the injury count"}` is invalid Hospital output even if CREAO marks its run completed.
- Major prior schema fixes explicitly accepted Intake limitations/status and richer Planning metadata/nested ETAs. Keep those fields and strict reference checks.
- Remote execution/research usually dominates latency. See `backend/CREAO_PERFORMANCE.md`; lowering polling delay cannot speed up remote reasoning.

## Approval and resource semantics

- **Approve plan remains enabled for `needs_information` plans.** The UI only disables it during an action. An approval note is optional; the UI supplies an audit note if needed. Revision/rejection still require a note.
- Explicit constrained approval accepts missing information and preserves recorded uncertainty. It does not bypass role checks, stale-version protection, nonexistent/duplicate resource checks, busy vehicles, known diversion, or known capacity limits.
- Unknown dispatch patient counts remain null. Approval creates static vehicle assignments, with no bed reservations, messages, arrivals or completion events. Legacy lifecycle columns remain for schema compatibility.
- Hospital discoveries are stored before Planning and missing records can be recovered during retries from validated upstream output. Agent-reported capacity never overwrites operator-owned hospital counts.
- Startup creates no hospital network or old SIM fleet. Mock mode, or live mode with `DEMO_FLEET_ENABLED=true`, seeds only six repeatable units: two ambulances, two police vehicles, one fire engine, one rescue unit. Seeding preserves assignments and positions.
- Hospital Network, Communications and community Resources pages/routes are retired. Hospital agent receives no locally invented capacity statuses. A mock-only real facility reference provides unknown beds/diversion when the database has no hospitals. `app.cleanup_legacy` explicitly removes the retired test dataset while preserving non-sample calls and their workflows.

## Reopen, retry, delete: distinct behaviors

| Action | Behavior |
| --- | --- |
| Retry failed transcription | Explicit bounded retry of a failed transcription job; claim tokens prevent stale results from overwriting it |
| Retry failed agent stage | Reuses its saved remote CREAO run if present; useful after local parser/schema fixes; cannot regenerate an already-invalid provider result |
| Back to call type | Reopens an unapproved response on the same recording, preserving transcript/location and historical attempts; returning itself calls no provider |
| Start agents after reopening | Creates fresh Report/Incident/Plan/job IDs and new CREAO execution IDs; old unfinished stages are cancelled and late results ignored |
| Delete recording | Version-checked, dispatcher-only deletion of call queue entry/private audio; preserves downstream reports/plans/assignments/history and does not cancel an ongoing response |

Approved/dispatched responses cannot be reopened. Deletion invalidates transcription claims; durable deletion markers permit retrying failed file cleanup. Reset cancels exercise work and invalidates claims while preserving historical provenance.

## Files to know

| Area | Files |
| --- | --- |
| API/roles/events | `backend/app/main.py`, `dependencies.py`, `response_api.py` |
| Call upload/start/review | `call_api.py`, `call_services.py`, `call_audio.py`, `call_worker.py` |
| Transcription and samples | `transcription.py`, `sample_calls.py`, `fixtures/calls/*.wav` |
| Location | `call_location.py`, `street_intersections.py`, `street_directory.py` |
| Call reopening/deletion | `call_reopen.py`, `call_delete.py` |
| Agent pipeline/transport | `worker.py`, `creao.py`, `agent_errors.py`, `mock_response.py` |
| Contracts/approval | `response_schemas.py`, `response_services.py` |
| Resources/lifecycle | `hospital_discovery.py`, `network.py`, `demo_fleet.py`, `response_seed.py` |
| Database | `models.py`, `db.py`, `backend/alembic/versions/0001…0007` |
| Frontend shell/calls | `frontend/components/workspace.tsx`, `calls.tsx`, `call-location.tsx`, `startup-screen.tsx` |
| Command/review/map | `coordinator.tsx`, `response-plans.tsx`, `network.tsx`, `map.tsx` |
| Review presentation | `frontend/lib/plan-review.ts` and its browser/logic tests |
| Frontend API/types | `frontend/lib/api.tsx`, `types.ts`, `response-types.ts`, `frontend/app/api/[...path]/route.ts` |

Frontend hospital comparison defaults to nearest first. Numbered pins retain proximity rank; list/pin selection is synchronized. Nearest/farthest/agent-recommended sorting is available. Straight-line miles are calculated from coordinates, separately from travel estimates and clinical suitability. Plan review deduplicates exact repeated notes for display while preserving saved agent output.

A startup truck animation runs once per full page load, supports immediate entry and reduced motion, and exits after a bounded delay. Sidebar navigation does not replay it.

## Setup and test scenario

```sh
# From the repository root; do not overwrite an existing configured .env:
cp .env.example .env
docker compose up --build -d
```

Defaults are `CREAO_MODE=mock` and `TRANSCRIPTION_MODE=mock`, which need no credentials. Migrations and bootstrap run automatically. Open `http://localhost:3000/coordinator/calls`; load **Multi-vehicle collision**, wait for transcription and location, select collision, then Start agents and review/approve the proposed response. Other bundled samples are **Reported cardiac arrest** and **Structure fire**; the latter intentionally exercises an unknown injury count. Mock transcription recognizes bundled samples only; use live transcription for other fictional uploads.

Existing `.env` settings override defaults. Live CREAO needs its key and four published app IDs, `CREAO_API_VERSION=v1`, correct invoke/poll paths, and `LIVE_SIMULATION_ENABLED=true` for these fictional calls. Live transcription has separate credentials/model/base URL. Keep secrets server-side. Audio fixtures ship with the repo; regenerating them is optional and requires macOS `say` plus FFmpeg.

For frontend hot reload, stop the Docker frontend, leave database/API/worker running, then run `npm ci` and `API_INTERNAL_URL=http://127.0.0.1:8000 npm run dev` from `frontend/` with Node 22. API docs are at `http://localhost:8000/docs`.

```sh
docker compose exec backend ruff check .
docker compose exec backend pytest -q
cd frontend
npm run lint
npm run typecheck
npm run build
```

Run the full Playwright suite only against a **disposable mock deployment** because tests reset exercise state. PostgreSQL integration/concurrency/migration tests require `TEST_DATABASE_URL` targeting the explicitly disposable `kontrol_response_test` database; they skip when it is absent. See README for exact commands. Avoid deleting persistent volumes casually.

## Snapshot status and limits

After the live-call implementation, the local frontend, API, worker, database and signed-only phone ingress were healthy; migration `0007` was applied. Existing local batch/CREAO settings were preserved. Telephony remains disabled until Twilio/OpenAI streaming credentials and the public ingress origin are configured. Verification covered 211 backend tests (14 PostgreSQL tests skipped in that run), a separate 14-test PostgreSQL run, 23 browser tests, lint, TypeScript and production builds. Protocol tests do not establish actual phone connectivity; no provider-backed phone call has been performed.

Uploaded recordings still use the original batch adapter. Live inbound phone calls use Twilio and independent OpenAI Realtime transcription; actual phone connectivity requires the provider setup and a real test call in `backend/LIVE_CALLS.md`. It has no production identity system, CAD/AVL/GPS integration, external responder messaging, verified emergency geocoding, or operational hospital-capacity feed. Vehicle markers remain stationary and ETAs are advisory; destinations are advisory. Preserve unknowns and provenance. Future development must follow `AGENTS.md`, inspect current code, and test the affected vertical slice rather than assuming old conversation behavior still applies.

## Additive live-call implementation (October 25, 2026)

- Existing batch provider, model, API calls and retry behavior are preserved; batch claims now explicitly select `source=recording`. Never send live calls through batch ASR or uploads through Realtime.
- `source=live` calls have a linked `LiveCallSession` and timestamped `LiveTranscriptSegment` rows. Twilio Voice SDK connects actual browser/caller audio; signed Media Streams fork inbound/outbound tracks to separate OpenAI transcription-only WebSockets. Separate `LIVE_TRANSCRIPTION_*` settings do not replace `TRANSCRIPTION_*`.
- Answer and hang-up never create agent jobs. Backend readiness checks require provider-ended and persisted-finalized state even if a caller forges `awaiting_review`. After finalization, existing location detection, address correction, category selection, Start Agents, planning and approval are reused.
- Streaming errors leave phone audio connected. Finalization reconciles only final segments. Missing frames/results/streams and empty or oversized text require explicit audited incomplete-transcript resolution after hang-up. Raw segment history is retained.
- Phone controls/device state live in a root provider across navigation. The Calls screen retains all upload/sample tools and adds connection, answer/decline, microphone mute, hang-up, timer and transcript controls. Existing SSE refresh drives updates.
- `phone-ingress` is an optional Compose profile (`--profile phone`) on localhost:8001. Tunnel this signed-only app, not the trusted local dispatcher API. Incoming-only short-lived Voice tokens and private recordings are inaccessible on public ingress.
- Main files: `telephony_provider.py`, `telephony_api.py`, `telephony_ingress.py`, `live_media.py`, `live_transcription.py`, `live_calls.py`, `live_worker.py`, migration `0007_live_calls.py`, `frontend/lib/live-phone.tsx`, and `frontend/components/live-phone.tsx`.
- Phone support defaults off; existing `.env` files are preserved. Full provisioning, webhook, OpenAI, optional replay recording and real-call instructions are in `backend/LIVE_CALLS.md`. Provider-backed connectivity must not be claimed based on protocol mocks.


## Approved response display

Approval displays incident, assigned-vehicle and selected-hospital markers only. The timed dispatch simulator and marker interpolation were removed, along with response route lines, travel progress bars, and the unused DISPATCH_STAGE_SECONDS setting. Existing historical statuses remain readable; new approved responses stay approved/assigned until an explicit subsequent action. Location detection and startup animations are separate features.
