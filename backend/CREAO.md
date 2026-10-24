# Kontrol Agents — CREAO integration

Kontrol runs four published agents:

1. Incident Intake
2. Hospital Finder and Dispatch Finder in parallel
3. Response Planner after both parallel stages complete successfully
4. Coordinator approval before any assignment

PostgreSQL owns reports, resource availability, plans, decisions, and execution state. Agent output is advisory and schema-validated.

## Configuration

```dotenv
CREAO_MODE=live
CREAO_BASE_URL=https://agent.creao.ai
CREAO_API_VERSION=v1
CREAO_API_KEY=
CREAO_INPUT_FIELD=context
CREAO_INVOKE_PATH=/api/v1/runs
CREAO_POLL_PATH=/api/v1/runs/{run_id}
CREAO_POLL_SECONDS=5
CREAO_INTAKE_AGENT_ID=
CREAO_HOSPITAL_AGENT_ID=
CREAO_DISPATCH_AGENT_ID=
CREAO_PLANNING_AGENT_ID=
```

The four IDs are the agents' published `appId` values. CREAO's currently documented API Trigger uses `POST /api/v1/runs` and `GET /api/v1/runs/{id}`. A prior product brief mentioned v2, but its request body and result envelope were not publicly documented or observed, so the adapter deliberately does not guess them. Endpoint paths remain configurable once a v2 tenant contract is verified.

Polling honors `Retry-After` and applies bounded backoff for HTTP 429 responses. Retrying a failed local execution reuses its existing CREAO run ID when one was already created, avoiding duplicate paid work.

## Inputs

Each invocation sends only the exact stage input as a JSON string in the configured form field. Agent instructions and output behavior remain owned by the published CREAO agents.

Intake receives only the resident report fields required by its contract. Hospital Finder receives incident location, intake requirements, search radius, and any real operator-confirmed hospital statuses. Dispatch Finder receives incident location, required response types, search radius, and available Kontrol vehicles (including the six opt-in hackathon units when `DEMO_FLEET_ENABLED=true`). Response Planner receives validated results only after both Hospital and Dispatch complete successfully.

Historical exercise hospitals and vehicles are supplied only in `CREAO_MODE=mock`; the explicitly enabled six-unit hackathon fleet is the sole live-mode exception.

## Outputs

The exact models live in `app/response_schemas.py`. The adapter first downloads and validates an authenticated `application/json` artifact from the configured CREAO HTTPS origin. If no valid JSON artifact is present, it accepts:

- a JSON object in a documented structured result field;
- a JSON string in `result.text` or `result.chatText`;
- JSON wrapped in one Markdown ```json fence.

For textual results and artifact downloads, the parser also accepts one unambiguous fenced JSON block surrounded by prose. Artifact downloads support this even if the response is labeled `application/json`. Ambiguous multiple blocks are rejected; provider-specific field names are not translated. Every parsed object is validated against its stage model. The complete credential-free run response is stored on `agent_runs.raw_response` for coordinator debugging.

Hospital coordinates, travel times, source URLs, and numeric values are validated. Missing travel estimates fall back to Kontrol's Haversine-based coordinate approximation. Agent-discovered hospital capacity never overwrites operator-confirmed capacity. Dispatch recommendations must reference currently available vehicle IDs already stored in Kontrol.

## Failure and approval behavior

Hospital and Dispatch run concurrently. Planning waits for both validated outputs. A failed upstream stage blocks planning until it is recovered. Discovered facilities with unknown coordinates are retained, but omitted from map markers. Plans needing more information appear in the coordinator review queue with approval disabled.

A plan with missing information cannot be approved. Approval locks and rechecks vehicle availability and confirmed hospital capacity, creates simulated dispatch assignments and internal communications, and starts deterministic map movement. Kontrol never sends real dispatch messages.

## Inspection

Print a stage schema inside the backend container:

```sh
python -c 'import json; from app.response_schemas import stage_schema; print(json.dumps(stage_schema("intake").model_json_schema(), indent=2))'
```

Replace `intake` with `hospital`, `dispatch`, or `planning`.

### Resource input isolation

Only Dispatch Finder receives `available_vehicles`. Intake reads only the incident report fields; Hospital Finder receives incident requirements and hospital statuses, with no fleet query or fleet snapshot. Response Planner receives the three validated agent results, including Dispatch recommendations, rather than the raw fleet. Planning retains a local resource snapshot for database validation; that snapshot is never serialized into the CREAO request. The `agent_input` field in a stored job is the exact context sent to CREAO.
