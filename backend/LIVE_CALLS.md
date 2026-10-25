# Live inbound phone calls

Kontrol supports uploaded recordings and live phone calls in the same Calls workspace. Their transcription implementations are independent. Both converge on the existing call review, location correction, category selection, four-agent workflow, and human plan approval.

```text
Uploaded audio → existing batch adapter ──────────────────────┐
                                                            ├→ shared Call review → explicit Start agents
Twilio number → browser Voice SDK → two-way conversation     │
                    └→ signed media ingress                 │
                         └→ OpenAI Realtime → final segments ─┘
```

Answering and hanging up never start agents. Live calls require a provider-confirmed end, a persisted finalized transcript (or explicit incomplete-transcript resolution), resolved incident location, and dispatcher-selected call type. Both `/calls/{id}/start` and the legacy confirm-review endpoint enforce the live-session barrier in the backend.

## Why Twilio

The implementation uses the official `@twilio/voice-sdk` for browser answering/audio/mute/hang-up and the official Python SDK for Voice grants, request signatures, TwiML, and provider hang-up. An incoming-only short-lived browser token is minted for the existing authenticated dispatcher identity. No API secrets reach the browser.

Twilio's `<Dial><Client>` bridges the caller and browser; `<Start><Stream track="both_tracks">` forks audio independently. A transcription failure therefore does not interrupt their conversation. Caller and dispatcher are attributed by the provider's separate audio tracks, not by invented ASR speaker labels. Telnyx's official browser SDK was also reviewed; Twilio's direct Dial/Client and both-track stream flow was selected for this repository.

Official references: [Twilio browser SDK](https://www.twilio.com/docs/voice/sdks/javascript/twiliodevice), [Twilio media streams](https://www.twilio.com/docs/voice/media-streams), [media messages](https://www.twilio.com/docs/voice/media-streams/websocket-messages), [webhook signatures](https://www.twilio.com/docs/usage/webhooks/webhooks-security), [Telnyx browser SDK](https://developers.telnyx.com/docs/development/webrtc/js-sdk/tutorials/make-your-first-call).

## Configure a real test call

1. Provision a Twilio voice-capable inbound number. Obtain its Account SID and Auth Token, and create a Twilio API Key SID/Secret for signing browser Voice grants. The implementation enables incoming calls only; it does not authorize browser outbound calls.
2. Expose **only the phone ingress**, not the trusted local API, with a public HTTPS endpoint supporting WebSocket upgrades. For local development, a tunnel can target port 8001:

   ```sh
   ngrok http 8001
   ```

   Copy that tunnel's HTTPS origin. No `/api` suffix or other path is allowed in the configured origin. A stable public hostname avoids reconfiguring callbacks after tunnel restarts.
3. Add the following values to your existing `.env` without replacing its batch transcription or CREAO settings:

   ```dotenv
   TELEPHONY_ENABLED=true
   TELEPHONY_INGRESS_PORT=8001
   TELEPHONY_PUBLIC_URL=https://YOUR-PUBLIC-INGRESS-HOST
   TWILIO_ACCOUNT_SID=AC...
   TWILIO_AUTH_TOKEN=...
   TWILIO_API_KEY_SID=SK...
   TWILIO_API_KEY_SECRET=...
   TWILIO_PHONE_NUMBER=+1...
   TWILIO_RECORD_CALLS=false
   LIVE_TRANSCRIPTION_API_KEY=...
   LIVE_TRANSCRIPTION_MODEL=gpt-live-transcribe
   LIVE_TRANSCRIPTION_URL=wss://api.openai.com/v1/realtime?intent=transcription
   LIVE_FINALIZATION_TIMEOUT=30
   ```

   Live ASR uses a separate server-only key, model, and WebSocket URL. The existing `TRANSCRIPTION_*` variables and batch model remain unchanged. Confirm that the selected Realtime transcription model is available to your OpenAI account. No credential is copied into a `NEXT_PUBLIC_*` variable.
4. Start the stack with the optional signed-only ingress service:

   ```sh
   docker compose --profile phone up -d --build
   ```

   Migration `0007` runs automatically. It preserves existing recordings, adds their ingestion source, allows missing audio while a phone call is active, and adds live-session/segment tables. Existing uploads retain the `recording` source.
5. Configure the Twilio number's incoming voice webhook as **POST**:

   ```text
   https://YOUR-PUBLIC-INGRESS-HOST/telephony/incoming
   ```

   Configure the number's parent call status callback as POST to:

   ```text
   https://YOUR-PUBLIC-INGRESS-HOST/telephony/status
   ```

   The returned TwiML configures its child-leg status, Dial-end, recording, and media URLs automatically. All callbacks and the media handshake require valid Twilio signatures and matching account/call identifiers. Preserve the external scheme, hostname, and path exactly: the configured canonical origin is used for validation instead of trusting forwarded headers.
6. Open `http://localhost:3000/coordinator/calls`, select **Enable phone**, and wait for **ready**. Keep that browser registered before calling the number. Browser microphone access requires localhost or a secure browser origin. Allow microphone access when answering.
7. From another phone, call the assigned Twilio number. The call appears in the queue and the browser receives an incoming-call notification. Select it and click **Answer Call**. Speak a scripted test report with an explicit San Francisco address. Both parties should hear each other; verify **Mute/Unmute** and **Hang Up**.
8. Watch partial and finalized transcript segments. After either party hangs up, wait for transcript finalization and location lookup. Review/correct the location, select the category, and explicitly select **Start agents**. Review and approve the response using the existing controls.

An actual provider-backed call is necessary to verify carrier routing, browser audio, account/model access, and public WebSocket connectivity. Automated tests simulate the provider protocols; they do not prove phone connectivity.

## Public ingress and privacy

`phone-ingress` is an optional Compose service exposing only signed callback/media endpoints on localhost port 8001. It cannot mint browser tokens, serve recordings, or access dispatcher APIs. The normal API stays on localhost port 8000 and the frontend proxies its authenticated private requests. Do not tunnel the full trusted-local API just to receive provider callbacks. Public hosting of the dispatcher UI still requires a production identity system, as documented in README.

Browser tokens expire after ten minutes and refresh before expiration. Call claims, controls, finalization, and incomplete-transcript resolution use existing database identity/version checks. Multiple answer attempts are serialized; terminal callbacks cannot revive a call, and a losing parallel browser leg cannot end the winner. Global phone state survives workspace navigation; provider callbacks synchronize browser disconnects and premature hang-ups.

Audio remains on Twilio's phone bridge even when the media-transcription connection fails. The server never synthesizes transcript text or substitutes the caller's phone number/device location for an incident address.

## Streaming transcription and finalization

The new `live_transcription.py` implements a streaming interface independent of `transcription.py`. It uses OpenAI transcription-only Realtime sessions over server-side WebSockets, with native G.711 μ-law input. Separate connections handle inbound caller and outbound dispatcher channels. Lightweight audio-energy segmentation commits after silence or four-second turn limits; trailing speech is committed and final events are drained at stream end.

The adapter handles transcript deltas and final item events, deduplicates event IDs, and associates items with provider media timestamps. Database segments are unique per call/track/item and ordered by stream-relative timestamps. Final results replace partial text for the same item; late partials cannot overwrite finalized text. The UI receives updates through existing authenticated SSE/query refresh. Time labels are application-level media timestamps, not claimed word-level ASR timestamps.

Reference: [OpenAI Realtime transcription](https://developers.openai.com/api/docs/guides/realtime-transcription). The model generates transcription only, not spoken responses or incident actions. No change to the uploaded-file model or `/audio/transcriptions` path is required.

New live call states are `live_ringing`, `live_answering`, `live_active`, `live_finalizing`, and `live_incomplete`. Once complete, they converge on the existing `awaiting_review` and `confirmed` states. Source-specific worker selection prevents live audio entering the batch queue. A separate finalizer thread reconciles only ended/drained calls and reuses existing location detection.

If ASR fails, media frames are missing, final events time out, or no stream arrives, the phone conversation can continue. After hang-up the call remains `live_incomplete`; Start agents stays unavailable. The dispatcher must review and explicitly save a usable transcript with a resolution note. Original machine segments remain unchanged and the resolution is audited. Empty or over-4,000-character transcripts are never silently converted or truncated; the same explicit resolution path handles them.

Reopening a completed intake preserves its finalized live transcript and location; starting again uses the existing fresh-workflow behavior. Deletion is unavailable during the live call/drain and thereafter uses existing private-storage cleanup. A terminal provider SID tombstone prevents duplicate incoming webhooks from recreating a deleted queue entry.

## Optional recording replay

Set `TWILIO_RECORD_CALLS=true` to request a dual-channel provider recording for replay. Once its signed completion callback arrives, a worker downloads the account-owned recording into the existing private audio volume. It validates the recording SID, constructs the account URL rather than trusting a supplied URL, bounds storage size, and keeps credentials off allowed storage redirects. Download attempts are durable and bounded.

Playback uses the existing authenticated `/calls/{id}/audio` endpoint. With recording off, live transcript review still works but no replay file is available. Recording retention never sends a live call to the batch transcription adapter. Provider-side retention is separate from local deletion.

## Files and endpoints

- `telephony_provider.py`: official SDK, tokens, signatures, TwiML, actual hang-up.
- `telephony_api.py`: incoming/status callbacks and dispatcher controls.
- `telephony_ingress.py`: public signed-only application.
- `live_media.py`: signed media WebSocket and safe segment persistence.
- `live_transcription.py`: independent OpenAI streaming adapter.
- `live_calls.py`, `live_worker.py`: shared readiness, reconciliation, finalization and private replay storage.
- `frontend/lib/live-phone.tsx`: persistent official browser Device and call controls.
- `frontend/components/live-phone.tsx`: connection, notification, transcript and resolution UI.

Private endpoints: `GET /telephony/config`, `POST /telephony/token`, `POST /telephony/calls/{id}/answer`, `POST /telephony/calls/{id}/decline`, `POST /telephony/calls/{id}/hangup`, and `POST /telephony/resolve/{id}`. Control bodies include the current call `version`; resolution additionally includes `transcript` and `note`.

## Verification

Run backend tests normally; live-call tests mock external transports while checking actual signatures, state transitions, media message handling, finalization, storage and shared agent jobs. Use a disposable mock Compose project for browser tests, as existing tests reset exercise state:

```sh
CREAO_MODE=mock TRANSCRIPTION_MODE=mock LIVE_SIMULATION_ENABLED=false TELEPHONY_ENABLED=false \
  BACKEND_PORT=8100 FRONTEND_PORT=3100 docker compose -p kontrol-live-test up -d --build
BASE_URL=http://127.0.0.1:3100 npx --prefix frontend playwright test --config frontend/playwright.config.ts
```

Do not claim real connectivity based only on these tests. To verify it, perform the real phone procedure above and inspect provider status logs alongside the app's private call state.
