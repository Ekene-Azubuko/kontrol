"use client";

import Image from "next/image";
import {
  useEffect,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { useQueryClient } from "@tanstack/react-query";

/** Follow the user's preference for reduced animation. */
function subscribeMotion(callback: () => void) {
  const media = window.matchMedia("(prefers-reduced-motion: reduce)");
  media.addEventListener("change", callback);
  return () => media.removeEventListener("change", callback);
}
const motionSnapshot = () =>
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const serverMotionSnapshot = () => true;
/** Animate a bundled vector truck without network or WebGL dependencies. */
function TruckScene() {
  return (
    <div className="startup-truck">
      <div className="startup-truck-art" aria-hidden="true">
        <svg viewBox="0 0 280 140" fill="none">
          <ellipse cx="139" cy="126" rx="118" ry="5" fill="#ececec" />
          <path d="M19 55h151v61H19z" fill="#850f1b" />
          <path d="M170 51h53l31 37v28h-84z" fill="#a11a28" />
          <path d="M185 60h33l21 26h-54z" fill="#e0edf0" />
          <path d="M180 93h62M23 96h140" stroke="white" strokeWidth="5" />
          <rect x="29" y="65" width="57" height="24" rx="2" fill="#ececec" />
          <path d="M35 71h45m-45 6h45m-45 6h45" stroke="#aaa" strokeWidth="2" />
          <path d="M98 65h57v25H98z" fill="#650e14" />
          <path
            d="M100 71h53m-53 6h53m-53 6h53"
            stroke="#b34b54"
            strokeWidth="2"
          />
          <path d="M30 44h128v9H30zM37 37h114v7H37z" fill="#d0d2d3" />
          <path
            d="M45 38v14m19-14v14m19-14v14m19-14v14m19-14v14m19-14v14"
            stroke="#747678"
            strokeWidth="3"
          />
          <rect x="186" y="43" width="28" height="8" rx="3" fill="#dd3947" />
          <path d="M251 96h7v9h-7z" fill="#edcc88" />
          <path d="M14 109h24m192 3h29" stroke="#b6b9bb" strokeWidth="7" />
          {[61, 208].map((x) => (
            <g
              key={x}
              className="startup-wheel"
              style={{ transformOrigin: `${x}px 115px` }}
            >
              <circle cx={x} cy="115" r="17" fill="#292523" />
              <circle cx={x} cy="115" r="9" fill="#d6d8d9" />
              <path d={`M${x} 108v14m-7-7h14`} stroke="#777" strokeWidth="2" />
            </g>
          ))}
        </svg>
      </div>
    </div>
  );
}

/** Show one bounded startup transition per document load, never on sidebar navigation. */
export function StartupScreen({ children }: { children: ReactNode }) {
  const cache = useQueryClient();
  const [visible, setVisible] = useState(true);
  const [leaving, setLeaving] = useState(false);
  const [progress, setProgress] = useState(8);
  const reducedMotion = useSyncExternalStore(
    subscribeMotion,
    motionSnapshot,
    serverMotionSnapshot,
  );
  const displayedProgress = leaving ? 100 : progress;
  useEffect(() => {
    const reduced = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    const started = performance.now();
    let fontsReady = false;
    let disposed = false;
    void document.fonts.ready.then(() => {
      fontsReady = true;
    });
    // Observe initial queries only; SSE refreshes must never restart the intro.
    const timer = window.setInterval(() => {
      if (disposed) return;
      const elapsed = performance.now() - started;
      const queries = cache
        .getQueryCache()
        .getAll()
        .filter((query) => query.isActive());
      const dataReady =
        queries.length > 0 &&
        queries.every((query) => query.state.status !== "pending");
      setProgress(15 + (fontsReady ? 25 : 0) + (dataReady ? 50 : 0));
      if (
        (fontsReady && dataReady && elapsed >= (reduced ? 200 : 2400)) ||
        elapsed >= 6500
      ) {
        setLeaving(true);
        window.clearInterval(timer);
      }
    }, 100);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [cache]);
  useEffect(() => {
    if (!leaving) return;
    const timer = window.setTimeout(
      () => setVisible(false),
      reducedMotion ? 0 : 500,
    );
    return () => window.clearTimeout(timer);
  }, [leaving, reducedMotion]);
  return (
    <>
      <div inert={visible || undefined}>{children}</div>
      {visible && (
        <div
          className={`startup-screen ${leaving ? "is-leaving" : ""}`}
          role="dialog"
          aria-modal="true"
          aria-label="Loading Kontrol"
        >
          <div className="startup-content">
            <div className="startup-scene" aria-hidden="true">
              {!reducedMotion && <TruckScene />}
              <div className="startup-road">
                <div />
              </div>
            </div>
            <div
              className="startup-progress"
              role="progressbar"
              aria-label="Preparing workspace"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={displayedProgress}
              aria-valuetext={leaving ? "Ready" : "Preparing workspace"}
            >
              <span style={{ width: `${displayedProgress}%` }} />
            </div>
            <div className="startup-brand">
              <Image
                src="/brand/kontrol-logo.png"
                width={832}
                height={544}
                alt=""
                unoptimized
              />
              <h1>KONTROL</h1>
            </div>
            <p role="status">
              {leaving ? "Ready when you are." : "Getting things ready…"}
            </p>
            <button className="startup-enter" onClick={() => setLeaving(true)}>
              Enter workspace <span aria-hidden="true">↗</span>
            </button>
          </div>
        </div>
      )}
    </>
  );
}
