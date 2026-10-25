"use client";
import { Fragment, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { request, useAuth, useData } from "@/lib/api";
import type { RecordedCall } from "@/lib/response-types";
import { Badge, Empty, ErrorBox, Loading, Panel } from "./shared";
import { PageHeading } from "./page-heading";
import { Button } from "./ui/button";
import { CallLocation } from "./call-location";
import { PlanDetail } from "./response-plans";
import { CallReopen } from "./call-reopen";
import { CallDelete } from "./call-delete";

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
    <div className="call-review">
      <CallLocation
        call={call}
        disabled={busy}
        onBlockingChange={setLocationBlocked}
        onUpdated={(result) => {
          cache.setQueryData([token, `/calls/${result.id}`], result);
          void cache.invalidateQueries();
        }}
      />
      <form className="call-type-form" onSubmit={submit}>
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
  const router = useRouter();
  const calls = useData<RecordedCall[]>("/calls");
  const samples = useData<{ key: string; title: string }[]>("/calls/samples");
  const { token } = useAuth();
  const cache = useQueryClient();
  const [selected, setSelected] = useState<string | null | undefined>();
  // Explicit null clears selection, including a deleted call originally opened from the URL.
  const selectedId =
    selected === undefined ? searchParams.get("call") : selected;
  const detail = useData<RecordedCall>(`/calls/${selectedId}`, !!selectedId);
  const [planId, setPlanId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const call = detail.data;
  const transcript = call?.reviewed_transcript ?? call?.original_transcript;
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
        eyebrow="RECORDED-CALL EXERCISE"
        title="Recorded Calls"
        subtitle="Review a recording, check the location, and choose a call type."
      />
      <section className="call-intake-tools" aria-label="Add a recording">
        <div className="call-upload-heading">
          <h2>Add a recording</h2>
          <p>Upload audio or start with a sample call.</p>
        </div>
        <label className="audio-upload">
          <span>Upload fictional audio (WAV, MP3, WebM, Ogg)</span>
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
            Default limit: 20 MiB / five minutes. Transcription supports bundled
            samples only.
          </small>
        </label>
        <div className="sample-buttons">
          <span>Sample calls</span>
          {samples.data?.map((sample) => (
            <Button
              key={sample.key}
              variant="secondary"
              aria-label={`Load sample call: ${sample.title}`}
              disabled={busy}
              onClick={() => perform(`/calls/sample/${sample.key}`)}
            >
              {sample.title}
            </Button>
          ))}
        </div>
      </section>
      {error && <ErrorBox message={error} />}
      {(calls.error || detail.error || samples.error) && (
        <ErrorBox
          message={(calls.error || detail.error || samples.error)!.message}
        />
      )}
      <div className="call-layout">
        <Panel
          title="Call queue"
          className="call-queue"
          action={<span className="count">{calls.data?.length ?? 0}</span>}
        >
          <div className="call-queue-list">
            {calls.isLoading && <Loading />}
            {!calls.data?.length && (
              <Empty>Load a fictional sample to begin.</Empty>
            )}
            {calls.data?.map((item) => (
              <button
                className={`call-row ${selectedId === item.id ? "selected" : ""}`}
                key={item.id}
                aria-pressed={selectedId === item.id}
                onClick={() => setSelected(item.id)}
              >
                <strong>
                  {samples.data?.find(
                    (sample) => sample.key === item.sample_key,
                  )?.title ||
                    item.sample_key ||
                    "Uploaded recording"}
                </strong>
                <small>{new Date(item.received_at).toLocaleString()}</small>
                <div className="call-row-meta">
                  <Badge
                    value={
                      item.status === "awaiting_review"
                        ? "ready_for_call_type"
                        : item.status
                    }
                  />
                  <span className="mono">{item.id.slice(0, 6)}</span>
                </div>
              </button>
            ))}
          </div>
        </Panel>
        <Panel
          title="Recording & call intake"
          className="call-detail"
          action={
            call && (
              <CallDelete
                key={call.id}
                call={call}
                onDeleted={(id) => {
                  setSelected(null);
                  setPlanId(null);
                  void cache.cancelQueries({
                    queryKey: [token, `/calls/${id}`],
                  });
                  cache.removeQueries({ queryKey: [token, `/calls/${id}`] });
                  cache.setQueryData<RecordedCall[]>(
                    [token, "/calls"],
                    (items) => items?.filter((item) => item.id !== id),
                  );
                  if (searchParams.get("call") === id) {
                    const params = new URLSearchParams(searchParams.toString());
                    params.delete("call");
                    router.replace(
                      `/coordinator/calls${params.size ? `?${params}` : ""}`,
                      { scroll: false },
                    );
                  }
                  void cache.invalidateQueries();
                }}
              />
            )
          }
        >
          <div className="call-detail-body">
            {!call ? (
              <Empty>
                Select a call from the queue to review its recording and
                transcript.
              </Empty>
            ) : (
              <Fragment key={call.id}>
                <CallAudio id={call.id} />
                <p className="call-recording-meta">
                  <Badge
                    value={
                      call.status === "awaiting_review"
                        ? "ready_for_call_type"
                        : call.status
                    }
                  />{" "}
                  · {Math.round(call.duration_seconds)} seconds · SIMULATION
                </p>
                {transcript && (
                  <details className="call-transcript" open>
                    <summary>Call transcript</summary>
                    <p className="transcript">{transcript}</p>
                  </details>
                )}
                {call.original_transcript &&
                  call.original_transcript !== transcript && (
                    <details className="call-transcript">
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
                    call={call}
                    onConfirmed={(result) => {
                      void cache.invalidateQueries();
                      setPlanId(result.plan_id);
                    }}
                  />
                )}
                {call.status === "confirmed" && (
                  <div className="call-complete">
                    <h3>Call intake complete</h3>
                    <p>
                      {call.confirmed_address} · {call.confirmed_latitude},{" "}
                      {call.confirmed_longitude}
                    </p>
                    <Button onClick={() => setPlanId(call.plan_id)}>
                      Open response plan
                    </Button>
                    <CallReopen
                      call={call}
                      onReopened={(result) => {
                        setSelected(result.id);
                        setPlanId(null);
                      }}
                    />
                  </div>
                )}
                {["queued", "transcribing"].includes(call.status) && (
                  <p>Transcribing the call and locating the incident…</p>
                )}
              </Fragment>
            )}
          </div>
        </Panel>
      </div>
      <PlanDetail
        id={planId}
        onClose={() => setPlanId(null)}
        onCallReopened={(result) => {
          setSelected(result.id);
          setPlanId(null);
        }}
      />
    </>
  );
}
