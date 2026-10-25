"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import type { Call, Device } from "@twilio/voice-sdk";
import { useQueryClient } from "@tanstack/react-query";
import { request, useAuth, useData } from "./api";
import type { RecordedCall } from "./response-types";

type PhoneContext = {
  enabled: boolean; number: string | null; connection: string; error: string;
  incomingIds: string[]; activeId: string | null; muted: boolean; busy: boolean;
  enable: () => Promise<void>; answer: (id: string) => Promise<void>;
  end: (id: string, decline?: boolean) => Promise<void>; mute: () => void;
};
const Context = createContext<PhoneContext | null>(null);

/** Keep the actual Twilio Device alive across workspace navigation; phone media never passes through React. */
export function LivePhoneProvider({ children }: { children: ReactNode }) {
  const { token } = useAuth();
  const config = useData<{ enabled: boolean; phone_number: string | null }>("/telephony/config");
  const cache = useQueryClient();
  const device = useRef<Device | null>(null);
  const calls = useRef(new Map<string, Call>());
  const owned = useRef<string | null>(null);
  const [incomingIds, setIncomingIds] = useState<string[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [connection, setConnection] = useState("offline");
  const [error, setError] = useState("");
  const [muted, setMuted] = useState(false);
  const [busy, setBusy] = useState(false);

  /** Reconcile provider hang-up through the backend, fetching its newest version first. */
  const control = useCallback(async (id: string, decline = false) => {
    const current = await request<RecordedCall>(`/calls/${id}`, token);
    await request(`/telephony/calls/${id}/${decline ? "decline" : "hangup"}`, token, "POST", { version: current.version });
    void cache.invalidateQueries();
  }, [token, cache]);

  /** Register only after an explicit dispatcher gesture so browser audio can be enabled reliably. */
  async function enable() {
    if (device.current?.state === "registered" || owned.current) return;
    device.current?.destroy();
    device.current = null;
    setBusy(true);
    setError("");
    try {
      const result = await request<{ token: string }>("/telephony/token", token, "POST", {});
      const { Device: TwilioDevice } = await import("@twilio/voice-sdk");
      const phone = new TwilioDevice(result.token, { logLevel: 0, tokenRefreshMs: 60000 });
      device.current = phone;
      phone.on("registered", () => setConnection("ready"));
      phone.on("unregistered", () => setConnection("offline"));
      phone.on("error", () => {
        setConnection("connection error");
        setError("Browser phone connection failed. Check microphone permissions and network access.");
      });
      phone.on("tokenWillExpire", async () => {
        try {
          const refresh = await request<{ token: string }>("/telephony/token", token, "POST", {});
          phone.updateToken(refresh.token);
        } catch {
          setError("Phone authentication could not be refreshed. Reconnect before the next call.");
        }
      });
      phone.on("incoming", (call: Call) => {
        const id = call.customParameters.get("KontrolCallId");
        if (!id) { call.reject(); return; }
        calls.current.set(id, call);
        setIncomingIds([...calls.current.keys()]);
        void cache.invalidateQueries();
        /** Remove this leg without terminating a different browser's winning call. */
        function clear() {
          if (owned.current === id) owned.current = null;
          calls.current.delete(id!);
          setIncomingIds([...calls.current.keys()]);
          setActiveId((current) => current === id ? null : current);
          void cache.invalidateQueries();
        }
        call.on("accept", () => { setActiveId(id); setMuted(false); setConnection("in call"); });
        call.on("cancel", clear);
        call.on("reject", clear);
        call.on("disconnect", () => {
          if (owned.current === id) {
            owned.current = null;
            void control(id).catch(() => setError("Call ended in the browser; waiting for provider confirmation."));
          }
          clear();
          setConnection("ready");
        });
        call.on("reconnecting", () => setConnection("reconnecting"));
        call.on("reconnected", () => setConnection("in call"));
        call.on("error", () => setError("Call audio connection encountered an error. Check the connection status."));
      });
      setConnection("connecting");
      await phone.register();
    } catch (failure) {
      device.current?.destroy();
      device.current = null;
      setConnection("offline");
      setError(failure instanceof Error ? failure.message : "Could not register browser phone");
    } finally { setBusy(false); }
  }

  /** Claim the incoming database session before accepting real SDK audio, never starting agents. */
  async function answer(id: string) {
    setBusy(true); setError("");
    try {
      const call = calls.current.get(id);
      if (!call) throw new Error("Enable the browser phone before placing a new incoming call.");
      const microphone = await navigator.mediaDevices.getUserMedia({ audio: true });
      microphone.getTracks().forEach((track) => track.stop());
      const current = await request<RecordedCall>(`/calls/${id}`, token);
      await request(`/telephony/calls/${id}/answer`, token, "POST", { version: current.version });
      owned.current = id;
      call.accept();
      void cache.invalidateQueries();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not answer call");
    } finally { setBusy(false); }
  }

  /** End the parent telephone call through the provider and then release the local audio leg. */
  async function end(id: string, decline = false) {
    setBusy(true); setError("");
    try {
      await control(id, decline);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not end call");
    } finally {
      // A REST outage must not trap a dispatcher in connected browser audio; signed callbacks reconcile the leg.
      owned.current = null;
      if (decline) calls.current.get(id)?.reject();
      else calls.current.get(id)?.disconnect();
      setBusy(false);
    }
  }

  /** Mute the actual SDK microphone track rather than merely changing the displayed icon. */
  function mute() {
    if (!activeId) return;
    calls.current.get(activeId)?.mute(!muted);
    setMuted(!muted);
  }
  useEffect(() => () => { device.current?.destroy(); }, []);
  return <Context.Provider value={{ enabled: config.data?.enabled ?? false, number: config.data?.phone_number ?? null,
    connection, error, incomingIds, activeId, muted, busy, enable, answer, end, mute }}>{children}</Context.Provider>;
}

/** Access persistent browser calling from the calls screen and global incoming-call notice. */
export function useLivePhone() {
  const value = useContext(Context);
  if (!value) throw new Error("Live phone controls require LivePhoneProvider");
  return value;
}
