"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Mic, MicOff, Phone, PhoneIncoming, PhoneOff } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { request, useAuth } from "@/lib/api";
import { useLivePhone } from "@/lib/live-phone";
import type { RecordedCall } from "@/lib/response-types";
import { Button } from "./ui/button";
import { ErrorBox } from "./shared";

/** Keep incoming and connected calls visible when the dispatcher navigates to another workspace. */
export function LivePhoneNotice() {
  const phone = useLivePhone();
  const id = phone.activeId || phone.incomingIds[0];
  if (!id) return null;
  return <aside className="live-phone-notice" role="status">
    <PhoneIncoming size={18} /> {phone.activeId ? "Phone call connected" : "Incoming phone call"}
    <Link href={`/coordinator/calls?call=${id}`}>Open call controls</Link>
  </aside>;
}

/** Register the authenticated browser device explicitly while preserving all recording upload tools. */
export function PhoneConnection() {
  const phone = useLivePhone();
  if (!phone.enabled) return null;
  return <section className="phone-connection" aria-label="Browser phone">
    <div><strong><Phone size={18} /> Live phone</strong><p>{phone.number || "Assigned number"} · {phone.connection}</p></div>
    {!phone.activeId && !["ready", "connecting"].includes(phone.connection) &&
      <Button disabled={phone.busy} onClick={() => void phone.enable()}>Enable phone</Button>}
    {phone.error && <ErrorBox message={phone.error} />}
  </section>;
}

/** Display channel-attributed speech and real controls; review and agent start remain post-call actions. */
export function LiveCallControls({ call }: { call: RecordedCall }) {
  const phone = useLivePhone();
  const live = call.live;
  const { token } = useAuth();
  const cache = useQueryClient();
  const [duration, setDuration] = useState(0);
  const [transcript, setTranscript] = useState(call.original_transcript || "");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [resolving, setResolving] = useState(false);
  useEffect(() => {
    /** Use provider timestamps so reloads do not restart the call timer. */
    function tick() {
      const start = live?.answered_at;
      setDuration(start ? Math.max(0, Math.floor(((live?.ended_at ? Date.parse(live.ended_at) : Date.now())
        - Date.parse(start)) / 1000)) : 0);
    }
    tick();
    const interval = setInterval(tick, 1000);
    return () => clearInterval(interval);
  }, [live?.answered_at, live?.ended_at]);
  if (!live) return null;
  const ended = !!live.ended_at;
  const ready = ended && !!live.finalized_at;
  /** Require a human resolution after transcript failure; raw segment history remains intact. */
  async function resolve(event: React.FormEvent) {
    event.preventDefault(); setResolving(true); setError("");
    try {
      await request(`/telephony/resolve/${call.id}`, token, "POST", { version: call.version, transcript, note });
      await cache.invalidateQueries();
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Could not resolve transcript"); }
    finally { setResolving(false); }
  }
  return <section className="live-call" aria-label="Live phone call">
    <div className="live-call-heading"><strong>{live.caller || "Unknown caller"}</strong>
      <span>{live.state.replaceAll("_", " ")} · {Math.floor(duration / 60)}:{String(duration % 60).padStart(2, "0")}</span></div>
    <div className="decision-actions">
      {!ended && live.state === "ringing" && <>
        <Button disabled={phone.busy || !phone.incomingIds.includes(call.id)} onClick={() => void phone.answer(call.id)}>
          <PhoneIncoming size={16} /> Answer Call
        </Button>
        <Button variant="secondary" disabled={phone.busy} onClick={() => void phone.end(call.id, true)}>Decline</Button>
      </>}
      {!ended && ["active", "answering"].includes(live.state) && <>
        <Button variant="secondary" disabled={phone.activeId !== call.id} onClick={phone.mute}>
          {phone.muted ? <MicOff size={16} /> : <Mic size={16} />}{phone.muted ? "Unmute" : "Mute"}
        </Button>
        <Button disabled={phone.busy} onClick={() => void phone.end(call.id)}><PhoneOff size={16} /> Hang Up</Button>
      </>}
    </div>
    {!ended && <p className="muted">{phone.connection} · Agents become available after the call and transcript finish.</p>}
    {!!live.segments.length && <div className="live-transcript" aria-label="Live transcript" aria-live="polite">
      {live.segments.map((segment) => <p key={segment.id} className={segment.finalized ? "" : "transcript-partial"}>
        <small>{(segment.start_ms / 1000).toFixed(1)}s · {segment.track === "inbound" ? "Caller" : "Dispatcher"}
          {!segment.finalized && " · transcribing"}</small>{segment.text}
      </p>)}
    </div>}
    {!live.segments.length && !ended && <p>Waiting for speech…</p>}
    {live.transcription_error && <ErrorBox message={live.transcription_error} />}
    {ended && !ready && call.status !== "live_incomplete" && <p>Finalizing transcript and locating the incident…</p>}
    {!ready && <Button disabled>Start agents</Button>}
    {call.status === "live_incomplete" && <form className="form live-resolution" onSubmit={resolve}>
      <h3>Resolve incomplete transcript</h3>
      <p>Review the available speech and enter the transcript you want to use. Original segments remain in history.</p>
      <label>Reviewed live transcript<textarea value={transcript} onChange={(event) => setTranscript(event.target.value)} rows={7} /></label>
      <small>{transcript.length} / 4,000 characters</small>
      <label>Resolution note<input value={note} onChange={(event) => setNote(event.target.value)} maxLength={1000} /></label>
      <Button type="submit" disabled={resolving || transcript.trim().length < 10 || transcript.length > 4000 || note.trim().length < 3}>
        Save transcript for review
      </Button>
      {error && <ErrorBox message={error} />}
    </form>}
  </section>;
}
