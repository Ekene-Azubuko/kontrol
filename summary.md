# Kontrol — frontend teammate handoff

Kontrol turns resident incident reports into AI-assisted response plans. Residents use **Kontrol Community** to report an incident; coordinators use **Kontrol Command** to review the agents' recommendations and approve assignments. The application title is **Kontrol | Emergency Intelligence**.

## Set up locally

You need Docker Desktop running, Docker Compose, internet access, and access to the team's four published CREAO agents. Node.js 22 is needed only if you want to run the frontend outside Docker for hot reload.

1. Clone the team's `kontrol` repository and open its root directory.
2. Create your local environment file if you do not already have one:

   ```sh
   cp .env.example .env
   ```

3. Get the CREAO API key and agent IDs from the team and fill these values in `.env`. Do not commit credentials:

   ```dotenv
   APP_ENV=development
   DEMO_AUTH=true
   CREAO_MODE=live
   CREAO_BASE_URL=https://agent.creao.ai
   CREAO_API_KEY=<team API key>
   CREAO_INTAKE_AGENT_ID=<intake agent ID>
   CREAO_HOSPITAL_AGENT_ID=<hospital agent ID>
   CREAO_DISPATCH_AGENT_ID=<dispatch agent ID>
   CREAO_PLANNING_AGENT_ID=<planning agent ID>
   CREAO_API_VERSION=v1
   CREAO_INPUT_FIELD=context
   CREAO_INVOKE_PATH=/api/v1/runs
   CREAO_POLL_PATH=/api/v1/runs/{run_id}
   DEMO_FLEET_ENABLED=true
   LIVE_SIMULATION_ENABLED=false
   ```

   Keep the other `.env.example` defaults. `DEMO_FLEET_ENABLED` enables only the hackathon vehicles; it does not replace live CREAO execution or populate fictional hospital capacity. `LIVE_SIMULATION_ENABLED` is a separate legacy report-replay switch and should stay off.

4. Build and start the app:

   ```sh
   docker compose up -d --build
   docker compose ps
   ```

   Wait for the services to become healthy. Compose runs Next.js, FastAPI, the background worker, and PostgreSQL/PostGIS separately. Database migrations and repeatable startup seeding run automatically; no manual migration is needed.

5. Open these pages:

   | Page | URL |
   | --- | --- |
   | Resident report portal | http://localhost:3000/resident/report |
   | Command overview and live response map | http://localhost:3000/coordinator/overview |
   | Response plans | http://localhost:3000/coordinator/response-plans |
   | Agent execution details | http://localhost:3000/coordinator/agents |
   | Vehicle fleet | http://localhost:3000/coordinator/dispatch |
   | Hospitals | http://localhost:3000/coordinator/hospitals |
   | Backend API docs | http://localhost:8000/docs |

There is no login/signup UI. Opening a portal selects its built-in local identity. This is a trusted hackathon setup, not production authentication. Resident views do not expose coordinator plans or resource information.

Data persists in Docker's `postgres_data` volume. `docker compose down` stops the stack without deleting it. Avoid `docker compose down -v` unless you intentionally want to delete local data. Docker frontend builds do not hot reload; rebuild after changes or use the development setup below.

### Frontend development with hot reload

Start the backend services through Compose and run Next.js locally:

```sh
# From the repository root:
docker compose stop frontend
docker compose up -d db backend worker
cd frontend
npm ci
API_INTERNAL_URL=http://127.0.0.1:8000 npm run dev
```

Open the same localhost:3000 pages. The server-side Next.js proxy forwards `/api/*` requests to FastAPI. CREAO secrets belong in the backend environment, not browser code or `NEXT_PUBLIC_*` variables.

## How the app works

1. **Resident submits a report.** The three-step form collects the observation, injury count, address, and map pin, then shows a receipt and status. Photos and observation time are optional. Entering an address alone does not move the pin: click the map or enter latitude/longitude. The submitted coordinates anchor the incident.
2. **Intake runs.** It classifies the observation, summarizes it, preserves reported injuries, and identifies required response types.
3. **Hospital Finder and Dispatch Finder run in parallel.** Hospital Finder researches nearby hospitals. Dispatch Finder receives available fleet records from PostgreSQL and recommends matching vehicles; it can also discover nearby emergency facilities. A discovered station is not automatically an available vehicle.
4. **Response Planner runs after both succeed.** It combines Intake, Hospital, and Dispatch results into a proposed response. A failed prerequisite prevents planning; an empty recommendation with explicit constraints can still be a valid completed result.
5. **Coordinator reviews.** A new reviewable plan opens a panel in Command. Plans appear in Response Plans too, including `needs_information` plans. The coordinator can approve a feasible plan, request a revision, or reject it, with a decision note.
6. **Approval updates the command map.** The backend rechecks availability, creates assignments, and reserves resources. The overview map then shows the approved response's incident, assigned vehicles, and any chosen hospitals. Its filter can show all ongoing responses or an individual response. Unapproved incidents do not populate this operational map; proposal details may show a preview.
7. **Updates arrive automatically.** Authenticated server-sent events invalidate TanStack Query data, with a 15-second polling fallback. A page refresh should not be necessary to see stage progress, plans, or assignment changes.

PostgreSQL owns reports, runs, plans, resources, and decisions. CREAO receives stage-specific input; the application reads and validates the returned JSON artifact rather than treating CREAO's short text summary as the full result. Unknown coordinates on a discovered dispatch facility no longer invalidate the whole result; that facility is omitted from map markers.

### What is supplied for the demo

The opted-in fleet has six database-backed units around central San Francisco: `AMB-01`, `AMB-02`, `POL-01`, `POL-02`, `FIR-01`, and `RES-01`. They provide two ambulances, two police vehicles, a fire engine, and a rescue unit. Only Dispatch receives the raw fleet: IDs, types, availability, capabilities, base locations, and current coordinates. Intake and Hospital receive no fleet information; Planning receives Dispatch recommendations rather than the full fleet. Busy or already assigned vehicles are excluded.

Startup does not reset assigned units or their positions. The fleet retains simulation provenance internally without extra UI banners. Existing historical exercise resources remain excluded from live inputs. Hospital capacity is not fabricated: an injury/transport plan can remain `needs_information` until receiving capacity is confirmed.

Vehicle movement is an application-driven demonstration, not GPS tracking or actual emergency dispatch. Internal communications are database records, not messages sent to responders. The default lifecycle advances roughly every 12 seconds per stage, so watch the map promptly after approval; completed responses leave the ongoing-response view. You can increase `DISPATCH_STAGE_SECONDS` in `.env` and recreate backend/worker containers if you need a slower presentation.

## First incident to test

Use this low-complexity collision first. Zero reported injuries avoids relying on hospital bed availability. Live agent recommendations can vary, so this is a test case rather than a guarantee of a specific plan.

Open the resident report portal in one tab and Command overview in another. Submit:

| Field | Value |
| --- | --- |
| Category | `collision` |
| Reported injuries | `0` — enter zero explicitly, do not leave blank |
| Location | `Market Street and 8th Street, San Francisco, CA` |
| Latitude | `37.7787` |
| Longitude | `-122.4148` |
| Photo | Leave empty |
| Observation time | Leave empty to use submission time |

Description to paste:

> Two cars had a minor collision at Market Street and 8th Street in San Francisco. Both drivers are out of their vehicles and report no injuries. The cars are stationary and blocking one traffic lane. There is no fire, smoke, leaking fuel, or trapped person. Traffic is moving slowly around the cars.

What to observe:

1. The resident gets a report reference and changing status.
2. The coordinator sees the incident and agent progress without refreshing. Use Agent execution details to inspect stage inputs and results. In Dispatch input, `available_vehicles` should contain the available demo units instead of an empty array.
3. Intake will likely request police for traffic/scene control. Hospital and Dispatch should both complete before Planning starts. A hospital may be researched without being assigned to a zero-injury response.
4. The suggested plan appears in the review panel and Response Plans. Check its reasoning and constraints. If feasible, enter a note such as `Reviewed the proposed traffic response for the demo.` and click **Approve plan**.
5. Watch the approved incident and assigned vehicle on the map, then observe the assignment lifecycle. To test multiple-response filtering, submit another distinct incident while the first response is ongoing.

If the plan says `needs_information`, read its constraints. Approval is intentionally unavailable for an infeasible plan; **Request revision** remains available. Do not treat the lack of an enabled Approve button as a frontend failure by itself.

### Optional injured-person variation

After the first case, use the same location with `1` reported injury and this description:

> Two vehicles collided at Market Street and 8th Street in San Francisco. One person is injured and conscious. Both vehicles are stationary. No fire, smoke, hazardous materials, or trapped people were observed.

This exercises ambulance and police recommendations plus hospital selection. It may end in `needs_information` because the app does not invent available beds. It is useful for checking the constrained-plan UI, but the zero-injury case is the simpler first approval/map test.

## Frontend files and API touchpoints

| File | Responsibility |
| --- | --- |
| `frontend/components/report-flow.tsx` | Resident form, validation, map pin, receipt |
| `frontend/components/coordinator.tsx` | Command overview, review popup, ongoing-response filter |
| `frontend/components/response-plans.tsx` | Plan groups, stage progress, detail panel, decisions |
| `frontend/components/agents.tsx` | Execution details and failed-stage retry |
| `frontend/components/network.tsx` | Fleet/hospital views and response map helpers |
| `frontend/components/map.tsx` | MapLibre map rendering |
| `frontend/lib/api.tsx` | Portal identity, fetch helpers, query cache, SSE and polling |
| `frontend/lib/response-types.ts` | Response-plan, hospital, vehicle, and dispatch types |
| `frontend/app/api/[...path]/route.ts` | Same-origin backend proxy, including streaming |

Key backend routes are `POST /reports`, `GET /response-plans`, `GET /vehicles`, `GET /hospitals`, `GET /dispatches`, and `POST /response-plans/{id}/decision`. The frontend calls these through `/api`. Keep backend-owned state authoritative rather than adding frontend placeholder markers or optimistic approval state.

## Troubleshooting and checks

- **API unavailable:** run `docker compose ps` and `docker compose logs --tail=100 backend worker`. Check database health, migrations, and CREAO configuration. Logs can contain report data or signed artifact URLs; redact them before sharing.
- **Dispatch receives no vehicles:** verify `DEMO_FLEET_ENABLED=true`, restart with `docker compose up -d --build backend worker`, and inspect the Fleet page. Then submit a new report or request a plan revision. Existing runs retain their original input snapshots; retrying an old run does not necessarily create fresh fleet input.
- **A stage fails:** inspect Agent execution details and worker logs. Retry the failed stage after fixing its cause. Planning cannot bypass failed Hospital/Dispatch prerequisites.
- **No plan popup:** open Response Plans directly and check whether stages are still running, failed, or awaiting information. Live CREAO execution can take minutes across the full workflow.
- **Map has no response markers:** verify the plan was approved and still has active assignments. Street tiles also require internet access to `tiles.openfreemap.org`.
- **Approval disabled:** inspect feasibility and constraints, and enter a decision note of at least three characters. Missing confirmed hospital capacity is a backend constraint.

Run checks after frontend changes:

```sh
cd frontend
npm run lint
npm run typecheck
npm run build
```

Backend checks, from the repository root:

```sh
docker compose exec backend ruff check .
docker compose exec backend pytest -q
```

At this handoff, backend lint and 25 tests passed, with 3 tests skipped. The six-unit live Dispatch input was verified locally; that check did not launch another paid CREAO run. For broader integration contracts, see `backend/CREAO.md` and `README.md`.
