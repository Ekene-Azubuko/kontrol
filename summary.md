# Kontrol dispatcher exercise

**SIMULATION (NOT FOR EMERGENCY USE)**

Kontrol is a recorded-call dispatcher co-pilot for fictional local exercises. It accepts three bundled samples or uploaded fictional audio, transcribes through a mock/live adapter, and automatically detects the incident address and coordinates from the transcript. A map fly-in and pin-drop reveal the location. Call type is the only required form input before the dispatcher starts agents.

Before starting agents, dispatchers can optionally edit the address and select Find location again. Each successful lookup replays the map animation. Failed corrections remove the old pin; retries reuse the last edited address without retranscribing. Version checks protect concurrent edits and starts, and the audit history preserves changes alongside the original transcript. Edited text does not make the inferred coordinates human-verified.

PostgreSQL stores immutable original text, reviewed text, approximate caller coordinates, detected incident location and inference provenance, audit history, durable transcription leases, and authoritative resource state. A shared private Docker volume stores audio. All call APIs and playback require dispatcher authorization. Resident UI and public APIs have been retired while historical data remains intact.

Back to call type returns an unapproved response to the same recording and location without retranscribing. A subsequent Start agents creates a fresh workflow; earlier reports and outputs remain in history, unfinished local work is cancelled, and late results are ignored. Approved responses cannot be reopened.

Intake → Hospital ∥ Dispatch → Planning remains the four-agent workflow. Patient counts extracted from transcripts are unconfirmed estimates; unknown stays null. Hospital destinations are provisional. Human approval rechecks current resources under locks and creates only simulated assignments. Reset invalidates in-flight claims and cancels exercise work without deleting provenance.

Live completion polling defaults to two seconds and is configurable through Compose. Most measured live latency comes from remote CREAO execution; `backend/CREAO_PERFORMANCE.md` contains instructions to reduce research and output verbosity in the published agents. Applying those remote changes remains a separate publishing step.

Plan review leads with four short checks and keeps full agent explanations expandable. Explicit unmet requirements and known resource conflicts remain visible. Hospital options share numbered proximity markers and a compact list, sortable nearest/farthest or by agent recommendation. Straight-line miles come from coordinates; travel estimates and suitability remain separate. The original agent output and approval checks are preserved.

Run `docker compose up --build` with mock modes from `.env.example`, then open `/coordinator/calls`. No credentials or manual fixture generation are needed. Real telephony, medical instructions, production identity, CAD integration, and operational deployment are outside V1.

Spoken exercise sites resolve locally. Spoken cross streets and short conversational location answers resolve through the official SF street-intersection dataset. A cached city street directory supports spacing differences and a unique single-character correction such as “Vaness” → “Van Ness,” with an exact second street and a unique shared intersection required. Original transcript and extracted evidence remain unchanged. Other numbered street addresses use configurable Photon geocoding within the San Francisco exercise area. Missing or ambiguous locations remain unavailable; caller-device coordinates are never substituted. Automatic locations remain explicitly unverified, and plan approval stays manual.
