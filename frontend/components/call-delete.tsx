"use client";
import * as Dialog from "@radix-ui/react-dialog";
import { useRef, useState } from "react";
import { Trash2 } from "lucide-react";
import { request, useAuth } from "@/lib/api";
import type { RecordedCall } from "@/lib/response-types";
import { ErrorBox } from "./shared";
import { Button } from "./ui/button";

/** Confirm deletion of the observed recording without cancelling its existing response. */
export function CallDelete({
  call,
  onDeleted,
}: {
  call: RecordedCall;
  onDeleted: (id: string) => void;
}) {
  const { token } = useAuth();
  const [open, setOpen] = useState(false);
  const [version, setVersion] = useState(call.version);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const cancel = useRef<HTMLButtonElement>(null);

  /** Delete only the version shown when the confirmation was opened. */
  async function remove() {
    setBusy(true);
    setError("");
    try {
      await request(`/calls/${call.id}`, token, "DELETE", { version });
      onDeleted(call.id);
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Could not delete recording",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog.Root
      open={open}
      onOpenChange={(next) => {
        if (busy) return;
        if (next) {
          setVersion(call.version);
          setError("");
        }
        setOpen(next);
      }}
    >
      <Dialog.Trigger asChild>
        <Button variant="destructive" size="sm">
          <Trash2 size={14} />
          Delete recording
        </Button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content
          className="confirmation-dialog"
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            cancel.current?.focus();
          }}
        >
          <Dialog.Title>Delete recording?</Dialog.Title>
          <Dialog.Description>
            This permanently removes the audio and call-queue entry for
            recording {call.id.slice(0, 6)}. Existing response plans and
            dispatch history stay. Ongoing responses are not cancelled.
          </Dialog.Description>
          {error && <ErrorBox message={error} />}
          <div className="button-row">
            <Dialog.Close asChild>
              <Button ref={cancel} variant="secondary" disabled={busy}>
                Cancel
              </Button>
            </Dialog.Close>
            <Button variant="destructive" disabled={busy} onClick={remove}>
              {busy ? "Deleting…" : "Delete permanently"}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
