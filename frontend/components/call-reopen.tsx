"use client";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { request, useAuth } from "@/lib/api";
import type { RecordedCall } from "@/lib/response-types";
import { Button } from "./ui/button";
import { ErrorBox } from "./shared";

/** Preserve the recording and return an unapproved workflow to explicit call-type selection. */
export function CallReopen({ call, onReopened }: {
  call: RecordedCall;
  onReopened: (call: RecordedCall) => void;
}) {
  const { token } = useAuth();
  const cache = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  /** Reopen only the observed version; starting a fresh paid workflow remains a separate action. */
  async function reopen() {
    setBusy(true);
    setError("");
    try {
      const result = await request<RecordedCall>(`/calls/${call.id}/reopen`, token, "POST", {
        version: call.version,
      });
      cache.setQueryData([token, `/calls/${result.id}`], result);
      void cache.invalidateQueries();
      onReopened(result);
    } catch (error) {
      setError(error instanceof Error ? error.message : "Could not return to call type");
    } finally {
      setBusy(false);
    }
  }
  if (!call.can_reopen) return null;
  return (
    <div className="form">
      <Button variant="secondary" disabled={busy} onClick={reopen}>
        {busy ? "Returning…" : "Back to call type"}
      </Button>
      <small>Keep this recording and location. Start agents again for a fresh response.</small>
      {error && <ErrorBox message={error} />}
    </div>
  );
}
