"use client";
import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { request, useAuth, useData } from "@/lib/api";
import type { RecordedCall } from "@/lib/response-types";
import { Badge, Empty, ErrorBox, Loading, Panel } from "./shared";
import { PageHeading } from "./page-heading";
import { Button } from "./ui/button";
import { CallLocation } from "./call-location";
import { PlanDetail } from "./response-plans";
import { CallReopen } from "./call-reopen";

/** Fetch protected audio with credentials and release the browser's private copy on cleanup. */
function CallAudio({ id }: { id: string }) {
  const { token } = useAuth();
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    let objectUrl = "";
    /** Read a protected recording without exposing the credential in its playback URL. */
    async function load() {
      try {
        const response = await fetch(`/api/calls/${id}/audio`, {
          headers: { Authorization: `Bearer ${token}` },
          signal: controller.signal,
        });
        if (!response.ok)
          throw new Error(
            "Recording unavailable. Refresh or load another sample.",
          );
        const blob = await response.blob();
        if (controller.signal.aborted) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      } catch (error) {
        if (!controller.signal.aborted)
          setError(
            error instanceof Error ? error.message : "Audio unavailable",
          );
      }
    }
    void load();
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [id, token]);
  return (
    <>
      {error && <ErrorBox message={error} />}
      {url ? (
        <audio aria-label="Call recording" controls src={url} />
      ) : (
        <p>Loading recording…</p>
      )}
    </>
  );
}

/** Require only call type while the server supplies transcript and incident coordinates. */
function CallReview({
  call,
  onConfirmed,
}: {
  call: RecordedCall;
  onConfirmed: (call: RecordedCall) => void;
}) {
  const { token } = useAuth();
  const [category, setCategory] = useState("");
  const cache = useQueryClient();
  const [locationBlocked, setLocationBlocked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const location = call.detected_location;
  /** Start from the server-owned detected location; the browser submits no address or pin. */
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      onConfirmed(
        await request<RecordedCall>(`/calls/${call.id}/start`, token, "POST", {
          category,
          version: call.version,
        }),
      );
    } catch (error) {
      setError(
        error instanceof Error ? error.message : "Could not start agents",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="form">
      <CallLocation
        call={call}
        disabled={busy}
        onBlockingChange={setLocationBlocked}
        onUpdated={(result) => {
          cache.setQueryData([token, `/calls/${result.id}`], result);
          void cache.invalidateQueries();
        }}
      />
      <form className="form" onSubmit={submit}>
        <label htmlFor={`call-type-${call.id}`}>Call type</label>
        <select
          id={`call-type-${call.id}`}
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          required
        >
          <option value="">Choose a call type</option>
          {[
            "collision",
            "medical",
            "fire",
            "rescue",
            "road",
            "wildfire",
            "smoke",
            "power",
            "water",
          ].map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>
        {error && <ErrorBox message={error} />}
        <Button
          type="submit"
          disabled={
            busy ||
            locationBlocked ||
            !category ||
            location?.status !== "resolved"
          }
        >
          {busy ? "Starting…" : "Start agents"}
        </Button>
      </form>
    </div>
  );
}

/** Keep simulated recorded calls and their human review in one authenticated workspace. */
export function Calls() {
  const searchParams = useSearchParams();
  const calls = useData<RecordedCall[]>("/calls");
  const samples = useData<{ key: string; title: string }[]>("/calls/samples");
  const { token } = useAuth();
  const cache = useQueryClient();
  const [selected, setSelected] = useState<string | null>(null);
  const selectedId = selected ?? searchParams.get("call");
  const detail = useData<RecordedCall>(`/calls/${selectedId}`, !!selectedId);
  const [planId, setPlanId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const call = detail.data;
  /** Queue an upload, sample or retry, then refresh the selected private call. */
  async function perform(path: string, body?: FormData) {
    setBusy(true);
    setError("");
    try {
      const result = await request<RecordedCall>(path, token, "POST", body);
      setSelected(result.id);
      await cache.invalidateQueries();
    } catch (error) {
      setError(error instanceof Error ? error.message : "Call request failed");
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <PageHeading
        eyebrow="FICTIONAL RECORDED-CALL EXERCISE"
        title="Recorded Calls"
        subtitle="The call supplies the location. Select a call type to start a simulated response."
      />
      <div className="row sample-buttons">
        {samples.data?.map((sample) => (
          <Button
            key={sample.key}
            variant="secondary"
            disabled={busy}
            onClick={() => perform(`/calls/sample/${sample.key}`)}
          >
            Load sample call: {sample.title}
          </Button>
        ))}
      </div>
      <label className="audio-upload">
        Upload fictional audio (WAV, MP3, WebM, Ogg)
        <input
          type="file"
          accept="audio/wav,audio/mpeg,audio/webm,audio/ogg"
          disabled={busy}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (!file) return;
            const data = new FormData();
            data.append("audio", file);
            void perform("/calls", data);
            e.target.value = "";
          }}
        />
        <small>
          Default limit: 20 MiB / five minutes. Mock transcription supports
          bundled samples only.
        </small>
      </label>
      {error && <ErrorBox message={error} />}
      {(calls.error || detail.error || samples.error) && (
        <ErrorBox
          message={(calls.error || detail.error || samples.error)!.message}
        />
      )}
      <div className="call-layout">
        <Panel title="Call queue">
          {calls.isLoading && <Loading />}
          {!calls.data?.length && (
            <Empty>Load a fictional sample to begin.</Empty>
          )}
          {calls.data?.map((item) => (
            <button
              className={`call-row ${selectedId === item.id ? "selected" : ""}`}
              key={item.id}
              onClick={() => setSelected(item.id)}
            >
              <strong>
                {item.sample_key || "Uploaded fictional call"} ·{" "}
                {item.id.slice(0, 6)}
              </strong>
              <Badge
                value={
                  item.status === "awaiting_review"
                    ? "ready_for_call_type"
                    : item.status
                }
              />
              <small>{new Date(item.received_at).toLocaleString()}</small>
            </button>
          ))}
        </Panel>
        <Panel title="Recording & call intake">
          {!call ? (
            <Empty>Select a call.</Empty>
          ) : (
            <>
              <CallAudio key={call.id} id={call.id} />
              <p>
                <Badge
                  value={
                    call.status === "awaiting_review"
                      ? "ready_for_call_type"
                      : call.status
                  }
                />{" "}
                · {Math.round(call.duration_seconds)} seconds · SIMULATION
              </p>
              {call.original_transcript && (
                <details open>
                  <summary>Original machine transcript</summary>
                  <p className="transcript">{call.original_transcript}</p>
                </details>
              )}
              {call.transcription_error && (
                <ErrorBox message={call.transcription_error} />
              )}
              {call.status === "failed" && call.attempts < 3 && (
                <Button
                  disabled={busy}
                  onClick={() =>
                    perform(`/calls/${call.id}/retry-transcription`)
                  }
                >
                  Retry transcription
                </Button>
              )}
              {call.status === "awaiting_review" && (
                <CallReview
                  key={call.id}
                  call={call}
                  onConfirmed={(result) => {
                    void cache.invalidateQueries();
                    setPlanId(result.plan_id);
                  }}
                />
              )}
              {call.status === "confirmed" && (
                <>
                  <h3>Call intake complete</h3>
                  <p>{call.reviewed_transcript}</p>
                  <p>
                    {call.confirmed_address} · {call.confirmed_latitude},{" "}
                    {call.confirmed_longitude}
                  </p>
                  <Button onClick={() => setPlanId(call.plan_id)}>
                    Open response plan
                  </Button>
                  <CallReopen call={call} onReopened={(result) => {
                    setSelected(result.id);
                    setPlanId(null);
                  }} />
                </>
              )}
              {["queued", "transcribing"].includes(call.status) && (
                <p>Transcribing the call and locating the incident…</p>
              )}
            </>
          )}
        </Panel>
      </div>
      <PlanDetail id={planId} onClose={() => setPlanId(null)} onCallReopened={(result) => {
        setSelected(result.id);
        setPlanId(null);
      }} />
    </>
  );
}
