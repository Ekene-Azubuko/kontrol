"use client";
import { useState } from "react";
import { MapPin, Pencil, RotateCcw } from "lucide-react";
import { request, useAuth } from "@/lib/api";
import type { RecordedCall } from "@/lib/response-types";
import { IncidentMap } from "./map";
import { ErrorBox } from "./shared";
import { Button } from "./ui/button";

/** Allow optional location corrections and replay the map reveal after every completed lookup. */
export function CallLocation({
  call,
  disabled,
  onUpdated,
  onBlockingChange,
}: {
  call: RecordedCall;
  disabled: boolean;
  onUpdated: (call: RecordedCall) => void;
  onBlockingChange: (blocked: boolean) => void;
}) {
  const { token } = useAuth();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const location = call.detected_location;
  const resolved =
    location?.status === "resolved" &&
    location.latitude !== null &&
    location.longitude !== null;
  const corrected = location?.input_source === "dispatcher_address";

  /** Seed a correction without overwriting in-progress edits on SSE refresh. */
  function editAddress() {
    setDraft(
      location?.input_address || location?.address || location?.evidence || "",
    );
    setError("");
    setEditing(true);
    onBlockingChange(true);
  }

  /** Resolve only location text, keeping the recording and original machine transcript intact. */
  async function locate(address?: string) {
    setBusy(true);
    setError("");
    onBlockingChange(true);
    let keepEditing = editing;
    try {
      const result = await request<RecordedCall>(
        `/calls/${call.id}/locate`,
        token,
        "POST",
        {
          ...(address === undefined ? {} : { address }),
          version: call.version,
        },
      );
      onUpdated(result);
      keepEditing = result.detected_location?.status !== "resolved" && editing;
      setEditing(keepEditing);
    } catch (error) {
      setError(
        error instanceof Error
          ? error.message
          : "Could not find the location. Try again.",
      );
    } finally {
      setBusy(false);
      onBlockingChange(keepEditing);
    }
  }

  return (
    <section
      className="call-location"
      aria-label="Incident location"
      aria-busy={busy}
    >
      <div className="call-location-heading">
        <span className="call-location-label">
          {corrected ? "DISPATCHER-EDITED ADDRESS" : "LOCATION FROM TRANSCRIPT"}
        </span>
        <span className="call-location-badge">
          {busy ? "Locating…" : corrected ? "Edited address" : "Auto-detected"}
        </span>
      </div>
      {busy ? (
        <div className="call-location-searching" role="status">
          <MapPin aria-hidden="true" />
          <strong>Finding the incident location…</strong>
          <span>Matching the address before placing the pin.</span>
        </div>
      ) : resolved ? (
        <>
          <h3>{location.address}</h3>
          {location.evidence && (
            <p className="call-location-quote">“{location.evidence}”</p>
          )}
          <IncidentMap
            key={call.version}
            items={[]}
            compact
            revealLocation={{
              latitude: location.latitude!,
              longitude: location.longitude!,
            }}
          />
          <small className="muted">
            Coordinates inferred for this simulation. Location is not
            human-verified.
          </small>
        </>
      ) : (
        <div className="call-location-unavailable" role="status">
          <strong>
            {location ? "Location unavailable" : "Location pending"}
          </strong>
          <p>{location?.reason || "The location has not been found yet."}</p>
          <small>Edit the address or try finding the location again.</small>
        </div>
      )}
      {editing ? (
        <form
          className="form call-location-editor"
          onSubmit={(event) => {
            event.preventDefault();
            if (!busy && !disabled) void locate(draft.trim());
          }}
        >
          <label htmlFor={`call-address-${call.id}`}>
            Incident address or intersection
          </label>
          <input
            id={`call-address-${call.id}`}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="e.g. Van Ness and Union"
            minLength={2}
            maxLength={160}
            required
            autoFocus
            disabled={busy || disabled}
            aria-describedby={`call-address-help-${call.id}`}
          />
          <small id={`call-address-help-${call.id}`} className="muted">
            Enter a San Francisco street address, intersection, or exercise
            landmark.
          </small>
          <div className="row call-location-actions">
            <Button
              type="submit"
              disabled={busy || disabled || draft.trim().length < 2}
            >
              {busy ? "Finding location…" : "Find location again"}
            </Button>
            <Button
              type="button"
              variant="ghost"
              disabled={busy || disabled}
              onClick={() => {
                setEditing(false);
                setError("");
                onBlockingChange(false);
              }}
            >
              Cancel
            </Button>
          </div>
        </form>
      ) : (
        <div className="row call-location-actions">
          <Button
            type="button"
            variant="secondary"
            size="sm"
            disabled={busy || disabled}
            onClick={editAddress}
          >
            <Pencil size={14} aria-hidden="true" /> Edit address
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={busy || disabled}
            onClick={() => void locate()}
          >
            <RotateCcw size={14} aria-hidden="true" />{" "}
            {busy ? "Finding location…" : "Find location again"}
          </Button>
        </div>
      )}
      {error && <ErrorBox message={error} />}
    </section>
  );
}
