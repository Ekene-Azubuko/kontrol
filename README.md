# Kontrol

Kontrol is an AI-assisted emergency response planning application. A resident submits an incident, Kontrol Agents prepare a response recommendation, and a coordinator reviews it before any resources appear on the live map.

| Surface | Name |
| --- | --- |
| Product / repository | Kontrol / `kontrol` |
| Application title | Kontrol \| Emergency Intelligence |
| Coordinator interface | Kontrol Command |
| Resident interface | Kontrol Community |
| AI system | Kontrol Agents |

## Run locally

Copy `.env.example` to `.env`, add the CREAO API key and four published agent IDs, then run:

```sh
docker compose up --build
```

Open the resident portal at <http://localhost:3000/resident/report>, Kontrol Command at <http://localhost:3000/coordinator/overview>, or the API docs at <http://localhost:8000/docs>.

There is no login or account-management screen. The local deployment assigns an internal resident or coordinator identity from the selected portal. This is suitable only for a trusted hackathon environment; add a production identity provider before exposing coordinator routes publicly.

The API runs migrations and its idempotent bootstrap automatically. PostgreSQL persists in the `postgres_data` volume. Street tiles require internet access to `tiles.openfreemap.org`.

## Live workflow

1. A resident reports an incident and places the location pin.
2. The intake agent interprets the report and identifies required response types. The resident-provided coordinates remain authoritative.
3. Hospital Finder researches nearby facilities while Dispatch Finder evaluates real Kontrol fleet records and discovers nearby emergency facilities in parallel.
4. The planning agent receives the three validated results and proposes assignments and destinations.
5. Server-sent events display the plan in Kontrol Command without a refresh and open its review panel.
6. Only coordinator approval creates dispatch assignments and adds the incident, chosen hospitals, vehicles, and routes to the map.
7. The command map can show all ongoing responses or one incident response at a time.

PostgreSQL—not agent memory—is authoritative. Agent output is schema-validated, and approval rechecks current vehicle and hospital capacity under database locks.

## CREAO configuration

Live mode is the default. Configure:

```dotenv
CREAO_MODE=live
CREAO_API_KEY=
CREAO_INTAKE_AGENT_ID=
CREAO_HOSPITAL_AGENT_ID=
CREAO_DISPATCH_AGENT_ID=
CREAO_PLANNING_AGENT_ID=
CREAO_API_VERSION=v1
CREAO_INPUT_FIELD=context
CREAO_INVOKE_PATH=/api/v1/runs
CREAO_POLL_PATH=/api/v1/runs/{run_id}
```

These are CREAO's currently documented and observed API Trigger routes. Although an earlier integration brief referenced `/v2/runs`, no public v2 request envelope was available to verify, so Kontrol does not guess one. Paths remain configurable for a verified tenant-specific contract. Kontrol sends only each agent's contract input. The adapter prefers the agent's authenticated JSON artifact, then falls back to structured results, JSON strings in `text` or `chatText`, and a single JSON Markdown fence. See [backend/CREAO.md](backend/CREAO.md). The deterministic mock adapter remains available for automated tests by setting `CREAO_MODE=mock`.

## Resource data

Hospital Finder may discover facilities independently. Kontrol stores their documented identity, coordinates, capabilities, and sources, but never treats agent-reported capacity as authoritative. Dispatch Finder may discover station locations, but can recommend only available vehicles already present in Kontrol. Historical seeded resources remain available only in mock mode, except for the explicitly enabled hackathon fleet described below.

Do not present fictional facilities or units as operational resources. Replace the bootstrap resource records with verified hospital and vehicle data before a real deployment.

## Architecture

```text
Next.js / TanStack Query / MapLibre
                 │ same-origin API proxy + server-sent events
                 ▼
FastAPI ─────────────────── PostgreSQL / PostGIS
                                   │ durable database jobs
                                   ▼
                         Python worker, two agent slots
                                   │
                              CREAO API

Intake ──┬── Hospital ──┬── Planning ── Coordinator approval ── Live map
         └── Dispatch ──┘
```

- `backend/app/worker.py`: durable stage orchestration and concurrent hospital/dispatch evaluation.
- `backend/app/response_schemas.py`: strict agent input and output contracts.
- `backend/app/response_services.py`: validation, plan versions, and atomic coordinator decisions.
- `frontend/components/report-flow.tsx`: resident report intake and map pin.
- `frontend/components/coordinator.tsx`: real-time review popup, approval map, and response filter.

AI can propose classifications and actions, but cannot approve official actions, publish public updates, or assign resources. Resident reports and agent output are treated as untrusted input. Residents cannot access operational plans, fleet data, hospital data, or internal communications.

## Checks

```sh
docker compose exec backend pytest -q
docker compose exec backend ruff check .
cd frontend
npm run lint
npm run typecheck
npm run build
```

Browser tests should run with `CREAO_MODE=mock` against a disposable local database so they do not invoke paid agents or change live operational state.

## Current limitations

- The built-in portal identity switch is not production authentication.
- Vehicle positions advance through the application lifecycle; there is no GPS feed.
- ETAs use an illustrative distance calculation rather than road routing.
- Internal communications are database records; no external responder messaging service is connected.
- CREAO calls require tenant-level verification with your published agents.

### Hackathon vehicle fleet

Set `DEMO_FLEET_ENABLED=true` in `.env` and run `docker compose up -d --build`. Startup adds six fleet units to PostgreSQL: two ambulances, two police vehicles, a fire engine, and a rescue unit around central San Francisco. Only these units are enabled in live Dispatch inputs and coordinator resource views; hospitals and incident reports are not simulated by this setting. CREAO continues to run live. Fleet records retain simulation provenance internally without extra UI banners.

Seeding is repeatable and preserves availability, active assignments, and positions. Busy units are excluded from Dispatch input. Set the flag to `false` to exclude the demo fleet again. Existing agent runs retain their original input snapshots; request a plan revision or submit a new report to use the fleet. No new migration is required. Hospital capacity constraints still apply independently.
