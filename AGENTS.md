Kontrol: Codex Instructions
Code quality
- Prefer simple, direct, readable implementations over clever abstractions.
- Use descriptive names, small functions, and clear module boundaries.
- Add a brief docstring to every nontrivial function, method, and class explaining its purpose. Keep docstrings to one or two sentences when possible.
- Add comments explaining why non-obvious logic exists, especially agent orchestration, incident status transitions, geospatial decisions, concurrency handling, and authorization. Do not comment every line or restate obvious code.
- Avoid unnecessary dependencies, speculative abstractions, premature optimization, and oversized files.
- Keep TypeScript types and Python/Pydantic schemas explicit. Avoid any unless unavoidable and explained.
- Favor conventional Next.js, FastAPI, SQLAlchemy, and Docker patterns.
Architecture
- Use Docker Compose to run frontend, API, background worker, and PostgreSQL/PostGIS in separate containers.
- Make docker compose up --build work for local development; document any one-time migration or seed command.
- Store secrets in environment variables and provide .env.example without secrets.
- Keep the authoritative incident and resource state in PostgreSQL, not in CREAO agent memory.
- Implement a small CREAO adapter behind a stable interface with mock and live modes. Do not invent undocumented API behavior.
- Keep mock mode deterministic and end-to-end functional without credentials.
- Use a simple queue or database-backed jobs before adding heavier infrastructure.
Safety and correctness
- Treat all incoming resident reports and AI outputs as untrusted.
- Validate external inputs and agent responses against schemas.
- Preserve report provenance, timestamps, uncertainty, and verification history.
- AI may propose classifications and actions, but only authorized coordinators can approve official verification, public updates, or resource assignments.
- Never expose private reports or internal coordinator data to residents.
- Mark every seeded event and all demo surfaces as SIMULATION / NOT FOR EMERGENCY USE.
- Never use fictional data to produce real-world emergency guidance.
Development workflow
- Before making major changes, inspect existing code and state a short implementation plan.
- Implement vertical slices that work end to end instead of building disconnected placeholder screens.
- Write focused tests for business logic, permission boundaries, agent schema validation, and public publishing.
- Run relevant tests, linting, and builds after changes. Fix failures before declaring completion.
- Update the README when setup, environment variables, architecture, or commands change.
- At the end of a task, summarize what changed, how to run it, which checks passed, and any remaining limitations.